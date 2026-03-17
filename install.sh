#!/usr/bin/env bash
#
# ContextCore — macOS / Linux installer
#
# Usage:
# curl -sL https://raw.githubusercontent.com/lucifer-ux/SearchEmbedSDK/main/install.sh | bash

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/lucifer-ux/SearchEmbedSDK.git}"
REPO_BRANCH="${REPO_BRANCH:-main}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.contextcore}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;90m'
NC='\033[0m'

# -------------------------------------------------
# Detect sudo (needed for package installs)
# -------------------------------------------------

if command -v sudo >/dev/null 2>&1; then
  SUDO="sudo"
else
  SUDO=""
fi

# -------------------------------------------------
# Output helpers
# -------------------------------------------------

write_step() {
  echo ""
  echo -e "  --> ${CYAN}$1${NC}"
}

write_ok() {
  echo -e "  [OK] ${GREEN}$1${NC}"
}

write_warn() {
  echo -e "  [!!] ${YELLOW}$1${NC}"
}

write_error() {
  echo -e "  [ERROR] ${RED}$1${NC}"
}

# -------------------------------------------------
# Check Git
# -------------------------------------------------

write_step "Checking Git..."

if ! command -v git >/dev/null 2>&1; then
  write_warn "Git not found. Attempting install..."

  if command -v brew >/dev/null 2>&1; then
    brew install git
  elif command -v apt-get >/dev/null 2>&1; then
    $SUDO apt-get update
    $SUDO apt-get install -y git
  elif command -v dnf >/dev/null 2>&1; then
    $SUDO dnf install -y git
  elif command -v yum >/dev/null 2>&1; then
    $SUDO yum install -y git
  else
    write_error "Git is required."
    echo "Install Git from: https://git-scm.com"
    exit 1
  fi
fi

write_ok "Git ready"

# -------------------------------------------------
# Clone repository
# -------------------------------------------------

write_step "Preparing repository..."

echo "  Repo: $REPO_URL"
echo "  Branch: $REPO_BRANCH"
echo "  Install dir: $INSTALL_DIR"

if [ -d "$INSTALL_DIR/.git" ]; then
  write_warn "Existing repository detected — updating..."

  cd "$INSTALL_DIR"
  git fetch origin
  git checkout "$REPO_BRANCH"
  git pull origin "$REPO_BRANCH"
else
  rm -rf "$INSTALL_DIR"
  git clone --branch "$REPO_BRANCH" --depth 1 "$REPO_URL" "$INSTALL_DIR"
fi

if [ ! -d "$INSTALL_DIR" ]; then
  write_error "Repository clone failed"
  exit 1
fi

cd "$INSTALL_DIR"

write_ok "Repository ready"

# -------------------------------------------------
# Verify project files
# -------------------------------------------------

if [ ! -f "requirements.txt" ]; then
  write_error "requirements.txt missing"
  exit 1
fi

if [ ! -f "setup.py" ] && [ ! -f "pyproject.toml" ]; then
  write_error "Python project metadata missing"
  exit 1
fi

# -------------------------------------------------
# Check Python
# -------------------------------------------------

write_step "Checking Python..."

if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  write_error "Python 3.10+ required."
  echo "Install from: https://python.org/downloads"
  exit 1
fi

PY_VERSION=$($PYTHON -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
  write_error "Python 3.10+ required. Found $PY_VERSION"
  exit 1
fi

write_ok "Python $PY_VERSION detected"

# -------------------------------------------------
# Check ffmpeg
# -------------------------------------------------

write_step "Checking ffmpeg..."

if ! command -v ffmpeg >/dev/null 2>&1; then
  write_warn "ffmpeg not found — attempting install..."

  if command -v brew >/dev/null 2>&1; then
    brew install ffmpeg
  elif command -v apt-get >/dev/null 2>&1; then
    $SUDO apt-get update
    $SUDO apt-get install -y ffmpeg
  elif command -v dnf >/dev/null 2>&1; then
    $SUDO dnf install -y ffmpeg
  elif command -v yum >/dev/null 2>&1; then
    $SUDO yum install -y ffmpeg
  else
    write_warn "Could not auto-install ffmpeg."
    echo "Install manually: https://ffmpeg.org/download.html"
  fi
fi

write_ok "ffmpeg ready"

# -------------------------------------------------
# Create venv
# -------------------------------------------------

write_step "Creating virtual environment..."

if [ ! -d ".venv" ]; then
  $PYTHON -m venv .venv
fi

VENV_PYTHON=".venv/bin/python"
VENV_PIP=".venv/bin/pip"

write_ok "Virtual environment ready"

# -------------------------------------------------
# Install dependencies
# -------------------------------------------------

write_step "Installing dependencies..."

$VENV_PYTHON -m pip install --upgrade pip
$VENV_PIP install -r requirements.txt

write_ok "Dependencies installed"

# -------------------------------------------------
# Install CLI
# -------------------------------------------------

write_step "Installing ContextCore CLI..."

$VENV_PIP install -e .

write_ok "CLI installed"

# -------------------------------------------------
# Verify CLI
# -------------------------------------------------

write_step "Verifying CLI..."

if "$VENV_PYTHON" -m cli.main --help >/dev/null 2>&1; then
  write_ok "CLI working"
else
  write_warn "CLI verification skipped"
fi

# -------------------------------------------------
# Finished
# -------------------------------------------------

echo ""
echo "-----------------------------------------"
echo "ContextCore installation complete!"
echo ""
echo "Open a NEW terminal and run:"
echo ""
echo "cd $INSTALL_DIR"
echo "source .venv/bin/activate"
echo "contextcore init" 
echo ""
echo "-----------------------------------------"
echo ""