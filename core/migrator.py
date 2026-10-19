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


def pick_folder_dialog(initial_dir: Optional[str] = None) -> Optional[str]:
    """
    Spawns a native OS folder picker dialog window (Explorer on Windows,
    Finder on macOS, or GTK/Tk on Linux) in a short-lived subprocess.
    Returns the chosen absolute path, or None if cancelled or failed.
    """
    # 1. On Windows: Try PowerShell FolderBrowserDialog for a 100% native WinForms experience
    if sys.platform == "win32":
        try:
            init_line = ""
            if initial_dir and os.path.isdir(initial_dir):
                safe_init = initial_dir.replace("'", "''")
                init_line = f"$f.SelectedPath = '{safe_init}'; "

            ps_script = (
                "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; "
                "$f = New-Object System.Windows.Forms.FolderBrowserDialog; "
                "$f.Description = 'Select Older WhatsApp Output Folder to Import'; "
                "$f.ShowNewFolderButton = $false; "
                f"{init_line}"
                "$w = New-Object System.Windows.Forms.Form; "
                "$w.TopMost = $true; "
                "$res = $f.ShowDialog($w); "
                "if ($res -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $f.SelectedPath }"
            )
            res = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if res.returncode == 0:
                selected = res.stdout.strip()
                if selected and os.path.isdir(selected):
                    return selected
        except Exception as e:
            logger.debug(f"[Migrator] Windows PowerShell folder picker fallback: {e}")

    # 2. Cross-platform fallback: Tkinter in a standalone subprocess
    try:
        init_arg = f"initialdir={repr(initial_dir)}" if (initial_dir and os.path.isdir(initial_dir)) else "initialdir=None"
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
            "        print(p)\n"
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
            selected = res.stdout.strip()
            if selected and os.path.isdir(selected):
                return selected
    except Exception as e:
        logger.debug(f"[Migrator] Tkinter folder picker fallback: {e}")

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

    media_items = discover_source_media(src_path)
    total_bytes = sum(sz for _, _, sz in media_items)

    # Check for database files in source
    has_gallery_data = (src_path / "gallery_data.js").is_file()
    has_hashes_db = (src_path / ".hashes_cache.sqlite3").is_file() or (src_path / ".hashes_cache.json").is_file()
    has_sync_db = (src_path / ".sync_state.sqlite3").is_file() or (src_path / ".sync_session.sqlite3").is_file()

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
) -> Dict[str, Any]:
    """
    Safely migrates media from older output folder to target output folder.
    - Copies new media files
    - Avoids duplicate work for files with identical size
    - Renames on size collision to prevent data loss
    - Merges gallery_data.js
    - Merges .hashes_cache.sqlite3
    - Merges .sync_state.sqlite3
    """
    valid, err, src_path, tgt_path = validate_paths(source_dir, target_dir)
    if not valid:
        return {"status": "error", "message": err}

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
    }
