@echo off
rem ======================================================================
rem  push_to_github.cmd — первичный/повторный пуш проекта в GitHub.
rem  Репозиторий: https://github.com/Cadr0/GERBER-to-DXF.git
rem ======================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
chcp 65001 >nul 2>nul

set "REMOTE_URL=https://github.com/Cadr0/GERBER-to-DXF.git"
set "BRANCH=main"

echo.
echo ==============================================================
echo  gerber2dxf -> GitHub push
echo  Remote: %REMOTE_URL%
echo  Branch: %BRANCH%
echo ==============================================================
echo.

rem --- 1. Проверка git ------------------------------------------------
git --version >nul 2>nul
if errorlevel 1 (
  echo [ERR] Git не найден в PATH.
  echo       Поставьте Git for Windows: https://git-scm.com/download/win
  echo       и перезапустите этот скрипт.
  echo.
  pause
  exit /b 1
)

rem --- 2. Инициализация репозитория ----------------------------------
if not exist ".git" (
  echo [..] git init
  git init -b %BRANCH%
  if errorlevel 1 ( echo [ERR] git init failed & pause & exit /b 1 )
) else (
  echo [i] Репозиторий уже инициализирован.
)

rem --- 3. Remote "origin" --------------------------------------------
git remote get-url origin >nul 2>nul
if errorlevel 1 (
  echo [..] Добавляю remote origin
  git remote add origin "%REMOTE_URL%"
) else (
  echo [..] Обновляю URL у origin
  git remote set-url origin "%REMOTE_URL%"
)

rem --- 4. Текущая ветка → main ---------------------------------------
git branch -M %BRANCH% 2>nul

rem --- 5. Стадия и коммит --------------------------------------------
echo [..] git add -A
git add -A

git diff --cached --quiet
if not errorlevel 1 (
  echo [i] Нет изменений для коммита.
) else (
  set "MSG="
  set /p "MSG=Сообщение коммита [Enter = 'Initial import: gerber2dxf']: "
  if "!MSG!"=="" set "MSG=Initial import: gerber2dxf"
  git commit -m "!MSG!"
  if errorlevel 1 ( echo [ERR] git commit failed & pause & exit /b 1 )
)

rem --- 6. Push --------------------------------------------------------
echo.
echo [..] git push -u origin %BRANCH%
git push -u origin %BRANCH%
if errorlevel 1 (
  echo.
  echo [!] Первый push не прошёл.
  echo     Возможные причины:
  echo      * репозиторий уже содержит коммиты (например, создан README на github.com);
  echo      * требуется авторизация Git Credential Manager откроет браузер.
  echo.
  echo     Попробуйте один из вариантов:
  echo.
  echo         git pull --rebase origin %BRANCH% --allow-unrelated-histories
  echo         git push -u origin %BRANCH%
  echo.
  echo     или форс-пуш (перезапишет удалённое):
  echo.
  echo         git push -u origin %BRANCH% --force
  echo.
  pause
  exit /b 1
)

echo.
echo ==============================================================
echo  [OK] Готово. Репозиторий обновлён:
echo       %REMOTE_URL%
echo ==============================================================
pause
endlocal
