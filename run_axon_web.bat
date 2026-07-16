@echo off
REM Launch the AXON combo: Python API (brain/PC/voice) + Next.js HUD.
cd /d "%~dp0"
set AXON_API_ONLY=1
start "AXON API (Python)" ".venv\Scripts\python.exe" server.py
start "AXON Web (Next.js)" cmd /k "cd /d %~dp0web && npm run dev"
echo.
echo AXON is starting. The HUD will open at http://localhost:3000
echo (Python API on http://127.0.0.1:8765)
timeout /t 6 >nul
start "" http://localhost:3000
