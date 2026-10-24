"""
WhatsApp Media Organizer - Configuration and Environment Settings.
Manages application defaults, configuration persistence, and path helpers.
"""

import json
import threading
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

    # macOS / Linux: the ffmpeg that the imageio-ffmpeg package (requirements.txt) installs
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass

    return "ffmpeg"


def is_ffmpeg_available(custom_path=None) -> bool:
    """
    Checks if a functional ffmpeg binary is available on the system or bundled locally.
    """
    bin_path = find_ffmpeg_binary(custom_path)
    if os.path.isabs(bin_path) and os.path.isfile(bin_path):
        return True
    import shutil
    return bool(shutil.which(bin_path))


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


# Settings of one account's library. Each WhatsApp account on a phone gets its own library: its
# own output folder, decrypted database, key and gallery server (one browser tab each). A server
# started for an account (set_active_profile) reads and writes these in config.json's
# "profiles"[<account folder>]; everything else (and the first account's library) stays top level.
PROFILE_KEYS = frozenset({
    "hex_key", "hex_key_account", "key_file", "db_dir", "output_dir", "media_dir", "skip_db_pull",
    "selected_account_path", "selected_account_id", "selected_account_phone", "selected_app_type",
    "selected_account_label", "last_sync_time", "account_folder_verdicts",
    # phone cleanup choices name this account's chats
    "exclude_jids", "include_jids", "chat_scope", "keep_starred", "min_age_days", "min_size_bytes",
    "media_types", "large_video_min_age", "large_video_min_bytes", "archived_min_age",
    "target_archived", "inactive_group_threshold_days", "inactive_group_min_age", "target_inactive_groups",
})
_active_profile = {"account": None}


def set_active_profile(account_path):
    """This process serves the library of the account in account_path (None: the first library)."""
    _active_profile["account"] = account_path or None


def active_profile():
    return _active_profile["account"]


def _config_defaults():
    return {
        "hex_key": "",
        "mode": "copy",
        "port": DEFAULT_PORT,
        "idle_timeout": DEFAULT_IDLE_TIMEOUT,
        "output_dir": DEFAULT_OUTPUT_DIR,
        "media_dir": DEFAULT_MEDIA_DIR,
        "db_dir": DEFAULT_DB_DIR,
        "allow_lan": False,
        "auto_check_updates": False,
        "last_update_check": 0,
        "onboarding_completed": False,
        "selected_account_path": "",
        "selected_account_id": "",
        "selected_account_phone": "",
        "selected_app_type": "",
        "selected_account_label": "",
    }


def _load_file_config(config_path):
    """config.json as stored (top level and profiles), over the defaults."""
    data = _config_defaults()
    cfg_file = Path(config_path)
    if cfg_file.exists():
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                data.update(stored)
        except Exception as e:
            sys.stderr.write(f"[Config] Warning: Failed to parse {config_path}: {e}\n")
    return data


def load_config(config_path=DEFAULT_CONFIG_FILE):
    """
    Loads persisted user configuration from config.json.
    Returns a dictionary of settings with safe defaults. A server started for an account's library
    sees that library's settings (PROFILE_KEYS) in place of the first library's.
    """
    data = _load_file_config(config_path)
    account = active_profile()
    if account:
        profile = (data.get("profiles") or {}).get(account) or {}
        defaults = _config_defaults()
        for k in PROFILE_KEYS:
            if k in profile:
                data[k] = profile[k]
            elif k in defaults:
                data[k] = defaults[k]
            else:
                data.pop(k, None)
    return data


class _InterprocessLock:
    """Several gallery servers (one per account) share config.json: one read-modify-write at a time."""

    def __init__(self, path, timeout=5.0):
        self.path = f"{path}.lock"
        self.timeout = timeout
        self.held = False

    def __enter__(self):
        import time
        deadline = time.time() + self.timeout
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                self.held = True
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.path) > 10:
                        os.remove(self.path)  # left by a process that died mid-save
                        continue
                except OSError:
                    continue
                if time.time() >= deadline:
                    return self  # never block a save for good
                time.sleep(0.02)
            except OSError:
                return self  # read-only folder: nothing to lock

    def __exit__(self, *exc):
        if self.held:
            try:
                os.remove(self.path)
            except OSError:
                pass
        return False


_config_lock = threading.RLock()


def save_config(config_data, config_path=DEFAULT_CONFIG_FILE):
    """
    Atomically writes user configuration to config.json.
    Serialized: the sync, the guided setup and the settings page save at the same time, and each
    save reads the file first; unserialized, one could read a half-written file and write back the
    defaults (losing the backup key). Each write uses its own temporary file. Across processes too:
    each account's gallery server saves to the same file.
    """
    import tempfile
    import time

    cfg_file = Path(config_path)
    config_data = {k: v for k, v in dict(config_data).items() if k != "profiles"}
    with _config_lock, _InterprocessLock(cfg_file):
        existing = _load_file_config(config_path)
        account = active_profile()
        if account:
            profiles = dict(existing.get("profiles") or {})
            scope = dict(profiles.get(account) or {})
            profiles[account] = scope
            existing["profiles"] = profiles
        else:
            scope = existing
        previous_key = scope.get("hex_key") or ""
        for k, v in config_data.items():
            (scope if (account and k in PROFILE_KEYS) else existing)[k] = v
        if "hex_key" in config_data and (config_data.get("hex_key") or "") != previous_key:
            # A new key has not opened any account's backup yet
            if "hex_key_account" not in config_data:
                scope["hex_key_account"] = None
            if not config_data.get("hex_key"):
                # Deleting the key also forgets it as this account's remembered key
                keys = dict(existing.get("account_keys") or {})
                keys.pop(scope.get("selected_account_path") or "", None)
                existing["account_keys"] = keys
        text = json.dumps(existing, indent=2)

        for attempt in range(5):
            temp_name = None
            try:
                fd, temp_name = tempfile.mkstemp(prefix=cfg_file.name + ".", suffix=".tmp",
                                                 dir=str(cfg_file.parent.resolve()))
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(text)
                os.replace(temp_name, cfg_file)
                return True
            except PermissionError:
                time.sleep(0.05 * (attempt + 1))
            except Exception:
                break
            finally:
                if temp_name and os.path.exists(temp_name):
                    try:
                        os.remove(temp_name)
                    except OSError:
                        pass

        # Fallback if atomic rename is blocked by an open file handle on Windows
        try:
            with open(cfg_file, "w", encoding="utf-8") as f:
                f.write(text)
            return True
        except Exception as e:
            sys.stderr.write(f"[Config] Error saving {config_path}: {e}\n")
            return False
