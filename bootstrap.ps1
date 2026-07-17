param([switch]$CheckOnly)

# AXON all-in-one: installs anything missing (Python, Node, Claude Code, deps)
# then launches. Safe to run every time — it skips whatever's already there.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Have($c) { [bool](Get-Command $c -ErrorAction SilentlyContinue) }
function RefreshPath() {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}
function Step($m) { Write-Host ("  " + $m) -ForegroundColor Cyan }

Write-Host "=== AXON ===" -ForegroundColor Cyan

# 1) Python
if (-not (Have python)) {
    Step "Installing Python (one time)…"
    if (-not $CheckOnly) {
        winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
        RefreshPath
    }
} else { Step ("Python OK  (" + (python --version 2>&1) + ")") }

# 2) Node.js
if (-not (Have node)) {
    Step "Installing Node.js (one time)…"
    if (-not $CheckOnly) {
        winget install -e --id OpenJS.NodeJS.LTS --silent --accept-package-agreements --accept-source-agreements
        RefreshPath
    }
} else { Step ("Node OK  (" + (node --version) + ")") }

# 3) Claude Code CLI (the brain's login)
if (-not (Have claude)) {
    Step "Installing Claude Code (one time)…"
    if (-not $CheckOnly) { npm install -g "@anthropic-ai/claude-code"; RefreshPath }
} else { Step "Claude Code OK" }

# 4) Python env + dependencies
if (-not (Test-Path ".venv")) {
    Step "Setting up Python environment (one time)…"
    if (-not $CheckOnly) {
        python -m venv .venv
        .\.venv\Scripts\python.exe -m pip install --upgrade pip | Out-Null
        .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    }
} else { Step "Python env OK" }

# 5) Web app dependencies
if (-not (Test-Path "web\node_modules")) {
    Step "Installing web app (one time)…"
    if (-not $CheckOnly) { Push-Location web; npm install; Pop-Location }
} else { Step "Web app OK" }

if ($CheckOnly) { Write-Host "check complete." -ForegroundColor Green; return }

# 6) Launch API + HUD, open the browser
Step "Launching AXON…"
$env:AXON_API_ONLY = "1"
Start-Process -WindowStyle Minimized ".\.venv\Scripts\python.exe" -ArgumentList "server.py"
Start-Process -WindowStyle Minimized "cmd" -ArgumentList "/c cd /d `"$PSScriptRoot\web`" && npm run dev"
Start-Sleep -Seconds 7
Start-Process "http://localhost:3000"
Write-Host ""
Write-Host "AXON is running -> http://localhost:3000  (sign in when prompted)" -ForegroundColor Green
