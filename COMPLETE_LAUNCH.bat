@echo off
cd /d "%~dp0"
set "PYTHON_CMD=%~dp0venv\Scripts\python.exe"

if not exist logs mkdir logs
if exist logs\runner.stop del logs\runner.stop

:: If the central runner (Admin_hub\runner.py) is alive, hand off to it: it
:: starts this project's process hidden and keeps it alive. Otherwise fall
:: back to the legacy visible-window launch below.
powershell -NoProfile -Command "$r = Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'runner\.py' }; if ($r) { exit 0 } else { exit 1 }"
if %ERRORLEVEL%==0 goto :runner

echo [WARN] Central runner not detected - legacy visible-window launch.
echo Stopping any existing processes...
call STOP_ALL.bat
if exist logs\runner.stop del logs\runner.stop

echo Starting Application...
start "Voice Transcription Bot" cmd /k RUN_APP.bat
exit /b 0

:runner
echo [INFO] Central runner detected - requesting hidden (re)start.
echo start > logs\runner.start
exit /b 0
