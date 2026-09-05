"""
WhatsApp Media Organizer - Configuration and Environment Settings.
Manages application defaults, configuration persistence, and path helpers.
"""

import json
import os
import sys
from pathlib import Path

DEFAULT_DB_DIR = "./Databases"
DEFAULT_MEDIA_DIR = "./output"
DEFAULT_OUTPUT_DIR = "./output"
DEFAULT_KEY_FILE = "encrypted_backup.key"
DEFAULT_CONTACTS_CACHE = "contacts_map.json"
DEFAULT_CONFIG_FILE = "config.json"
DEFAULT_PORT = 8000
DEFAULT_IDLE_TIMEOUT = 45  # In minutes. Set to 0 to disable.

# Windows MAX_PATH length threshold
WINDOWS_MAX_PATH = 260


def to_long_path(path_input):
    """
    Ensures that a path on Windows uses the extended-length prefix (\\\\?\\)
    if it approaches or exceeds the MAX_PATH limit (260 characters).
    """
    path_str = str(path_input)
    if sys.platform == "win32":
        resolved = os.path.abspath(path_str)
        if len(resolved) >= 240 and not resolved.startswith("\\\\?\\"):
            if resolved.startswith("\\\\"):
                # UNC path: \\server\share -> \\?\UNC\server\share
                return "\\\\?\\UNC\\" + resolved[2:]
            return "\\\\?\\" + resolved
        return resolved
    return path_str


def find_ffmpeg_binary(custom_path=None):
    """
    Locates the ffmpeg executable on the system.
    Checks custom path, bundled local bin directories, and system PATH.
    """
    if custom_path and os.path.isfile(custom_path):
        return custom_path

    app_root = Path(__file__).resolve().parent.parent
    exe_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    bundled_candidates = [
        app_root / "bin" / exe_name,
        app_root / "bin" / "ffmpeg" / exe_name,
        app_root / "ffmpeg" / exe_name,
    ]
    for candidate in bundled_candidates:
        if candidate.is_file():
            return str(candidate)

    import shutil
    found = shutil.which("ffmpeg")
    if found:
        return found

    return "ffmpeg"


def mask_key(hex_key):
    """
    Returns a masked representation of a 64-character hex key for safe UI display.
    Example: 'a3f8' + 56 asterisks + 'e19b'
    """
    if not hex_key or len(hex_key) < 8:
        return ""
    if len(hex_key) == 64:
        return f"{hex_key[:4]}{'*' * 56}{hex_key[-4:]}"
    # Generic masking for non-standard lengths
    visible = min(4, len(hex_key) // 4)
    masked_count = len(hex_key) - (visible * 2)
    return f"{hex_key[:visible]}{'*' * masked_count}{hex_key[-visible:]}"


def load_config(config_path=DEFAULT_CONFIG_FILE):
    """
    Loads persisted user configuration from config.json.
    Returns a dictionary of settings with safe defaults.
    """
    cfg_file = Path(config_path)
    defaults = {
        "hex_key": "",
        "mode": "copy",
        "port": DEFAULT_PORT,
        "idle_timeout": DEFAULT_IDLE_TIMEOUT,
        "output_dir": DEFAULT_OUTPUT_DIR,
        "media_dir": DEFAULT_MEDIA_DIR,
        "db_dir": DEFAULT_DB_DIR,
        "allow_lan": False,
        "onboarding_completed": False,
    }
    if not cfg_file.exists():
        return defaults

    try:
        with open(cfg_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            defaults.update(data)
    except Exception as e:
        sys.stderr.write(f"[Config] Warning: Failed to parse {config_path}: {e}\n")

    return defaults


def save_config(config_data, config_path=DEFAULT_CONFIG_FILE):
    """
    Atomically writes user configuration to config.json.
    """
    cfg_file = Path(config_path)
    temp_file = cfg_file.with_suffix(".tmp")

    existing = load_config(config_path)
    existing.update(config_data)

    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)
        os.replace(temp_file, cfg_file)
        return True
    except Exception as e:
        sys.stderr.write(f"[Config] Error saving {config_path}: {e}\n")
        if temp_file.exists():
            try:
                os.remove(temp_file)
            except OSError:
                pass
        return False
