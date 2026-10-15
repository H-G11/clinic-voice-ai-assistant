@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3 -m venv .venv
  if errorlevel 1 (echo Python 3 not found & pause & exit /b 1)
)
if not exist .venv\.deps_installed (
  .venv\Scripts\python.exe -m pip install -r requirements.txt
  if errorlevel 1 (echo Installation failed & pause & exit /b 1)
  echo OK > .venv\.deps_installed
)
.venv\Scripts\python.exe -m unittest discover -s tests -v
if errorlevel 1 (echo Tests failed - fix before demo & pause & exit /b 1)
if /I "%~1"=="--check" exit /b 0
.venv\Scripts\python.exe app.py
pause
