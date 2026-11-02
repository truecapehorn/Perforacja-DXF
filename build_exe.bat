@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "APP_NAME="
set /p "APP_NAME=Podaj nazwe pliku EXE bez rozszerzenia [PerforacjaDXF]: "
if not defined APP_NAME set "APP_NAME=PerforacjaDXF"

if not exist ".build-venv\Scripts\python.exe" (
  python -m venv .build-venv
  if errorlevel 1 exit /b 1
)

".build-venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

".build-venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --onefile ^
  --name "%APP_NAME%" ^
  app.py
if errorlevel 1 exit /b 1

echo.
set "BUILT_EXE=dist\%APP_NAME%.exe"
echo Gotowy plik: %BUILT_EXE%
echo.

call :copy_to "G:\Mój dysk\!!Projekty\Perforacja-DXF"
call :copy_to "Z:\BACKUPS\INSTALKI"
call :copy_to "P:\DZIAŁ_OBRÓBKI_WSTEPNEJ\Jablonski_Norbert\!!!WYMIANA\Perforacja-DXF"
exit /b 0

:copy_to
set "TARGET_ROOT=%~1"
set "TARGET_DIR=%TARGET_ROOT%\%APP_NAME%"
if not exist "%TARGET_ROOT%\" (
  echo NIE SKOPIOWANO do "%TARGET_DIR%\%APP_NAME%.exe" - katalog docelowy jest niedostepny.
  exit /b 0
)
if not exist "%TARGET_DIR%\" mkdir "%TARGET_DIR%" 2>nul
if not exist "%TARGET_DIR%\" (
  echo NIE SKOPIOWANO do "%TARGET_DIR%\%APP_NAME%.exe" - nie mozna utworzyc katalogu.
  exit /b 0
)
copy /Y "%BUILT_EXE%" "%TARGET_DIR%\%APP_NAME%.exe" >nul
if errorlevel 1 (
  echo NIE SKOPIOWANO do "%TARGET_DIR%\%APP_NAME%.exe" - blad kopiowania.
) else (
  echo Skopiowano do: "%TARGET_DIR%\%APP_NAME%.exe"
)
exit /b 0
