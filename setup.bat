@echo off
REM Double-click this to set up AXON (runs setup.ps1 without PowerShell
REM execution-policy hassles for downloaded scripts).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
echo.
pause
