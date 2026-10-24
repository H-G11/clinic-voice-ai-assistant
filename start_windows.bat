@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3.11 -m venv .venv
  if errorlevel 1 (echo Python 3.11 is required & exit /b 1)
)
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (echo Installation failed & exit /b 1)
if /I "%~1"=="--check" (
  .venv\Scripts\python.exe -m unittest discover -s tests -v
  exit /b
)
.venv\Scripts\python.exe app.py
exit /b
