@echo off
setlocal
cd /d "%~dp0"

if not exist ".build-venv\Scripts\python.exe" (
  python -m venv .build-venv
  if errorlevel 1 exit /b 1
)

".build-venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

".build-venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --onefile ^
  --name PerforacjaDXF ^
  app.py
if errorlevel 1 exit /b 1

echo.
echo Gotowy plik: dist\PerforacjaDXF.exe
