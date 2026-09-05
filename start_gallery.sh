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
# 2. Optional: ADB check
# ============================================================
if ! command -v adb >/dev/null 2>&1 && [ ! -f "$SCRIPT_DIR/bin/platform-tools/adb" ]; then
    log_warn "ADB (Android Debug Bridge) not found. USB phone sync will not work."
    echo ""
    echo "  To install ADB:"
    case "$(uname -s)" in
        Darwin)  echo "    macOS:  brew install android-platform-tools" ;;
        Linux)   echo "    Linux:  sudo apt install adb  (or: sudo dnf install android-tools)" ;;
    esac
    echo ""
fi

# ============================================================
# 3. Optional: ffmpeg check
# ============================================================
if ! command -v ffmpeg >/dev/null 2>&1 && [ ! -f "$SCRIPT_DIR/bin/ffmpeg" ]; then
    log_warn "ffmpeg not found. Video thumbnail generation will be unavailable."
    echo ""
    echo "  To install ffmpeg:"
    case "$(uname -s)" in
        Darwin)  echo "    macOS:  brew install ffmpeg" ;;
        Linux)   echo "    Linux:  sudo apt install ffmpeg  (or: sudo dnf install ffmpeg)" ;;
    esac
    echo ""
fi

# ============================================================
# 4. Self-healing venv bootstrap
# ============================================================
VENV_DIR="$SCRIPT_DIR/venv"
if [ ! -f "$VENV_DIR/bin/python" ]; then
    log_info "Creating Python virtual environment in ./venv ..."
    "$PYTHON_EXE" -m venv "$VENV_DIR"
    log_ok "Virtual environment created."
fi

if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    log_info "Installing/verifying dependencies from requirements.txt ..."
    "$VENV_DIR/bin/pip" install -q -r "$SCRIPT_DIR/requirements.txt" --no-warn-script-location
    log_ok "Dependencies ready."
fi

# ============================================================
# 5. Single-instance check
# ============================================================
if command -v curl >/dev/null 2>&1; then
    if curl -s -m 1 http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
        log_info "Gallery server already running. Opening browser..."
        case "$(uname -s)" in
            Darwin) open "http://127.0.0.1:8000/gallery.html" ;;
            Linux)  xdg-open "http://127.0.0.1:8000/gallery.html" 2>/dev/null || true ;;
        esac
        exit 0
    fi
fi

# ============================================================
# 6. Launch gallery server
# ============================================================
log_info "Starting WhatsApp Media Gallery server..."
"$VENV_DIR/bin/python" "$SCRIPT_DIR/wa_media_organizer.py" --serve --auto-open
