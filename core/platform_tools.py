"""
Phone and video tools for the macOS / Linux package.

The Windows portable ZIP ships ADB and ffmpeg inside bin/. The macOS / Linux package is source
only, so setup provides them here instead:

- ADB: Google's official platform-tools (the same download the Windows build uses) is fetched
  from dl.google.com into bin/platform-tools/ when no adb is installed. This happens only during
  setup (install.sh, or start_gallery.sh when it installs dependencies), never on a normal launch.
- ffmpeg: comes from the imageio-ffmpeg package in requirements.txt (see core.config).

Run by the launch scripts with the app's venv Python:
    python -m core.platform_tools --setup   download ADB if missing, then report
    python -m core.platform_tools           report only (no network)

Standard library only, so it also works before the dependencies are installed.
"""

import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
PLATFORM_TOOLS_URLS = {
    "Darwin": "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip",
    "Linux": "https://dl.google.com/android/repository/platform-tools-latest-linux.zip",
}
MAX_DOWNLOAD_BYTES = 150 * 1024 * 1024
HTTP_TIMEOUT_SECS = 60


def bundled_adb_path(app_root: Path = APP_ROOT) -> Path:
    return app_root / "bin" / "platform-tools" / ("adb.exe" if sys.platform == "win32" else "adb")


def platform_tools_url(system=None, machine=None):
    """Google's download for this computer, or None (Google only builds Linux ADB for x86-64)."""
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    if system == "Linux" and machine not in ("x86_64", "amd64"):
        return None
    return PLATFORM_TOOLS_URLS.get(system)


def find_adb(app_root: Path = APP_ROOT):
    bundled = bundled_adb_path(app_root)
    if bundled.is_file():
        return str(bundled)
    return shutil.which("adb")


def _wanted_member(name: str):
    """Maps a zip entry to its path under bin/, or None. Only adb and its libraries are kept."""
    parts = name.split("/")
    if len(parts) < 2 or parts[0] != "platform-tools" or any(p in ("", ".", "..") for p in parts[1:]):
        return None
    if parts[1:] == ["adb"] or (len(parts) == 3 and parts[1] == "lib64"):
        return Path(*parts)
    return None


def _works(adb: Path) -> bool:
    try:
        result = subprocess.run([str(adb), "version"], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=30)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def install_adb(app_root: Path = APP_ROOT, url=None) -> Path:
    """Downloads platform-tools and installs adb into <app>/bin/platform-tools/. Returns its path."""
    url = url or platform_tools_url()
    if not url:
        raise RuntimeError("Google does not publish ADB for this computer")
    bin_dir = app_root / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".platform-tools-", dir=bin_dir))
    try:
        archive = work / "platform-tools.zip"
        with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_SECS) as resp, open(archive, "wb") as out:
            total = 0
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise RuntimeError("the download is larger than expected")
                out.write(chunk)

        staged = work / "extracted"
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                rel = _wanted_member(info.filename)
                if rel is None or info.is_dir():
                    continue
                target = staged / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                target.chmod(0o755)

        adb = staged / "platform-tools" / "adb"
        if not adb.is_file():
            raise RuntimeError("the download did not contain adb")
        if not _works(adb):
            raise RuntimeError("the downloaded adb does not run on this computer")

        final = bin_dir / "platform-tools"
        if final.exists():
            shutil.rmtree(final)
        os.replace(staged / "platform-tools", final)
        return final / "adb"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def find_ffmpeg():
    sys.path.insert(0, str(APP_ROOT))
    try:
        from core.config import find_ffmpeg_binary, is_ffmpeg_available
    finally:
        sys.path.pop(0)
    return find_ffmpeg_binary() if is_ffmpeg_available() else None


# ---------------------------------------------------------------- launcher output

def _colors():
    if sys.stdout.isatty():
        return {"ok": "\033[0;32m", "warn": "\033[1;33m", "info": "\033[0;36m", "reset": "\033[0m"}
    return {"ok": "", "warn": "", "info": "", "reset": ""}


def _log(kind: str, label: str, message: str) -> None:
    c = _colors()
    print(f"{c[kind]}[{label}]{c['reset']}{' ' * (8 - len(label) - 2)}{message}", flush=True)


def _manual_adb_hint() -> None:
    if platform.system() == "Darwin":
        print("  To install it yourself:  brew install android-platform-tools\n")
    else:
        print("  To install it yourself:  sudo apt install adb  (or: sudo dnf install android-tools)\n")


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    setup = "--setup" in args

    adb = find_adb()
    if not adb and setup:
        url = platform_tools_url()
        if url:
            _log("info", "INFO", "Downloading Google's Android platform-tools (ADB) for USB phone sync ...")
            print(f"        from {url}", flush=True)
            try:
                adb = str(install_adb(url=url))
            except Exception as e:  # never stop setup: everything except phone sync still works
                _log("warn", "WARN", f"Could not download ADB: {e}")
    if adb:
        _log("ok", "OK", f"ADB ready for USB phone sync ({adb})")
    else:
        _log("warn", "WARN", "ADB (Android Debug Bridge) not found. USB phone sync will not work.")
        _manual_adb_hint()

    ffmpeg = find_ffmpeg()
    if ffmpeg:
        _log("ok", "OK", "ffmpeg ready for video thumbnails and previews")
    else:
        _log("warn", "WARN", "ffmpeg not found. Video thumbnails, previews and video duplicate checks will not work.")
        print("  Run ./install.sh again to reinstall it.\n")
    return 0  # missing tools are reported, never fatal


if __name__ == "__main__":
    sys.exit(main())
