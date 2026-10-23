@echo off
rem Double-click this file to start HomePulse on Windows. It installs what it needs the first time.
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python is not installed. Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^), then double-click this file again.
  pause
  exit /b 1
)
python -m pip install --quiet -r requirements.txt
python run.py
pause
