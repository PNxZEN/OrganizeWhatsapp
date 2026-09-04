"""
WhatsApp Media Organizer - Duplicate Detection and Hashing Engine.
Handles two-tier duplicate checking, SQLite hash caching, perceptual image hashing,
and quality duplicate detection.
"""

import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

from core.organizer import normalize_filename


def compute_file_md5(filepath, chunk_size=65536):
    """Computes the full hex MD5 checksum of a file in streaming chunks."""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_fast_hash(filepath, chunk_size=16384):
    """
    Computes a composite fast hash from the first 16KB and last 16KB of a file.
    If the file size is <= chunk_size * 2, reads the entire file.
    Takes microseconds compared to reading full multi-megabyte/gigabyte media files.
    """
    try:
        size = os.path.getsize(filepath)
        if size == 0:
            return "empty"
        h = hashlib.md5()
        with open(filepath, "rb") as f:
            if size <= chunk_size * 2:
                h.update(f.read())
            else:
                h.update(f.read(chunk_size))
                f.seek(size - chunk_size)
                h.update(f.read(chunk_size))
        return h.hexdigest()
    except Exception:
        return None


def compute_image_phash(filepath):
    """Computes perceptual hash for supported image formats using imagehash."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext not in [".jpg", ".jpeg", ".png", ".webp", ".bmp"]:
        return None

    try:
        from PIL import Image
        import imagehash
        import warnings

        warnings.filterwarnings("ignore", category=UserWarning, module="PIL")

        with Image.open(filepath) as img:
            if img.mode == "P" and "transparency" in img.info:
                img = img.convert("RGBA")
            return str(imagehash.phash(img))
    except Exception:
        return None


class HashCache:
    """
    SQLite-backed persistent hash cache (.hashes_cache.sqlite3).
    Replaces uncompressed JSON monolith with O(1) indexed lookups (<1ms).
    Automatically migrates from .hashes_cache.json on first run.
    """

    def __init__(self, db_path, json_fallback_path=None):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._init_db()

        # Check if migration is needed from JSON
        if json_fallback_path and os.path.isfile(json_fallback_path):
            self._auto_migrate_from_json(json_fallback_path)

    def _init_db(self):
        cur = self.conn.cursor()
        cur.execute("PRAGMA journal_mode = WAL;")
        cur.execute("PRAGMA synchronous = NORMAL;")
        cur.execute(
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
        cur.execute("CREATE INDEX IF NOT EXISTS idx_size ON file_hashes(size);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_md5 ON file_hashes(md5);")
        self.conn.commit()

    def _auto_migrate_from_json(self, json_path):
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM file_hashes")
        row_count = cur.fetchone()[0]

        if row_count == 0:
            try:
                sys.stdout.write(
                    f"[Duplicates] Migrating existing hash cache from {json_path} to SQLite...\n"
                )
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                records = []
                for fpath, val in data.items():
                    records.append(
                        (
                            fpath,
                            float(val.get("mtime", 0)),
                            int(val.get("size", 0)),
                            val.get("md5"),
                            val.get("phash"),
                            None,
                        )
                    )

                if records:
                    cur.executemany(
                        """
                        INSERT OR REPLACE INTO file_hashes
                        (filepath, mtime, size, md5, phash, fast_hash)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        records,
                    )
                    self.conn.commit()
                sys.stdout.write(
                    f"[Duplicates] Successfully migrated {len(records):,} cached hashes into SQLite.\n"
                )
            except Exception as e:
                sys.stderr.write(f"[Duplicates] Warning: Migration from JSON failed: {e}\n")

    def get(self, filepath, stat_mtime=None, stat_size=None):
        """
        Retrieves cached record for filepath.
        Validates composite (mtime, size) if provided (fixing BUG-03).
        """
        cur = self.conn.cursor()
        cur.execute(
            "SELECT mtime, size, md5, phash, fast_hash FROM file_hashes WHERE filepath = ?",
            (filepath,),
        )
        row = cur.fetchone()
        if not row:
            return None

        cached_mtime, cached_size, md5, phash, fast_hash = row
        if stat_mtime is not None and abs(cached_mtime - stat_mtime) >= 0.01:
            return None
        if stat_size is not None and cached_size != stat_size:
            return None

        return {
            "mtime": cached_mtime,
            "size": cached_size,
            "md5": md5,
            "phash": phash,
            "fast_hash": fast_hash,
        }

    def bulk_put(self, records):
        """Batch inserts or updates a list of (filepath, mtime, size, md5, phash, fast_hash) tuples."""
        if not records:
            return
        cur = self.conn.cursor()
        cur.executemany(
            """
            INSERT OR REPLACE INTO file_hashes
            (filepath, mtime, size, md5, phash, fast_hash)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            records,
        )
        self.conn.commit()

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass


def analyze_duplicates(file_index, skip_imagehash=False, cache_path=None):
    """
    Intelligent two-tier duplicate checking with SQLite caching (TODO Item 2).
    1. Size Pre-Filter: files with unique size across all files skip full MD5 streaming.
    2. Size Collisions: computes 16KB head + 16KB tail fast hash.
    3. Collision Match: only files with identical size and fast hash undergo full MD5.
    4. Strict Cache Invalidation: verifies (mtime, size) on every check (BUG-03 fix).
    Returns (md5_map, phash_map, file_hashes).
    """
    # Determine cache paths
    sqlite_cache_path = None
    json_fallback_path = None

    if cache_path:
        cp = Path(cache_path)
        if cp.suffix.lower() == ".sqlite3":
            sqlite_cache_path = cp
            json_fallback_path = cp.with_suffix(".json")
        else:
            json_fallback_path = cp
            sqlite_cache_path = cp.with_suffix(".sqlite3")
    else:
        sqlite_cache_path = Path("./output/.hashes_cache.sqlite3")
        json_fallback_path = Path("./output/.hashes_cache.json")

    cache = HashCache(sqlite_cache_path, json_fallback_path=json_fallback_path)

    # 1. Gather stat info and group files by size
    file_stats = {}  # filepath -> (mtime, size, norm_name, raw_name)
    files_by_size = defaultdict(list)

    for filename, filepath in file_index.items():
        if not os.path.isfile(filepath):
            continue
        try:
            st = os.stat(filepath)
            mtime = st.st_mtime
            size = st.st_size
        except Exception:
            continue

        norm_name = normalize_filename(filename, strip_dup_suffix=True)
        file_stats[filepath] = (mtime, size, norm_name, filename)
        files_by_size[size].append(filepath)

    md5_map = defaultdict(list)
    phash_map = defaultdict(list)
    file_hashes = {}
    pending_cache_updates = []

    # 2. Process each size group
    for size, paths in files_by_size.items():
        if size <= 0:
            continue

        is_size_unique = len(paths) == 1

        if is_size_unique:
            filepath = paths[0]
            mtime, _, norm_name, raw_name = file_stats[filepath]
            cached = cache.get(filepath, stat_mtime=mtime, stat_size=size)

            if cached and cached.get("md5"):
                md5_str = cached["md5"]
                phash_str = cached.get("phash")
            else:
                # Unique size: exact duplicate is impossible.
                # Compute fast hash for future reference
                fast_hash_str = compute_fast_hash(filepath)
                # Compute full MD5 only if small (<= 1MB) or retrieve from fast_hash
                if size <= 1024 * 1024:
                    md5_str = compute_file_md5(filepath)
                else:
                    # Skip full streaming disk read for unique large files
                    md5_str = fast_hash_str

                phash_str = None
                if not skip_imagehash:
                    phash_str = compute_image_phash(filepath)

                pending_cache_updates.append((filepath, mtime, size, md5_str, phash_str, fast_hash_str))

            if md5_str:
                md5_map[md5_str].append(raw_name)
            if phash_str:
                phash_map[phash_str].append(raw_name)

            file_hashes[norm_name] = (md5_str, phash_str)
            file_hashes[raw_name] = (md5_str, phash_str)
            file_hashes[normalize_filename(raw_name)] = (md5_str, phash_str)

        else:
            # Size collision: multiple files share this exact size
            # Tier 1: Check or compute fast head/tail hash
            fast_hash_groups = defaultdict(list)
            resolved_hashes = {}  # filepath -> (md5, phash, fast_hash)

            for filepath in paths:
                mtime, _, norm_name, raw_name = file_stats[filepath]
                cached = cache.get(filepath, stat_mtime=mtime, stat_size=size)

                if cached and cached.get("fast_hash"):
                    fast_h = cached["fast_hash"]
                    resolved_hashes[filepath] = cached
                else:
                    fast_h = compute_fast_hash(filepath)
                    resolved_hashes[filepath] = {
                        "mtime": mtime,
                        "size": size,
                        "md5": cached.get("md5") if cached else None,
                        "phash": cached.get("phash") if cached else None,
                        "fast_hash": fast_h,
                    }

                fast_hash_groups[fast_h].append(filepath)

            # Tier 2: Check fast hash collisions
            for fast_h, sub_paths in fast_hash_groups.items():
                is_fast_unique = len(sub_paths) == 1

                for filepath in sub_paths:
                    mtime, _, norm_name, raw_name = file_stats[filepath]
                    entry = resolved_hashes[filepath]
                    md5_str = entry.get("md5")
                    phash_str = entry.get("phash")

                    # If fast hash collides or file is small, compute full MD5 if missing
                    if not md5_str:
                        if not is_fast_unique or size <= 1024 * 1024:
                            md5_str = compute_file_md5(filepath)
                        else:
                            md5_str = fast_h

                    if not phash_str and not skip_imagehash:
                        phash_str = compute_image_phash(filepath)

                    pending_cache_updates.append((filepath, mtime, size, md5_str, phash_str, fast_h))

                    if md5_str:
                        md5_map[md5_str].append(raw_name)
                    if phash_str:
                        phash_map[phash_str].append(raw_name)

                    file_hashes[norm_name] = (md5_str, phash_str)
                    file_hashes[raw_name] = (md5_str, phash_str)
                    file_hashes[normalize_filename(raw_name)] = (md5_str, phash_str)

    # 3. Commit new and updated hashes to SQLite in a single transaction
    if pending_cache_updates:
        cache.bulk_put(pending_cache_updates)

    cache.close()
    return md5_map, phash_map, file_hashes


def detect_quality_duplicates(organized_list, output_dir, file_hashes=None):
    """
    Identifies quality-based duplicates (e.g., HD vs standard versions of the same video/audio/image)
    by matching files in the same chat with consecutive WhatsApp sequence numbers.
    For images, content similarity is verified using imagehash.phash lazily.
    """
    try:
        from PIL import Image
        import imagehash

        has_imagehash = True
    except ImportError:
        has_imagehash = False

    pattern = re.compile(r"^(VID|AUD|IMG)-(\d{8})-WA(\d{4})(?:_dup\d+)?$", re.IGNORECASE)
    groups = defaultdict(list)

    for idx, item in enumerate(organized_list):
        chat_jid = item.get("chat_jid")
        if not chat_jid or chat_jid == "status@broadcast":
            continue

        filename = item.get("filename") or ""
        stem, _ = os.path.splitext(filename)
        m = pattern.match(stem)
        if not m:
            continue

        media_type, date_str, counter_str = m.groups()
        counter = int(counter_str)

        duration_val = 0
        if media_type.upper() in ("VID", "AUD"):
            duration = item.get("media_duration")
            try:
                duration_val = round(float(duration), 1) if duration is not None else 0
            except (ValueError, TypeError):
                duration_val = 0

        key = (item.get("chat_jid"), media_type.upper(), date_str, duration_val)
        groups[key].append(
            {
                "index": idx,
                "counter": counter,
                "size": item.get("size_bytes") or 0,
                "filename": filename,
                "rel_path": item.get("rel_path"),
            }
        )

    for key, members in groups.items():
        if len(members) < 2:
            continue

        chat_jid, media_type, date_str, duration_val = key
        members.sort(key=lambda x: x["counter"])

        i = 0
        while i < len(members) - 1:
            m1 = members[i]
            m2 = members[i + 1]
            diff = abs(m1["counter"] - m2["counter"])

            if 0 < diff <= 2:
                pair = [m1, m2]
                j = i + 2
                while j < len(members):
                    next_diff = abs(members[j]["counter"] - pair[-1]["counter"])
                    if 0 < next_diff <= 2:
                        pair.append(members[j])
                        j += 1
                    else:
                        break

                original_len = len(pair)

                if media_type == "IMG":
                    if not has_imagehash:
                        i += original_len
                        continue

                    verified_pair = [pair[0]]
                    h1 = None

                    if file_hashes:
                        norm1 = normalize_filename(pair[0]["filename"], strip_dup_suffix=True)
                        _, h1_str = file_hashes.get(
                            norm1, file_hashes.get(pair[0]["filename"], (None, None))
                        )
                        if h1_str:
                            try:
                                h1 = imagehash.hex_to_hash(h1_str)
                            except Exception:
                                pass

                    p1_path = None
                    for candidate in pair[1:]:
                        try:
                            h2 = None
                            if file_hashes:
                                norm2 = normalize_filename(candidate["filename"], strip_dup_suffix=True)
                                _, h2_str = file_hashes.get(
                                    norm2,
                                    file_hashes.get(candidate["filename"], (None, None)),
                                )
                                if h2_str:
                                    try:
                                        h2 = imagehash.hex_to_hash(h2_str)
                                    except Exception:
                                        pass

                            if h1 is not None and h2 is not None:
                                if h1 - h2 <= 4:
                                    if p1_path is None:
                                        p1_path = os.path.abspath(
                                            os.path.join(output_dir, pair[0]["rel_path"])
                                        )
                                    cand_path = os.path.abspath(
                                        os.path.join(output_dir, candidate["rel_path"])
                                    )
                                    with Image.open(p1_path) as img1, Image.open(cand_path) as img2:
                                        w1, h1_dim = img1.size
                                        w2, h2_dim = img2.size
                                        ratio1 = round(w1 / h1_dim, 3) if h1_dim else 0
                                        ratio2 = round(w2 / h2_dim, 3) if h2_dim else 0
                                    if ratio1 == ratio2:
                                        verified_pair.append(candidate)
                                    continue

                            if p1_path is None:
                                p1_path = os.path.abspath(
                                    os.path.join(output_dir, pair[0]["rel_path"])
                                )
                            cand_path = os.path.abspath(
                                os.path.join(output_dir, candidate["rel_path"])
                            )
                            with Image.open(p1_path) as img1, Image.open(cand_path) as img2:
                                w1, h1_dim = img1.size
                                w2, h2_dim = img2.size
                                ratio1 = round(w1 / h1_dim, 3) if h1_dim else 0
                                ratio2 = round(w2 / h2_dim, 3) if h2_dim else 0

                            if ratio1 == ratio2:
                                if h1 is None:
                                    h1 = imagehash.phash(Image.open(p1_path))
                                if h2 is None:
                                    h2 = imagehash.phash(Image.open(cand_path))
                                if h1 - h2 <= 4:
                                    verified_pair.append(candidate)
                        except Exception:
                            pass

                    pair = verified_pair

                if len(pair) > 1:
                    pair.sort(key=lambda x: x["size"], reverse=True)
                    primary = pair[0]

                    for dup in pair[1:]:
                        dup_item = organized_list[dup["index"]]
                        dup_item["is_duplicate"] = True
                        dup_item["duplicate_reason"] = "quality"
                        dup_item["duplicate_primary"] = primary["filename"]

                i += original_len
            else:
                i += 1
