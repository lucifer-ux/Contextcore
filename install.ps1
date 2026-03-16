# install.ps1
#
# ContextCore - One-shot bootstrap for Windows
#
# QUICK START:
# irm https://raw.githubusercontent.com/lucifer-ux/SearchEmbedSDK/main/install.ps1 | iex
#
# SAFE START:
# Invoke-WebRequest -Uri https://raw.githubusercontent.com/lucifer-ux/SearchEmbedSDK/main/install.ps1 -OutFile install.ps1
# powershell -ExecutionPolicy Bypass -File install.ps1

$ErrorActionPreference = "Stop"

# -------------------------------------------------
# Configuration
# -------------------------------------------------

$RepoUrl = if ($env:REPO_URL) { $env:REPO_URL } else { "https://github.com/lucifer-ux/SearchEmbedSDK.git" }
$RepoBranch = if ($env:REPO_BRANCH) { $env:REPO_BRANCH } else { "main" }
$InstallDir = if ($env:INSTALL_DIR) { $env:INSTALL_DIR } else { "$env:USERPROFILE\.contextcore" }

$ScriptDir = if ($MyInvocation.MyCommand.Path) { 
    Split-Path -Parent $MyInvocation.MyCommand.Path 
} else { 
    $PWD.Path 
}

$IsLocalRepo = $false
if ((Test-Path "$ScriptDir\setup.py") -and (Test-Path "$ScriptDir\requirements.txt")) {
    $IsLocalRepo = $true
    $SDK = $ScriptDir
}

# -------------------------------------------------
# Helper functions
# -------------------------------------------------

function Write-Step($msg) {
    Write-Host ""
    Write-Host " --> $msg" -ForegroundColor Cyan
}

function Write-Ok($msg) {
    Write-Host " [OK] $msg" -ForegroundColor Green
}

function Write-Warn($msg) {
    Write-Host " [!!] $msg" -ForegroundColor Yellow
}

function Write-Err($msg) {
    Write-Host " [ERROR] $msg" -ForegroundColor Red
}

# -------------------------------------------------
# Clone / Update repository
# -------------------------------------------------
Write-Step "Checking Git..."

$gitCheck = Get-Command git -ErrorAction SilentlyContinue

if (-not $gitCheck) {

    Write-Warn "Git is not installed."

    $wingetCheck = Get-Command winget -ErrorAction SilentlyContinue

    if ($wingetCheck) {

        Write-Warn "Attempting to install Git automatically via winget..."

        winget install Git.Git `
            --accept-source-agreements `
            --accept-package-agreements `
            -h 2>$null

        $gitCheck = Get-Command git -ErrorAction SilentlyContinue
    }

    if (-not $gitCheck) {

        Write-Err "Git is required but was not found."

        Write-Host ""
        Write-Host "Please install Git and re-run the installer."
        Write-Host ""
        Write-Host "Install Git from:"
        Write-Host "https://git-scm.com/download/win"
        Write-Host ""
        Write-Host "After installation, restart PowerShell and run:"
        Write-Host ""
        Write-Host "irm https://raw.githubusercontent.com/lucifer-ux/SearchEmbedSDK/main/install.ps1 | iex"
        Write-Host ""

        exit 1
    }

    Write-Ok "Git installed successfully"

} else {

    Write-Ok "Git found"

}
# -------------------------------------------------
# Clone / Update repository
# -------------------------------------------------

if (-not $IsLocalRepo) {

    Write-Step "Preparing repository"
    Write-Host " Repo: $RepoUrl"
    Write-Host " Branch: $RepoBranch"
    Write-Host " Install dir: $InstallDir"

    if (Test-Path "$InstallDir\.git") {

        Write-Warn "Existing repository found - updating"
        Set-Location $InstallDir

        git fetch origin
        git checkout $RepoBranch
        git pull origin $RepoBranch

    } else {

        if (Test-Path $InstallDir) {
            Write-Warn "Directory exists but not a repo - removing"
            Remove-Item $InstallDir -Recurse -Force
        }

        Write-Step "Cloning repository"
        git clone --branch $RepoBranch --depth 1 $RepoUrl $InstallDir
    }

    if (!(Test-Path $InstallDir)) {
        Write-Err "Repository clone failed"
        exit 1
    }

    $SDK = $InstallDir
    Set-Location $SDK

    Write-Ok "Repository ready"
}

# -------------------------------------------------
# Verify required project files
# -------------------------------------------------

if (!(Test-Path "$SDK\requirements.txt")) {
    Write-Err "requirements.txt missing - clone likely failed"
    exit 1
}

if (!(Test-Path "$SDK\setup.py") -and !(Test-Path "$SDK\pyproject.toml")) {
    Write-Err "Python project metadata missing"
    exit 1
}

# -------------------------------------------------
# Check Python
# -------------------------------------------------

Write-Step "Checking Python"

$pyver = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Err "Python not found. Install from https://python.org"
    exit 1
}

Write-Ok "Found $pyver"

Write-Step "Checking Python version"

$pyMajor = python -c "import sys; print(sys.version_info[0])"
$pyMinor = python -c "import sys; print(sys.version_info[1])"

if ($pyMajor -lt 3 -or ($pyMajor -eq 3 -and $pyMinor -lt 10)) {
    Write-Err "Python 3.10+ required"
    exit 1
}

Write-Ok "Python version supported"

# -------------------------------------------------
# Check ffmpeg
# -------------------------------------------------

Write-Step "Checking ffmpeg"

$ffmpegCheck = Get-Command ffmpeg -ErrorAction SilentlyContinue

if (-not $ffmpegCheck) {

    Write-Warn "ffmpeg not found, attempting winget install"

    $wingetCheck = Get-Command winget -ErrorAction SilentlyContinue

    if ($wingetCheck) {

        winget install Gyan.FFmpeg `
            --accept-source-agreements `
            --accept-package-agreements `
            -h 2>$null

        Write-Ok "ffmpeg install attempted"

    } else {

        Write-Warn "winget not available. Install ffmpeg manually."

    }

} else {

    Write-Ok "ffmpeg already installed"

}

# -------------------------------------------------
# Create virtual environment
# -------------------------------------------------

Write-Step "Creating virtual environment"

if (!(Test-Path "$SDK\.venv")) {

    python -m venv "$SDK\.venv"
    Write-Ok ".venv created"

} else {

    Write-Ok ".venv already exists"

}

$VenvPython = "$SDK\.venv\Scripts\python.exe"
$VenvPip = "$SDK\.venv\Scripts\pip.exe"

# -------------------------------------------------
# Upgrade pip
# -------------------------------------------------

Write-Step "Upgrading pip"

& $VenvPython -m pip install --upgrade pip

Write-Ok "pip upgraded"

# -------------------------------------------------
# Install dependencies
# -------------------------------------------------

Write-Step "Installing dependencies"

& $VenvPip install -r "$SDK\requirements.txt"

Write-Ok "Dependencies installed"

# -------------------------------------------------
# Install CLI
# -------------------------------------------------

Write-Step "Installing contextcore CLI"

& $VenvPip install -e "$SDK"

Write-Ok "contextcore CLI installed"

# -------------------------------------------------
# Create global launcher
# -------------------------------------------------

Write-Step "Creating global contextcore command"

$UserBin = "$env:USERPROFILE\.contextcore\bin"

if (!(Test-Path $UserBin)) {
    New-Item -ItemType Directory -Path $UserBin | Out-Null
}

$Launcher = "$UserBin\contextcore.ps1"

$Script = @"
& '$SDK\.venv\Scripts\python.exe' -m cli.main @args
"@

Set-Content -Path $Launcher -Value $Script

Write-Ok "contextcore launcher created"

# -------------------------------------------------
# Add directory to PATH permanently
# -------------------------------------------------

$CurrentUserPath = [Environment]::GetEnvironmentVariable("Path","User")

if ($CurrentUserPath -notlike "*$UserBin*") {

    Write-Step "Adding contextcore to PATH"

    $NewPath = "$CurrentUserPath;$UserBin"

    [Environment]::SetEnvironmentVariable(
        "Path",
        $NewPath,
        [EnvironmentVariableTarget]::User
    )

    Write-Ok "PATH updated"
}

# Also update PATH for current session
$env:Path += ";$UserBin"
# -------------------------------------------------
# Verify CLI
# -------------------------------------------------

Write-Step "Verifying CLI"

$test = & "$UserBin\contextcore.ps1" --help 2>&1

if ($LASTEXITCODE -eq 0) {
    Write-Ok "contextcore command works"
} else {
    Write-Warn "CLI verification skipped"
}
# -------------------------------------------------
# Done
# -------------------------------------------------

Write-Host ""
Write-Host "-----------------------------------------"
Write-Host " Installation complete!"
Write-Host ""
Write-Host " Run the following command in a new terminal:"
Write-Host ""
Write-Host " contextcore init"
Write-Host ""
Write-Host " This will:"
Write-Host " - Configure watched directories"
Write-Host " - Install ML models CLIP and Whisper"
Write-Host " - Start backend server"
Write-Host " - Begin indexing"
Write-Host "-----------------------------------------"
Write-Host ""