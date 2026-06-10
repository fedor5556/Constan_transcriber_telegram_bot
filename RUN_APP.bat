@echo off
cd /d "%~dp0"
set "PYTHON_CMD=%~dp0venv\Scripts\python.exe"

echo Installing requirements...
"%PYTHON_CMD%" -m pip install -r requirements.txt

:: The bot writes its own rotating UTF-8 log (logs\main.log) from inside
:: Python (src\log_tee.py). NEVER pipe/Tee/redirect output into that file here -
:: a second writer locks it (see TELEGRAM_BOT_NOTE.md in GEMINI_PROJECTS root).
echo Starting Application...
"%PYTHON_CMD%" -u src\main.py
pause
