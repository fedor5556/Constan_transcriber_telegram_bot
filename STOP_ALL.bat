@echo off
cd /d "%~dp0"

echo Stopping Application Processes...
powershell -NoProfile -Command "$procs = Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python' -and $_.CommandLine -match 'main.py' -and $_.CommandLine -notmatch 'admin_bot' }; if ($procs) { $procs | Invoke-CimMethod -MethodName Terminate }"

echo Waiting for processes to close...
timeout /t 3 /nobreak
echo Done.
