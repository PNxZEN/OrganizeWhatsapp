#!/usr/bin/env python3
"""
WhatsApp Media Organizer - Windows Portable ZIP Builder
========================================================
Builds a self-contained, zero-install Windows portable distribution:

    dist/WhatsAppMediaOrganizer-v<VERSION>-Windows-Portable.zip

Contents:
    runtime/          - Python 3.13 Embeddable (with pip + all wheels)
    bin/platform-tools/ - Google ADB binaries (adb.exe + DLLs)
    core/             - Application core package (+ tutorial assets)
    Start-Gallery.bat - Launcher pointing to runtime/python.exe
    wa_media_organizer.py
    gallery.html
    requirements.txt
    README.md
    config.json       - Clean default (onboarding_completed: false)

Usage:
    python scripts/build_windows_portable.py
    python scripts/build_windows_portable.py --version 1.1.0
    python scripts/build_windows_portable.py --dry-run
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

# ============================================================
# Configuration
# ============================================================
PYTHON_VERSION = "3.13.2"
PYTHON_EMBED_URL = (
    f"https://www.python.org/ftp/python/{PYTHON_VERSION}/"
    f"python-{PYTHON_VERSION}-embed-amd64.zip"
)
PYTHON_EMBED_FILENAME = f"python-{PYTHON_VERSION}-embed-amd64.zip"

GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

ADB_URL = (
    "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
)
ADB_BINARIES = ["adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll"]

APP_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = APP_ROOT / "dist"
BUILD_DIR = APP_ROOT / "build" / "staging"
CACHE_DIR = APP_ROOT / ".cache" / "downloads"

APP_FILES = [
    "wa_media_organizer.py",
    "gallery.html",
    "requirements.txt",
    "README.md",
]
APP_DIRS = ["core"]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, label: str) -> None:
    """Download url to dest with progress dots, using cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / dest.name
    if cached.exists():
        print(f"  [CACHE] {label} ({cached.name})")
        shutil.copy2(cached, dest)
        return
    print(f"  [DOWNLOAD] {label} ... ", end="", flush=True)
    urllib.request.urlretrieve(url, dest)
    shutil.copy2(dest, cached)
    size_mb = dest.stat().st_size / 1_048_576
    print(f"done ({size_mb:.1f} MB)")


def build(version: str, dry_run: bool = False) -> None:
    zip_name = f"WhatsAppMediaOrganizer-v{version}-Windows-Portable.zip"
    zip_path = DIST_DIR / zip_name

    print(f"\n{'='*64}")
    print(f"  WhatsApp Media Organizer - Windows Portable Builder")
    print(f"  Version: {version}")
    print(f"  Output:  {zip_path}")
    print(f"{'='*64}\n")

    if dry_run:
        print("[DRY RUN] Would build:", zip_path)
        print("[DRY RUN] Python embed:", PYTHON_EMBED_URL)
        print("[DRY RUN] ADB:", ADB_URL)
        return

    # --------------------------------------------------------
    # 1. Clean & create staging dir
    # --------------------------------------------------------
    print("[1/7] Preparing build directories...")
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    BUILD_DIR.mkdir(parents=True)
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    runtime_dir = BUILD_DIR / "runtime"
    runtime_dir.mkdir()
    bin_dir = BUILD_DIR / "bin" / "platform-tools"
    bin_dir.mkdir(parents=True)

    # --------------------------------------------------------
    # 2. Fetch Python Embeddable
    # --------------------------------------------------------
    print("\n[2/7] Fetching Python Embeddable Runtime...")
    embed_zip = CACHE_DIR / PYTHON_EMBED_FILENAME
    download(PYTHON_EMBED_URL, embed_zip, f"Python {PYTHON_VERSION} embed-amd64")

    print("  [EXTRACT] Python runtime...", end=" ", flush=True)
    with zipfile.ZipFile(embed_zip, "r") as zf:
        zf.extractall(runtime_dir)
    print("done")

    # --------------------------------------------------------
    # 3. Configure _pth for pip / site-packages
    # --------------------------------------------------------
    print("\n[3/7] Configuring Python runtime (._pth + site)...")
    pth_files = list(runtime_dir.glob("python*._pth"))
    if not pth_files:
        print("  [WARN] No ._pth file found; site-packages may not load.")
    else:
        pth_path = pth_files[0]
        pth_text = pth_path.read_text(encoding="utf-8")
        # Uncomment 'import site' and ensure Lib/site-packages is included
        lines = []
        for line in pth_text.splitlines():
            if line.strip() == "#import site":
                lines.append("import site")
            else:
                lines.append(line)
        if "Lib/site-packages" not in pth_text:
            lines.append("Lib/site-packages")
        if "." not in pth_text.splitlines():
            lines.append(".")
        pth_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"  [OK] Patched {pth_path.name}")

    # --------------------------------------------------------
    # 4. Bootstrap pip + install wheels
    # --------------------------------------------------------
    print("\n[4/7] Bootstrapping pip and installing dependencies...")
    get_pip = runtime_dir / "get-pip.py"
    download(GET_PIP_URL, get_pip, "get-pip.py")

    python_exe = runtime_dir / "python.exe"
    print("  [RUN] python get-pip.py ...")
    subprocess.run(
        [str(python_exe), str(get_pip), "--no-warn-script-location", "-q"],
        cwd=str(runtime_dir),
        check=True,
    )

    req_file = APP_ROOT / "requirements.txt"
    print("  [RUN] pip install -r requirements.txt ...")
    subprocess.run(
        [
            str(python_exe), "-m", "pip", "install",
            "-r", str(req_file),
            "--no-warn-script-location",
            "-q",
        ],
        check=True,
    )

    # Clean up pip installer
    get_pip.unlink(missing_ok=True)

    # Remove unnecessary __pycache__ bloat
    for p in runtime_dir.rglob("__pycache__"):
        shutil.rmtree(p, ignore_errors=True)

    # --------------------------------------------------------
    # 5. Fetch Google ADB platform-tools
    # --------------------------------------------------------
    print("\n[5/7] Fetching Google ADB platform-tools...")
    adb_zip_cache = CACHE_DIR / "platform-tools-latest-windows.zip"
    adb_zip_local = BUILD_DIR / "platform-tools-latest-windows.zip"
    download(ADB_URL, adb_zip_local, "Google platform-tools (ADB)")

    print("  [EXTRACT] ADB binaries...", end=" ", flush=True)
    with zipfile.ZipFile(adb_zip_local, "r") as zf:
        for member in zf.namelist():
            basename = Path(member).name
            if basename in ADB_BINARIES:
                data = zf.read(member)
                (bin_dir / basename).write_bytes(data)
                print(f"\n    -> {basename}", end="")
    adb_zip_local.unlink(missing_ok=True)
    print("\n  [OK] ADB binaries extracted")

    # --------------------------------------------------------
    # 6. Copy application payload
    # --------------------------------------------------------
    print("\n[6/7] Assembling application payload...")
    for fname in APP_FILES:
        src = APP_ROOT / fname
        if src.exists():
            shutil.copy2(src, BUILD_DIR / fname)
            print(f"  [COPY] {fname}")
        else:
            print(f"  [WARN] {fname} not found, skipping")

    for dname in APP_DIRS:
        src = APP_ROOT / dname
        dest = BUILD_DIR / dname
        if src.exists():
            shutil.copytree(src, dest, ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", "*.pyo", ".DS_Store"
            ))
            print(f"  [COPY] {dname}/")
        else:
            print(f"  [WARN] {dname}/ not found, skipping")

    # Copy the launcher as Start-Gallery.bat
    bat_src = APP_ROOT / "start_gallery.bat"
    if bat_src.exists():
        shutil.copy2(bat_src, BUILD_DIR / "Start-Gallery.bat")
        print("  [COPY] Start-Gallery.bat")

    # Write clean default config.json (onboarding_completed: false, no key)
    default_config = {
        "hex_key": "",
        "mode": "copy",
        "port": 8000,
        "output_dir": "./output",
        "media_dir": "./output",
        "db_dir": "./Databases",
        "allow_lan": False,
        "onboarding_completed": False,
        "idle_timeout": 45,
    }
    (BUILD_DIR / "config.json").write_text(
        json.dumps(default_config, indent=2) + "\n", encoding="utf-8"
    )
    print("  [WRITE] config.json (clean defaults)")

    # --------------------------------------------------------
    # 7. Package as ZIP
    # --------------------------------------------------------
    print(f"\n[7/7] Creating ZIP archive: {zip_name} ...")
    if zip_path.exists():
        zip_path.unlink()

    file_count = 0
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for fpath in sorted(BUILD_DIR.rglob("*")):
            if fpath.is_file():
                arcname = fpath.relative_to(BUILD_DIR)
                zf.write(fpath, arcname)
                file_count += 1

    size_mb = zip_path.stat().st_size / 1_048_576
    sha256 = sha256_file(zip_path)

    print(f"\n{'='*64}")
    print(f"  BUILD COMPLETE")
    print(f"  Archive:   {zip_path.name}")
    print(f"  Files:     {file_count}")
    print(f"  Size:      {size_mb:.1f} MB")
    print(f"  SHA256:    {sha256}")
    print(f"{'='*64}\n")

    # Write checksum sidecar
    (DIST_DIR / (zip_name + ".sha256")).write_text(
        f"{sha256}  {zip_name}\n", encoding="utf-8"
    )
    print(f"  Checksum written to {zip_name}.sha256")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Windows Portable ZIP")
    parser.add_argument("--version", default="1.0.0", help="Release version string (e.g. 1.0.0)")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without downloading or building")
    args = parser.parse_args()
    build(args.version, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
