@echo off
cd /d "%~dp0"
set "PYTHON_CMD=%~dp0venv\Scripts\python.exe"

echo Stopping any existing processes...
call STOP_ALL.bat

if not exist logs mkdir logs

echo Starting Application...
start "Voice Transcription Bot" cmd /k RUN_APP.bat
