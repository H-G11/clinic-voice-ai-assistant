@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (echo Run start_windows.bat first & pause & exit /b 1)
.venv\Scripts\python.exe -m pip install -r requirements-tts.txt --only-binary=:all:
if errorlevel 1 (echo Installation failed & pause & exit /b 1)
.venv\Scripts\python.exe -m piper.download_voices ru_RU-irina-medium --data-dir data/models
if errorlevel 1 (echo Voice download failed & pause & exit /b 1)
.venv\Scripts\python.exe scripts/check_voice.py
pause
