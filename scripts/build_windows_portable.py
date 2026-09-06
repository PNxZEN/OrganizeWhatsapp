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
    if not cached.exists() or cached.stat().st_size == 0:
        print(f"  [DOWNLOAD] {label} ... ", end="", flush=True)
        tmp_dest = CACHE_DIR / (dest.name + ".tmp")
        urllib.request.urlretrieve(url, tmp_dest)
        if cached.exists():
            cached.unlink()
        tmp_dest.replace(cached)
        size_mb = cached.stat().st_size / 1_048_576
        print(f"done ({size_mb:.1f} MB)")
    else:
        print(f"  [CACHE] {label} ({cached.name})")

    if dest.resolve() != cached.resolve():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cached, dest)


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
        if "Lib/site-packages.zip" not in pth_text:
            lines.append("Lib/site-packages.zip")
        if "Lib/site-packages" not in pth_text:
            lines.append("Lib/site-packages")
        if "." not in pth_text.splitlines():
            lines.append(".")
        if ".." not in pth_text.splitlines():
            lines.append("..")
        pth_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"  [OK] Patched {pth_path.name}")

    # --------------------------------------------------------
    # 4. Bootstrap pip + install wheels
    # --------------------------------------------------------
    print("\n[4/7] Bootstrapping pip and installing dependencies...")
    get_pip = runtime_dir / "get-pip.py"
    download(GET_PIP_URL, get_pip, "get-pip.py")

    python_exe = runtime_dir / "python.exe"
    python_env = os.environ.copy()
    python_env["PYTHONNOUSERSITE"] = "1"

    print("  [RUN] python get-pip.py ...")
    subprocess.run(
        [
            str(python_exe), str(get_pip),
            "--no-warn-script-location",
            "--no-setuptools",
            "--no-wheel",
            "-q",
        ],
        cwd=str(runtime_dir),
        env=python_env,
        check=True,
    )

    req_file = APP_ROOT / "requirements.txt"
    print("  [RUN] pip install -r requirements.txt ...")
    subprocess.run(
        [
            str(python_exe), "-m", "pip", "install",
            "-r", str(req_file),
            "--no-user",
            "--isolated",
            "--no-warn-script-location",
            "-q",
        ],
        env=python_env,
        check=True,
    )

    # Clean up pip installer
    get_pip.unlink(missing_ok=True)

    # --------------------------------------------------------
    # Optimization: Reduce extracted file count for fast unzipping
    # --------------------------------------------------------
    print("\n  [OPTIMIZE] Pruning build artifacts to minimize extracted file count...")
    site_packages = runtime_dir / "Lib" / "site-packages"

    # Point 1: Strip pip and its command-line wrappers (not used at runtime)
    pip_dir = site_packages / "pip"
    if pip_dir.exists():
        shutil.rmtree(pip_dir, ignore_errors=True)
    for pip_info in site_packages.glob("pip-*.dist-info"):
        shutil.rmtree(pip_info, ignore_errors=True)
    scripts_dir = runtime_dir / "Scripts"
    if scripts_dir.exists():
        for p in scripts_dir.glob("pip*"):
            p.unlink(missing_ok=True)
    print("    -> Stripped pip installation tools")

    # Point 2: Strip scipy (102 MB uncompressed) and pywt, replacing with pure-NumPy DCT stub
    scipy_dir = site_packages / "scipy"
    scipy_libs = site_packages / "scipy.libs"
    pywt_dir = site_packages / "pywt"
    if scipy_dir.exists():
        shutil.rmtree(scipy_dir, ignore_errors=True)
    if scipy_libs.exists():
        shutil.rmtree(scipy_libs, ignore_errors=True)
    if pywt_dir.exists():
        shutil.rmtree(pywt_dir, ignore_errors=True)

    scipy_dir.mkdir(parents=True, exist_ok=True)
    (scipy_dir / "__init__.py").write_text(
        '"""Lightweight pure-NumPy scipy stub for ImageHash."""\n__version__ = "1.16.2"\n',
        encoding="utf-8",
    )
    fftpack_code = '''"""Lightweight pure-NumPy Discrete Cosine Transform (DCT Type-2)."""
import numpy as np

def dct(x, type=2, n=None, axis=-1, norm=None, overwrite_x=False):
    x = np.asarray(x, dtype=float)
    if axis < 0:
        axis = x.ndim + axis
    if axis != x.ndim - 1:
        x = np.swapaxes(x, axis, -1)
    N = x.shape[-1]
    n_idx = np.arange(N)
    k_idx = n_idx[:, None]
    M = 2.0 * np.cos((np.pi * k_idx * (2 * n_idx + 1)) / (2.0 * N))
    res = np.dot(x, M.T)
    if norm == 'ortho':
        res[..., 0] *= 1.0 / (2.0 * np.sqrt(N))
        res[..., 1:] *= 1.0 / np.sqrt(2.0 * N)
    if axis != x.ndim - 1:
        res = np.swapaxes(res, axis, -1)
    return res
'''
    (scipy_dir / "fftpack.py").write_text(fftpack_code, encoding="utf-8")
    print("    -> Replaced heavy scipy (102 MB) with lightweight pure-NumPy DCT stub")

    # Point 3: Remove package test suites and non-runtime CLI tools (numpy/tests, numpy/f2py, etc.)
    for test_dir in list(site_packages.rglob("tests")):
        if test_dir.is_dir():
            shutil.rmtree(test_dir, ignore_errors=True)
    testing_dir = site_packages / "numpy" / "testing"
    if testing_dir.is_dir():
        shutil.rmtree(testing_dir, ignore_errors=True)
    f2py_dir = site_packages / "numpy" / "f2py"
    if f2py_dir.is_dir():
        shutil.rmtree(f2py_dir, ignore_errors=True)
    print("    -> Removed package test suites and non-runtime tools (numpy/tests, numpy/f2py)")

    # Point 4: Remove all *.dist-info metadata folders and IDE type stubs (.pyi)
    for dist_info in site_packages.glob("*.dist-info"):
        shutil.rmtree(dist_info, ignore_errors=True)
    for pyi in site_packages.rglob("*.pyi"):
        pyi.unlink(missing_ok=True)
    for doc in site_packages.rglob("*.rst"):
        doc.unlink(missing_ok=True)
    for doc in site_packages.rglob("*.md"):
        doc.unlink(missing_ok=True)
    print("    -> Removed package metadata (.dist-info) and type stubs (.pyi)")

    # Point 5: Archive verified pure-Python packages into Lib/site-packages.zip
    # Only 100% pure Python packages with explicit __init__.py files are archived.
    # Packages containing C-extensions (.pyd, .dll) remain on disk.
    pure_candidates = ["javaobj", "imagehash", "scipy"]
    archived_packages = []
    zip_target = runtime_dir / "Lib" / "site-packages.zip"

    with zipfile.ZipFile(zip_target, "w", zipfile.ZIP_DEFLATED) as zf:
        for pkg_name in pure_candidates:
            pkg_path = site_packages / pkg_name
            if pkg_path.exists() and pkg_path.is_dir():
                has_binaries = any(
                    f.suffix.lower() in (".pyd", ".dll", ".so")
                    for f in pkg_path.rglob("*")
                )
                if not has_binaries:
                    for f in pkg_path.rglob("*"):
                        if f.is_file() and not f.name.endswith(".pyc") and "__pycache__" not in f.parts:
                            arcname = f.relative_to(site_packages)
                            zf.write(f, str(arcname))
                    archived_packages.append(pkg_name)

    # Remove archived packages from disk
    for pkg_name in archived_packages:
        shutil.rmtree(site_packages / pkg_name, ignore_errors=True)
    if archived_packages:
        print(f"    -> Consolidated pure packages ({', '.join(archived_packages)}) into site-packages.zip")

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
    # Verification: Validate runtime execution before archiving
    # --------------------------------------------------------
    print("\n  [VERIFY] Validating portable runtime execution...")
    portable_python = runtime_dir / "python.exe"
    verify_cmd = [
        str(portable_python),
        "-c",
        (
            "import sys; "
            "import Cryptodome.Cipher.AES; "
            "import PIL.Image; "
            "import pillow_heif; "
            "import imagehash; "
            "test_ph = str(imagehash.phash(PIL.Image.new('RGB', (32, 32)))); "
            "assert len(test_ph) > 0; "
            "import javaobj; "
            "from wa_crypt_tools.lib.key.key15 import Key15; "
            "from core.adb import check_adb_device, find_adb_binary; "
            "from core.decrypt import validate_hex_key; "
            "print('PORTABLE_RUNTIME_VERIFIED_OK')"
        ),
    ]
    verify_res = subprocess.run(
        verify_cmd, cwd=str(BUILD_DIR), env=python_env, capture_output=True, text=True
    )
    if verify_res.returncode != 0 or "PORTABLE_RUNTIME_VERIFIED_OK" not in verify_res.stdout:
        print(f"  [ERROR] Runtime verification failed:\n{verify_res.stderr}")
        raise RuntimeError("Portable runtime verification failed!")

    help_cmd = [str(portable_python), "wa_media_organizer.py", "--help"]
    help_res = subprocess.run(help_cmd, cwd=str(BUILD_DIR), env=python_env, capture_output=True, text=True)
    if help_res.returncode != 0:
        print(f"  [ERROR] wa_media_organizer.py execution check failed:\n{help_res.stderr}")
        raise RuntimeError("Application invocation check failed!")
    print("  [OK] Portable runtime successfully verified with all dependencies.")

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
    parser.add_argument("--version", default="1.0.1", help="Release version string (e.g. 1.0.1)")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without downloading or building")
    args = parser.parse_args()
    build(args.version, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
