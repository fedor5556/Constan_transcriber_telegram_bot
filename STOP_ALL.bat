@echo off
cd /d "%~dp0"

echo Stopping ONLY this project's processes...

REM Only kill python processes whose command line points INSIDE this project
REM folder. A generic script name like "main.py" must never match an unrelated
REM app elsewhere on the machine. Also never touch the admin bot.
powershell -NoProfile -Command "$proj = '%~dp0'.TrimEnd('\'); $procs = Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python' -and $_.CommandLine -like ('*' + $proj + '*') -and $_.CommandLine -notmatch 'admin_bot' }; if ($procs) { $procs | ForEach-Object { Write-Host ('Killing PID ' + $_.ProcessId); Invoke-CimMethod -InputObject $_ -MethodName Terminate | Out-Null } } else { Write-Host 'No matching processes for this project.' }"

echo Waiting for processes to close...
timeout /t 3 /nobreak >nul
echo Done.
