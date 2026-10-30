@echo off
setlocal
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
echo Gotowy plik: dist\%APP_NAME%.exe
