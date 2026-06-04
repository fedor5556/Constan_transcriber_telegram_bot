@echo off
cd /d "%~dp0"
set "PYTHON_CMD=%~dp0venv\Scripts\python.exe"

echo Installing requirements...
"%PYTHON_CMD%" -m pip install -r requirements.txt

if not exist logs mkdir logs

echo Starting Application...
powershell -NoProfile -Command "& '%PYTHON_CMD%' -u src\main.py 2>&1 | Tee-Object -FilePath logs\main.log"
