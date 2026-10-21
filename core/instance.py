"""
One gallery server per output folder.

Two servers on the same folder each keep their own in-memory locks and caches, so they can
overwrite each other's changes to gallery_data.js (a recycle in one tab undone by a sync flush
in another). The first server claims <output>/.gallery_server.json; a second launch finds it,
checks that the server it names is really this app and still running, and opens the browser
on it instead of starting another server.
"""

import json
import os
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Optional

APP_MARKER = "wa-media-organizer"
LOCK_NAME = ".gallery_server.json"
INSTANCE_ID = uuid.uuid4().hex

_CLAIM_WAIT_SECS = 6.0


def _pid_alive(pid) -> bool:
    from core.update_helper import pid_alive

    return pid_alive(pid)


def _read(lock: Path) -> Optional[dict]:
    try:
        data = json.loads(lock.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _answers_as(port, instance) -> bool:
    """True when the server on `port` is this app and the instance recorded in the lock."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{int(port)}/api/health", timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("app") == APP_MARKER and data.get("instance") == instance
    except Exception:
        return False


def find_running_instance(output_dir) -> Optional[dict]:
    """
    Returns {"port": ..., "pid": ...} of a live server already serving output_dir, else None.
    Waits briefly when another server has claimed the folder but is still starting up.
    """
    lock = Path(output_dir) / LOCK_NAME
    deadline = time.time() + _CLAIM_WAIT_SECS
    while True:
        info = _read(lock)
        if not info or info.get("instance") == INSTANCE_ID or not _pid_alive(info.get("pid")):
            return None
        if info.get("port") and _answers_as(info["port"], info.get("instance")):
            return info
        if time.time() >= deadline:
            return None  # claimed but never answered: treat as stale
        time.sleep(0.25)


def claim(output_dir, port: int, host: str) -> None:
    """Records this server as the one serving output_dir (best effort: a read-only folder is fine)."""
    lock = Path(output_dir) / LOCK_NAME
    data = {"app": APP_MARKER, "instance": INSTANCE_ID, "pid": os.getpid(), "port": int(port),
            "host": host, "started_at": time.time()}
    try:
        tmp = lock.with_name(LOCK_NAME + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, lock)
    except OSError:
        pass


def release(output_dir) -> None:
    """Removes the claim on shutdown, unless another server has taken over meanwhile."""
    lock = Path(output_dir) / LOCK_NAME
    info = _read(lock)
    if info and info.get("instance") == INSTANCE_ID:
        try:
            lock.unlink()
        except OSError:
            pass


def lost_claim(output_dir) -> Optional[dict]:
    """
    Two launches at the same moment can both start a server before either has claimed the folder.
    Each checks shortly after claiming: the one whose claim was overwritten steps aside.
    """
    info = _read(Path(output_dir) / LOCK_NAME)
    if info and info.get("instance") != INSTANCE_ID and _pid_alive(info.get("pid")) \
            and info.get("port") and _answers_as(info["port"], info.get("instance")):
        return info
    return None
