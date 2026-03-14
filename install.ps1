# install.ps1
#
# ContextCore — One-shot bootstrap for Windows
#
# QUICK START (pipe to PowerShell - review first!):
#   irm https://your-domain.com/install.ps1 | iex
#
# SAFE START (download and inspect first):
#   Invoke-WebRequest -Uri https://your-domain.com/install.ps1 -OutFile install.ps1
#   powershell -ExecutionPolicy Bypass -File install.ps1
#
# LOCAL DEVELOPMENT:
#   powershell -ExecutionPolicy Bypass -File install.ps1

$ErrorActionPreference = "Stop"

# Detect script location for remote execution, or use current directory for local
if ($MyInvocation.MyCommand.Path) {
    $SDK = Split-Path -Parent $MyInvocation.MyCommand.Path
} else {
    $SDK = $PWD.Path
}

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

function Write-Error($msg) {
    Write-Host "  [ERROR] $msg" -ForegroundColor Red
}

# ── 1. Check Python ────────────────────────────────────────────────────────────
Write-Step "Checking Python..."
$pyver = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "Python not found. Download from https://python.org/downloads"
    exit 1
}
Write-Ok "Found $pyver"

# ── 2. Check Python version (require >= 3.10) ─────────────────────────────────
Write-Step "Checking Python version..."
$pyVersion = python -c "import sys; print('.'.join(map(str, sys.version_info[:2])))"
$pyMajor = python -c "import sys; print(sys.version_info[0])"
$pyMinor = python -c "import sys; print(sys.version_info[1])"

if ($pyMajor -lt 3 -or ($pyMajor -eq 3 -and $pyMinor -lt 10)) {
    Write-Error "Python 3.10+ required, found $pyVersion"
    exit 1
}
Write-Ok "Python $pyVersion meets requirement"

# ── 3. Check/Install ffmpeg ────────────────────────────────────────────────────
Write-Step "Checking ffmpeg (for video indexing)..."
$ffmpegCheck = Get-Command ffmpeg -ErrorAction SilentlyContinue
if (-not $ffmpegCheck) {
    Write-Warn "ffmpeg not found. Attempting to install via winget..."
    
    $wingetCheck = Get-Command winget -ErrorAction SilentlyContinue
    if ($wingetCheck) {
        winget install Gyan.FFmpeg --accept-source-agreements --accept-package-agreements -h 2>$null
        if ($LASTEXITCODE -eq 0) {
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
            Write-Ok "ffmpeg installed"
        } else {
            Write-Warn "winget install failed. Install ffmpeg manually from https://ffmpeg.org/download.html"
        }
    } else {
        Write-Warn "winget not found. Install ffmpeg manually from https://ffmpeg.org/download.html"
    }
    
    $ffmpegCheck = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if ($ffmpegCheck) {
        Write-Ok "ffmpeg is now available"
    }
} else {
    Write-Ok "ffmpeg already installed"
}

# ── 4. Create venv ────────────────────────────────────────────────────────────
Write-Step "Creating virtual environment..."
if (-not (Test-Path "$SDK\.venv")) {
    python -m venv "$SDK\.venv"
    Write-Ok "Created .venv"
} else {
    Write-Ok ".venv already exists, reusing"
}

# Get venv Python path (use explicitly instead of relying on activation)
$VenvPython = "$SDK\.venv\Scripts\python.exe"
$VenvPip = "$SDK\.venv\Scripts\pip.exe"

# ── 5. Upgrade pip (critical — pip < 22 can hang on installs) ──────────────────
Write-Step "Upgrading pip..."
& $VenvPython -m pip install --upgrade pip
Write-Ok "pip upgraded"

# ── 6. Install base dependencies ───────────────────────────────────────────────
Write-Step "Installing base dependencies..."
& $VenvPip install -r "$SDK\requirements.txt"
Write-Ok "Base dependencies installed"

# ── 7. Install contextcore CLI (editable install - idempotent) ─────────────────
Write-Step "Installing contextcore CLI..."
& $VenvPip install -e "$SDK"
Write-Ok "contextcore CLI installed"

# ── 8. Verify CLI works ─────────────────────────────────────────────────────────
Write-Step "Verifying CLI..."
$cliTest = & $VenvPython -m cli.main --version 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Ok "contextcore CLI is ready"
} else {
    Write-Warn "Could not verify CLI in current session"
}

# ── 9. Done — hand off to the wizard in NEW TERMINAL ─────────────────────────
Write-Host ""
Write-Host "─────────────────────────────────────────" -ForegroundColor Cyan
Write-Host "  Installation complete!" -ForegroundColor Green  
Write-Host ""
Write-Host "  IMPORTANT: Open a NEW terminal/tab, then run:" -ForegroundColor White
Write-Host ""
Write-Host "    cd $SDK" -ForegroundColor Yellow
Write-Host "    .\.venv\Scripts\Activate.ps1" -ForegroundColor Yellow
Write-Host "    contextcore init" -ForegroundColor Yellow
Write-Host ""
Write-Host "  This will:" -ForegroundColor Gray
Write-Host "    - Configure your watched directories" -ForegroundColor Gray
Write-Host "    - Install ML models (CLIP, Whisper)" -ForegroundColor Gray
Write-Host "    - Start the backend server" -ForegroundColor Gray
Write-Host "    - Begin initial indexing" -ForegroundColor Gray
Write-Host "─────────────────────────────────────────" -ForegroundColor Cyan
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

# ── 2. Check/Install ffmpeg ───────────────────────────────────────────────────
Write-Step "Checking ffmpeg (for video indexing)..."
$ffmpegCheck = Get-Command ffmpeg -ErrorAction SilentlyContinue
if (-not $ffmpegCheck) {
    Write-Host "  ffmpeg not found. Attempting to install via winget..." -ForegroundColor Yellow
    
    # Check if winget is available
    $wingetCheck = Get-Command winget -ErrorAction SilentlyContinue
    if ($wingetCheck) {
        winget install Gyan.FFmpeg --accept-source-agreements --accept-package-agreements -h 2>$null
        if ($LASTEXITCODE -eq 0) {
            # Refresh PATH for current session
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
            Write-Ok "ffmpeg installed"
        } else {
            Write-Warn "winget install failed. Install ffmpeg manually from https://ffmpeg.org/download.html"
        }
    } else {
        Write-Warn "winget not found. Install ffmpeg manually from https://ffmpeg.org/download.html"
    }
    
    # Verify ffmpeg after install attempt
    $ffmpegCheck = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if ($ffmpegCheck) {
        Write-Ok "ffmpeg is now available"
    }
} else {
    Write-Ok "ffmpeg already installed"
}

# ── 3. Create venv ────────────────────────────────────────────────────────────
Write-Step "Creating virtual environment..."
if (-not (Test-Path "$SDK\.venv")) {
    python -m venv "$SDK\.venv"
    Write-Ok "Created .venv"
} else {
    Write-Ok ".venv already exists, reusing"
}

# Activate
& "$SDK\.venv\Scripts\Activate.ps1"

# ── 4. Upgrade pip (critical — pip < 22 can hang on installs) ──────────────────
Write-Step "Upgrading pip..."
python -m pip install --upgrade pip --quiet
Write-Ok "pip upgraded"

# ── 5. Install base dependencies (fast — no ML models) ───────────────────────
Write-Step "Installing base dependencies..."
pip install -r "$SDK\requirements.txt" --quiet
Write-Ok "Base dependencies installed"

# ── 6. Install contextcore CLI ────────────────────────────────────────────────
Write-Step "Installing contextcore CLI..."
pip install -e "$SDK" --quiet
Write-Ok "contextcore CLI installed"

# ── 7. Verify CLI works ─────────────────────────────────────────────────────────
Write-Step "Verifying CLI..."
$cliTest = contextcore --version 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Ok "contextcore CLI is ready"
} else {
    Write-Warn "Could not verify CLI in current session"
}

# ── 8. Done — hand off to the wizard in NEW TERMINAL ─────────────────────────
Write-Host ""
Write-Host "─────────────────────────────────────────" -ForegroundColor Cyan
Write-Host "  Installation complete!" -ForegroundColor Green  
Write-Host ""
Write-Host "  IMPORTANT: Open a NEW terminal/tab, then run:" -ForegroundColor White
Write-Host ""
Write-Host "    cd $SDK" -ForegroundColor Yellow
Write-Host "    .\.venv\Scripts\Activate.ps1" -ForegroundColor Yellow
Write-Host "    contextcore init" -ForegroundColor Yellow
Write-Host ""
Write-Host "  This will:" -ForegroundColor Gray
Write-Host "    - Configure your watched directories" -ForegroundColor Gray
Write-Host "    - Install ML models (CLIP, Whisper)" -ForegroundColor Gray
Write-Host "    - Start the backend server" -ForegroundColor Gray
Write-Host "    - Begin initial indexing" -ForegroundColor Gray
Write-Host "─────────────────────────────────────────" -ForegroundColor Cyan
Write-Host ""
