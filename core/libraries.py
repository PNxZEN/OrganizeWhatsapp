"""
One library per WhatsApp account.

A phone can carry several WhatsApp accounts (WhatsApp's own accounts/<id> folders, WhatsApp
Business, a second copy of WhatsApp). Their chats and media must not mix, and each has its own
64-digit key, so each account gets its own library:

  - an output folder (gallery, organized media, sync state), beside the first one
  - a folder for its decrypted chat database and a key file of its own
  - its settings in config.json's "profiles"[<account folder>] (see core.config.PROFILE_KEYS)
  - its own gallery server, on its own port: each account opens in its own browser tab

The first library (./output and the top level of config.json) stays what it always was: the
account the user synced first. Only one library syncs the phone at a time (phone_lock).
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from core import instance as _instance
from core.config import active_profile, load_config, save_config

PHONE_LOCK = ".phone_sync.json"
_open_lock = threading.Lock()
_START_WAIT_SECS = 25.0


def _app_root() -> Path:
    return Path(__file__).resolve().parent.parent


def account_label(account: dict) -> str:
    """'WhatsApp Business (+91 98…)', 'WhatsApp (account 1003)'... for an account from the phone scan."""
    app = "WhatsApp Business" if account.get("app_type") == "whatsapp_business" else "WhatsApp"
    phone = (account.get("phone_number") or "").strip() if account.get("phone_verified") else ""
    if phone and phone.lower() not in ("whatsapp", "whatsapp business", "unknown"):
        return f"{app} ({phone})"
    acc_id = account.get("account_id") or "main"
    path = account.get("path") or ""
    if acc_id != "main" and not acc_id.startswith("dual_"):
        return f"{app} (account {acc_id})"
    m = re.search(r"/storage/emulated/(\d+)/", path + "/")
    if m and m.group(1) != "0":
        return f"{app} (phone user {m.group(1)})"
    return app


def _folder_safe(text: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text).strip(" .")
    return re.sub(r"\s+", " ", safe)[:60] or "account"


def primary_output_dir() -> Path:
    """The first library's output folder (recorded by its server)."""
    cfg = load_config()
    return Path(cfg.get("primary_output_dir") or "./output")


def library_dirs(label: str) -> dict:
    """Folders for a new library, beside the first one: 'output - WhatsApp Business (+91…)' etc."""
    primary = primary_output_dir()
    name = _folder_safe(label)
    taken = {Path(v.get("output_dir", "")).name for v in (load_config().get("libraries") or {}).values()}
    suffix, n = "", 1
    while (f"{primary.name} - {name}{suffix}" in taken) or (primary.parent / f"{primary.name} - {name}{suffix}").exists():
        n += 1
        suffix = f" {n}"
    out = primary.parent / f"{primary.name} - {name}{suffix}"
    return {
        "output_dir": str(out),
        "db_dir": str(Path(f"./Databases - {name}{suffix}")),
        "key_file": f"encrypted_backup - {name}{suffix}.key",
    }


def library_account() -> str:
    """The account this process's library belongs to ("" while the first library has none yet)."""
    return active_profile() or (load_config().get("selected_account_path") or "")


def _first_library_has_data(output_dir) -> bool:
    return (Path(output_dir) / "media_index.csv").is_file()


def list_libraries(this_output_dir=None) -> list:
    """
    Every library: {"account", "label", "output_dir", "primary", "current", "running", "url",
    "has_data"}. The first library is the account the top level of config.json is bound to.
    """
    cfg = _raw_config()
    here = Path(this_output_dir).resolve() if this_output_dir else None
    primary_out = Path(cfg.get("primary_output_dir") or "./output")
    libs = [{
        "account": cfg.get("selected_account_path") or "",
        "label": cfg.get("selected_account_label") or "",
        "output_dir": str(primary_out),
        "primary": True,
    }]
    profiles = cfg.get("profiles") or {}
    for account, entry in sorted((cfg.get("libraries") or {}).items(), key=lambda kv: kv[1].get("created_at", 0)):
        # The label its own sync recorded (with the number its backup confirmed) when there is one
        label = (profiles.get(account) or {}).get("selected_account_label") or entry.get("label") or ""
        libs.append({"account": account, "label": label,
                     "output_dir": entry.get("output_dir") or "", "primary": False})
    for lib in libs:
        out = Path(lib["output_dir"])
        try:
            lib["current"] = bool(here) and out.resolve() == here
        except OSError:
            lib["current"] = False
        running = None if lib["current"] else _running(out)
        lib["running"] = bool(running) or lib["current"]
        lib["port"] = running["port"] if running else None
        lib["has_data"] = _first_library_has_data(out)
    return libs


def _raw_config() -> dict:
    """config.json's top level, whatever library this process serves."""
    from core.config import _load_file_config, DEFAULT_CONFIG_FILE
    return _load_file_config(DEFAULT_CONFIG_FILE)


def _running(output_dir) -> Optional[dict]:
    """The live server of a library, without waiting for one that is starting."""
    lock = Path(output_dir) / _instance.LOCK_NAME
    try:
        info = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(info, dict) or info.get("instance") == _instance.INSTANCE_ID:
        return None
    if not _instance._pid_alive(info.get("pid")) or not info.get("port"):
        return None
    return info if _instance._answers_as(info["port"], info.get("instance")) else None


def library_for(account_path: str) -> Optional[dict]:
    for lib in list_libraries():
        if lib["account"] == account_path:
            return lib
    return None


def ensure_library(account: dict) -> dict:
    """The library of a phone account, created (folders, settings, its remembered key) if new."""
    path = account["path"]
    existing = library_for(path)
    if existing:
        return existing
    raw = _raw_config()
    if not raw.get("selected_account_path"):
        raise ValueError("The first library has no account yet: choose the account for it first.")
    label = account_label(account)
    dirs = library_dirs(label)
    libraries = dict(raw.get("libraries") or {})
    libraries[path] = {"label": label, "output_dir": dirs["output_dir"], "created_at": time.time()}
    profiles = dict(raw.get("profiles") or {})
    remembered_key = (raw.get("account_keys") or {}).get(path, "")
    profiles[path] = {
        **dirs,
        "media_dir": dirs["output_dir"],
        "hex_key": remembered_key,
        "hex_key_account": path if remembered_key else None,
        "selected_account_path": path,
        "selected_account_id": account.get("account_id") or ("main" if "/accounts/" not in path else Path(path).name),
        "selected_account_phone": account.get("phone_number") or "",
        "selected_app_type": account.get("app_type") or "whatsapp",
        "selected_account_label": label,
    }
    _save_top_level({"libraries": libraries, "profiles": profiles})
    Path(dirs["output_dir"]).mkdir(parents=True, exist_ok=True)
    return library_for(path)


def _save_top_level(values: dict):
    """Writes top-level keys (and whole profiles) whatever library this process serves."""
    from core import config as _cfg
    with _cfg._config_lock, _cfg._InterprocessLock(Path(_cfg.DEFAULT_CONFIG_FILE)):
        data = _cfg._load_file_config(_cfg.DEFAULT_CONFIG_FILE)
        if "profiles" in values:
            merged = dict(data.get("profiles") or {})
            for acc, prof in values["profiles"].items():
                merged[acc] = {**(merged.get(acc) or {}), **prof}
            values = {**values, "profiles": merged}
        data.update(values)
        tmp = Path(f"{_cfg.DEFAULT_CONFIG_FILE}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, _cfg.DEFAULT_CONFIG_FILE)


def open_library(account: dict, idle_timeout=45, allow_lan=False, preferred_port=8001) -> dict:
    """
    Starts the gallery server of an account's library (creating the library first) unless it runs
    already. Returns {"url", "port", "output_dir", "label", "started"}.
    """
    with _open_lock:
        lib = ensure_library(account)
        if lib["current"]:
            raise ValueError("This account's library is the one open in this tab.")
        running = _running(lib["output_dir"])
        if running:
            return {"url": _url(running["port"]), "port": running["port"], "output_dir": lib["output_dir"],
                    "label": lib["label"], "started": False}
        out = Path(lib["output_dir"])
        out.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, str(_app_root() / "wa_media_organizer.py"), "--serve",
               "--output", str(out), "--idle-timeout", str(int(idle_timeout or 0))]
        if lib["primary"]:
            # The first library (its window was closed): it serves the top level, on its usual port
            cmd += ["--port", str(_raw_config().get("port") or 8000)]
        else:
            cmd += ["--port", str(preferred_port), "--profile", account["path"]]
        if allow_lan:
            cmd.append("--allow-lan")
        log = open(out / ".gallery_server.log", "ab")
        kwargs = {"cwd": os.getcwd(), "stdout": log, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL}
        if sys.platform == "win32":
            kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(cmd, **kwargs)
        log.close()
        deadline = time.time() + _START_WAIT_SECS
        while time.time() < deadline:
            running = _running(out)
            if running:
                return {"url": _url(running["port"]), "port": running["port"], "output_dir": str(out),
                        "label": lib["label"], "started": True}
            if proc.poll() is not None:
                break
            time.sleep(0.2)
        tail = ""
        try:
            tail = (out / ".gallery_server.log").read_text(encoding="utf-8", errors="replace")[-400:]
        except OSError:
            pass
        raise RuntimeError(f"The gallery for {lib['label']} did not start. {tail}".strip())


def _url(port) -> str:
    return f"http://127.0.0.1:{int(port)}/gallery.html"


def stop_other_libraries():
    """Asks every other running library server to shut down (the app is quitting or updating)."""
    import urllib.request
    stopped = 0
    for lib in list_libraries():
        if lib["current"] or not lib["port"]:
            continue
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{lib['port']}/api/shutdown", data=b"{}",
                                         headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=3).read()
            stopped += 1
        except Exception:
            pass
    return stopped


# --- one sync on the phone at a time --------------------------------------------------------

def phone_lock_holder() -> Optional[dict]:
    """{"pid", "label", "output_dir"} of the library syncing the phone now (another process), else None."""
    try:
        info = json.loads(Path(PHONE_LOCK).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(info, dict) or info.get("pid") == os.getpid():
        return None
    return info if _instance._pid_alive(info.get("pid")) else None


def acquire_phone(label: str, output_dir) -> Optional[dict]:
    """Takes the phone for this library's sync. Returns the holder instead when another has it."""
    from core import config as _cfg
    with _cfg._InterprocessLock(Path(PHONE_LOCK)):
        holder = phone_lock_holder()
        if holder:
            return holder
        Path(PHONE_LOCK).write_text(json.dumps({"pid": os.getpid(), "label": label,
                                                "output_dir": str(output_dir), "since": time.time()}),
                                    encoding="utf-8")
    return None


def release_phone():
    try:
        info = json.loads(Path(PHONE_LOCK).read_text(encoding="utf-8"))
        if info.get("pid") == os.getpid():
            os.remove(PHONE_LOCK)
    except (OSError, ValueError, AttributeError):
        pass


def folders_of_other_libraries(base_path: str) -> list:
    """
    Media folders (relative to the storage folder, e.g. "accounts/1003/Media" or "Media") of the
    same storage that belong to another account's library: that library collects them, so this one
    does not copy them too. Except a folder the sync report found to hold this account's own older
    media (account_folder_verdicts).
    """
    from core.adb import media_tar_root
    root = media_tar_root(base_path or "")
    if not root:
        return []
    verdicts = load_config().get("account_folder_verdicts") or {}
    folders = []
    for lib in list_libraries():
        acc = (lib.get("account") or "").rstrip("/")
        if not acc or acc == (base_path or "").rstrip("/") or media_tar_root(acc) != root:
            continue
        folder = (acc[len(root) + 1:] + "/Media") if acc != root else "Media"
        if verdicts.get(f"{root}/{folder}") == "this_account":
            continue
        folders.append(folder)
    return folders


def this_library_label() -> str:
    cfg = load_config()
    return cfg.get("selected_account_label") or ("WhatsApp" if not active_profile() else "this account")


def record_primary_output(output_dir):
    """The first library's server notes where its output folder is (other libraries go beside it)."""
    if active_profile():
        return
    try:
        resolved = str(Path(output_dir).resolve())
        if _raw_config().get("primary_output_dir") != resolved:
            save_config({"primary_output_dir": resolved})
    except OSError:
        pass
