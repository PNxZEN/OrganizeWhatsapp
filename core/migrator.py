"""
core/migrator.py - Dedicated migration engine for importing older WhatsApp media backups.

Provides:
- Native OS folder picker dialog (Windows Explorer / macOS Finder / Linux file dialog)
- Pre-flight scanning & analysis of source output folder
- Safe non-destructive media file migration with collision protection
- Merge of gallery_data.js (chats and media items)
- Merge of .hashes_cache.sqlite3 (instant duplicate detection cache)
- Merge of .sync_state.sqlite3 (sync manifest reconciliation to prevent re-pulling)
"""

import json
import logging
import mimetypes
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("organize_whatsapp.migrator")

# Media file extensions recognized for WhatsApp media organization
KNOWN_MEDIA_EXTENSIONS = {
    # Images
    ".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".gif", ".bmp", ".tiff",
    # Videos
    ".mp4", ".m4v", ".webm", ".mov", ".3gp", ".avi", ".mkv", ".flv",
    # Audio
    ".opus", ".ogg", ".mp3", ".m4a", ".aac", ".wav", ".amr",
    # Documents
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".zip", ".vcf",
}

# Directories and files to strictly skip during media discovery
IGNORED_DIRS = {
    ".git", "__pycache__", ".gemini", ".cache", ".thumbnails", ".part",
    "node_modules", ".temp", ".tempmediaStorage", "gallery_assets",
    # Media the user deleted in the older library must not come back as a "chat"
    ".duplicates_recycle_bin",
    ".update",
}
IGNORED_FILES = {
    "gallery.html", "index.html", ".hashes_cache.sqlite3", ".hashes_cache.sqlite3-wal",
    ".hashes_cache.sqlite3-shm", ".hashes_cache.json", ".sync_state.sqlite3",
    ".sync_state.sqlite3-wal", ".sync_state.sqlite3-shm", ".sync_session.sqlite3",
    "gallery_data.js", "config.json", ".deleted_media.json", ".gallery_server.json"
}


PICK_SELECTED = "selected"
PICK_CANCELLED = "cancelled"
PICK_UNAVAILABLE = "unavailable"


def _pick_folder_windows_ctypes(initial_dir: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """
    Native Windows folder picker dialog using the Win32 Shell API via ctypes.
    Returns (PICK_SELECTED, path), (PICK_CANCELLED, None) or (PICK_UNAVAILABLE, None).

    Every pointer-returning call declares its restype/argtypes: ctypes defaults to a 32-bit
    int, which truncated the PIDL from SHBrowseForFolderW on 64-bit Windows whenever it lived
    above 4 GB. SHGetPathFromIDListW then failed and the chosen folder was silently dropped.
    """
    try:
        import ctypes
        from ctypes import wintypes

        class BROWSEINFOW(ctypes.Structure):
            _fields_ = [
                ("hwndOwner", wintypes.HWND),
                ("pidlRoot", ctypes.c_void_p),
                ("pszDisplayName", wintypes.LPWSTR),
                ("lpszTitle", wintypes.LPCWSTR),
                ("ulFlags", wintypes.UINT),
                ("lpfn", ctypes.c_void_p),
                ("lParam", wintypes.LPARAM),
                ("iImage", ctypes.c_int),
            ]

        ole32 = ctypes.windll.ole32
        shell32 = ctypes.windll.shell32
        user32 = ctypes.windll.user32

        ole32.CoInitialize.argtypes = [ctypes.c_void_p]
        ole32.CoInitialize.restype = ctypes.c_long
        ole32.CoUninitialize.argtypes = []
        ole32.CoUninitialize.restype = None
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        ole32.CoTaskMemFree.restype = None
        shell32.SHBrowseForFolderW.argtypes = [ctypes.POINTER(BROWSEINFOW)]
        shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
        shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR]
        shell32.SHGetPathFromIDListW.restype = wintypes.BOOL
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.SendMessageW.restype = ctypes.c_ssize_t

        # Initialize COM (apartment threaded) on the calling HTTP handler thread
        com_hr = ole32.CoInitialize(None)
        try:
            display_name = ctypes.create_unicode_buffer(260)
            bi = BROWSEINFOW()
            # Attach to the active foreground window (the user's browser) so the dialog stays on top
            bi.hwndOwner = user32.GetForegroundWindow()
            bi.pszDisplayName = ctypes.cast(display_name, wintypes.LPWSTR)
            bi.lpszTitle = "Select Older WhatsApp Output Folder"
            # BIF_RETURNONLYFSDIRS (0x01) | BIF_NEWDIALOGSTYLE (0x40) | BIF_NONEWFOLDERBUTTON (0x200)
            bi.ulFlags = 0x00000001 | 0x00000040 | 0x00000200

            # Optional initial folder selection callback (kept referenced until the dialog closes)
            cb_func = None
            init_buf = None
            if initial_dir and os.path.isdir(initial_dir):
                BFFCALLBACK = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HWND, wintypes.UINT, wintypes.LPARAM, wintypes.LPARAM)
                init_buf = ctypes.create_unicode_buffer(os.path.abspath(initial_dir))

                def _cb(hwnd, uMsg, lParam, lpData):
                    if uMsg == 1 and lpData:  # BFFM_INITIALIZED
                        user32.SendMessageW(hwnd, 0x400 + 103, 1, lpData)  # BFFM_SETSELECTIONW
                    return 0

                cb_func = BFFCALLBACK(_cb)
                bi.lpfn = ctypes.cast(cb_func, ctypes.c_void_p)
                bi.lParam = ctypes.addressof(init_buf)

            pidl = shell32.SHBrowseForFolderW(ctypes.byref(bi))
            if not pidl:
                return PICK_CANCELLED, None
            try:
                path_buf = ctypes.create_unicode_buffer(32768)
                ok = shell32.SHGetPathFromIDListW(pidl, path_buf)
            finally:
                ole32.CoTaskMemFree(pidl)
            res = path_buf.value if ok else ""
            if res and os.path.isdir(res):
                return PICK_SELECTED, os.path.abspath(res)
            # A virtual location (e.g. "This PC", a library) has no file system path
            return PICK_CANCELLED, None
        finally:
            if com_hr >= 0:
                ole32.CoUninitialize()
    except Exception as e:
        logger.warning(f"[Migrator] Win32 folder picker failed: {e}")
        return PICK_UNAVAILABLE, None


def pick_folder(initial_dir: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """
    Spawns a native OS folder picker dialog window (File Explorer on Windows,
    Finder on macOS, zenity/kdialog or Tkinter on Linux).
    Returns (PICK_SELECTED, path), (PICK_CANCELLED, None) if the user dismissed the dialog,
    or (PICK_UNAVAILABLE, None) if no picker could be shown on this system.
    """
    # 1. On Windows, use native Win32 ctypes (instant, zero child processes, works in embedded Python)
    if sys.platform == "win32":
        status, selected = _pick_folder_windows_ctypes(initial_dir=initial_dir)
        if status != PICK_UNAVAILABLE:
            return status, selected

    # 2. On macOS, use native osascript / Finder dialog
    if sys.platform == "darwin":
        try:
            prompt = "Select Older WhatsApp Output Folder"
            init_part = f'default location POSIX file "{initial_dir}"' if (initial_dir and os.path.isdir(initial_dir)) else ""
            script = f'POSIX path of (choose folder with prompt "{prompt}" {init_part})'
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=600)
            if res.returncode == 0 and res.stdout.strip():
                p = res.stdout.strip()
                if os.path.isdir(p):
                    return PICK_SELECTED, os.path.abspath(p)
            # osascript exits 1 with "User canceled" when the dialog is dismissed
            if "-128" in (res.stderr or "") or "cancel" in (res.stderr or "").lower():
                return PICK_CANCELLED, None
        except Exception as e:
            logger.debug(f"[Migrator] macOS osascript folder picker failed: {e}")

    # 3. On Linux, use zenity or kdialog (exit code 1 means the user cancelled)
    if sys.platform.startswith("linux"):
        for cmd in [
            ["zenity", "--file-selection", "--directory", "--title=Select Older WhatsApp Output Folder"],
            ["kdialog", "--getexistingdirectory"],
        ]:
            if not shutil.which(cmd[0]):
                continue
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                if res.returncode == 0 and res.stdout.strip():
                    p = res.stdout.strip()
                    if os.path.isdir(p):
                        return PICK_SELECTED, os.path.abspath(p)
                if res.returncode == 1:
                    return PICK_CANCELLED, None
            except Exception:
                pass

    # 4. Standard Python Tkinter in subprocess (if Tkinter is installed)
    init_arg = f"initialdir={repr(initial_dir)}" if (initial_dir and os.path.isdir(initial_dir)) else "initialdir=None"
    try:
        py_code = (
            "import sys, os\n"
            "try:\n"
            "    import tkinter as tk\n"
            "    from tkinter import filedialog\n"
            "    root = tk.Tk()\n"
            "    root.withdraw()\n"
            "    root.wm_attributes('-topmost', 1)\n"
            f"    p = filedialog.askdirectory(title='Select Older WhatsApp Output Folder', {init_arg})\n"
            "    root.destroy()\n"
            "    if p and os.path.isdir(p):\n"
            "        print('SELECTED:' + os.path.abspath(p))\n"
            "    else:\n"
            "        print('CANCELLED')\n"
            "except Exception:\n"
            "    sys.exit(1)\n"
        )
        res = subprocess.run(
            [sys.executable, "-c", py_code],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if res.returncode == 0:
            out = res.stdout.strip()
            if out.startswith("SELECTED:"):
                selected = out[len("SELECTED:"):].strip()
                if selected and os.path.isdir(selected):
                    return PICK_SELECTED, os.path.abspath(selected)
            if out == "CANCELLED":
                return PICK_CANCELLED, None
    except Exception as e:
        logger.debug(f"[Migrator] Tkinter folder picker fallback error: {e}")

    return PICK_UNAVAILABLE, None


def pick_folder_dialog(initial_dir: Optional[str] = None) -> Optional[str]:
    """Returns the chosen absolute path, or None if cancelled or no picker is available."""
    status, path = pick_folder(initial_dir)
    return path if status == PICK_SELECTED else None


def validate_paths(source_dir: str, target_dir: str) -> Tuple[bool, str, Optional[Path], Optional[Path]]:
    """Validates source and target paths to avoid collisions, traversal, and self-copying."""
    if not source_dir or not str(source_dir).strip():
        return False, "Source folder path is required", None, None
    if not target_dir or not str(target_dir).strip():
        return False, "Target output folder path is required", None, None

    src_path = Path(source_dir).resolve()
    tgt_path = Path(target_dir).resolve()

    if not src_path.exists():
        return False, f"Source folder does not exist: {src_path}", None, None
    if not src_path.is_dir():
        return False, f"Source path is not a directory: {src_path}", None, None

    if src_path == tgt_path or _same_folder(src_path, tgt_path):
        return False, "This is the gallery's own output folder: the older folder cannot be the same as the current output folder.", None, None

    # Compare the real folders, not their spelling: a mapped drive, network path, junction or
    # symlink can name the same folder in a different way.
    if any(_same_folder(src_path, parent) for parent in tgt_path.parents) or tgt_path.is_relative_to(src_path):
        return False, "The current output folder is inside the selected folder. Choose the older output folder itself.", None, None
    if any(_same_folder(tgt_path, parent) for parent in src_path.parents) or src_path.is_relative_to(tgt_path):
        return False, "The selected folder is inside the current output folder. Choose an older output folder instead.", None, None

    return True, "", src_path, tgt_path


def _same_folder(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


KEY_NONE = "none"            # the older folder has no backup key
KEY_NEW = "new"              # it has one and the app has none yet: it will be used
KEY_SAME = "same"            # it is the key the app already uses
KEY_DIFFERENT = "different"  # it differs: only replaced when the user explicitly asks


def classify_backup_key(found_key: Optional[str]) -> str:
    if not found_key:
        return KEY_NONE
    from core.config import load_config

    current = str(load_config().get("hex_key") or "").strip().lower()
    if not current:
        return KEY_NEW
    return KEY_SAME if current == found_key.strip().lower() else KEY_DIFFERENT


def _target_deleted_index(tgt_path: Path) -> Dict[str, int]:
    from core.gallery import deleted_media_index

    try:
        return deleted_media_index(tgt_path)
    except Exception:
        return {}


def discover_source_media(source_dir: Path) -> List[Tuple[Path, str, int]]:
    """
    Recursively scans source_dir for media files.
    Returns list of tuples: (absolute_file_path, relative_path_str, file_size_bytes).
    """
    media_files = []
    source_resolved = source_dir.resolve()

    for root, dirs, files in os.walk(str(source_resolved)):
        # Prune ignored directories in-place
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".part_")]

        for fn in files:
            if fn in IGNORED_FILES or fn.startswith(".part_") or fn.startswith("~"):
                continue

            ext = os.path.splitext(fn)[1].lower()
            if ext in KNOWN_MEDIA_EXTENSIONS:
                fp = Path(root) / fn
                try:
                    st = fp.stat()
                    if st.st_size > 0:
                        rel = str(fp.relative_to(source_resolved)).replace("\\", "/")
                        media_files.append((fp, rel, st.st_size))
                except (OSError, ValueError):
                    pass

    return media_files


def extract_key_from_folder(source_dir_or_file: str) -> Optional[str]:
    """
    Attempts to extract a valid 64-character WhatsApp hex backup key from an older installation
    folder, an older output folder, or a key/config file.
    Checks:
    - config.json (hex_key, key, whatsapp_key, backup_key)
    - encrypted_backup.key (59-byte Java serialized Key15: last 32 bytes)
    - whatsapp.cryptkey, key, wa.key, whatsapp.key (32 bytes binary or 64 hex characters)
    - Checks source_dir and parent directory if source_dir is an output folder.
    Returns the validated 64-character lowercase hex string, or None if not found.
    """
    from core.decrypt import validate_hex_key

    if not source_dir_or_file:
        return None

    p = Path(source_dir_or_file).resolve()

    def _try_extract_from_file(file_path: Path) -> Optional[str]:
        if not file_path.is_file():
            return None
        try:
            # 1. Try JSON configuration
            if file_path.name.lower().endswith(".json"):
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    for k in ("hex_key", "key", "whatsapp_key", "backup_key"):
                        val = data.get(k)
                        if val and isinstance(val, str):
                            is_val, _ = validate_hex_key(val)
                            if is_val:
                                return val.strip().lower()

            # 2. Try binary / raw text key file
            raw = file_path.read_bytes()
            if len(raw) == 59 and raw.startswith(b"\xac\xed\x00\x05"):
                # Java-serialized Key15: last 32 bytes are the raw key
                cand = raw[-32:].hex().lower()
                is_val, _ = validate_hex_key(cand)
                if is_val:
                    return cand

            if len(raw) == 32:
                # 32 bytes raw key
                cand = raw.hex().lower()
                is_val, _ = validate_hex_key(cand)
                if is_val:
                    return cand

            if len(raw) == 64:
                # 64 hex characters ascii
                cand = raw.decode("ascii", errors="ignore").strip().lower()
                is_val, _ = validate_hex_key(cand)
                if is_val:
                    return cand

            # Also check text content in case there are trailing whitespace or newlines
            try:
                txt = raw.decode("utf-8", errors="ignore").strip().lower()
                if len(txt) == 64:
                    is_val, _ = validate_hex_key(txt)
                    if is_val:
                        return txt
            except Exception:
                pass

        except Exception as e:
            logger.debug(f"[Migrator] Error inspecting candidate key file {file_path}: {e}")

        return None

    # If user selected a file directly:
    if p.is_file():
        k = _try_extract_from_file(p)
        if k:
            return k
        p = p.parent

    # Candidate directories to search:
    # 1. Directory itself (e.g. C:\OldInstall or C:\OldInstall\output)
    # 2. Parent directory (e.g. C:\OldInstall when output was selected)
    candidate_dirs = [p]
    if p.parent and p.parent != p and p.parent.is_dir():
        candidate_dirs.append(p.parent)

    candidate_filenames = [
        "config.json",
        "encrypted_backup.key",
        "whatsapp.cryptkey",
        "key",
        "wa.key",
        "whatsapp.key",
    ]

    for d in candidate_dirs:
        for fname in candidate_filenames:
            cand_file = d / fname
            k = _try_extract_from_file(cand_file)
            if k:
                return k

    return None


def analyze_import_folder(source_dir: str, target_dir: str) -> Dict[str, Any]:
    """
    Performs pre-flight analysis of the source older output folder without making changes.
    Returns metrics on media counts, size, existing overlaps, and databases present.
    """
    valid, err, src_path, tgt_path = validate_paths(source_dir, target_dir)
    if not valid:
        return {
            "valid": False,
            "error": err,
        }

    # Check for database files in source: verify valid WhatsApp Media Organizer structure
    has_gallery_data = (src_path / "gallery_data.js").is_file() or (src_path / "gallery.js").is_file()
    if not has_gallery_data:
        return {
            "valid": False,
            "error": "The selected folder is not a valid WhatsApp Media Organizer output folder (missing gallery_data.js). Please select a valid output directory.",
            "source_dir": str(src_path),
            "target_dir": str(tgt_path),
            "has_gallery_data": False,
        }

    media_items = discover_source_media(src_path)
    if len(media_items) == 0:
        return {
            "valid": False,
            "error": "No media files found in the selected folder.",
            "source_dir": str(src_path),
            "target_dir": str(tgt_path),
            "has_gallery_data": True,
            "media_count": 0,
        }

    total_bytes = sum(sz for _, _, sz in media_items)
    has_hashes_db = (src_path / ".hashes_cache.sqlite3").is_file() or (src_path / ".hashes_cache.json").is_file()
    has_sync_db = (src_path / ".sync_state.sqlite3").is_file() or (src_path / ".sync_session.sqlite3").is_file()

    # Detect if source or its parent contains a WhatsApp backup key
    found_key = extract_key_from_folder(str(src_path))
    from core.config import mask_key
    detected_key_masked = mask_key(found_key) if found_key else ""

    # Compare against target folder to check overlaps
    already_exists_count = 0
    collision_count = 0
    new_files_count = 0
    bytes_to_import = 0
    previously_deleted_count = 0
    deleted_index = _target_deleted_index(tgt_path)

    # Collect chats inferred from folders or gallery_data.js
    chat_names = set()

    for src_file, rel_path, sz in media_items:
        parts = rel_path.split("/")
        if len(parts) > 1:
            chat_names.add(parts[0])

        target_file = tgt_path / rel_path
        if not target_file.exists() and deleted_index.get(rel_path) == sz:
            previously_deleted_count += 1  # the user deleted it from this gallery: do not bring it back
            continue
        if target_file.is_file():
            try:
                if target_file.stat().st_size == sz:
                    already_exists_count += 1
                else:
                    collision_count += 1
                    bytes_to_import += sz
            except OSError:
                new_files_count += 1
                bytes_to_import += sz
        else:
            new_files_count += 1
            bytes_to_import += sz

    return {
        "valid": True,
        "source_dir": str(src_path),
        "target_dir": str(tgt_path),
        "media_count": len(media_items),
        "total_bytes": total_bytes,
        "new_files_count": new_files_count,
        "already_exists_count": already_exists_count,
        "collision_count": collision_count,
        "files_to_import": new_files_count + collision_count,
        "bytes_to_import": bytes_to_import,
        # Moving within one drive is a rename (instant); across drives it is copy + delete
        "same_volume": is_same_volume(src_path, tgt_path),
        "chat_count": len(chat_names),
        "has_gallery_data": has_gallery_data,
        "has_hashes_db": has_hashes_db,
        "has_sync_db": has_sync_db,
        "has_key": bool(found_key),
        "detected_key_masked": detected_key_masked,
        "key_status": classify_backup_key(found_key),
        "previously_deleted_count": previously_deleted_count,
    }


def _merge_gallery_data(source_dir: Path, target_dir: Path, copied_files_map: Dict[str, str]) -> int:
    """
    Holds the gallery lock for the whole read-modify-write, so a recycle or a preview update
    made while the import merges is not overwritten with the older copy it read.
    """
    from core.gallery import gallery_data_lock

    with gallery_data_lock:
        return _merge_gallery_data_locked(source_dir, target_dir, copied_files_map)


def _merge_gallery_data_locked(source_dir: Path, target_dir: Path, copied_files_map: Dict[str, str]) -> int:
    """
    Merges chats and media items from source gallery_data.js into target gallery_data.js.
    copied_files_map maps original_rel_path -> final_rel_path (handles any collision renaming).
    Returns number of newly added media entries in target gallery dataset.
    """
    from core.gallery import parse_gallery_data_js, gallery_data_lock, _memory_cache

    source_data_js = source_dir / "gallery_data.js"
    target_data_js = target_dir / "gallery_data.js"

    source_dataset = None
    if source_data_js.is_file():
        try:
            with open(source_data_js, "r", encoding="utf-8") as f:
                source_dataset = parse_gallery_data_js(f.read())
        except Exception as e:
            logger.debug(f"[Migrator] Failed to read source gallery_data.js: {e}")

    target_dataset = {"chats": []}
    if target_data_js.is_file():
        try:
            with open(target_data_js, "r", encoding="utf-8") as f:
                parsed = parse_gallery_data_js(f.read())
                if parsed and isinstance(parsed.get("chats"), list):
                    target_dataset = parsed
        except Exception as e:
            logger.debug(f"[Migrator] Failed to read target gallery_data.js: {e}")

    target_chats = target_dataset.get("chats", [])
    target_chats_by_jid = {c.get("jid"): c for c in target_chats if c.get("jid")}
    target_chats_by_name = {c.get("name"): c for c in target_chats if c.get("name")}

    added_media_count = 0

    handled_source_rels = set()
    if source_dataset and isinstance(source_dataset.get("chats"), list):
        for s_chat in source_dataset["chats"]:
            s_jid = s_chat.get("jid", "")
            s_name = s_chat.get("name", "")

            t_chat = target_chats_by_jid.get(s_jid) or target_chats_by_name.get(s_name)

            if not t_chat:
                # Brand new chat from older backup
                new_chat = dict(s_chat)
                # Remap media paths if renamed
                remapped_media = []
                for m in s_chat.get("media", []):
                    m_copy = dict(m)
                    orig_rel = m.get("rel_path", "")
                    handled_source_rels.add(orig_rel)
                    if orig_rel in copied_files_map:
                        m_copy["rel_path"] = copied_files_map[orig_rel]
                        m_copy["filename"] = os.path.basename(copied_files_map[orig_rel])
                    if not _present(target_dir, m_copy.get("rel_path", "")):
                        continue  # not transferred (cancelled, failed, or deleted by the user)
                    remapped_media.append(m_copy)
                if not remapped_media:
                    continue
                new_chat["media"] = remapped_media
                new_chat["file_count"] = len(remapped_media)
                new_chat["total_size"] = sum(m.get("size_bytes", 0) for m in remapped_media)
                target_chats.append(new_chat)
                if s_jid:
                    target_chats_by_jid[s_jid] = new_chat
                if s_name:
                    target_chats_by_name[s_name] = new_chat
                added_media_count += len(remapped_media)
            else:
                # Chat already exists in target; merge unique media items
                existing_sigs = {
                    (m.get("filename"), m.get("size_bytes")) for m in t_chat.get("media", [])
                }
                existing_rels = {m.get("rel_path") for m in t_chat.get("media", [])}

                for m in s_chat.get("media", []):
                    orig_rel = m.get("rel_path", "")
                    handled_source_rels.add(orig_rel)
                    final_rel = copied_files_map.get(orig_rel, orig_rel)
                    final_fn = os.path.basename(final_rel)
                    sig = (final_fn, m.get("size_bytes"))

                    if sig not in existing_sigs and final_rel not in existing_rels and _present(target_dir, final_rel):
                        m_copy = dict(m)
                        m_copy["rel_path"] = final_rel
                        m_copy["filename"] = final_fn
                        t_chat.setdefault("media", []).append(m_copy)
                        existing_sigs.add(sig)
                        existing_rels.add(final_rel)
                        added_media_count += 1

                t_chat["file_count"] = len(t_chat.get("media", []))
                t_chat["total_size"] = sum(m.get("size_bytes", 0) for m in t_chat.get("media", []))

    # Also synthesize entries for any newly copied files on disk that were NOT in source_dataset
    remaining_copied = {
        orig_rel: final_rel
        for orig_rel, final_rel in copied_files_map.items()
        if orig_rel not in handled_source_rels
    }
    if remaining_copied:
        chats_to_synthesize = {}
        for orig_rel, final_rel in remaining_copied.items():
            parts = final_rel.split("/")
            chat_name = parts[0] if len(parts) > 1 else "_unmatched"
            chats_to_synthesize.setdefault(chat_name, []).append(final_rel)

        for chat_name, rel_list in chats_to_synthesize.items():
            t_chat = target_chats_by_name.get(chat_name)
            if not t_chat:
                t_chat = {
                    "jid": f"{chat_name.lower().replace(' ', '_')}@imported",
                    "name": chat_name,
                    "total_size": 0,
                    "file_count": 0,
                    "archived": False,
                    "last_message_ts": int(time.time()),
                    "is_group": False,
                    "media": [],
                }
                target_chats.append(t_chat)
                target_chats_by_name[chat_name] = t_chat

            existing_rels = {m.get("rel_path") for m in t_chat.get("media", [])}
            for rel in rel_list:
                if rel not in existing_rels:
                    abs_p = target_dir / rel
                    try:
                        st = abs_p.stat()
                        sz = st.st_size
                        mtime_ts = st.st_mtime
                    except OSError:
                        sz = 0
                        mtime_ts = time.time()

                    mime, _ = mimetypes.guess_type(rel)
                    item_obj = {
                        "filename": os.path.basename(rel),
                        "rel_path": rel,
                        "size_bytes": sz,
                        "mime_type": mime or "application/octet-stream",
                        "received_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime_ts)),
                    }
                    t_chat.setdefault("media", []).append(item_obj)
                    existing_rels.add(rel)
                    added_media_count += 1

            t_chat["file_count"] = len(t_chat.get("media", []))
            t_chat["total_size"] = sum(m.get("size_bytes", 0) for m in t_chat.get("media", []))

    # Save target gallery_data.js atomically
    target_dataset["chats"] = target_chats
    json_str = json.dumps(target_dataset, ensure_ascii=False)
    content = f"// Auto-generated WhatsApp Media Gallery dataset\nwindow.GALLERY_DATA = {json_str};\n"

    with gallery_data_lock:
        target_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=str(target_dir), prefix="gallery_data_", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, str(target_data_js))
        _memory_cache["data"] = None

    return added_media_count


def _present(target_dir: Path, rel: str) -> bool:
    return bool(rel) and (target_dir / rel).is_file()


def _merge_hash_databases(source_dir: Path, target_dir: Path, copied_files_map: Dict[str, str]) -> int:
    """
    Merges file_hashes records from source .hashes_cache.sqlite3 into target .hashes_cache.sqlite3.
    Returns count of hash records merged.
    """
    src_db = source_dir / ".hashes_cache.sqlite3"
    tgt_db = target_dir / ".hashes_cache.sqlite3"

    records_to_insert = []

    # 1. From SQLite
    if src_db.is_file():
        try:
            src_conn = sqlite3.connect(str(src_db), timeout=10.0)
            src_cur = src_conn.cursor()
            src_cur.execute("SELECT filepath, mtime, size, md5, phash, fast_hash FROM file_hashes")
            rows = src_cur.fetchall()
            src_conn.close()

            src_base_str = str(source_dir.resolve()).replace("\\", "/")
            tgt_base_str = str(target_dir.resolve()).replace("\\", "/")

            for fpath, mtime, size, md5, phash, fast_hash in rows:
                norm_fp = str(fpath).replace("\\", "/")
                # Extract relative path if possible
                rel = None
                if norm_fp.startswith(src_base_str):
                    rel = norm_fp[len(src_base_str):].lstrip("/")
                elif "/" in norm_fp and not os.path.isabs(norm_fp):
                    rel = norm_fp
                else:
                    rel = norm_fp

                if rel:
                    final_rel = copied_files_map.get(rel, rel)
                    tgt_abs = str((target_dir / final_rel).resolve())
                    records_to_insert.append((tgt_abs, mtime, size, md5, phash, fast_hash))
                    records_to_insert.append((final_rel, mtime, size, md5, phash, fast_hash))
        except Exception as e:
            logger.debug(f"[Migrator] SQLite hash merge error: {e}")

    # 2. From legacy JSON if present and SQLite was missing
    src_json = source_dir / ".hashes_cache.json"
    if not records_to_insert and src_json.is_file():
        try:
            with open(src_json, "r", encoding="utf-8") as f:
                j_data = json.load(f)
            src_base_str = str(source_dir.resolve()).replace("\\", "/")
            for fpath, val in j_data.items():
                norm_fp = str(fpath).replace("\\", "/")
                rel = norm_fp[len(src_base_str):].lstrip("/") if norm_fp.startswith(src_base_str) else norm_fp
                final_rel = copied_files_map.get(rel, rel)
                tgt_abs = str((target_dir / final_rel).resolve())
                records_to_insert.append((
                    tgt_abs,
                    float(val.get("mtime", 0)),
                    int(val.get("size", 0)),
                    val.get("md5"),
                    val.get("phash"),
                    val.get("fast_hash"),
                ))
        except Exception as e:
            logger.debug(f"[Migrator] JSON hash merge error: {e}")

    if not records_to_insert:
        return 0

    try:
        tgt_conn = sqlite3.connect(str(tgt_db), timeout=20.0)
        tgt_cur = tgt_conn.cursor()
        tgt_cur.execute(
            """
            CREATE TABLE IF NOT EXISTS file_hashes (
                filepath TEXT PRIMARY KEY,
                mtime REAL,
                size INTEGER,
                md5 TEXT,
                phash TEXT,
                fast_hash TEXT
            );
            """
        )
        tgt_cur.execute("CREATE INDEX IF NOT EXISTS idx_size ON file_hashes(size);")
        tgt_cur.execute("CREATE INDEX IF NOT EXISTS idx_md5 ON file_hashes(md5);")

        tgt_cur.executemany(
            """
            INSERT OR REPLACE INTO file_hashes
            (filepath, mtime, size, md5, phash, fast_hash)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            records_to_insert,
        )
        tgt_conn.commit()
        tgt_conn.close()
        return len(records_to_insert)
    except Exception as e:
        logger.debug(f"[Migrator] Target hash DB write error: {e}")
        return 0


def _merge_sync_manifests(source_dir: Path, target_dir: Path, copied_files_map: Dict[str, str]) -> int:
    """
    Merges completed sync manifest records into target .sync_state.sqlite3 so future ADB syncs
    recognize imported files as already pulled and never redownload them over USB.
    """
    src_sync = source_dir / ".sync_state.sqlite3"
    if not src_sync.is_file():
        src_sync = source_dir / ".sync_session.sqlite3"
    if not src_sync.is_file():
        return 0

    tgt_sync = target_dir / ".sync_state.sqlite3"

    try:
        src_conn = sqlite3.connect(str(src_sync), timeout=10.0)
        src_cur = src_conn.cursor()
        src_cur.execute(
            """
            SELECT rel_path, target_path, file_size, file_mtime, status, synced_bytes, synced_at
            FROM sync_manifest
            WHERE status = 'completed'
            """
        )
        rows = src_cur.fetchall()
        src_conn.close()
    except Exception as e:
        logger.debug(f"[Migrator] Source sync DB read error: {e}")
        return 0

    if not rows:
        return 0

    try:
        from core.sync_session import SyncSessionManager
        mgr = SyncSessionManager(str(tgt_sync))
        with mgr._get_connection() as tgt_conn:
            # Ensure an imported session exists
            session_id = "session_imported_archive"
            now_ts = time.time()
            tgt_conn.execute(
                """
                INSERT OR IGNORE INTO sync_sessions
                (session_id, device_serial, device_model, status, current_phase, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, "IMPORTED_MEDIA", "Local Archive", "completed", "completed", now_ts, now_ts),
            )

            manifest_records = []
            for rel_path, target_path, file_size, file_mtime, status, synced_bytes, synced_at in rows:
                final_rel = copied_files_map.get(rel_path, rel_path)
                final_target = str((target_dir / final_rel).resolve())
                manifest_records.append((
                    session_id,
                    rel_path,
                    final_target,
                    file_size,
                    file_mtime or 0,
                    "completed",
                    synced_bytes or file_size,
                    synced_at or now_ts,
                    None,
                ))

            tgt_conn.executemany(
                """
                INSERT OR REPLACE INTO sync_manifest
                (session_id, rel_path, target_path, file_size, file_mtime, status, synced_bytes, synced_at, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                manifest_records,
            )
        return len(rows)
    except Exception as e:
        logger.debug(f"[Migrator] Target sync DB write error: {e}")
        return 0


IMPORT_MODE_COPY = "copy"
IMPORT_MODE_MOVE = "move"
_COPY_CHUNK_BYTES = 8 * 1024 * 1024
_PROGRESS_INTERVAL_SECS = 0.25
_TEMP_SUFFIX = ".importing"


class ImportCancelled(Exception):
    """Raised inside a file transfer when the user cancels the import."""


def is_same_volume(path_a: Path, path_b: Path) -> bool:
    """True when both paths live on the same file system, so a move is a cheap rename."""
    try:
        b = path_b if path_b.exists() else path_b.parent
        return os.stat(path_a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


def _copy_with_progress(src: Path, dest: Path, on_bytes: Callable[[int], None], cancel_event=None) -> None:
    """
    Copies src to dest through a temporary sibling file, verifies the size and atomically
    renames it into place, so an interrupted import never leaves a truncated media file.
    """
    tmp = dest.with_name(f".{dest.name}{_TEMP_SUFFIX}")
    try:
        with open(src, "rb") as fin, open(tmp, "wb") as fout:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise ImportCancelled()
                chunk = fin.read(_COPY_CHUNK_BYTES)
                if not chunk:
                    break
                fout.write(chunk)
                on_bytes(len(chunk))
        shutil.copystat(src, tmp)
        if tmp.stat().st_size != src.stat().st_size:
            raise OSError(f"Size mismatch after copying {src.name}")
        os.replace(tmp, dest)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _transfer_file(src: Path, dest: Path, mode: str, on_bytes: Callable[[int], None], cancel_event=None) -> None:
    """Copies or moves one file. Moves use a rename when possible, else copy + verify + delete."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    size = src.stat().st_size
    if mode == IMPORT_MODE_MOVE:
        try:
            os.rename(src, dest)  # same drive: instant and atomic
            on_bytes(size)
            return
        except OSError:
            pass  # different drive (or locked file): fall back to copy then delete the source
    _copy_with_progress(src, dest, on_bytes, cancel_event)
    if mode == IMPORT_MODE_MOVE:
        os.unlink(src)


def execute_import_folder(
    source_dir: str,
    target_dir: str,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    import_key: bool = True,
    mode: str = IMPORT_MODE_COPY,
    cancel_event=None,
    replace_key: bool = False,
) -> Dict[str, Any]:
    """
    Safely migrates media from an older output folder into the target output folder.
    - mode "copy" keeps the source untouched; mode "move" relocates files (instant on the
      same drive, copy + verify + delete across drives). Files already present with the same
      size are skipped and, in move mode, left in the source.
    - Copies are atomic (temp file + size check + rename): no truncated files on failure
    - Renames on size collision to prevent data loss
    - Reports byte-accurate progress (phase, percent, files, bytes, speed, ETA)
    - Honors cancel_event; already transferred files are still merged into the gallery
    - Merges gallery_data.js, .hashes_cache.sqlite3 and .sync_state.sqlite3
    - Optionally imports WhatsApp backup key if found. A key that differs from the one the app
      already uses is only installed when replace_key is True (the user confirmed it).
    - Never brings back media the user deleted from the current gallery (recycle bin or purged)
    """
    if mode not in (IMPORT_MODE_COPY, IMPORT_MODE_MOVE):
        return {"status": "error", "message": f"Unknown import mode: {mode}"}

    valid, err, src_path, tgt_path = validate_paths(source_dir, target_dir)
    if not valid:
        return {"status": "error", "message": err}

    has_gallery_data = (src_path / "gallery_data.js").is_file() or (src_path / "gallery.js").is_file()
    if not has_gallery_data:
        return {
            "status": "error",
            "message": "The selected folder is not a valid WhatsApp Media Organizer output folder (missing gallery_data.js).",
        }

    def emit(update: Dict[str, Any]) -> None:
        if progress_callback:
            try:
                progress_callback(update)
            except Exception:
                pass

    emit({"phase": "scanning", "percent": 0, "message": "Scanning older folder..."})

    # Step 0: Optionally import encryption backup key from source
    imported_key = False
    masked_key = ""
    key_status = KEY_NONE
    if import_key:
        found_key = extract_key_from_folder(str(src_path))
        key_status = classify_backup_key(found_key)
        if key_status == KEY_NEW or (key_status == KEY_DIFFERENT and replace_key):
            try:
                from core.config import save_config, mask_key
                from core.decrypt import create_key_file
                save_config({"hex_key": found_key})
                create_key_file(found_key, "encrypted_backup.key")
                imported_key = True
                masked_key = mask_key(found_key)
                logger.info(f"[Migrator] Successfully imported backup key from source ({masked_key})")
            except Exception as e:
                logger.warning(f"[Migrator] Failed to save imported key: {e}")

    # Step 1: Plan every file first so progress is measured against known totals
    media_items = discover_source_media(src_path)
    total_files = len(media_items)
    copied_files_map: Dict[str, str] = {}  # orig_rel -> final_rel
    plan: List[Tuple[Path, Path, str, int]] = []
    skipped_count = 0
    previously_deleted_count = 0
    deleted_index = _target_deleted_index(tgt_path)
    for src_file, rel_path, sz in media_items:
        target_file = tgt_path / rel_path
        if not target_file.exists() and deleted_index.get(rel_path) == sz:
            previously_deleted_count += 1  # deleted from this gallery by the user: never bring it back
            continue
        if target_file.is_file():
            try:
                if target_file.stat().st_size == sz:
                    # Identical size: already imported, nothing to transfer
                    skipped_count += 1
                    copied_files_map[rel_path] = rel_path
                    continue
                # Collision with different size: import under a new name
                stem, ext = os.path.splitext(target_file.name)
                counter = 1
                while True:
                    cand_file = target_file.parent / f"{stem}_imported_{counter}{ext}"
                    if not cand_file.exists():
                        target_file = cand_file
                        break
                    counter += 1
            except OSError:
                pass
        plan.append((src_file, target_file, rel_path, sz))

    bytes_total = sum(item[3] for item in plan)
    files_to_transfer = len(plan)
    same_volume = is_same_volume(src_path, tgt_path)

    # Step 2: Transfer files with byte-level progress
    state = {"bytes_done": 0, "last_emit": 0.0}
    start_time = time.time()
    copied_count = 0
    copied_bytes = 0
    failed: List[Dict[str, str]] = []
    cancelled = False
    current_name = ""

    def emit_transfer(force: bool = False) -> None:
        now = time.time()
        if not force and now - state["last_emit"] < _PROGRESS_INTERVAL_SECS:
            return
        state["last_emit"] = now
        elapsed = max(now - start_time, 1e-6)
        done = state["bytes_done"]
        speed = done / elapsed if elapsed > 0.5 else 0
        remaining = max(bytes_total - done, 0)
        frac = (done / bytes_total) if bytes_total else ((copied_count + len(failed)) / max(files_to_transfer, 1))
        emit({
            "phase": "transferring",
            "mode": mode,
            "percent": round(2 + 86 * min(frac, 1.0), 1),
            "files_done": copied_count + len(failed),
            "files_total": files_to_transfer,
            "bytes_done": done,
            "bytes_total": bytes_total,
            "speed_bps": round(speed),
            "eta_seconds": round(remaining / speed) if speed > 0 else None,
            "current_file": current_name,
            "skipped_count": skipped_count,
        })

    def on_bytes(n: int) -> None:
        state["bytes_done"] += n
        emit_transfer()

    emit_transfer(force=True)
    for src_file, target_file, rel_path, sz in plan:
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            break
        current_name = rel_path
        before = state["bytes_done"]
        try:
            _transfer_file(src_file, target_file, mode, on_bytes, cancel_event)
            copied_count += 1
            copied_bytes += sz
            copied_files_map[rel_path] = str(target_file.relative_to(tgt_path)).replace("\\", "/")
        except ImportCancelled:
            state["bytes_done"] = before
            cancelled = True
            break
        except Exception as e:
            # Keep byte totals honest: count the failed file as processed
            state["bytes_done"] = before + sz
            logger.warning(f"[Migrator] Failed to {mode} {src_file} -> {target_file}: {e}")
            failed.append({"file": rel_path, "error": str(e)})
        emit_transfer()
    emit_transfer(force=True)

    # Steps 3-5: Merge metadata for everything that is now in the target (also after a cancel)
    emit({"phase": "merging_gallery", "percent": 90, "message": "Updating gallery dataset..."})
    added_gallery_entries = _merge_gallery_data(src_path, tgt_path, copied_files_map)

    emit({"phase": "merging_hashes", "percent": 94, "message": "Merging duplicate hash index..."})
    merged_hashes = _merge_hash_databases(src_path, tgt_path, copied_files_map)

    emit({"phase": "merging_sync", "percent": 97, "message": "Reconciling sync manifests..."})
    merged_manifest_items = _merge_sync_manifests(src_path, tgt_path, copied_files_map)

    status = "cancelled" if cancelled else "success"
    emit({
        "phase": "cancelled" if cancelled else "done",
        "percent": 100,
        "message": "Import cancelled." if cancelled else "Migration completed successfully!",
    })

    return {
        "status": status,
        "mode": mode,
        "same_volume": same_volume,
        "copied_count": copied_count,
        "skipped_count": skipped_count,
        "copied_bytes": copied_bytes,
        "failed_count": len(failed),
        "failed": failed[:20],
        "left_in_source_count": skipped_count if mode == IMPORT_MODE_MOVE else 0,
        "added_gallery_entries": added_gallery_entries,
        "merged_hashes": merged_hashes,
        "merged_manifest_items": merged_manifest_items,
        "total_source_files": total_files,
        "imported_key": imported_key,
        "masked_key": masked_key,
        "key_status": key_status,
        "key_kept": key_status == KEY_DIFFERENT and not imported_key,
        "previously_deleted_count": previously_deleted_count,
        "elapsed_seconds": round(time.time() - start_time, 2),
    }
