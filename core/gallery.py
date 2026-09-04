"""
WhatsApp Media Organizer - Gallery Asset and Index Generation.
Generates gallery_data.js and media_index.csv with thread-safe atomic writes.
"""

import csv
import json
import os
import shutil
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

from core.contacts import resolve_jid_name

# Global re-entrant mutex protecting gallery_data.js and media_index.csv against concurrent writes
gallery_data_lock = threading.RLock()


def generate_gallery(
    organized_list,
    output_dir,
    contacts=None,
    lid_to_phone=None,
    chat_names=None,
    progress=False,
):
    """
    Generates gallery_data.js and copies gallery.html to the output folder.
    Guarantees thread-safe atomic writes to gallery_data.js.
    """
    out_path = Path(output_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    chats_map = defaultdict(
        lambda: {
            "jid": "",
            "name": "",
            "total_size": 0,
            "file_count": 0,
            "media": [],
        }
    )

    contacts_map = contacts or {}
    lids_map = lid_to_phone or {}
    chats_names_map = chat_names or {}

    for item in organized_list:
        jid = item.get("chat_jid") or "unknown_jid"
        name = item.get("chat_name") or "Unknown Chat"

        # Resolve chat name dynamically
        resolved_chat_name = resolve_jid_name(jid, contacts_map, lids_map, chats_names_map)
        if resolved_chat_name:
            name = resolved_chat_name

        chats_map[jid]["jid"] = jid
        chats_map[jid]["name"] = name
        chats_map[jid]["total_size"] += item.get("size_bytes") or 0
        chats_map[jid]["file_count"] += 1

        sender_jid = item.get("sender_jid")
        sender_name = (
            resolve_jid_name(sender_jid, contacts_map, lids_map, chats_names_map)
            if sender_jid
            else None
        )

        media_item = {
            "filename": item.get("filename"),
            "rel_path": item.get("rel_path"),
            "size_bytes": item.get("size_bytes"),
            "mime_type": item.get("mime_type"),
            "thumb_path": item.get("thumb_path"),
            "preview_path": item.get("preview_path"),
            "is_doc": item.get("is_doc", False),
            "received_at": item.get("received_at"),
            "sender_jid": sender_jid,
            "sender_name": sender_name,
            "is_duplicate": item.get("is_duplicate", False),
            "duplicate_reason": item.get("duplicate_reason"),
            "duplicate_primary": item.get("duplicate_primary"),
            "media_duration": item.get("media_duration"),
            "starred": item.get("starred") or 0,
            "from_me": item.get("from_me") or 0,
            "forward_score": item.get("forward_score") or 0,
        }
        chats_map[jid]["media"].append(media_item)

    # Sort chats by total_size, descending
    sorted_chats = sorted(chats_map.values(), key=lambda x: x["total_size"], reverse=True)

    data_js = f"const GALLERY_DATA = {json.dumps({'chats': sorted_chats})};"
    data_path = out_path / "gallery_data.js"
    tmp_data_path = out_path / "gallery_data.js.tmp"

    # Thread-safe atomic file write
    with gallery_data_lock:
        try:
            with open(tmp_data_path, "w", encoding="utf-8") as f:
                f.write(data_js)
            os.replace(tmp_data_path, data_path)
        except Exception as e:
            sys.stderr.write(f"[Gallery] Warning: Failed to write gallery_data.js: {e}\n")

    if progress:
        sys.stdout.write(f"\r[Progress] Streamed {len(organized_list)} files to gallery_data.js...")
        sys.stdout.flush()
    else:
        # Copy gallery.html template to output directory
        script_dir = Path(__file__).resolve().parent.parent
        src_html = script_dir / "gallery.html"
        dest_html = out_path / "gallery.html"
        if src_html.is_file():
            shutil.copy2(src_html, dest_html)

        # Create start_gallery.bat launcher in output_dir
        bat_path = out_path / "start_gallery.bat"
        try:
            with open(bat_path, "w", encoding="utf-8") as bf:
                bf.write(
                    "@echo off\n"
                    'cd /d "%~dp0.."\n'
                    "start venv\\Scripts\\python.exe wa_media_organizer.py --serve --auto-open\n"
                )
        except Exception:
            pass

        # Create sync_and_start_gallery.bat launcher in output_dir
        sync_bat_path = out_path / "sync_and_start_gallery.bat"
        try:
            with open(sync_bat_path, "w", encoding="utf-8") as sbf:
                sbf.write(
                    "@echo off\n"
                    'cd /d "%~dp0.."\n'
                    "start venv\\Scripts\\python.exe wa_media_organizer.py --live\n"
                )
        except Exception:
            pass

    return str(data_path)


def update_gallery_data_js(output_dir, rel_path, preview_path, thumb_path=None):
    """
    Thread-safely updates preview_path and thumb_path for an item in gallery_data.js.
    Uses atomic temp-file replacement.
    """
    data_path = Path(output_dir) / "gallery_data.js"
    if not data_path.is_file():
        return False

    with gallery_data_lock:
        try:
            with open(data_path, "r", encoding="utf-8") as f:
                content = f.read()

            prefix = "const GALLERY_DATA = "
            suffix = ";"
            if content.startswith(prefix):
                js_json = content[len(prefix) :]
                if js_json.strip().endswith(suffix):
                    js_json = js_json.strip()[: -len(suffix)]
                data = json.loads(js_json)

                updated = False
                for chat in data.get("chats", []):
                    for item in chat.get("media", []):
                        if item.get("rel_path") == rel_path:
                            item["preview_path"] = preview_path
                            if thumb_path:
                                item["thumb_path"] = thumb_path
                            updated = True
                            break
                    if updated:
                        break

                if updated:
                    new_content = f"const GALLERY_DATA = {json.dumps(data)};"
                    tmp_path = data_path.with_suffix(".tmp")
                    with open(tmp_path, "w", encoding="utf-8") as f:
                        f.write(new_content)
                    os.replace(tmp_path, data_path)
                    return True
        except Exception as e:
            sys.stderr.write(f"[Gallery] Warning: Failed to update gallery_data.js: {e}\n")
    return False


def update_media_index_csv(output_dir, rel_path, preview_path, thumb_path=None):
    """
    Thread-safely updates preview_path and thumb_path for an item in media_index.csv.
    """
    csv_path = Path(output_dir) / "media_index.csv"
    if not csv_path.is_file():
        return False

    with gallery_data_lock:
        try:
            rows = []
            fieldnames = []
            with open(csv_path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames
                for row in reader:
                    if row.get("rel_path") == rel_path:
                        row["preview_path"] = preview_path
                        if thumb_path:
                            row["thumb_path"] = thumb_path
                    rows.append(row)

            tmp_csv = csv_path.with_suffix(".tmp")
            with open(tmp_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            os.replace(tmp_csv, csv_path)
            return True
        except Exception as e:
            sys.stderr.write(f"[Gallery] Warning: Failed to update media_index.csv: {e}\n")
    return False


def update_gallery_data_live(new_organized, output_dir, contacts=None, lid_to_phone=None, chat_names=None):
    """
    Merges newly organized items into gallery_data.js during live-sync.
    Thread-safe and atomic.
    """
    data_path = Path(output_dir) / "gallery_data.js"
    contacts_map = contacts or {}
    lids_map = lid_to_phone or {}
    chats_names_map = chat_names or {}

    with gallery_data_lock:
        existing_data = {"chats": []}
        if data_path.is_file():
            try:
                with open(data_path, "r", encoding="utf-8") as f:
                    raw = f.read()
                prefix = "const GALLERY_DATA = "
                if raw.startswith(prefix):
                    json_part = raw[len(prefix):].rstrip().rstrip(";")
                    existing_data = json.loads(json_part)
            except Exception as e:
                sys.stderr.write(f"[Live] Warning: Could not parse gallery_data.js: {e}\n")

        chats_by_jid = {c["jid"]: c for c in existing_data.get("chats", [])}
        existing_rel_paths = {
            m["rel_path"] for c in chats_by_jid.values() for m in c.get("media", [])
        }

        added = 0
        for item in new_organized:
            rel_path = item.get("rel_path")
            if not rel_path or rel_path in existing_rel_paths:
                continue

            jid = item.get("chat_jid") or "unknown_jid"
            name = item.get("chat_name") or "Unknown Chat"
            resolved = resolve_jid_name(jid, contacts_map, lids_map, chats_names_map)
            if resolved:
                name = resolved

            sender_jid = item.get("sender_jid")
            sender_name = (
                resolve_jid_name(sender_jid, contacts_map, lids_map, chats_names_map)
                if sender_jid
                else None
            )

            media_item = {
                "filename": item.get("filename"),
                "rel_path": rel_path,
                "size_bytes": item.get("size_bytes"),
                "mime_type": item.get("mime_type"),
                "thumb_path": item.get("thumb_path"),
                "preview_path": item.get("preview_path"),
                "is_doc": item.get("is_doc", False),
                "received_at": item.get("received_at"),
                "sender_jid": sender_jid,
                "sender_name": sender_name,
                "is_duplicate": item.get("is_duplicate", False),
                "duplicate_reason": item.get("duplicate_reason"),
                "duplicate_primary": item.get("duplicate_primary"),
                "media_duration": item.get("media_duration"),
                "starred": item.get("starred") or 0,
                "from_me": item.get("from_me") or 0,
                "forward_score": item.get("forward_score") or 0,
            }

            if jid not in chats_by_jid:
                chats_by_jid[jid] = {
                    "jid": jid,
                    "name": name,
                    "total_size": 0,
                    "file_count": 0,
                    "media": [],
                }

            chats_by_jid[jid]["media"].append(media_item)
            chats_by_jid[jid]["total_size"] += item.get("size_bytes") or 0
            chats_by_jid[jid]["file_count"] += 1
            existing_rel_paths.add(rel_path)
            added += 1

        if added == 0:
            return 0

        sorted_chats = sorted(chats_by_jid.values(), key=lambda x: x["total_size"], reverse=True)
        new_content = f"const GALLERY_DATA = {json.dumps({'chats': sorted_chats})};"

        tmp_path = data_path.with_suffix(".tmp")
        for attempt in range(5):
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    f.write(new_content)
                os.replace(tmp_path, data_path)
                try:
                    current_mtime = data_path.stat().st_mtime
                except Exception:
                    current_mtime = None
                _memory_cache["data"] = {"chats": sorted_chats}
                _memory_cache["mtime"] = current_mtime
                _memory_cache["path"] = str(data_path)
                return added
            except (PermissionError, OSError) as e:
                if attempt == 4:
                    sys.stderr.write(f"[Live] Warning: Failed to write gallery_data.js: {e}\n")
                    return 0
                time.sleep(0.05 * (attempt + 1))
            except Exception as e:
                sys.stderr.write(f"[Live] Warning: Failed to write gallery_data.js: {e}\n")
                return 0
        return 0


# In-memory cached gallery data for fast REST API responses
_memory_cache = {
    "mtime": None,
    "data": None,
    "path": None,
}


def load_gallery_data(output_dir):
    """
    Loads and parses gallery_data.js.
    Caches parsed structure in memory and invalidates automatically if disk mtime changes.
    Thread-safe under gallery_data_lock.
    """
    data_path = Path(output_dir) / "gallery_data.js"
    if not data_path.is_file():
        return {"chats": []}

    try:
        current_mtime = data_path.stat().st_mtime
    except OSError:
        return {"chats": []}

    with gallery_data_lock:
        if (
            _memory_cache["data"] is not None
            and _memory_cache["path"] == str(data_path)
            and _memory_cache["mtime"] == current_mtime
        ):
            return _memory_cache["data"]

        try:
            with open(data_path, "r", encoding="utf-8") as f:
                content = f.read()

            prefix = "const GALLERY_DATA = "
            suffix = ";"
            if content.startswith(prefix):
                js_json = content[len(prefix) :]
                if js_json.strip().endswith(suffix):
                    js_json = js_json.strip()[: -len(suffix)]
                parsed = json.loads(js_json)
                _memory_cache["data"] = parsed
                _memory_cache["mtime"] = current_mtime
                _memory_cache["path"] = str(data_path)
                return parsed
        except Exception as e:
            sys.stderr.write(f"[Gallery] Warning: Failed to parse gallery_data.js: {e}\n")

    return {"chats": []}


def get_chats_summary(output_dir):
    """
    Returns lightweight summary list of all chats (stripping individual media items).
    Payload is ~70 KB for 600+ chats, loading in <10ms (400x smaller than 28.4 MB gallery_data.js).
    """
    data = load_gallery_data(output_dir)
    chats = data.get("chats", [])
    summary = []
    for c in chats:
        summary.append(
            {
                "jid": c.get("jid"),
                "name": c.get("name"),
                "total_size": c.get("total_size", 0),
                "file_count": c.get("file_count", 0),
            }
        )
    return summary


def get_chat_media(output_dir, jid, offset=0, limit=None):
    """
    Returns media items for a specific chat JID with pagination support.
    """
    data = load_gallery_data(output_dir)
    chats = data.get("chats", [])

    matched = None
    for c in chats:
        if c.get("jid") == jid:
            matched = c
            break

    if not matched:
        return None

    media = matched.get("media", [])
    total_items = len(media)

    if limit is not None:
        slice_end = offset + limit
        paginated_media = media[offset:slice_end]
    else:
        paginated_media = media[offset:]

    return {
        "jid": matched.get("jid"),
        "name": matched.get("name"),
        "total_size": matched.get("total_size", 0),
        "file_count": matched.get("file_count", 0),
        "offset": offset,
        "limit": limit,
        "total_items": total_items,
        "media": paginated_media,
    }


