@echo off
cd /d "%~dp0"

REM Check of port 5000 al in gebruik is — zo ja, app draait al.
netstat -ano | findstr /R /C:":5000 .*LISTENING" >nul
if %errorlevel%==0 (
    echo Show-Up System draait al op http://localhost:5000
    timeout /t 2 >nul
    exit /b
)

start "" pythonw run.py
exit /b
