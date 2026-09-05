#!/usr/bin/env sh
# WhatsApp Media Organizer - Unix One-Step Setup Script
# Sets up the Python virtual environment without launching the server.
# Run this once after cloning, then use start_gallery.sh to launch.
#
# POSIX-compliant - syntax verified with: bash -n install.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ============================================================
# Color helpers
# ============================================================
if [ -t 1 ]; then
    C_GREEN='\033[0;32m' C_YELLOW='\033[1;33m' C_RED='\033[0;31m'
    C_CYAN='\033[0;36m'  C_BOLD='\033[1m'       C_RESET='\033[0m'
else
    C_GREEN='' C_YELLOW='' C_RED='' C_CYAN='' C_BOLD='' C_RESET=''
fi

log_ok()   { printf "${C_GREEN}[OK]${C_RESET}    %s\n" "$1"; }
log_info() { printf "${C_CYAN}[INFO]${C_RESET}  %s\n" "$1"; }
log_err()  { printf "${C_RED}[ERROR]${C_RESET} %s\n" "$1" >&2; }

printf "${C_BOLD}WhatsApp Media Organizer - Setup${C_RESET}\n"
printf "================================\n\n"

# ============================================================
# 1. Find Python >=3.10
# ============================================================
PYTHON_EXE=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        ver=$("$candidate" -c "import sys; print(sys.version_info >= (3,10))" 2>/dev/null || true)
        if [ "$ver" = "True" ]; then
            PYTHON_EXE="$candidate"
            log_ok "Python found: $($PYTHON_EXE --version 2>&1)"
            break
        fi
    fi
done

if [ -z "$PYTHON_EXE" ]; then
    log_err "Python 3.10+ required but not found."
    echo ""
    echo "  Install options:"
    case "$(uname -s)" in
        Darwin)
            echo "    brew install python@3.13"
            echo "    https://www.python.org/downloads/macos/"
            ;;
        Linux)
            echo "    Ubuntu/Debian: sudo apt install python3.12"
            echo "    Fedora/RHEL:   sudo dnf install python3.12"
            echo "    Arch:          sudo pacman -S python"
            ;;
        *)
            echo "    https://www.python.org/downloads/"
            ;;
    esac
    exit 1
fi

# ============================================================
# 2. Create / update venv
# ============================================================
VENV_DIR="$SCRIPT_DIR/venv"
if [ ! -f "$VENV_DIR/bin/python" ]; then
    log_info "Creating virtual environment in ./venv ..."
    "$PYTHON_EXE" -m venv "$VENV_DIR"
    log_ok "Virtual environment created."
else
    log_ok "Virtual environment already exists."
fi

# ============================================================
# 3. Install dependencies
# ============================================================
if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    log_info "Installing dependencies from requirements.txt ..."
    "$VENV_DIR/bin/pip" install -q --upgrade pip
    "$VENV_DIR/bin/pip" install -q -r "$SCRIPT_DIR/requirements.txt" --no-warn-script-location
    log_ok "All dependencies installed."
else
    log_err "requirements.txt not found in $SCRIPT_DIR"
    exit 1
fi

# ============================================================
# 4. Done
# ============================================================
printf "\n${C_GREEN}Setup complete!${C_RESET}\n"
printf "To start the gallery, run:\n\n"
printf "    ${C_BOLD}./start_gallery.sh${C_RESET}\n\n"
