"""CLI: пакетная конвертация Gerber/Excellon в DXF и запуск веб-интерфейса."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gerber2dxf.dxf_export import write_drill_dxf, write_geometry_dxf
from gerber2dxf.excellon import DrillUnits, is_probably_excellon, read_drill_file
from gerber2dxf.gerber_convert import parse_gerber_file, units_is_mm
from gerber2dxf.naming import output_stem


GLOBS = [
    "*.gtl", "*.gbl", "*.gts", "*.gbs", "*.gtp", "*.gbp",
    "*.gto", "*.gbo", "*.gko", "*.gdl",
    "*.gm1", "*.gm2", "*.gm3", "*.gm13", "*.gm15",
    "*.gpt", "*.gpb",
    "*.gbr", "*.grb", "*.pho", "*.art",
    "*.drl", "*.exc", "*.xln",
    "*.GTL", "*.GBL", "*.GTS", "*.GBS", "*.GTP", "*.GBP",
    "*.GTO", "*.GBO", "*.GKO", "*.GDL",
    "*.GM1", "*.GM2", "*.GM3", "*.GM13", "*.GM15",
    "*.GPT", "*.GPB",
    "*.GBR", "*.GRB", "*.PHO", "*.ART",
    "*.DRL", "*.EXC", "*.XLN",
]


def collect_inputs(paths: list[Path]) -> list[Path]:
    found: set[Path] = set()
    for p in paths:
        if p.is_file():
            found.add(p.resolve())
        elif p.is_dir():
            for pattern in GLOBS:
                for f in p.glob(pattern):
                    if f.is_file():
                        found.add(f.resolve())
    return sorted(found)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gerber/Excellon -> DXF. По одному DXF на слой. "
        "Замкнутые LWPOLYLINE для контура, окружности для сверловки.",
    )
    parser.add_argument("--web", action="store_true", help="Запустить веб-интерфейс")
    parser.add_argument("inputs", nargs="*", type=Path,
                        help="Файлы Gerber/Excellon или каталоги с ними")
    parser.add_argument("-o", "--out", type=Path, default=Path("dxf_out"))
    parser.add_argument("--flip-y", action="store_true", help="Отразить ось Y")
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--tx", type=float, default=0.0)
    parser.add_argument("--ty", type=float, default=0.0)
    ns = parser.parse_args(argv)

    if ns.web:
        from gerber2dxf.web.launcher import main as web_main
        return web_main([])

    if not ns.inputs:
        parser.print_help()
        return 1

    out_dir: Path = ns.out
    out_dir.mkdir(parents=True, exist_ok=True)

    files = collect_inputs(ns.inputs)
    if not files:
        print("Не найдено ни одного подходящего файла.", file=sys.stderr)
        return 1

    ok, fail = 0, 0
    for src in files:
        stem = output_stem(src)
        dest = out_dir / f"{stem}.dxf"
        try:
            if is_probably_excellon(src):
                hits, units = read_drill_file(src)
                write_drill_dxf(
                    [(h.x, h.y, h.diameter) for h in hits],
                    str(dest),
                    units_mm=(units is DrillUnits.MM),
                    flip_y=ns.flip_y, scale=ns.scale,
                    translate=(ns.tx, ns.ty),
                )
            else:
                geom = parse_gerber_file(src)
                write_geometry_dxf(
                    geom.shape, str(dest),
                    units_mm=units_is_mm(geom.units),
                    flip_y=ns.flip_y, scale=ns.scale,
                    translate=(ns.tx, ns.ty),
                )
            print(f"OK  {src.name} -> {dest.name}")
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"ERR {src.name}: {e}", file=sys.stderr)
            fail += 1

    print(f"Готово: {ok} файлов, ошибок: {fail}.")
    return 0 if fail == 0 else 2
