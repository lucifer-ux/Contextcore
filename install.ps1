# install.ps1
# ContextCore Windows Installer

$ErrorActionPreference = "Stop"

# -------------------------------------------------
# Configuration
# -------------------------------------------------

$RepoUrl = "https://github.com/lucifer-ux/SearchEmbedSDK.git"
$RepoBranch = "main"
$InstallDir = "$env:USERPROFILE\.contextcore"

# -------------------------------------------------
# Helper functions
# -------------------------------------------------

function Write-Step($msg) { Write-Host "`n--> $msg" -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[!!] $msg" -ForegroundColor Yellow }
function Write-Err($msg) { Write-Host "[ERROR] $msg" -ForegroundColor Red }

function Refresh-Path {
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path","User")
}

# -------------------------------------------------
# Check winget
# -------------------------------------------------

$winget = Get-Command winget -ErrorAction SilentlyContinue
if (-not $winget) {
    Write-Err "winget is required but not available."
    Write-Host "Please install Git and Python manually."
    return
}

# -------------------------------------------------
# Check Git
# -------------------------------------------------

Write-Step "Checking Git"

$git = Get-Command git -ErrorAction SilentlyContinue

if (-not $git) {

    Write-Warn "Git not found, installing..."

    winget install Git.Git `
        --accept-source-agreements `
        --accept-package-agreements `
        -h

    Refresh-Path
    $git = Get-Command git -ErrorAction SilentlyContinue
}

if (-not $git) {
    Write-Err "Git installation failed."
    Write-Host "Install Git manually from https://git-scm.com/download/win"
    return
}

Write-Ok "Git found"

# -------------------------------------------------
# Check Python
# -------------------------------------------------

Write-Step "Checking Python"

$python = Get-Command python -ErrorAction SilentlyContinue

if (-not $python) {

    Write-Warn "Python not found, installing..."

    winget install Python.Python.3.11 `
        --accept-source-agreements `
        --accept-package-agreements `
        -h

    Refresh-Path
    $python = Get-Command python -ErrorAction SilentlyContinue
}

if (-not $python) {
    Write-Err "Python installation failed."
    Write-Host "Install Python from https://python.org"
    return
}

$pyver = python --version
Write-Ok "$pyver"

# -------------------------------------------------
# Clone repository
# -------------------------------------------------

Write-Step "Preparing repository"

if (Test-Path "$InstallDir\.git") {

    Write-Warn "Existing repository detected, updating..."

    Set-Location $InstallDir
    git fetch origin
    git checkout $RepoBranch
    git pull origin $RepoBranch

} else {

    if (Test-Path $InstallDir) {
        Remove-Item $InstallDir -Recurse -Force
    }

    git clone --branch $RepoBranch --depth 1 $RepoUrl $InstallDir
}

if (!(Test-Path $InstallDir)) {
    Write-Err "Repository clone failed"
    return
}

$SDK = $InstallDir
Set-Location $SDK

Write-Ok "Repository ready"

# -------------------------------------------------
# Check ffmpeg
# -------------------------------------------------

Write-Step "Checking ffmpeg"

$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue

if (-not $ffmpeg) {

    Write-Warn "Installing ffmpeg..."

    winget install Gyan.FFmpeg `
        --accept-source-agreements `
        --accept-package-agreements `
        -h

    Refresh-Path
}

Write-Ok "ffmpeg ready"

# -------------------------------------------------
# Create virtual environment
# -------------------------------------------------

Write-Step "Creating Python environment"

if (!(Test-Path "$SDK\.venv")) {
    python -m venv "$SDK\.venv"
}

$VenvPython = "$SDK\.venv\Scripts\python.exe"
$VenvPip = "$SDK\.venv\Scripts\pip.exe"

Write-Ok "Virtual environment ready"

# -------------------------------------------------
# Install dependencies
# -------------------------------------------------

Write-Step "Installing dependencies"

& $VenvPython -m pip install --upgrade pip
& $VenvPip install -r "$SDK\requirements.txt"

Write-Ok "Dependencies installed"

# -------------------------------------------------
# Install CLI
# -------------------------------------------------

Write-Step "Installing contextcore CLI"

& $VenvPip install -e "$SDK"

Write-Ok "CLI installed"

# -------------------------------------------------
# Create global launcher
# -------------------------------------------------

Write-Step "Creating global command"

$UserBin = "$env:USERPROFILE\.contextcore\bin"

if (!(Test-Path $UserBin)) {
    New-Item -ItemType Directory -Path $UserBin | Out-Null
}

$Launcher = "$UserBin\contextcore.ps1"

@"
& '$SDK\.venv\Scripts\python.exe' -m cli.main @args
"@ | Set-Content $Launcher

# Add to PATH permanently
$currentPath = [Environment]::GetEnvironmentVariable("Path","User")

if ($currentPath -notlike "*$UserBin*") {

    [Environment]::SetEnvironmentVariable(
        "Path",
        "$currentPath;$UserBin",
        [EnvironmentVariableTarget]::User
    )

}

$env:Path += ";$UserBin"

Write-Ok "contextcore command ready"

# -------------------------------------------------
# Verify CLI
# -------------------------------------------------

Write-Step "Verifying CLI"

$test = & "$UserBin\contextcore.ps1" --help 2>&1

if ($LASTEXITCODE -eq 0) {
    Write-Ok "CLI working"
}

# -------------------------------------------------
# Done
# -------------------------------------------------

Write-Host ""
Write-Host "-----------------------------------------"
Write-Host "Installation complete!"
Write-Host ""
Write-Host "Open a NEW terminal and run:"
Write-Host ""
Write-Host "contextcore init"
Write-Host ""
Write-Host "-----------------------------------------"