@echo off
setlocal EnableExtensions
chcp 65001 >nul

rem ============================================================
rem   gerber2dxf — диагностика окружения.
rem   Запускайте, если run_gerber2dxf.cmd не работает.
rem ============================================================

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "VENV_PY=%SCRIPT_DIR%\.venv\Scripts\python.exe"
set "LOG=%SCRIPT_DIR%\last_run.log"

pushd "%SCRIPT_DIR%"
echo.
echo === gerber2dxf diagnose ===
echo SCRIPT_DIR = %SCRIPT_DIR%
echo LOG        = %LOG%
echo.

echo [python launcher]
where py 2>nul && (py -3 --version) || echo   py (Python Launcher) not found
where python 2>nul && (python --version) || echo   python not found
echo.

if exist "%VENV_PY%" (
    echo [.venv python]
    "%VENV_PY%" --version
    echo.
    echo [pip list (venv)]
    "%VENV_PY%" -m pip list
    echo.
    echo [gerber2dxf diagnose]
    "%VENV_PY%" -m gerber2dxf.web.launcher --diagnose
) else (
    echo .venv ещё не создан. Сначала запустите run_gerber2dxf.cmd
)

echo.
echo === done ===
popd
pause
endlocal
