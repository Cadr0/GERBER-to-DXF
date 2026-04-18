"""Запуск веб-интерфейса: диагностика, установка пакетов, uvicorn, браузер.

Никогда не завершается молча — при любой ошибке пишет трейс и остаётся в фокусе.
"""

from __future__ import annotations

import argparse
import datetime
import importlib
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path


REQUIRED_PACKAGES: list[tuple[tuple[str, ...], str]] = [
    # (возможные имена для import, спецификация для pip)
    # 3.0.0a4+ нужен для pygerber.gerber.* и shapely-бэкенда.
    (("pygerber",), "pygerber[shapely]>=3.0.0a4,<4"),
    (("shapely",), "shapely>=2.0.0"),
    (("ezdxf",), "ezdxf>=1.3.0"),
    (("fastapi",), "fastapi>=0.110"),
    (("uvicorn",), "uvicorn>=0.27"),
    (("multipart", "python_multipart"), "python-multipart>=0.0.9"),
    (("matplotlib",), "matplotlib>=3.7"),
]

# Минимальная версия pygerber, которая содержит нужный нам API.
MIN_PYGERBER = (3, 0, 0)


LOG_PATH = Path(__file__).resolve().parent.parent.parent.parent / "last_run.log"


def _log_line(s: str) -> None:
    print(s, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(s + "\n")
    except OSError:
        pass


def _log_header() -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("\n" + "=" * 70 + "\n")
            f.write(f"gerber2dxf launch {datetime.datetime.now().isoformat()}\n")
            f.write(f"python: {sys.version.splitlines()[0]}\n")
            f.write(f"executable: {sys.executable}\n")
            f.write(f"cwd: {os.getcwd()}\n")
            f.write("=" * 70 + "\n")
    except OSError:
        pass


def _import_any(names: tuple[str, ...]):
    for n in names:
        try:
            return importlib.import_module(n)
        except ImportError:
            continue
    raise ImportError(f"none of {names} importable")


def diagnose() -> list[tuple[str, str]]:
    report: list[tuple[str, str]] = []
    report.append(("python", sys.version.splitlines()[0]))
    report.append(("executable", sys.executable))
    for names, spec in REQUIRED_PACKAGES:
        try:
            m = _import_any(names)
            ver = getattr(m, "__version__", "?")
            report.append((f"dep {names[0]}", f"OK {ver}"))
        except ImportError:
            report.append((f"dep {names[0]}", f"MISSING ({spec})"))
    try:
        import gerber2dxf  # noqa: F401
        import gerber2dxf.web.server  # noqa: F401
        report.append(("gerber2dxf", "OK"))
    except Exception as e:  # noqa: BLE001
        report.append(("gerber2dxf", f"IMPORT ERROR: {e}"))
    return report


def _parse_version(v: str) -> tuple[int, ...]:
    """Грубый парсер версии '3.0.0a4' -> (3, 0, 0). Alpha/beta отбрасываются."""
    import re
    m = re.match(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", v or "")
    if not m:
        return (0, 0, 0)
    return tuple(int(x) if x else 0 for x in m.groups())


def _pygerber_too_old() -> bool:
    try:
        m = importlib.import_module("pygerber")
    except ImportError:
        return True
    ver = getattr(m, "__version__", None)
    if not ver:
        # Если версию не узнали, проверим по наличию ключевого модуля.
        try:
            importlib.import_module("pygerber.gerber.parser")
            return False
        except ImportError:
            return True
    # 3.0.0a4 должен считаться валидным. _parse_version("3.0.0a4") = (3,0,0).
    return _parse_version(ver) < MIN_PYGERBER


def ensure_deps(verbose: bool = True) -> None:
    missing: list[str] = []
    for names, spec in REQUIRED_PACKAGES:
        try:
            _import_any(names)
        except ImportError:
            missing.append(spec)

    # Отдельная проверка: pygerber может импортироваться, но быть 2.x (нет нужного API).
    needs_pygerber_upgrade = _pygerber_too_old()
    if needs_pygerber_upgrade:
        spec = next(s for ns, s in REQUIRED_PACKAGES if ns == ("pygerber",))
        if spec not in missing:
            missing.append(spec)
            _log_line(
                "[deps] установленный pygerber слишком старый (нет pygerber.gerber.*), "
                "обновляю до 3.0.0a4+"
            )

    if not missing:
        if verbose:
            _log_line("[deps] все пакеты уже установлены и подходящей версии")
        return

    _log_line(f"[deps] устанавливаю/обновляю: {missing}")
    cmd = [
        sys.executable, "-m", "pip", "install",
        "--disable-pip-version-check",
        "--upgrade",
        "--pre",  # разрешить alpha/beta (нужно для pygerber 3.0.0a4)
        *missing,
    ]
    _log_line(f"[deps] команда: {' '.join(cmd)}")
    try:
        # В реальное время выводим pip, иначе кажется, что лаунчер «завис».
        proc = subprocess.run(cmd, check=False)
    except FileNotFoundError as e:
        _log_line(f"[deps] pip не найден: {e}")
        raise
    if proc.returncode != 0:
        raise RuntimeError(f"pip install завершился с кодом {proc.returncode}")


def find_free_port(preferred: int = 8765) -> int:
    candidates = [preferred] + [p for p in range(8766, 8800)]
    for port in candidates:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _open_browser_delayed(url: str, delay: float = 1.5) -> None:
    def _open() -> None:
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception as e:  # noqa: BLE001
            _log_line(f"[browser] не удалось открыть автоматически: {e}")
    threading.Thread(target=_open, daemon=True).start()


def _print_banner(url: str) -> None:
    bar = "═" * 62
    _log_line("")
    _log_line(bar)
    _log_line("  gerber2dxf — веб-интерфейс запущен")
    _log_line(f"  откройте в браузере:  {url}")
    _log_line("  для выхода: Ctrl+C в этом окне или просто закройте его")
    _log_line(bar)
    _log_line("")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="gerber2dxf: веб-интерфейс")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="0 = свободный порт")
    parser.add_argument("--no-browser", action="store_true", help="Не открывать браузер автоматически")
    parser.add_argument("--ensure-deps", action="store_true", help="Поставить недостающие пакеты при старте")
    parser.add_argument("--diagnose", action="store_true", help="Только диагностика окружения и выход")
    ns = parser.parse_args(argv)

    _log_header()

    if ns.diagnose:
        _log_line("=== diagnose ===")
        for k, v in diagnose():
            _log_line(f"  {k:24s}: {v}")
        _log_line("=== end ===")
        return 0

    if ns.ensure_deps:
        pygerber_was_old = _pygerber_too_old()
        try:
            ensure_deps()
        except Exception as e:  # noqa: BLE001
            _log_line(f"[deps] ошибка: {e}")
            _log_line(traceback.format_exc())
            input("Нажмите Enter, чтобы закрыть окно...")
            return 2
        # После обновления pygerber нужно перезапустить процесс,
        # иначе в памяти останется старая версия.
        if pygerber_was_old and not _pygerber_too_old():
            _log_line("[deps] pygerber обновлён, перезапускаю процесс...")
            os.execv(sys.executable, [sys.executable, "-m", "gerber2dxf.web.launcher",
                                      *[a for a in (argv or sys.argv[1:]) if a != "--ensure-deps"]])

    try:
        port = ns.port or find_free_port()
    except Exception as e:  # noqa: BLE001
        _log_line(f"[port] не удалось подобрать порт: {e}")
        input("Нажмите Enter, чтобы закрыть окно...")
        return 3

    url = f"http://{ns.host}:{port}/"

    _print_banner(url)

    if not ns.no_browser:
        _open_browser_delayed(url)

    # импорт uvicorn — с повторной попыткой после ensure_deps
    try:
        import uvicorn  # type: ignore
    except ImportError:
        _log_line("[deps] uvicorn не найден, пробую установить")
        try:
            ensure_deps()
        except Exception as e:  # noqa: BLE001
            _log_line(f"[deps] не удалось поставить uvicorn: {e}")
            input("Нажмите Enter, чтобы закрыть окно...")
            return 4
        import uvicorn  # type: ignore  # noqa: F401

    # проверяем, что сервер импортируется
    try:
        importlib.import_module("gerber2dxf.web.server")
    except Exception as e:  # noqa: BLE001
        _log_line(f"[server] ошибка импорта gerber2dxf.web.server: {e}")
        _log_line(traceback.format_exc())
        _log_line("=== diagnose ===")
        for k, v in diagnose():
            _log_line(f"  {k:24s}: {v}")
        input("Нажмите Enter, чтобы закрыть окно...")
        return 5

    try:
        uvicorn.run(
            "gerber2dxf.web.server:app",
            host=ns.host,
            port=port,
            log_level="info",
            access_log=False,
        )
    except Exception as e:  # noqa: BLE001
        _log_line(f"[uvicorn] крах: {e}")
        _log_line(traceback.format_exc())
        input("Нажмите Enter, чтобы закрыть окно...")
        return 6
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except KeyboardInterrupt:
        _log_line("[main] остановлено пользователем (Ctrl+C)")
    except Exception as e:  # noqa: BLE001
        _log_line(f"[main] необработанная ошибка: {e}")
        _log_line(traceback.format_exc())
        try:
            input("Нажмите Enter, чтобы закрыть окно...")
        except EOFError:
            pass
