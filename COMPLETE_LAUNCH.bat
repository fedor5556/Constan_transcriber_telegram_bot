@echo off
cd /d "%~dp0"
set "PYTHON_CMD=%~dp0venv\Scripts\python.exe"

if not exist venv\Scripts\python.exe (
    echo [INFO] venv missing - creating it...
    python -m venv venv || py -m venv venv
)
:: Install deps BEFORE the runner handoff: on a fresh clone the Hub's pip step
:: runs before the venv exists ([No venv found]) and the runner starts the
:: script directly - without this line a first deploy crash-loops on missing
:: modules (bit Transcriber_userbot on 2026-07-09).
"%PYTHON_CMD%" -m pip install -r requirements.txt || (echo [FATAL] pip failed & exit /b 1)

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
:: plain "exit" (not /b): the Hub starts this bat via `start`, which keeps the
:: console open after the script ends - exit closes the window too.
exit 0

:runner
echo [INFO] Central runner detected - requesting hidden (re)start.
echo start > logs\runner.start
exit 0
