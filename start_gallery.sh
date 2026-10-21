#!/usr/bin/env sh
# WhatsApp Media Organizer - Unix Companion Launcher
# Compatible with: bash, dash, sh, zsh on macOS and Linux
# POSIX-compliant - syntax verified with: bash -n start_gallery.sh
#
# NOTE: This script is provided as a Companion POSIX Shell Script.
# It has been written to POSIX standards and syntax-validated on Windows via
# "bash -n start_gallery.sh". Live execution on macOS/Linux is not available
# from the development environment. If you encounter issues, please open a
# GitHub Issue with your OS version and error output.

set -e

# ============================================================
# Color helpers (degrade gracefully if no tty)
# ============================================================
if [ -t 1 ]; then
    C_GREEN='\033[0;32m'
    C_YELLOW='\033[1;33m'
    C_RED='\033[0;31m'
    C_CYAN='\033[0;36m'
    C_RESET='\033[0m'
else
    C_GREEN='' C_YELLOW='' C_RED='' C_CYAN='' C_RESET=''
fi

log_ok()   { printf "${C_GREEN}[OK]${C_RESET}    %s\n" "$1"; }
log_info() { printf "${C_CYAN}[INFO]${C_RESET}  %s\n" "$1"; }
log_warn() { printf "${C_YELLOW}[WARN]${C_RESET}  %s\n" "$1"; }
log_err()  { printf "${C_RED}[ERROR]${C_RESET} %s\n" "$1" >&2; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ============================================================
# 1. Python version detection (>=3.10 required)
# ============================================================
PYTHON_EXE=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        ver=$("$candidate" -c "import sys; print(sys.version_info >= (3,10))" 2>/dev/null || true)
        if [ "$ver" = "True" ]; then
            PYTHON_EXE="$candidate"
            log_ok "Found Python: $($PYTHON_EXE --version 2>&1)"
            break
        fi
    fi
done

if [ -z "$PYTHON_EXE" ]; then
    log_err "Python 3.10 or later is required but was not found."
    echo ""
    echo "  To install Python:"
    case "$(uname -s)" in
        Darwin)
            echo "    macOS:  brew install python@3.13"
            echo "    Or download from: https://www.python.org/downloads/macos/"
            ;;
        Linux)
            echo "    Ubuntu/Debian:  sudo apt install python3.12"
            echo "    Fedora/RHEL:    sudo dnf install python3.12"
            echo "    Arch:           sudo pacman -S python"
            ;;
    esac
    exit 1
fi

# ============================================================
# 2. Single-instance check (before anything slow)
# ============================================================
if command -v curl >/dev/null 2>&1; then
    # -f fails on HTTP errors and grep checks it is this app, not another program on port 8000.
    # (A gallery on another port or folder is found by the app itself: see core/instance.py.)
    if curl -s -f -m 1 http://127.0.0.1:8000/api/health 2>/dev/null | grep -q "wa-media-organizer"; then
        log_info "Gallery server already running. Opening browser..."
        case "$(uname -s)" in
            Darwin) open "http://127.0.0.1:8000/gallery.html" ;;
            Linux)  xdg-open "http://127.0.0.1:8000/gallery.html" 2>/dev/null || true ;;
        esac
        exit 0
    fi
fi

# ============================================================
# 3. Self-healing venv bootstrap
#    Dependencies are installed only when the venv is new or requirements.txt changed, so a
#    normal launch never goes online (pip would otherwise contact PyPI on every start).
# ============================================================
VENV_DIR="$SCRIPT_DIR/venv"
if [ ! -f "$VENV_DIR/bin/python" ]; then
    log_info "Creating Python virtual environment in ./venv ..."
    "$PYTHON_EXE" -m venv "$VENV_DIR"
    log_ok "Virtual environment created."
fi

TOOLS_ARG=""
if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    REQ_STAMP="$VENV_DIR/.requirements.cksum"
    REQ_SUM="$(cat "$SCRIPT_DIR/requirements.txt" "$SCRIPT_DIR/core/requirements-optional.txt" 2>/dev/null | cksum)"
    if [ ! -f "$REQ_STAMP" ] || [ "$(cat "$REQ_STAMP")" != "$REQ_SUM" ]; then
        log_info "Installing dependencies from requirements.txt ..."
        "$VENV_DIR/bin/pip" install -q --disable-pip-version-check -r "$SCRIPT_DIR/requirements.txt" --no-warn-script-location
        printf '%s' "$REQ_SUM" > "$REQ_STAMP"
        log_ok "Dependencies ready."
        TOOLS_ARG="--setup"  # already online for pip: also fetch ADB if it is missing
    fi
fi

# ============================================================
# 4. Phone (ADB) and video (ffmpeg) tools
#    Downloads ADB only together with the dependency install above; otherwise just reports.
# ============================================================
"$VENV_DIR/bin/python" -m core.platform_tools $TOOLS_ARG || true

# ============================================================
# 5. Launch gallery server
# ============================================================
log_info "Starting WhatsApp Media Gallery server..."
"$VENV_DIR/bin/python" "$SCRIPT_DIR/wa_media_organizer.py" --serve --auto-open
