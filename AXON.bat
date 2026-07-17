@echo off
title AXON
REM ── The only file you need. Double-click it. ──
REM First run: installs everything it needs, then launches.
REM Later runs: just launches. Sign in in the browser when asked.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0bootstrap.ps1"
