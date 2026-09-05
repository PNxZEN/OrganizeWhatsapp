"""
WhatsApp Media Organizer - Media Organization Engine.
Handles folder sanitization, file indexing, copy/symlink operations, salvaging, and ZIP archiving.
"""

import errno
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.config import find_ffmpeg_binary, to_long_path

INVALID_CHARS_RE = re.compile(r'[<>:"/\\|?*]')
DUP_SUFFIX_RE = re.compile(r"(_dup\d+|-\d+)$")


WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}


def sanitize_folder_name(name, max_len=60):
    """
    Creates a safe Windows folder name from a chat/group name.
    Replaces invalid characters with underscores, strips trailing dots/spaces,
    and caps length at max_len (default 60) to prevent MAX_PATH overflow.
    """
    if not name:
        return "unnamed_chat"
    sanitized = INVALID_CHARS_RE.sub("_", str(name)).strip()
    sanitized = sanitized.rstrip(". ")
    if not sanitized or not re.sub(r"[\s.]", "", sanitized):
        return "unnamed_chat"
    sanitized = sanitized[:max_len].rstrip(". ")
    if not sanitized:
        return "unnamed_chat"
    if sanitized.upper() in WINDOWS_RESERVED_NAMES:
        sanitized = f"_{sanitized}"
    return sanitized


def sanitize_filename(filename):
    """
    Replaces invalid filesystem characters and trims trailing periods/whitespace.
    """
    if not filename:
        return "unnamed_file"
    sanitized = INVALID_CHARS_RE.sub("_", str(filename)).strip()
    sanitized = sanitized.rstrip(". ")
    if not sanitized:
        return "unnamed_file"
    stem, ext = os.path.splitext(sanitized)
    if stem.upper() in WINDOWS_RESERVED_NAMES:
        sanitized = f"_{stem}{ext}"
    return sanitized


def normalize_filename(filename, strip_dup_suffix=False):
    """
    Unified filename normalization for indexing and duplicate detection.
    Lowercases, sanitizes invalid characters, and optionally strips duplicate counters.
    Trims trailing dots and spaces to maintain parity between Android and Windows naming.
    Resolves BUG-01.
    """
    if not filename:
        return ""
    stem, ext = os.path.splitext(str(filename).lower())
    sanitized_stem = INVALID_CHARS_RE.sub("_", stem).rstrip(". ")
    if strip_dup_suffix:
        sanitized_stem = DUP_SUFFIX_RE.sub("", sanitized_stem).rstrip(". ")
    full = sanitized_stem + ext.lower()
    return full.rstrip(". ")



def index_media_files(media_root, secondary_roots=None):
    """
    Recursively walks the Media directory (and optional secondary roots like output)
    and builds normalized_filename -> path map and path -> size map.
    Primary root takes precedence; secondary roots fill in only if filename not already seen.
    """
    index = {}
    sizes = {}

    def _walk_root(root_path, is_primary):
        p = Path(root_path)
        if not p.is_dir():
            return
        for root, dirs, files in os.walk(str(p)):
            # Prune .cache and .thumbnails directories in-place
            dirs[:] = [d for d in dirs if d not in (".cache", ".thumbnails")]
            for f in files:
                if f in (
                    "media_index.csv",
                    "gallery.html",
                    "gallery_data.js",
                    "start_gallery.bat",
                    "sync_and_start_gallery.bat",
                ):
                    continue
                norm = normalize_filename(f)
                if is_primary or norm not in index:
                    full_p = os.path.join(root, f)
                    index[norm] = full_p
                    try:
                        sizes[full_p] = os.stat(full_p).st_size
                    except Exception:
                        sizes[full_p] = 0

    _walk_root(media_root, is_primary=True)
    for sec in secondary_roots or []:
        _walk_root(sec, is_primary=False)

    return index, sizes


def organize_media(
    media_rows,
    file_index,
    file_hashes,
    md5_map,
    phash_map,
    output_dir,
    contacts=None,
    mode="copy",
    actual_sizes=None,
    quality_duplicate_detector=None,
):
    """
    Copies or symlinks each media file into output/<chat_name>/<YYYY-MM>/<filename>.
    Returns (summary_dict, organized_list).
    """
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    summary = defaultdict(lambda: {"count": 0, "total_bytes": 0, "unmatched": 0})
    organized_list = []

    dest_file_sizes = {}
    if out.is_dir():
        for root, _, files in os.walk(str(out)):
            for f in files:
                p = os.path.join(root, f)
                try:
                    rel = Path(p).relative_to(out)
                    dest_file_sizes[str(rel).replace("\\", "/")] = os.stat(p).st_size
                except Exception:
                    continue

    if actual_sizes is None:
        actual_sizes = {}
        for row in media_rows:
            filename = row.get("filename", "")
            norm_filename = normalize_filename(filename)
            actual_path = file_index.get(norm_filename)
            if actual_path and actual_path not in actual_sizes:
                try:
                    actual_sizes[actual_path] = os.path.getsize(actual_path)
                except Exception:
                    actual_sizes[actual_path] = 0

    # Calculate required disk space
    total_required_bytes = 0
    for row in media_rows:
        filename = row.get("filename", "")
        norm_filename = normalize_filename(filename)
        actual_path = file_index.get(norm_filename)
        if actual_path:
            actual_size = actual_sizes.get(actual_path, 0)
            if actual_size > 0:
                chat_name = sanitize_folder_name(row.get("chat_name", ""))
                try:
                    dt = datetime.fromisoformat(row["received_at"])
                    date_folder = f"{dt.year:04d}-{dt.month:02d}"
                except (ValueError, TypeError, KeyError):
                    date_folder = "unknown-date"

                rel_dest_key = f"{chat_name}/{date_folder}/{filename}"
                if (
                    rel_dest_key not in dest_file_sizes
                    or dest_file_sizes[rel_dest_key] != actual_size
                ):
                    total_required_bytes += actual_size

    if mode == "copy" and total_required_bytes > 0:
        try:
            _, _, free = shutil.disk_usage(str(out))
            if free < (total_required_bytes + 50 * 1024 * 1024):
                raise OSError(
                    errno.ENOSPC,
                    f"Insufficient disk space on destination drive. "
                    f"Required: {total_required_bytes / (1024*1024):.1f} MB, "
                    f"Available: {free / (1024*1024):.1f} MB",
                )
        except OSError:
            raise
        except Exception as e:
            sys.stderr.write(f"[Organizer] Warning: Could not verify disk space: {e}\n")

    for idx, row in enumerate(media_rows):
        chat_name = sanitize_folder_name(row.get("chat_name", ""))
        filename = row.get("filename", "")

        norm_filename = normalize_filename(filename)
        actual_path = file_index.get(norm_filename)
        if (
            not actual_path
            or actual_path not in actual_sizes
            or actual_sizes[actual_path] == 0
        ):
            summary[chat_name]["unmatched"] += 1
            continue

        actual_size = actual_sizes[actual_path]
        is_heic = filename.lower().endswith((".heic", ".heif"))
        dest_filename = sanitize_filename(filename)

        try:
            dt = datetime.fromisoformat(row["received_at"])
            date_folder = f"{dt.year:04d}-{dt.month:02d}"
        except (ValueError, TypeError, KeyError):
            date_folder = "unknown-date"

        dest_dir = out / chat_name / date_folder
        dest_file = dest_dir / dest_filename

        need_copy = True
        rel_dest_key = f"{chat_name}/{date_folder}/{dest_filename}"
        if rel_dest_key in dest_file_sizes:
            if dest_file_sizes[rel_dest_key] == actual_size:
                need_copy = False
            else:
                stem, ext = os.path.splitext(dest_filename)
                counter = 1
                while True:
                    candidate_name = f"{stem}_dup{counter}{ext}"
                    candidate_key = f"{chat_name}/{date_folder}/{candidate_name}"
                    candidate_file = dest_dir / candidate_name
                    if candidate_key in dest_file_sizes:
                        if dest_file_sizes[candidate_key] == actual_size:
                            dest_filename = candidate_name
                            dest_file = candidate_file
                            need_copy = False
                            break
                        else:
                            counter += 1
                    else:
                        dest_filename = candidate_name
                        dest_file = candidate_file
                        need_copy = True
                        break

        try:
            if need_copy:
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_long = to_long_path(dest_file)
                actual_long = to_long_path(actual_path)
                if mode == "symlink":
                    os.symlink(actual_long, dest_long)
                else:
                    shutil.copy2(actual_long, dest_long)
                dest_file_sizes[f"{chat_name}/{date_folder}/{dest_filename}"] = actual_size

            # Thumbnail and preview paths
            thumb_path = None
            preview_path = None

            mime_type = (
                "image/heic"
                if is_heic
                else (
                    mimetypes.guess_type(dest_filename)[0]
                    if not row.get("mime_type")
                    or row.get("mime_type") in ("NULL", "application/octet-stream", "")
                    else row.get("mime_type")
                )
            ) or ""

            if is_heic:
                thumb_dir = out / ".thumbnails" / chat_name / date_folder
                thumb_file = thumb_dir / (dest_filename + ".jpg")
                thumb_small = thumb_dir / (dest_filename + ".thumb.jpg")
                if not thumb_file.is_file() or thumb_file.stat().st_size == 0 or not thumb_small.is_file():
                    try:
                        thumb_dir.mkdir(parents=True, exist_ok=True)
                        from PIL import Image
                        from pillow_heif import register_heif_opener

                        register_heif_opener()
                        with Image.open(actual_path) as img:
                            if not thumb_file.is_file() or thumb_file.stat().st_size == 0:
                                img.save(thumb_file, "JPEG", quality=80)
                            if not thumb_small.is_file() or thumb_small.stat().st_size == 0:
                                img_thumb = img.copy()
                                img_thumb.thumbnail((280, 280), Image.Resampling.BILINEAR)
                                if img_thumb.mode != "RGB":
                                    img_thumb = img_thumb.convert("RGB")
                                img_thumb.save(thumb_small, "JPEG", quality=80)
                    except Exception as heic_err:
                        sys.stderr.write(
                            f"[Organizer] Warning: Failed to generate HEIC thumbnail for {filename}: {heic_err}\n"
                        )

                if thumb_file.is_file() and thumb_file.stat().st_size > 0:
                    thumb_path = f".thumbnails/{chat_name}/{date_folder}/{dest_filename}.jpg"
            elif mime_type.startswith("video/") or dest_filename.lower().endswith(
                (".mp4", ".m4v", ".mov", ".avi", ".mkv", ".3gp", ".flv")
            ):
                lower_name = dest_filename.lower()
                is_unsupported = lower_name.endswith((".mov", ".avi", ".mkv", ".3gp", ".flv"))
                thumb_dir = out / ".thumbnails" / chat_name / date_folder
                thumb_file = thumb_dir / (dest_filename + ".jpg")
                cache_dir = out / ".cache" / chat_name / date_folder
                preview_file = cache_dir / (dest_filename + "_preview.mp4")

                if is_unsupported:
                    if thumb_file.is_file() and thumb_file.stat().st_size > 0:
                        thumb_path = f".thumbnails/{chat_name}/{date_folder}/{dest_filename}.jpg"
                        if preview_file.is_file() and preview_file.stat().st_size > 0:
                            preview_path = f".cache/{chat_name}/{date_folder}/{dest_filename}_preview.mp4"
                    else:
                        try:
                            thumb_dir.mkdir(parents=True, exist_ok=True)
                            cmd = [
                                find_ffmpeg_binary(),
                                "-y",
                                "-ss",
                                "00:00:00.500",
                                "-i",
                                str(actual_path),
                                "-frames:v",
                                "1",
                                "-q:v",
                                "4",
                                str(thumb_file),
                            ]
                            subprocess.run(
                                cmd,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                check=False,
                            )
                        except Exception:
                            pass

                        if thumb_file.is_file() and thumb_file.stat().st_size > 0:
                            thumb_path = f".thumbnails/{chat_name}/{date_folder}/{dest_filename}.jpg"
                        if preview_file.is_file() and preview_file.stat().st_size > 0:
                            preview_path = f".cache/{chat_name}/{date_folder}/{dest_filename}_preview.mp4"
                else:
                    if preview_file.is_file() and preview_file.stat().st_size > 0:
                        preview_path = f".cache/{chat_name}/{date_folder}/{dest_filename}_preview.mp4"
                    if thumb_file.is_file() and thumb_file.stat().st_size > 0:
                        thumb_path = f".thumbnails/{chat_name}/{date_folder}/{dest_filename}.jpg"

            summary[chat_name]["count"] += 1
            summary[chat_name]["total_bytes"] += actual_size

            md5, phash = file_hashes.get(norm_filename, (None, None))
            is_dup = False
            dup_reason = None
            dup_primary = None

            if md5 and len(md5_map.get(md5, [])) > 1:
                is_dup = True
                dup_reason = "exact"
                dup_primary = sorted(md5_map[md5])[0]
            elif phash and len(phash_map.get(phash, [])) > 1:
                is_dup = True
                dup_reason = "perceptual"
                dup_primary = sorted(phash_map[phash])[0]

            is_doc = False
            if actual_path:
                norm_actual = actual_path.replace("\\", "/")
                if any(k in norm_actual for k in ("WhatsApp Documents", "Databases", "Backups")):
                    is_doc = True

            organized_list.append(
                {
                    "chat_jid": row.get("chat_jid"),
                    "chat_name": row.get("chat_name"),
                    "filename": dest_filename,
                    "rel_path": f"{chat_name}/{date_folder}/{dest_filename}",
                    "size_bytes": actual_size,
                    "mime_type": mime_type,
                    "thumb_path": thumb_path,
                    "preview_path": preview_path,
                    "is_doc": is_doc,
                    "received_at": row.get("received_at"),
                    "sender_jid": row.get("sender_jid"),
                    "md5": md5,
                    "phash": phash,
                    "is_duplicate": is_dup,
                    "duplicate_reason": dup_reason,
                    "duplicate_primary": dup_primary if dup_primary != norm_filename else None,
                    "media_duration": row.get("media_duration"),
                    "starred": row.get("starred") or 0,
                    "from_me": row.get("from_me") or 0,
                    "forward_score": row.get("forward_score") or 0,
                }
            )

        except OSError as e:
            if e.errno == errno.ENOSPC:
                raise
            sys.stderr.write(f"[Organizer] Warning: Failed to copy {filename}: {e}\n")
        except Exception as e:
            sys.stderr.write(f"[Organizer] Warning: Failed to copy {filename}: {e}\n")

    if organized_list and quality_duplicate_detector:
        try:
            quality_duplicate_detector(organized_list, out, file_hashes)
        except Exception as e:
            sys.stderr.write(f"[Organizer] Warning: Quality duplicate detection error: {e}\n")

    return dict(summary), organized_list


def salvage_unmatched_media(media_dir, output_dir, organized_filenames_lower):
    """
    Salvages media files from media_dir not matched to any database record.
    Copies them into output_dir/_unmatched/<subfolder>/<filename>.
    """
    media_root = Path(media_dir)
    out = Path(output_dir)
    unmatched_root = out / "_unmatched"

    if not media_root.is_dir():
        return 0

    # Clean up _unmatched files that are now organized
    if unmatched_root.is_dir():
        for p in list(unmatched_root.rglob("*")):
            if p.is_file() and p.name.lower() in organized_filenames_lower:
                try:
                    p.unlink()
                except OSError:
                    pass

    salvaged_count = 0
    for root, dirs, files in os.walk(str(media_root)):
        dirs[:] = [d for d in dirs if d not in (".cache", ".thumbnails")]
        for f in files:
            if f.lower() in organized_filenames_lower:
                continue
            src_path = Path(root) / f
            try:
                rel = src_path.relative_to(media_root)
            except ValueError:
                continue

            dest_path = unmatched_root / rel
            if dest_path.is_file() and dest_path.stat().st_size == src_path.stat().st_size:
                continue

            dest_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(to_long_path(src_path), to_long_path(dest_path))
                salvaged_count += 1
            except Exception as e:
                sys.stderr.write(f"[Salvage] Warning: Failed to copy {f}: {e}\n")

    return salvaged_count


def zip_chat(chat_name, output_dir, verify=True):
    """
    Zips all media files in the organized directory for the specified chat_name.
    Stores the zip in output_dir/backups/<chat_name>_<timestamp>.zip.
    Returns (success: bool, zip_path: str, file_count: int).
    """
    sanitized_name = sanitize_folder_name(chat_name)
    chat_dir = Path(output_dir) / sanitized_name

    if not chat_dir.is_dir():
        # Case-insensitive and space/underscore flexible search
        matched = None
        target_norm = re.sub(r"[\s_]+", "", sanitized_name.lower())
        for item in Path(output_dir).iterdir():
            if item.is_dir() and not item.name.startswith("."):
                item_norm = re.sub(r"[\s_]+", "", item.name.lower())
                if item_norm == target_norm:
                    matched = item
                    sanitized_name = item.name
                    break
        if matched:
            chat_dir = matched
        else:
            return False, f"Chat folder '{sanitized_name}' not found", 0

    backup_dir = Path(output_dir) / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_filename = f"{sanitized_name}_{timestamp}.zip"
    zip_path = backup_dir / zip_filename

    media_files = []
    for root, dirs, files in os.walk(str(chat_dir)):
        dirs[:] = [d for d in dirs if d not in (".cache", ".thumbnails")]
        for f in files:
            full_p = os.path.join(root, f)
            rel_p = os.path.relpath(full_p, str(chat_dir)).replace("\\", "/")
            media_files.append((full_p, rel_p))

    if not media_files:
        return False, "No media files found in chat folder", 0

    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as z:
        for full_p, rel_p in media_files:
            z.write(full_p, arcname=rel_p)

    if verify:
        with zipfile.ZipFile(str(zip_path), "r") as z:
            for full_p, rel_p in media_files:
                h_orig = hashlib.md5()
                with open(full_p, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        h_orig.update(chunk)

                with z.open(rel_p) as f:
                    h_zip = hashlib.md5()
                    for chunk in iter(lambda: f.read(65536), b""):
                        h_zip.update(chunk)

                if h_orig.hexdigest() != h_zip.hexdigest():
                    return False, f"MD5 mismatch on {rel_p}", 0

    return True, str(zip_path), len(media_files)


def zip_file_list(rel_paths, output_dir, verify=True):
    """
    Zips a specific list of relative paths under output_dir into selected_backup.zip.
    Returns (success: bool, zip_path: str, file_count: int).
    """
    if not rel_paths:
        return False, "No files specified", 0

    backup_dir = Path(output_dir) / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = backup_dir / f"selected_{timestamp}.zip"

    packed = []
    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as z:
        for r_path in rel_paths:
            full_path = Path(output_dir) / r_path
            if full_path.is_file():
                arcname = str(r_path).replace("\\", "/")
                z.write(str(full_path), arcname=arcname)
                packed.append((str(full_path), arcname))

    if not packed:
        return False, "None of the specified files were found on disk", 0

    if verify:
        with zipfile.ZipFile(str(zip_path), "r") as z:
            for full_path, arcname in packed:
                h_orig = hashlib.md5()
                with open(full_path, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        h_orig.update(chunk)

                with z.open(arcname) as f:
                    h_zip = hashlib.md5()
                    for chunk in iter(lambda: f.read(65536), b""):
                        h_zip.update(chunk)

                if h_orig.hexdigest() != h_zip.hexdigest():
                    return False, f"MD5 mismatch on {arcname}", 0

    return True, str(zip_path), len(packed)


class StreamingMediaRouter:
    """
    On-the-fly streaming router and live organizer for WhatsApp media transfers.
    Routes incoming phone files directly into final chat/date folders:
      - Matched to WhatsApp message -> output/<Chat Name>/<YYYY-MM>/<filename>
      - Unmatched / Deleted Chat -> output/_unmatched/<Folder>/<filename>
      - Backups / Wallpapers -> output/Backups/<filename>
    Preserves exact original phone_path traceability, avoids duplicate storage,
    handles name collisions safely, and flushes incremental updates to gallery_data.js.
    """

    def __init__(self, output_dir, media_rows=None, contacts=None, lid_to_phone=None, chat_names=None, mode="copy"):
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.mode = mode
        self.contacts = contacts or {}
        self.lid_to_phone = lid_to_phone or {}
        self.chat_names = chat_names or {}

        # Pre-index media_rows by lowercase sanitized and raw filename, hashes, and size
        self.media_map: Dict[str, dict] = {}
        self.hash_map: Dict[str, dict] = {}
        self.size_map: Dict[int, List[dict]] = defaultdict(list)
        if media_rows:
            for r in media_rows:
                fn = r.get("filename")
                mn = r.get("media_name")
                fp = r.get("file_path")
                fh = r.get("file_hash")
                efh = r.get("enc_file_hash")
                sz = r.get("size_bytes")

                for name_cand in (fn, mn, os.path.basename(fp) if fp else None):
                    if name_cand:
                        raw_lower = name_cand.strip().lower()
                        clean_lower = sanitize_filename(name_cand).lower()
                        if raw_lower not in self.media_map:
                            self.media_map[raw_lower] = r
                        if clean_lower not in self.media_map:
                            self.media_map[clean_lower] = r

                if fh and isinstance(fh, str):
                    self.hash_map[fh.strip()] = r
                if efh and isinstance(efh, str):
                    self.hash_map[efh.strip()] = r

                if sz and isinstance(sz, int) and sz > 0:
                    self.size_map[sz].append(r)

        # Track existing file paths and sizes in output_dir to prevent overwrites
        self.dest_file_sizes: Dict[str, int] = {}
        self._init_dest_index()

        self.gallery_buffer: List[dict] = []
        self.all_organized: List[dict] = []
        self.summary: Dict[str, dict] = defaultdict(lambda: {"count": 0, "total_bytes": 0, "unmatched": 0})
        self.last_flush_time = time.time()
        self.lock = threading.Lock()

    def _init_dest_index(self):
        if not self.output_dir.is_dir():
            return
        skip_dirs = {".thumbnails", ".cache", ".git"}
        for p in self.output_dir.rglob("*"):
            if p.is_file() and not any(part in skip_dirs for part in p.parts):
                try:
                    rel = p.relative_to(self.output_dir).as_posix()
                    self.dest_file_sizes[rel] = p.stat().st_size
                except Exception:
                    pass

    def resolve_destination(self, phone_rel_path: str, file_size: int) -> Tuple[Optional[Path], Optional[dict]]:
        """
        Determines the target path for an incoming phone file and returns (dest_path, matched_row).
        Returns (None, None) if the file should be skipped (e.g. .nomedia or link previews).
        """
        norm_phone = phone_rel_path.replace("\\", "/").lstrip("/")
        filename = os.path.basename(norm_phone)

        # 1. Filter out Android system marker files (.nomedia)
        if filename == ".nomedia" or norm_phone.endswith("/.nomedia"):
            return None, None

        # 2. Filter out link preview thumbnail cache (.Links)
        if norm_phone.startswith("Media/.Links/") or norm_phone.startswith(".Links/"):
            return None, None

        # Databases go directly to Databases/
        if norm_phone.startswith("Databases/"):
            sub = norm_phone[len("Databases/") :]
            dest_p = Path("./Databases") / sub
            return dest_p, None

        # Backups go to output/Backups/
        if norm_phone.startswith("Backups/"):
            sub = norm_phone[len("Backups/") :]
            dest_p = self.output_dir / "Backups" / sub
            return dest_p, None

        # Tier 1: Filename lookup (exact or sanitized)
        lookup_key = filename.strip().lower()
        matched_row = self.media_map.get(lookup_key)

        # Tier 2: Hash lookup (for stickers / hashed names)
        if not matched_row:
            raw_stem = Path(filename).stem
            matched_row = self.hash_map.get(raw_stem)

        # Tier 3: Unambiguous exact byte-size lookup
        if not matched_row and file_size > 0:
            candidates = self.size_map.get(file_size)
            if candidates and len(candidates) == 1:
                matched_row = candidates[0]

        if matched_row:
            raw_chat_name = matched_row.get("chat_name") or "Unknown_Chat"
            chat_folder = sanitize_folder_name(raw_chat_name)
            try:
                dt = datetime.fromisoformat(matched_row.get("received_at", ""))
                date_folder = f"{dt.year:04d}-{dt.month:02d}"
            except Exception:
                date_folder = "unknown-date"

            dest_dir = self.output_dir / chat_folder / date_folder

            # User requirement: Store and display the real human-readable media_name for documents
            media_name = matched_row.get("media_name")
            if media_name and media_name != "NULL" and not media_name.endswith(".crypt15") and ("." in media_name and "." not in filename):
                clean_fn = sanitize_filename(media_name)
            elif media_name and matched_row.get("message_type") == 9 and "." in media_name:
                clean_fn = sanitize_filename(media_name)
            else:
                clean_fn = sanitize_filename(filename)
        else:
            # Unmatched media
            # User requirement: Downloaded sticker packs go to Stickers/Sticker Packs
            if "Backup Excluded Stickers" in norm_phone or norm_phone.startswith("Media/WhatsApp Sticker Packs") or norm_phone.startswith("WhatsApp Sticker Packs"):
                dest_dir = self.output_dir / "Stickers" / "Sticker Packs"
            else:
                parts = norm_phone.split("/")
                if len(parts) > 2 and parts[0] == "Media":
                    sub_parts = parts[1:-1]
                    sanitized_subs = [sanitize_folder_name(p) for p in sub_parts if p]
                    dest_dir = self.output_dir / "_unmatched" / Path(*sanitized_subs) if sanitized_subs else self.output_dir / "_unmatched"
                else:
                    dest_dir = self.output_dir / "_unmatched"
            clean_fn = sanitize_filename(filename)

        os.makedirs(to_long_path(dest_dir), exist_ok=True)
        dest_file = dest_dir / clean_fn

        # Collision avoidance: if file exists with different size, suffix with _dupN
        try:
            rel_key = dest_file.relative_to(self.output_dir).as_posix()
        except ValueError:
            rel_key = dest_file.as_posix()

        if rel_key in self.dest_file_sizes and self.dest_file_sizes[rel_key] != file_size:
            stem, ext = os.path.splitext(clean_fn)
            counter = 1
            while True:
                candidate_name = f"{stem}_dup{counter}{ext}"
                candidate_file = dest_dir / candidate_name
                try:
                    candidate_key = candidate_file.relative_to(self.output_dir).as_posix()
                except ValueError:
                    candidate_key = candidate_file.as_posix()
                if candidate_key in self.dest_file_sizes:
                    if self.dest_file_sizes[candidate_key] == file_size:
                        dest_file = candidate_file
                        break
                    counter += 1
                else:
                    dest_file = candidate_file
                    break

        return dest_file, matched_row

    def record_committed_file(
        self,
        phone_rel_path: str,
        dest_path: Path,
        file_size: int,
        matched_row: Optional[dict] = None,
    ):
        """
        Records a successfully committed file, updates in-memory gallery buffer,
        and flushes incrementally to gallery_data.js.
        """
        norm_phone = phone_rel_path.replace("\\", "/").lstrip("/")
        if norm_phone.startswith("Databases/"):
            return

        with self.lock:
            try:
                rel_dest = dest_path.relative_to(self.output_dir).as_posix()
            except ValueError:
                rel_dest = dest_path.as_posix()

            self.dest_file_sizes[rel_dest] = file_size

            is_heic = dest_path.suffix.lower() in (".heic", ".heif")
            mime_type = (
                "image/heic"
                if is_heic
                else (mimetypes.guess_type(dest_path.name)[0] or "application/octet-stream")
            )

            if matched_row is None:
                filename = os.path.basename(norm_phone)
                matched_row = self.media_map.get(filename.strip().lower())
                if not matched_row:
                    raw_stem = Path(filename).stem
                    matched_row = self.hash_map.get(raw_stem)
                if not matched_row and file_size > 0:
                    candidates = self.size_map.get(file_size)
                    if candidates and len(candidates) == 1:
                        matched_row = candidates[0]

            if matched_row:
                chat_name = matched_row.get("chat_name") or "Unknown_Chat"
                chat_jid = matched_row.get("chat_jid") or "unknown"
                received_at = matched_row.get("received_at", "")
                sender_jid = matched_row.get("sender_jid", "")
                is_doc = matched_row.get("is_doc", False) or matched_row.get("message_type") == 9
                starred = matched_row.get("starred", 0)
                from_me = matched_row.get("from_me", 0)
                forward_score = matched_row.get("forward_score", 0)
                self.summary[chat_name]["count"] += 1
                self.summary[chat_name]["total_bytes"] += file_size
            elif "Backup Excluded Stickers" in norm_phone or norm_phone.startswith("Media/WhatsApp Sticker Packs") or norm_phone.startswith("WhatsApp Sticker Packs"):
                chat_name = "Sticker Packs"
                chat_jid = "stickers@whatsapp.net"
                received_at = ""
                sender_jid = ""
                is_doc = False
                starred = 0
                from_me = 0
                forward_score = 0
                self.summary["Sticker Packs"]["count"] += 1
                self.summary["Sticker Packs"]["total_bytes"] += file_size
            else:
                chat_name = "_unmatched"
                chat_jid = "_unmatched"
                received_at = ""
                sender_jid = ""
                is_doc = False
                starred = 0
                from_me = 0
                forward_score = 0
                self.summary["_unmatched"]["unmatched"] += 1
                self.summary["_unmatched"]["count"] += 1
                self.summary["_unmatched"]["total_bytes"] += file_size

            is_dup = bool(re.search(r"_dup\d+", dest_path.name))
            dup_reason = "collision" if is_dup else ""
            dup_primary = re.sub(r"_dup\d+", "", dest_path.name) if is_dup else ""

            item = {
                "chat_jid": chat_jid,
                "chat_name": chat_name,
                "filename": dest_path.name,
                "rel_path": rel_dest,
                "phone_path": norm_phone,  # PRESERVE ORIGINAL DEVICE PATH!
                "size_bytes": file_size,
                "mime_type": mime_type,
                "thumb_path": None,
                "preview_path": None,
                "is_doc": is_doc,
                "received_at": received_at,
                "sender_jid": sender_jid,
                "md5": "",
                "phash": "",
                "is_duplicate": is_dup,
                "duplicate_reason": dup_reason,
                "duplicate_primary": dup_primary,
                "media_duration": 0,
                "starred": starred,
                "from_me": from_me,
                "forward_score": forward_score,
            }

            self.gallery_buffer.append(item)
            self.all_organized.append(item)

            now = time.time()
            if len(self.gallery_buffer) >= 50 or (now - self.last_flush_time) >= 2.0:
                self._flush_buffer()

    def _flush_buffer(self):
        if not self.gallery_buffer:
            return
        from core.gallery import update_gallery_data_live
        update_gallery_data_live(
            self.gallery_buffer,
            str(self.output_dir),
            contacts=self.contacts,
            lid_to_phone=self.lid_to_phone,
            chat_names=self.chat_names,
        )
        self.gallery_buffer.clear()
        self.last_flush_time = time.time()

    def flush_all(self, export_csv: bool = True):
        """Flushes any remaining items in buffer and exports media_index.csv."""
        with self.lock:
            self._flush_buffer()
            if export_csv and self.all_organized:
                self._export_csv()
            return dict(self.summary), list(self.all_organized)

    def _export_csv(self):
        csv_path = self.output_dir / "media_index.csv"
        fieldnames = [
            "chat_jid",
            "chat_name",
            "filename",
            "rel_path",
            "phone_path",  # Dedicated column for phone space reclamation
            "size_bytes",
            "mime_type",
            "thumb_path",
            "preview_path",
            "is_doc",
            "received_at",
            "sender_jid",
            "md5",
            "phash",
            "is_duplicate",
            "duplicate_reason",
            "duplicate_primary",
            "media_duration",
            "starred",
            "from_me",
            "forward_score",
        ]
        tmp_csv = csv_path.with_suffix(".tmp")
        try:
            with open(tmp_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(self.all_organized)
            os.replace(tmp_csv, csv_path)
        except Exception as e:
            sys.stderr.write(f"[Live] Warning: Failed to export media_index.csv: {e}\n")


def reorganize_unmatched_media(
    output_dir,
    media_rows=None,
    contacts=None,
    lid_to_phone=None,
    chat_names=None,
):
    """
    Cleans and reorganizes output/_unmatched/ media:
    1. Purges zero-byte .nomedia marker files.
    2. Purges .Links/ web preview thumbnail cache icons.
    3. Moves downloaded sticker pack assets into output/Stickers/Sticker Packs/.
    4. Deterministically rematches remaining media files against WhatsApp database
       metadata (via exact filename, document media_name, file hash, or unambiguous exact byte size).
    5. Prunes empty directories under output/_unmatched/.
    6. Synchronizes gallery_data.js and media_index.csv.
    Returns a summary dictionary with counts.
    """
    out_dir = Path(output_dir).resolve()
    unmatched_dir = out_dir / "_unmatched"

    summary = {
        "deleted_nomedia": 0,
        "deleted_links": 0,
        "rematched": 0,
        "sticker_packs": 0,
        "still_unmatched": 0,
    }

    if not unmatched_dir.is_dir():
        return summary

    # Auto-load database mappings if not supplied
    if media_rows is None:
        msgstore = Path("./Databases/msgstore.db")
        wa_db = Path("./Databases/wa.db")
        if msgstore.is_file():
            try:
                from core.contacts import load_contacts_mapping, load_db_mappings
                from core.database import build_media_index

                if chat_names is None or lid_to_phone is None:
                    c_names, lids = load_db_mappings(str(msgstore))
                    if chat_names is None:
                        chat_names = c_names
                    if lid_to_phone is None:
                        lid_to_phone = lids
                if contacts is None:
                    contacts = load_contacts_mapping(skip_pull=True)
                wa_active = str(wa_db) if wa_db.is_file() else None
                media_rows = build_media_index(
                    str(msgstore), wa_active, contacts, lid_to_phone, chat_names
                )
            except Exception as e:
                sys.stderr.write(f"[Reorganize] Warning: Failed to load media rows: {e}\n")

    router = StreamingMediaRouter(
        output_dir=out_dir,
        media_rows=media_rows,
        contacts=contacts,
        lid_to_phone=lid_to_phone,
        chat_names=chat_names,
    )

    # 1. Purge .nomedia files
    for p in list(unmatched_dir.rglob(".nomedia")):
        try:
            p.unlink(missing_ok=True)
            summary["deleted_nomedia"] += 1
        except Exception:
            pass

    # 2. Purge .Links directories and preview thumbnails
    for p in list(unmatched_dir.rglob("*")):
        if p.is_file() and ".Links" in p.parts:
            try:
                p.unlink(missing_ok=True)
                summary["deleted_links"] += 1
            except Exception:
                pass
    links_dir = unmatched_dir / ".Links"
    if links_dir.is_dir():
        try:
            shutil.rmtree(str(links_dir), ignore_errors=True)
        except Exception:
            pass

    # 3. Process remaining physical files in _unmatched
    remaining_files = [p for p in unmatched_dir.rglob("*") if p.is_file()]
    for p in remaining_files:
        if p.name == ".nomedia" or ".Links" in p.parts:
            continue

        try:
            file_size = p.stat().st_size
        except Exception:
            continue

        rel_under_unmatched = p.relative_to(unmatched_dir).as_posix()
        if rel_under_unmatched.startswith("Media/"):
            virtual_phone = rel_under_unmatched
        else:
            virtual_phone = f"Media/{rel_under_unmatched}"

        dest_p, matched_row = router.resolve_destination(virtual_phone, file_size)

        if dest_p is None:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
            continue

        try:
            rel_target = dest_p.relative_to(out_dir).as_posix()
        except ValueError:
            rel_target = dest_p.as_posix()

        if matched_row:
            dest_p.parent.mkdir(parents=True, exist_ok=True)
            if dest_p.resolve() != p.resolve():
                if dest_p.is_file() and dest_p.stat().st_size == file_size:
                    p.unlink(missing_ok=True)
                else:
                    shutil.move(str(p), str(dest_p))
            router.record_committed_file(virtual_phone, dest_p, file_size, matched_row)
            summary["rematched"] += 1
        elif rel_target.startswith("Stickers/Sticker Packs"):
            dest_p.parent.mkdir(parents=True, exist_ok=True)
            if dest_p.resolve() != p.resolve():
                if dest_p.is_file() and dest_p.stat().st_size == file_size:
                    p.unlink(missing_ok=True)
                else:
                    shutil.move(str(p), str(dest_p))
            router.record_committed_file(virtual_phone, dest_p, file_size, None)
            summary["sticker_packs"] += 1
        else:
            summary["still_unmatched"] += 1

    # 4. Prune empty directories
    for root, dirs, files in os.walk(str(unmatched_dir), topdown=False):
        for d in dirs:
            dp = Path(root) / d
            try:
                if not any(dp.iterdir()):
                    dp.rmdir()
            except Exception:
                pass

    # 5. Synchronize gallery_data.js and media_index.csv
    router.flush_all(export_csv=False)

    # Reconcile existing gallery_data.js against current files on disk
    data_path = out_dir / "gallery_data.js"
    if data_path.is_file():
        from core.gallery import load_gallery_data, gallery_data_lock
        with gallery_data_lock:
            try:
                existing_data = load_gallery_data(str(out_dir))
                chats = existing_data.get("chats", [])

                updated_chats = []
                for c in chats:
                    kept_media = []
                    for m in c.get("media", []):
                        m_rel = m.get("rel_path")
                        if not m_rel:
                            continue
                        local_f = out_dir / m_rel
                        if local_f.is_file() and m.get("filename") != ".nomedia" and ".Links" not in m_rel:
                            kept_media.append(m)

                    c["media"] = kept_media
                    c["file_count"] = len(kept_media)
                    c["total_size"] = sum(m.get("size_bytes", 0) for m in kept_media)
                    if c["file_count"] > 0:
                        updated_chats.append(c)

                # Add newly organized items
                chat_index = {c["jid"]: c for c in updated_chats}
                for item in router.all_organized:
                    jid = item.get("chat_jid") or "unknown"
                    if jid not in chat_index:
                        new_chat = {
                            "jid": jid,
                            "name": item.get("chat_name") or "Unknown Chat",
                            "total_size": 0,
                            "file_count": 0,
                            "media": [],
                        }
                        chat_index[jid] = new_chat
                        updated_chats.append(new_chat)

                    chat_obj = chat_index[jid]
                    if not any(m.get("rel_path") == item.get("rel_path") for m in chat_obj["media"]):
                        media_entry = {
                            "filename": item.get("filename"),
                            "rel_path": item.get("rel_path"),
                            "size_bytes": item.get("size_bytes"),
                            "mime_type": item.get("mime_type"),
                            "thumb_path": item.get("thumb_path"),
                            "preview_path": item.get("preview_path"),
                            "is_doc": item.get("is_doc", False),
                            "received_at": item.get("received_at"),
                            "sender_jid": item.get("sender_jid"),
                            "sender_name": None,
                            "is_duplicate": False,
                            "duplicate_reason": "",
                            "duplicate_primary": "",
                            "media_duration": 0,
                            "starred": item.get("starred", 0),
                            "from_me": item.get("from_me", 0),
                            "forward_score": item.get("forward_score", 0),
                        }
                        chat_obj["media"].append(media_entry)
                        chat_obj["total_size"] += item.get("size_bytes", 0)
                        chat_obj["file_count"] += 1

                sorted_chats = sorted(updated_chats, key=lambda x: x["total_size"], reverse=True)
                new_content = f"const GALLERY_DATA = {json.dumps({'chats': sorted_chats})};"
                tmp_js = data_path.with_suffix(".tmp")
                for attempt in range(5):
                    try:
                        with open(tmp_js, "w", encoding="utf-8") as f:
                            f.write(new_content)
                        os.replace(tmp_js, data_path)
                        break
                    except (PermissionError, OSError) as e:
                        if attempt == 4:
                            sys.stderr.write(f"[Reorganize] Warning: Failed to refresh gallery_data.js: {e}\n")
                        else:
                            time.sleep(0.05 * (attempt + 1))
            except Exception as e:
                sys.stderr.write(f"[Reorganize] Warning: Failed to refresh gallery_data.js: {e}\n")

    # Reconcile media_index.csv
    csv_path = out_dir / "media_index.csv"
    if csv_path.is_file():
        try:
            with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames
                old_rows = list(reader)

            kept_rows = []
            seen_rels = set()
            for r in old_rows:
                r_rel = r.get("rel_path")
                if not r_rel:
                    continue
                local_f = out_dir / r_rel
                if local_f.is_file() and r.get("filename") != ".nomedia" and ".Links" not in r_rel:
                    kept_rows.append(r)
                    seen_rels.add(r_rel)

            for item in router.all_organized:
                i_rel = item.get("rel_path")
                if i_rel and i_rel not in seen_rels:
                    kept_rows.append(item)
                    seen_rels.add(i_rel)

            if fieldnames:
                tmp_csv = csv_path.with_suffix(".tmp")
                with open(tmp_csv, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                    writer.writeheader()
                    writer.writerows(kept_rows)
                os.replace(tmp_csv, csv_path)
        except Exception as e:
            sys.stderr.write(f"[Reorganize] Warning: Failed to refresh media_index.csv: {e}\n")

    # Copy gallery.html if present
    src_html = Path("gallery.html")
    dest_html = out_dir / "gallery.html"
    if src_html.is_file() and (not dest_html.is_file() or src_html.stat().st_mtime > dest_html.stat().st_mtime):
        try:
            shutil.copy2(src_html, dest_html)
        except Exception:
            pass

    return summary

