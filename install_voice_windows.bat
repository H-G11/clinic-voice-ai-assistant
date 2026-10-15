@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (echo Run start_windows.bat first & pause & exit /b 1)
call .venv\Scripts\activate.bat
python -m pip install -r requirements-voice.txt
if errorlevel 1 (echo Installation failed & pause & exit /b 1)
echo Installed. First audio transcription downloads the ASR model. Default CPU int8 base.
pause
