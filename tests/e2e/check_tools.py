"""
Checks, inside an installed macOS / Linux package, that the phone and video tools setup provides
really work on this computer. Run with the package's venv Python from the package folder:

    venv/bin/python <repo>/tests/e2e/check_tools.py

1. The app finds ADB and it runs.
2. Google's platform-tools download for this OS installs and runs (fresh, in a temp folder).
3. The pip-installed ffmpeg (imageio-ffmpeg) is used when no system ffmpeg exists, can encode
   H.264 (needed for video previews) and makes a video thumbnail through the app's own code.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path.cwd()))

from core import config, platform_tools, thumbnail  # noqa: E402

failures = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'  (' + str(detail) + ')' if detail else ''}", flush=True)
    if not ok:
        failures.append(name)


adb = platform_tools.find_adb()
check("the app finds ADB", bool(adb), adb)
if adb:
    check("ADB runs", subprocess.run([adb, "version"], capture_output=True).returncode == 0)

with tempfile.TemporaryDirectory() as tmp:
    fresh = platform_tools.install_adb(Path(tmp))
    out = subprocess.run([str(fresh), "version"], capture_output=True, text=True).stdout
    check("Google's ADB download for this OS installs and runs", "Android Debug Bridge" in out, out.splitlines()[:1])

real_which = shutil.which
with mock.patch("shutil.which", lambda name, *a, **k: None if name == "ffmpeg" else real_which(name, *a, **k)):
    ffmpeg = config.find_ffmpeg_binary()
    check("pip-installed ffmpeg is used when no system ffmpeg exists", "imageio_ffmpeg" in ffmpeg, ffmpeg)
    check("...and the app reports it available", config.is_ffmpeg_available())
    encoders = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    check("it can encode H.264 and AAC (video previews)", "libx264" in encoders and " aac " in encoders)

    with tempfile.TemporaryDirectory() as out_dir:
        video = Path(out_dir) / "Chat" / "2024-01" / "clip.mp4"
        video.parent.mkdir(parents=True)
        made = subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=10",
                               "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        check("it can make a video", made)
        thumb = thumbnail.get_or_create_thumbnail(out_dir, "Chat/2024-01/clip.mp4")
        check("the app makes a video thumbnail with it", bool(thumb and thumb.is_file() and thumb.stat().st_size), thumb)

print(f"\n{'All tool checks passed' if not failures else str(len(failures)) + ' check(s) failed'}")
sys.exit(1 if failures else 0)
