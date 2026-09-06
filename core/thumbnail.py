"""
WhatsApp Media Organizer - Dynamic Thumbnail Generator Engine.
Provides high-performance on-demand image downscaling and video frame extraction.
Caches generated thumbnails in .thumbnails/ to eliminate redundant processing.
"""

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from PIL import Image, ImageOps
from core.config import find_ffmpeg_binary, is_ffmpeg_available

# Ensure HEIC/HEIF format opener is registered
try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:
    pass

# Mutex to ensure thread-safe creation per path
_thumb_locks = {}
_global_lock = threading.Lock()


def _get_path_lock(cache_key: str) -> threading.Lock:
    with _global_lock:
        if cache_key not in _thumb_locks:
            _thumb_locks[cache_key] = threading.Lock()
        return _thumb_locks[cache_key]


def get_or_create_thumbnail(output_dir, rel_path: str, max_size=(280, 280)) -> Path | None:
    """
    Retrieves or generates an on-demand downscaled thumbnail for an image or video.
    Returns the absolute Path to the cached thumbnail JPEG, or None if creation fails.
    """
    out_dir = Path(output_dir).resolve()
    safe_rel = rel_path.lstrip("/\\")
    src_file = (out_dir / safe_rel).resolve()

    # Security check: ensure path is within output_dir
    try:
        src_file.relative_to(out_dir)
    except ValueError:
        return None

    if not src_file.is_file():
        return None

    # Destination in .thumbnails/
    thumb_file = (out_dir / ".thumbnails" / f"{safe_rel}.thumb.jpg").resolve()
    if thumb_file.is_file() and thumb_file.stat().st_size > 0:
        return thumb_file

    lock = _get_path_lock(str(src_file))
    with lock:
        # Double-check inside lock
        if thumb_file.is_file() and thumb_file.stat().st_size > 0:
            return thumb_file

        thumb_file.parent.mkdir(parents=True, exist_ok=True)
        ext = src_file.suffix.lower()

        # 1. Handle Images
        if ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".heif"):
            try:
                # Fast path for HEIC: if a full-size JPEG was already pre-converted in .thumbnails/,
                # read the JPEG directly using draft() for 10x faster downscaling.
                src_to_open = src_file
                if ext in (".heic", ".heif"):
                    pre_jpeg = out_dir / ".thumbnails" / f"{safe_rel}.jpg"
                    if pre_jpeg.is_file() and pre_jpeg.stat().st_size > 0:
                        src_to_open = pre_jpeg

                with Image.open(src_to_open) as im:
                    if src_to_open != src_file:
                        im.draft("RGB", max_size)
                    im = ImageOps.exif_transpose(im)
                    if im.mode in ("RGBA", "LA", "P"):
                        # Convert transparent backgrounds to dark glass color for consistency
                        background = Image.new("RGB", im.size, (17, 24, 39))
                        if im.mode == "P":
                            im = im.convert("RGBA")
                        background.paste(im, mask=im.split()[-1])
                        im = background
                    elif im.mode != "RGB":
                        im = im.convert("RGB")

                    im.thumbnail(max_size, Image.Resampling.BILINEAR)
                    # Atomic write via temporary file
                    tmp_file = thumb_file.with_suffix(".tmp.jpg")
                    im.save(tmp_file, format="JPEG", quality=80, optimize=True)
                    tmp_file.replace(thumb_file)
                    return thumb_file
            except Exception as e:
                sys.stderr.write(f"[Thumbnail] Image error on {src_file.name}: {e}\n")
                return None

        # 2. Handle Videos
        elif ext in (".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv", ".3gp", ".flv"):
            if not is_ffmpeg_available():
                return None

            ffmpeg_cmd = find_ffmpeg_binary()
            tmp_file = thumb_file.with_suffix(".tmp.jpg")
            
            # Try frame at 1 second, then fallback to 0 seconds
            for seek_time in ("00:00:01", "00:00:00"):
                cmd = [
                    ffmpeg_cmd,
                    "-ss", seek_time,
                    "-i", str(src_file),
                    "-vframes", "1",
                    "-vf", f"scale={max_size[0]}:{max_size[1]}:force_original_aspect_ratio=decrease",
                    "-q:v", "3",
                    "-y",
                    str(tmp_file),
                ]
                try:
                    res = subprocess.run(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                        timeout=8,
                    )
                    if res.returncode == 0 and tmp_file.is_file() and tmp_file.stat().st_size > 0:
                        tmp_file.replace(thumb_file)
                        return thumb_file
                except Exception:
                    pass

            if tmp_file.is_file():
                tmp_file.unlink(missing_ok=True)
            return None

    return None
