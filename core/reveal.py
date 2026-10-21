"""
"Show in File Explorer / Finder / Files": opens the folder with the media file selected.

Windows: SHOpenFolderAndSelectItems, the API Explorer itself uses. Building an
`explorer /select,"<path>"` command line is fragile: Explorer splits its arguments at commas,
so a file inside a chat folder such as "Andi mandi shandi , jisne..." opened the folder without
selecting the file. The command line remains only as a fallback.
macOS: `open -R` (reveal in Finder).
Linux: the freedesktop FileManager1 D-Bus call (Files/Nautilus, Dolphin, Nemo, Caja, Thunar...),
falling back to opening the folder when no file manager offers it.
"""

import os
import platform
import shutil
import subprocess
from pathlib import Path


def _reveal_windows_shell(path: Path) -> bool:
    import ctypes

    shell32 = ctypes.windll.shell32
    ole32 = ctypes.windll.ole32
    ole32.CoInitialize.argtypes = [ctypes.c_void_p]
    ole32.CoInitialize.restype = ctypes.c_long
    shell32.ILCreateFromPathW.argtypes = [ctypes.c_wchar_p]
    shell32.ILCreateFromPathW.restype = ctypes.c_void_p
    shell32.SHOpenFolderAndSelectItems.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_ulong]
    shell32.SHOpenFolderAndSelectItems.restype = ctypes.c_long
    shell32.ILFree.argtypes = [ctypes.c_void_p]

    hr = ole32.CoInitialize(None)
    try:
        pidl = shell32.ILCreateFromPathW(os.path.normpath(str(path)))
        if not pidl:
            return False
        try:
            return shell32.SHOpenFolderAndSelectItems(pidl, 0, None, 0) == 0
        finally:
            shell32.ILFree(pidl)
    finally:
        if hr >= 0:
            ole32.CoUninitialize()


def _reveal_linux_dbus(path: Path) -> bool:
    uri = path.resolve().as_uri()
    if shutil.which("gdbus"):
        cmd = ["gdbus", "call", "--session", "--dest", "org.freedesktop.FileManager1",
               "--object-path", "/org/freedesktop/FileManager1",
               "--method", "org.freedesktop.FileManager1.ShowItems", f"['{uri}']", ""]
    elif shutil.which("dbus-send"):
        cmd = ["dbus-send", "--session", "--print-reply", "--dest=org.freedesktop.FileManager1",
               "--type=method_call", "/org/freedesktop/FileManager1",
               "org.freedesktop.FileManager1.ShowItems", f"array:string:{uri}", "string:"]
    else:
        return False
    try:
        return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5).returncode == 0
    except Exception:  # any failure just means: fall back to opening the folder
        return False


def reveal_in_file_manager(path) -> str:
    """Shows `path` in the system file manager, selected. Returns how it was done (for logs and tests)."""
    path = Path(path)
    system = platform.system()
    if system == "Windows":
        try:
            if path.is_file() and _reveal_windows_shell(path):
                return "shell"
        except Exception:
            pass
        norm = os.path.normpath(str(path))
        # Fallback: a raw command line (a list would make Python quote "/select,<path>" as one token)
        subprocess.Popen(f'explorer /select,"{norm}"' if path.is_file() else f'explorer "{norm}"')
        return "explorer"
    if system == "Darwin":
        subprocess.Popen(["open", "-R", str(path)] if path.is_file() else ["open", str(path)])
        return "finder"
    if path.is_file() and _reveal_linux_dbus(path):
        return "dbus"
    subprocess.Popen(["xdg-open", str(path.parent if path.is_file() else path)])
    return "xdg-open"
