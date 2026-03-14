# install.ps1
#
# ContextCore — One-shot bootstrap for Windows
# Run this from a fresh terminal in any folder:
#
#   irm https://your-domain.com/install.ps1 | iex
# OR copy this file locally and run:
#   powershell -ExecutionPolicy Bypass -File install.ps1

$ErrorActionPreference = "Stop"
$SDK = "C:\Users\USER\Documents\SDKSearchImplementation\SearchEmbedSDK"

function Write-Step($msg) {
    Write-Host ""
    Write-Host "  --> $msg" -ForegroundColor Cyan
}

function Write-Ok($msg) {
    Write-Host "  [OK] $msg" -ForegroundColor Green
}

function Write-Warn($msg) {
    Write-Host "  [!!] $msg" -ForegroundColor Yellow
}

# ── 1. Check Python ────────────────────────────────────────────────────────────
Write-Step "Checking Python..."
$pyver = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Python not found. Download from https://python.org/downloads" -ForegroundColor Red
    exit 1
}
Write-Ok "Found $pyver"

# ── 2. Create venv ────────────────────────────────────────────────────────────
Write-Step "Creating virtual environment..."
if (-not (Test-Path ".venv")) {
    python -m venv .venv
    Write-Ok "Created .venv"
} else {
    Write-Ok ".venv already exists, reusing"
}

# Activate
& ".venv\Scripts\Activate.ps1"

# ── 3. Upgrade pip (critical — pip < 22 can hang on installs) ──────────────────
Write-Step "Upgrading pip..."
python -m pip install --upgrade pip --quiet
Write-Ok "pip upgraded"

# ── 4. Install base dependencies (fast — no ML models) ───────────────────────
Write-Step "Installing base dependencies..."
pip install -r "$SDK\requirements.txt" --quiet
Write-Ok "Base dependencies installed"

# ── 5. Install contextcore CLI ────────────────────────────────────────────────
Write-Step "Installing contextcore CLI..."
pip install -e "$SDK" --quiet
Write-Ok "contextcore CLI installed"

# ── 6. Done — hand off to the wizard ─────────────────────────────────────────
Write-Host ""
Write-Host "─────────────────────────────────────────" -ForegroundColor Cyan
Write-Host "  Installation complete!" -ForegroundColor Green  
Write-Host ""
Write-Host "  Run the setup wizard:" -ForegroundColor White
Write-Host "    contextcore init" -ForegroundColor Yellow
Write-Host "─────────────────────────────────────────" -ForegroundColor Cyan
Write-Host ""
