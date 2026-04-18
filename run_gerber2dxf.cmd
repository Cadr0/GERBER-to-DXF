@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

rem ============================================================
rem   gerber2dxf — локальный веб-интерфейс. Двойной клик.
rem   Никогда не закрывает окно молча; пишет last_run.log.
rem ============================================================

set "SCRIPT_DIR=%~dp0"
rem срезаем концевой backslash
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

set "LOG=%SCRIPT_DIR%\last_run.log"
set "VENV_DIR=%SCRIPT_DIR%\.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"

echo. >>"%LOG%"
echo ====================================================== >>"%LOG%"
echo [%date% %time%] gerber2dxf launch >>"%LOG%"
echo SCRIPT_DIR=%SCRIPT_DIR% >>"%LOG%"
echo ====================================================== >>"%LOG%"

pushd "%SCRIPT_DIR%" || goto :halt_error

echo.
echo [gerber2dxf] каталог: %SCRIPT_DIR%
echo [gerber2dxf] лог:     %LOG%
echo.

rem --- 1) ищем Python 3.10+ --------------------------------------------------
set "PYCMD="
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul
    if not errorlevel 1 set "PYCMD=py -3"
)
if not defined PYCMD (
    where python >nul 2>nul
    if not errorlevel 1 (
        python -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul
        if not errorlevel 1 set "PYCMD=python"
    )
)
if not defined PYCMD (
    echo [ERROR] Не найден Python 3.10 или новее.
    echo         Скачайте и установите с https://www.python.org/downloads/
    echo         В мастере установки отметьте "Add to PATH".
    echo [%date% %time%] python not found >>"%LOG%"
    goto :halt_error
)
echo [1/4] найден Python: !PYCMD!

rem --- 2) создаём venv при первом запуске ----------------------------------
if not exist "%VENV_PY%" (
    echo [2/4] создаю виртуальное окружение .venv ...
    !PYCMD! -m venv "%VENV_DIR%" >>"%LOG%" 2>&1
    if errorlevel 1 (
        echo [ERROR] не удалось создать venv. см. "%LOG%".
        goto :halt_error
    )
) else (
    echo [2/4] .venv уже есть
)

rem --- 3) устанавливаем / обновляем пакет ----------------------------------
rem Считаем «установленным», только если и gerber2dxf >= 0.3.0, и pygerber имеет
rem модуль pygerber.gerber (т.е. это 3.x, а не 2.x).
set "NEED_INSTALL=1"
"%VENV_PY%" -c "import gerber2dxf, pygerber.gerber.parser; import gerber2dxf as g; v=tuple(int(x) for x in g.__version__.split('.')[:2] if x.isdigit()); import sys; sys.exit(0 if v>=(0,3) else 1)" >nul 2>nul
if not errorlevel 1 set "NEED_INSTALL="

if defined NEED_INSTALL (
    echo [3/4] устанавливаю gerber2dxf и зависимости, это занимает 1-3 минуты...
    echo      (pre-release pygerber 3.0.0a4+ нужен для shapely-бэкенда)
    "%VENV_PY%" -m pip install --disable-pip-version-check --upgrade pip setuptools wheel
    if errorlevel 1 (
        echo [ERROR] не удалось обновить pip. См. "%LOG%".
        goto :halt_error
    )
    "%VENV_PY%" -m pip install --disable-pip-version-check --upgrade --pre -e "%SCRIPT_DIR%"
    if errorlevel 1 (
        echo [ERROR] не удалось установить пакет. См. "%LOG%".
        goto :halt_error
    )
) else (
    echo [3/4] пакет и зависимости уже установлены
)

rem --- 4) запуск сервера ----------------------------------------------------
echo [4/4] запускаю веб-интерфейс...
echo.
"%VENV_PY%" -m gerber2dxf.web.launcher --ensure-deps
set "RC=%ERRORLEVEL%"

echo.
echo [gerber2dxf] завершено, код %RC%. Журнал: "%LOG%"
echo.
pause
popd
endlocal
exit /b %RC%

:halt_error
echo.
echo [gerber2dxf] прерывание из-за ошибки. Журнал: "%LOG%"
echo.
pause
popd
endlocal
exit /b 1
