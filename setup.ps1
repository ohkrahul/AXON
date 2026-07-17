# AXON — one-shot setup for a fresh Windows PC (no VS Code needed).
# Run in PowerShell from the AXON folder:   .\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Write-Host "== AXON setup ==" -ForegroundColor Cyan

# 1) Python
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Python not found. Install Python 3.11+ from https://python.org (tick 'Add to PATH'), then re-run." -ForegroundColor Red
    exit 1
}
Write-Host ("python: " + (python --version))

# 2) Node.js
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Host "Node.js not found. Install Node 18+ from https://nodejs.org, then re-run." -ForegroundColor Red
    exit 1
}
Write-Host ("node: " + (node --version))

# 3) Claude CLI (the brain's login; uses your Claude subscription via the browser)
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Write-Host "Installing Claude CLI (npm i -g @anthropic-ai/claude-code)..."
    npm install -g "@anthropic-ai/claude-code"
}
Write-Host ("claude: " + (claude --version))

# 4) Python virtual env + dependencies
if (-not (Test-Path ".venv")) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install --upgrade pip | Out-Null
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 5) Web (Next.js) dependencies
Push-Location web
npm install
Pop-Location

# 6) Login check
Write-Host "Checking Claude login..." -ForegroundColor Cyan
$probe = ""
try { $probe = ("" | claude -p "reply with the single word READY" 2>$null) } catch {}
if ($probe -match "READY") {
    Write-Host "Claude is logged in and working." -ForegroundColor Green
} else {
    Write-Host "Not logged in yet. Run:  claude   then type  /login  and sign in in your browser." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Setup complete. Start AXON with:" -ForegroundColor Cyan
Write-Host "   .\run_axon_web.bat        (Next.js HUD + Python API)"
Write-Host "   or  .\.venv\Scripts\python.exe server.py   (built-in HUD)"
