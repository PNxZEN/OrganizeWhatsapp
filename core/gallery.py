"""
WhatsApp Media Organizer - Gallery Asset and Index Generation.
Generates gallery_data.js and media_index.csv with thread-safe atomic writes.
"""

import csv
import json
import os
import re
import shutil
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

from core.contacts import resolve_jid_name

# Global re-entrant mutex protecting gallery_data.js and media_index.csv against concurrent writes
gallery_data_lock = threading.RLock()


def is_subpath(child: Path, parent: Path) -> bool:
    """Safely verifies child path is strictly inside parent directory (prevents path traversal)."""
    try:
        c_res = Path(child).resolve()
        p_res = Path(parent).resolve()
        try:
            return c_res.is_relative_to(p_res)
        except AttributeError:
            return os.path.commonpath([str(c_res), str(p_res)]) == str(p_res)
    except Exception:
        return False


_GALLERY_ASSIGN_RE = re.compile(
    r"^(?:const\s+|let\s+|var\s+|window\.)?GALLERY_DATA\s*=\s*",
    re.IGNORECASE,
)


def parse_gallery_data_js(raw):
    """
    Parses gallery_data.js in both live (`const GALLERY_DATA = ...`) and
    bootstrap (`// comment\\nwindow.GALLERY_DATA = ...`) formats.
    """
    if not raw:
        return None
    text = raw.lstrip("\ufeff").strip()
    while text.startswith("//") or text.startswith("/*"):
        if text.startswith("//"):
            nl = text.find("\n")
            if nl < 0:
                return None
            text = text[nl + 1 :].lstrip()
            continue
        end = text.find("*/")
        if end < 0:
            return None
        text = text[end + 2 :].lstrip()

    match = _GALLERY_ASSIGN_RE.match(text)
    if not match:
        return None
    json_part = text[match.end() :].strip()
    if json_part.endswith(";"):
        json_part = json_part[:-1].rstrip()
    return json.loads(json_part)


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
            "archived": False,
            "last_message_ts": 0,
            "is_group": False,
            "media": [],
        }
    )

    contacts_map = contacts or {}
    lids_map = lid_to_phone or {}
    chats_names_map = chat_names or {}

    # Only run quality duplicate detection if not already analyzed in Step 5
    already_analyzed = any("is_duplicate" in item for item in organized_list[:100]) if organized_list else True
    if not already_analyzed:
        try:
            from core.duplicates import detect_quality_duplicates
            detect_quality_duplicates(organized_list, out_path)
        except Exception as e:
            logger.debug(f"detect_quality_duplicates in generate_gallery: {e}")

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
        chats_map[jid]["is_group"] = bool(jid.endswith("@g.us"))
        if item.get("chat_archived"):
            chats_map[jid]["archived"] = True
        ts = int(item.get("chat_last_active_ts") or 0)
        if ts > chats_map[jid]["last_message_ts"]:
            chats_map[jid]["last_message_ts"] = ts

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
            "md5": item.get("md5"),
            "phash": item.get("phash"),
            "width": item.get("width"),
            "height": item.get("height"),
            "chat_jid": jid,
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

            data = parse_gallery_data_js(content)
            if data is None:
                return False

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
                parsed = parse_gallery_data_js(raw)
                if parsed is not None:
                    existing_data = parsed
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
                "md5": item.get("md5"),
                "phash": item.get("phash"),
                "width": item.get("width"),
                "height": item.get("height"),
                "chat_jid": jid,
            }

            if jid not in chats_by_jid:
                chats_by_jid[jid] = {
                    "jid": jid,
                    "name": name,
                    "total_size": 0,
                    "file_count": 0,
                    "archived": bool(item.get("chat_archived")),
                    "last_message_ts": int(item.get("chat_last_active_ts") or 0),
                    "is_group": bool(jid.endswith("@g.us")),
                    "media": [],
                }
            if item.get("chat_archived"):
                chats_by_jid[jid]["archived"] = True
            ts = int(item.get("chat_last_active_ts") or 0)
            if ts > (chats_by_jid[jid].get("last_message_ts") or 0):
                chats_by_jid[jid]["last_message_ts"] = ts

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

            parsed = parse_gallery_data_js(content)
            if parsed is not None:
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
                "archived": bool(c.get("archived", False)),
                "last_message_ts": int(c.get("last_message_ts") or 0),
                "is_group": bool(c.get("is_group", (c.get("jid") or "").endswith("@g.us"))),
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


def list_recycled_items(output_dir):
    """Returns list of currently recycled items from .duplicates_recycle_bin/manifest.json."""
    recycle_dir = Path(output_dir).resolve() / ".duplicates_recycle_bin"
    manifest_file = recycle_dir / "manifest.json"
    if not manifest_file.is_file():
        return []
    try:
        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        items = []
        for it in manifest.values():
            item_copy = dict(it)
            rel = item_copy.get("rel_path", "")
            if "recycled_path" not in item_copy:
                item_copy["recycled_path"] = f".duplicates_recycle_bin/{rel}"
            if "original_chat" not in item_copy:
                item_copy["original_chat"] = rel.split("/")[0] if "/" in rel else ""
            items.append(item_copy)
        return items
    except Exception:
        return []


def recycle_media_items(output_dir, rel_paths):
    """
    Safely moves duplicate media files into .duplicates_recycle_bin/<rel_path>,
    updates manifest.json, and atomically updates gallery_data.js and media_index.csv.
    Reversible staged quarantine preventing accidental data loss.
    """
    out_path = Path(output_dir).resolve()
    recycle_dir = out_path / ".duplicates_recycle_bin"
    recycle_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = recycle_dir / "manifest.json"

    manifest = {}
    if manifest_file.is_file():
        try:
            with open(manifest_file, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            manifest = {}

    moved = []
    total_reclaimed = 0
    clean_paths_set = set()

    for rel in rel_paths:
        clean_rel = rel.replace("\\", "/").lstrip("/")
        src = (out_path / clean_rel).resolve()
        if not is_subpath(src, out_path):
            continue
        if not src.is_file():
            continue

        dest = (recycle_dir / clean_rel).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        size = src.stat().st_size

        try:
            shutil.move(str(src), str(dest))
            clean_paths_set.add(clean_rel)
            total_reclaimed += size
            clean_chat = clean_rel.split("/")[0] if "/" in clean_rel else ""
            entry = {
                "rel_path": clean_rel,
                "filename": src.name,
                "size_bytes": size,
                "recycled_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "recycled_path": f".duplicates_recycle_bin/{clean_rel}",
                "original_chat": clean_chat,
            }
            manifest[clean_rel] = entry
            moved.append(entry)
        except Exception as e:
            sys.stderr.write(f"[Recycle] Warning: Failed to move {clean_rel}: {e}\n")

    if not moved:
        return {"status": "success", "recycled_count": 0, "reclaimed_bytes": 0, "moved": []}

    # Save manifest
    try:
        tmp_m = manifest_file.with_suffix(".tmp")
        with open(tmp_m, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        os.replace(tmp_m, manifest_file)
    except Exception as e:
        sys.stderr.write(f"[Recycle] Warning: Failed to save manifest: {e}\n")

    # Update gallery_data.js
    with gallery_data_lock:
        data_path = out_path / "gallery_data.js"
        if data_path.is_file():
            try:
                with open(data_path, "r", encoding="utf-8") as f:
                    content = f.read()
                data = parse_gallery_data_js(content)
                if data and "chats" in data:
                    chats = data["chats"]
                    for chat in chats:
                        kept_media = []
                        removed_size = 0
                        for m in chat.get("media", []):
                            m_rel = (m.get("rel_path") or "").replace("\\", "/").lstrip("/")
                            if m_rel in clean_paths_set:
                                removed_size += m.get("size_bytes") or 0
                            else:
                                kept_media.append(m)
                        chat["media"] = kept_media
                        chat["file_count"] = len(kept_media)
                        chat["total_size"] = max(0, (chat.get("total_size") or 0) - removed_size)

                    sorted_chats = sorted(chats, key=lambda x: x["total_size"], reverse=True)
                    new_js = f"const GALLERY_DATA = {json.dumps({'chats': sorted_chats})};"
                    tmp_js = data_path.with_suffix(".tmp")
                    with open(tmp_js, "w", encoding="utf-8") as f:
                        f.write(new_js)
                    os.replace(tmp_js, data_path)
            except Exception as e:
                sys.stderr.write(f"[Recycle] Warning: Failed to update gallery_data.js: {e}\n")

        # Update media_index.csv
        csv_path = out_path / "media_index.csv"
        if csv_path.is_file():
            try:
                rows = []
                fieldnames = []
                with open(csv_path, "r", newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    fieldnames = reader.fieldnames or []
                    for r in reader:
                        r_rel = (r.get("rel_path") or "").replace("\\", "/").lstrip("/")
                        if r_rel not in clean_paths_set:
                            rows.append(r)
                if fieldnames:
                    tmp_csv = csv_path.with_suffix(".tmp")
                    with open(tmp_csv, "w", newline="", encoding="utf-8") as f:
                        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                        writer.writeheader()
                        writer.writerows(rows)
                    os.replace(tmp_csv, csv_path)
            except Exception as e:
                sys.stderr.write(f"[Recycle] Warning: Failed to update media_index.csv: {e}\n")

    return {
        "status": "success",
        "recycled_count": len(moved),
        "reclaimed_bytes": total_reclaimed,
        "moved": moved,
    }


def restore_media_items(output_dir, rel_paths=None, restore_all=False):
    """
    Restores quarantined duplicate files from .duplicates_recycle_bin/ back to original output folders.
    Fully reversible.
    """
    out_path = Path(output_dir).resolve()
    recycle_dir = out_path / ".duplicates_recycle_bin"
    manifest_file = recycle_dir / "manifest.json"

    if not manifest_file.is_file():
        return {"status": "success", "restored_count": 0, "restored": []}

    try:
        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception:
        return {"status": "error", "message": "Could not read manifest.json"}

    target_keys = set(manifest.keys()) if restore_all else set(rel_paths or [])
    restored = []
    keys_to_delete = []

    for key in target_keys:
        if key not in manifest:
            continue
        clean_rel = key.replace("\\", "/").lstrip("/")
        recycled_file = (recycle_dir / clean_rel).resolve()
        dest_file = (out_path / clean_rel).resolve()

        if not is_subpath(dest_file, out_path):
            continue
        if recycled_file.is_file():
            try:
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(recycled_file), str(dest_file))
                restored.append(clean_rel)
                keys_to_delete.append(key)
            except Exception as e:
                sys.stderr.write(f"[Restore] Warning: Failed to restore {clean_rel}: {e}\n")

    for k in keys_to_delete:
        manifest.pop(k, None)

    try:
        tmp_m = manifest_file.with_suffix(".tmp")
        with open(tmp_m, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        os.replace(tmp_m, manifest_file)
    except Exception:
        pass

    return {
        "status": "success",
        "restored_count": len(restored),
        "restored": restored,
    }


def empty_recycle_bin(output_dir):
    """
    Permanently deletes all files quarantined inside .duplicates_recycle_bin and resets manifest.json.
    """
    out_path = Path(output_dir).resolve()
    recycle_dir = out_path / ".duplicates_recycle_bin"
    if not recycle_dir.is_dir():
        return {"status": "success", "success": True, "deleted_count": 0, "freed_bytes": 0}

    manifest_file = recycle_dir / "manifest.json"
    manifest = {}
    if manifest_file.is_file():
        try:
            with open(manifest_file, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            manifest = {}

    deleted_count = len(manifest)
    freed_bytes = sum(int(it.get("size_bytes", 0)) for it in manifest.values())

    # Safely purge all contents inside recycle_dir
    for item in recycle_dir.iterdir():
        try:
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            elif item.is_file():
                item.unlink(missing_ok=True)
        except Exception as e:
            sys.stderr.write(f"[RecycleBin] Warning: Failed to delete {item}: {e}\n")

    # Re-initialize an empty manifest.json
    try:
        recycle_dir.mkdir(parents=True, exist_ok=True)
        with open(recycle_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump({}, f, indent=2)
    except Exception:
        pass

    return {
        "status": "success",
        "success": True,
        "deleted_count": deleted_count,
        "freed_bytes": freed_bytes,
    }



