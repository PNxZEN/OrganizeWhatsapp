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
    "node_modules", ".temp", ".tempmediaStorage"
}
IGNORED_FILES = {
    "gallery.html", "index.html", ".hashes_cache.sqlite3", ".hashes_cache.sqlite3-wal",
    ".hashes_cache.sqlite3-shm", ".hashes_cache.json", ".sync_state.sqlite3",
    ".sync_state.sqlite3-wal", ".sync_state.sqlite3-shm", ".sync_session.sqlite3",
    "gallery_data.js", "config.json"
}


def _pick_folder_windows_ctypes(initial_dir: Optional[str] = None) -> Optional[str]:
    """Native Windows folder picker dialog using Win32 Shell API via ctypes."""
    try:
        import ctypes
        from ctypes import wintypes

        class BROWSEINFOW(ctypes.Structure):
            _fields_ = [
                ("hwndOwner", wintypes.HWND),
                ("pidlRoot", wintypes.LPVOID),
                ("pszDisplayName", wintypes.LPWSTR),
                ("lpszTitle", wintypes.LPCWSTR),
                ("ulFlags", wintypes.UINT),
                ("lpfn", wintypes.LPVOID),
                ("lParam", wintypes.LPARAM),
                ("iImage", wintypes.INT),
            ]

        ole32 = ctypes.windll.ole32
        shell32 = ctypes.windll.shell32
        user32 = ctypes.windll.user32

        # Initialize COM on the calling thread
        ole32.CoInitialize(None)

        display_name = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        bi = BROWSEINFOW()
        # Attach to the active foreground window (e.g. user's browser)
        bi.hwndOwner = user32.GetForegroundWindow()
        bi.pszDisplayName = ctypes.cast(display_name, wintypes.LPWSTR)
        bi.lpszTitle = "Select Older WhatsApp Output Folder"
        # BIF_RETURNONLYFSDIRS (0x01) | BIF_NEWDIALOGSTYLE (0x40) | BIF_NONEWFOLDERBUTTON (0x200)
        bi.ulFlags = 0x00000001 | 0x00000040 | 0x00000200

        # Optional initial folder selection callback
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
            bi.lpfn = ctypes.cast(cb_func, wintypes.LPVOID)
            bi.lParam = ctypes.addressof(init_buf)

        pidl = shell32.SHBrowseForFolderW(ctypes.byref(bi))
        if pidl:
            path_buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            shell32.SHGetPathFromIDListW(pidl, path_buf)
            ole32.CoTaskMemFree(pidl)
            ole32.CoUninitialize()
            res = path_buf.value
            if res and os.path.isdir(res):
                return os.path.abspath(res)
            return None

        ole32.CoUninitialize()
        return None
    except Exception as e:
        logger.debug(f"[Migrator] Win32 ctypes folder picker failed: {e}")
        return None


def pick_folder_dialog(initial_dir: Optional[str] = None) -> Optional[str]:
    """
    Spawns a native OS folder picker dialog window (File Explorer on Windows,
    Finder on macOS, or Tkinter/GTK on Linux).
    Returns the chosen absolute path, or None if cancelled or failed.
    """
    # 1. On Windows, use native Win32 ctypes (instant, zero child processes, works in embedded Python)
    if sys.platform == "win32":
        selected = _pick_folder_windows_ctypes(initial_dir=initial_dir)
        if selected:
            return selected

    # 2. On macOS, use native osascript / Finder dialog
    if sys.platform == "darwin":
        try:
            prompt = "Select Older WhatsApp Output Folder"
            init_part = f'default location POSIX file "{initial_dir}"' if (initial_dir and os.path.isdir(initial_dir)) else ""
            script = f'POSIX path of (choose folder with prompt "{prompt}" {init_part})'
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=120)
            if res.returncode == 0 and res.stdout.strip():
                p = res.stdout.strip()
                if os.path.isdir(p):
                    return os.path.abspath(p)
        except Exception as e:
            logger.debug(f"[Migrator] macOS osascript folder picker failed: {e}")

    # 3. On Linux, use zenity or kdialog
    if sys.platform.startswith("linux"):
        for cmd in [
            ["zenity", "--file-selection", "--directory", "--title=Select Older WhatsApp Output Folder"],
            ["kdialog", "--getexistingdirectory"],
        ]:
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if res.returncode == 0 and res.stdout.strip():
                    p = res.stdout.strip()
                    if os.path.isdir(p):
                        return os.path.abspath(p)
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
            timeout=120,
        )
        if res.returncode == 0:
            out = res.stdout.strip()
            if out.startswith("SELECTED:"):
                selected = out[len("SELECTED:"):].strip()
                if selected and os.path.isdir(selected):
                    return os.path.abspath(selected)
    except Exception as e:
        logger.debug(f"[Migrator] Tkinter folder picker fallback error: {e}")

    return None


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

    if src_path == tgt_path:
        return False, "Source folder cannot be the same as the current output folder", None, None

    try:
        if tgt_path.is_relative_to(src_path):
            return False, "Target output folder is inside the source folder", None, None
        if src_path.is_relative_to(tgt_path):
            return False, "Source folder is inside the target output folder", None, None
    except AttributeError:
        # Fallback for Python < 3.9
        src_str = str(src_path)
        tgt_str = str(tgt_path)
        if os.path.commonpath([src_str, tgt_str]) in (src_str, tgt_str):
            return False, "Source and target folders cannot be nested inside each other", None, None

    return True, "", src_path, tgt_path


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

    # Collect chats inferred from folders or gallery_data.js
    chat_names = set()

    for src_file, rel_path, sz in media_items:
        parts = rel_path.split("/")
        if len(parts) > 1:
            chat_names.add(parts[0])

        target_file = tgt_path / rel_path
        if target_file.is_file():
            try:
                if target_file.stat().st_size == sz:
                    already_exists_count += 1
                else:
                    collision_count += 1
            except OSError:
                new_files_count += 1
        else:
            new_files_count += 1

    return {
        "valid": True,
        "source_dir": str(src_path),
        "target_dir": str(tgt_path),
        "media_count": len(media_items),
        "total_bytes": total_bytes,
        "new_files_count": new_files_count,
        "already_exists_count": already_exists_count,
        "collision_count": collision_count,
        "chat_count": len(chat_names),
        "has_gallery_data": has_gallery_data,
        "has_hashes_db": has_hashes_db,
        "has_sync_db": has_sync_db,
        "has_key": bool(found_key),
        "detected_key_masked": detected_key_masked,
    }


def _merge_gallery_data(source_dir: Path, target_dir: Path, copied_files_map: Dict[str, str]) -> int:
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
                    remapped_media.append(m_copy)
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

                    if sig not in existing_sigs and final_rel not in existing_rels:
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


def execute_import_folder(
    source_dir: str,
    target_dir: str,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    import_key: bool = True,
) -> Dict[str, Any]:
    """
    Safely migrates media from older output folder to target output folder.
    - Copies new media files
    - Avoids duplicate work for files with identical size
    - Renames on size collision to prevent data loss
    - Merges gallery_data.js
    - Merges .hashes_cache.sqlite3
    - Merges .sync_state.sqlite3
    - Optionally imports WhatsApp backup key if found
    """
    valid, err, src_path, tgt_path = validate_paths(source_dir, target_dir)
    if not valid:
        return {"status": "error", "message": err}

    has_gallery_data = (src_path / "gallery_data.js").is_file() or (src_path / "gallery.js").is_file()
    if not has_gallery_data:
        return {
            "status": "error",
            "message": "The selected folder is not a valid WhatsApp Media Organizer output folder (missing gallery_data.js).",
        }

    # Step 0: Optionally import encryption backup key from source
    imported_key = False
    masked_key = ""
    if import_key:
        found_key = extract_key_from_folder(str(src_path))
        if found_key:
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

    media_items = discover_source_media(src_path)
    total_files = len(media_items)

    copied_count = 0
    skipped_count = 0
    copied_bytes = 0
    copied_files_map: Dict[str, str] = {}  # orig_rel -> final_rel

    for idx, (src_file, rel_path, sz) in enumerate(media_items):
        target_file = tgt_path / rel_path

        if target_file.is_file():
            try:
                if target_file.stat().st_size == sz:
                    # Identical size: safe to skip copying
                    skipped_count += 1
                    copied_files_map[rel_path] = rel_path
                    continue
                else:
                    # Collision with different size: rename safely
                    stem, ext = os.path.splitext(target_file.name)
                    counter = 1
                    while True:
                        cand_name = f"{stem}_imported_{counter}{ext}"
                        cand_file = target_file.parent / cand_name
                        if not cand_file.exists():
                            target_file = cand_file
                            break
                        counter += 1
            except OSError:
                pass

        # Perform safe copy
        try:
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, target_file)
            copied_count += 1
            copied_bytes += sz
            final_rel = str(target_file.relative_to(tgt_path)).replace("\\", "/")
            copied_files_map[rel_path] = final_rel
        except Exception as e:
            logger.warning(f"[Migrator] Failed to copy {src_file} -> {target_file}: {e}")

        if progress_callback and (idx % 25 == 0 or idx == total_files - 1):
            progress_callback({
                "phase": "copying",
                "current": idx + 1,
                "total": total_files,
                "percent": int(((idx + 1) / max(total_files, 1)) * 75),
                "copied_count": copied_count,
                "skipped_count": skipped_count,
            })

    # Step 2: Merge Gallery Data
    if progress_callback:
        progress_callback({
            "phase": "merging_gallery",
            "percent": 80,
            "message": "Updating gallery dataset...",
        })
    added_gallery_entries = _merge_gallery_data(src_path, tgt_path, copied_files_map)

    # Step 3: Merge Hash Cache
    if progress_callback:
        progress_callback({
            "phase": "merging_hashes",
            "percent": 90,
            "message": "Merging duplicate hash index...",
        })
    merged_hashes = _merge_hash_databases(src_path, tgt_path, copied_files_map)

    # Step 4: Merge Sync State
    if progress_callback:
        progress_callback({
            "phase": "merging_sync",
            "percent": 95,
            "message": "Reconciling sync manifests...",
        })
    merged_manifest_items = _merge_sync_manifests(src_path, tgt_path, copied_files_map)

    if progress_callback:
        progress_callback({
            "phase": "done",
            "percent": 100,
            "message": "Migration completed successfully!",
        })

    return {
        "status": "success",
        "copied_count": copied_count,
        "skipped_count": skipped_count,
        "copied_bytes": copied_bytes,
        "added_gallery_entries": added_gallery_entries,
        "merged_hashes": merged_hashes,
        "merged_manifest_items": merged_manifest_items,
        "total_source_files": total_files,
        "imported_key": imported_key,
        "masked_key": masked_key,
    }
