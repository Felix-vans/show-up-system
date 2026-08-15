@echo off
cd /d "%~dp0"

REM Kill wat er ook op poort 5000 draait (alleen die ene proces, niet alle pythonw).
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /R /C:":5000 .*LISTENING"') do (
    echo Bestaand proces op poort 5000 gevonden [PID %%a] - stoppen...
    taskkill /F /PID %%a >nul 2>&1
)

REM Even wachten tot Windows de poort echt vrijgeeft.
timeout /t 1 >nul

echo Show-Up System opstarten...
start "" pythonw run.py

REM Korte check dat hij effectief opstart.
timeout /t 2 >nul
netstat -ano | findstr /R /C:":5000 .*LISTENING" >nul
if %errorlevel%==0 (
    echo OK - draait op http://localhost:5000
) else (
    echo WAARSCHUWING - poort 5000 nog niet actief. Check handmatig of hij opkomt.
)

timeout /t 3 >nul
exit /b
