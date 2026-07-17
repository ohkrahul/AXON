# AXON one-line installer.
# Run in PowerShell:
#   irm https://raw.githubusercontent.com/ohkrahul/AXON/main/install.ps1 | iex
$ErrorActionPreference = "Stop"
$dest = Join-Path $env:USERPROFILE "AXON"

Write-Host "=== Installing AXON to $dest ===" -ForegroundColor Cyan

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Installing git (one time)…" -ForegroundColor Cyan
    winget install -e --id Git.Git --silent --accept-package-agreements --accept-source-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
}

if (Test-Path $dest) {
    git -C $dest pull --ff-only 2>$null
} else {
    git clone https://github.com/ohkrahul/AXON.git $dest
}

# hand off to the all-in-one bootstrap (installs Python/Node/deps + launches)
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $dest "bootstrap.ps1")
