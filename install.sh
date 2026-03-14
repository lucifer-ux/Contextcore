#!/bin/bash
#
# ContextCore — One-shot bootstrap for macOS / Linux
#
# QUICK START (pipe to bash - review first!):
#   curl -sL https://your-domain.com/install.sh | bash
#
# SAFE START (download and inspect first):
#   curl -sL https://your-domain.com/install.sh -o install.sh
#   chmod +x install.sh && ./install.sh
#
# LOCAL DEVELOPMENT:
#   chmod +x install.sh && ./install.sh

set -euo pipefail

SDK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;90m'
NC='\033[0m'

trap 'last_exit=$?; if [ $last_exit -ne 0 ]; then echo -e "\n${RED}Installation failed (exit code: $last_exit)${NC}"; fi' EXIT

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

# ── 1. Check Python ────────────────────────────────────────────────────────────
write_step "Checking Python..."
if command -v python3 &> /dev/null; then
    PYTHON=python3
    PYVER=$(python3 --version 2>&1)
elif command -v python &> /dev/null; then
    PYTHON=python
    PYVER=$(python --version 2>&1)
else
    write_error "Python not found. Download from https://python.org/downloads"
    exit 1
fi

# ── 2. Check Python version (require >= 3.10) ─────────────────────────────────
write_step "Checking Python version..."
PYTHON_VERSION=$($PYTHON -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
PYTHON_MAJOR=$($PYTHON -c 'import sys; print(sys.version_info[0])')
PYTHON_MINOR=$($PYTHON -c 'import sys; print(sys.version_info[1])')

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]); then
    write_error "Python 3.10+ required, found $PYTHON_VERSION"
    exit 1
fi
write_ok "Found Python $PYTHON_VERSION"

# ── 3. Check/Install ffmpeg (for video indexing) ───────────────────────────────
write_step "Checking ffmpeg (for video indexing)..."
if command -v ffmpeg &> /dev/null; then
    write_ok "ffmpeg already installed"
else
    write_warn "ffmpeg not found. Attempting to install..."
    
    if command -v brew &> /dev/null; then
        brew install ffmpeg
        write_ok "ffmpeg installed via Homebrew"
    elif command -v apt-get &> /dev/null; then
        sudo apt-get update && sudo apt-get install -y ffmpeg
        write_ok "ffmpeg installed via apt"
    elif command -v yum &> /dev/null; then
        sudo yum install -y ffmpeg
        write_ok "ffmpeg installed via yum"
    elif command -v dnf &> /dev/null; then
        sudo dnf install -y ffmpeg
        write_ok "ffmpeg installed via dnf"
    else
        write_warn "Could not auto-install ffmpeg. Install manually:"
        echo -e "    macOS:  brew install ffmpeg${GRAY}"
        echo -e "    Ubuntu: sudo apt install ffmpeg${GRAY}"
    fi
fi

# ── 4. Create venv ────────────────────────────────────────────────────────────
write_step "Creating virtual environment..."
if [ ! -d "$SDK_DIR/.venv" ]; then
    $PYTHON -m venv "$SDK_DIR/.venv"
    write_ok "Created .venv"
else
    write_ok ".venv already exists, reusing"
fi

# Get venv Python path (use explicitly instead of relying on activation)
VENV_PYTHON="$SDK_DIR/.venv/bin/python"
VENV_PIP="$SDK_DIR/.venv/bin/pip"

# ── 5. Upgrade pip (critical — pip < 22 can hang on installs) ──────────────────
write_step "Upgrading pip..."
$VENV_PYTHON -m pip install --upgrade pip
write_ok "pip upgraded"

# ── 6. Install base dependencies ──────────────────────────────────────────────
write_step "Installing base dependencies..."
$VENV_PIP install -r "$SDK_DIR/requirements.txt"
write_ok "Base dependencies installed"

# ── 7. Install contextcore CLI (editable install - idempotent) ─────────────────
write_step "Installing contextcore CLI..."
$VENV_PIP install -e "$SDK_DIR"
write_ok "contextcore CLI installed"

# ── 8. Verify CLI works ─────────────────────────────────────────────────────────
write_step "Verifying CLI..."
if "$VENV_PYTHON" -m cli.main --version &> /dev/null; then
    write_ok "contextcore CLI is ready"
else
    write_warn "Could not verify CLI in current session"
fi

# ── 9. Done — hand off to the wizard in NEW TERMINAL ─────────────────────────
trap - EXIT

echo ""
echo -e "─────────────────────────────────────────${CYAN}"
echo -e "  Installation complete!${GREEN}"  
echo ""
echo -e "  IMPORTANT: Open a NEW terminal/tab, then run:${NC}"
echo ""
echo -e "    cd $SDK_DIR ${YELLOW}"
echo -e "    source .venv/bin/activate ${YELLOW}"
echo -e "    contextcore init ${YELLOW}"
echo ""
echo -e "  This will:${GRAY}"
echo -e "    - Configure your watched directories${NC}"
echo -e "    - Install ML models (CLIP, Whisper)${NC}"
echo -e "    - Start the backend server${NC}"
echo -e "    - Begin initial indexing${NC}"
echo -e "─────────────────────────────────────────${CYAN}"
echo ""
