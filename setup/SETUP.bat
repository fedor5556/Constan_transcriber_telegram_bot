@echo off
echo ====================================================
echo Telegram Voice Transcription Bot - Initial Setup
echo ====================================================
echo.

:: Check for Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH!
    echo Please install Python 3.10+ and check "Add to PATH" during installation.
    pause
    exit /b 1
)

:: Check for Git
git --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Git is not installed or not in PATH!
    echo Please install Git from https://git-scm.com/download/win
    pause
    exit /b 1
)

set /p INSTALL_DIR="Enter installation directory [Default: C:\TranscriptionBot]: "
if "%INSTALL_DIR%"=="" set "INSTALL_DIR=C:\TranscriptionBot"

echo.
echo Installing to %INSTALL_DIR%...
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

echo Cloning repository...
:: NOTE: Replace the URL below with your actual GitHub repository URL once created!
git clone https://github.com/your-username/your-repo-name.git "%INSTALL_DIR%"

echo Copying secrets...
copy /Y "%~dp0server_data\.env" "%INSTALL_DIR%\.env"

echo Setting up virtual environment...
cd /d "%INSTALL_DIR%"
python -m venv venv
"%INSTALL_DIR%\venv\Scripts\python.exe" -m pip install -r requirements.txt

echo.
echo Setup Complete!
echo You can now run the bot by double-clicking COMPLETE_LAUNCH.bat in %INSTALL_DIR%
pause
