@echo off
cd /d "%~dp0"
echo 4 test-mails versturen via de app...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0test_mails.ps1"
exit /b
