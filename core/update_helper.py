"""
Applies a staged update after the running server has exited.

This file is copied to <app>/.update/update_helper.py and started as a detached process by
core.updater, so it must stay standard-library only and must not import anything from core/
(core/ is one of the folders it replaces).

Steps: wait for the old server to exit -> move the current files into a backup folder ->
move the staged files in -> start the new version -> wait until it answers with the new
version. If anything goes wrong the backup is restored and the previous version is started
again, so a failed update leaves the app exactly as it was.

All progress is recorded in .update/journal.json, which lets the app roll back an update that
was interrupted by a crash or power loss (see recover_interrupted_update).
"""

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

JOURNAL_NAME = "journal.json"
RESULT_NAME = "last_result.json"
SERVER_LOG_NAME = "server.log"

WAIT_FOR_EXIT_SECS = 90
HEALTH_TIMEOUT_SECS = 60
MOVE_RETRIES = 8
MOVE_RETRY_DELAY_SECS = 0.5
KEEP_BACKUPS = 1

STATUS_WAITING = "waiting"
STATUS_APPLYING = "applying"
STATUS_LAUNCHING = "launching"
STATUS_DONE = "done"
STATUS_ROLLED_BACK = "rolled_back"
STATUS_FAILED = "failed"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_json_atomic(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def pid_alive(pid) -> bool:
    if not pid or pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.OpenProcess(0x1000, 0, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5  # access denied: it exists
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _retry(action, what: str):
    """Runs action(), retrying briefly: antivirus and search indexers can hold files for a moment."""
    last = None
    for attempt in range(MOVE_RETRIES):
        try:
            return action()
        except OSError as e:
            last = e
            time.sleep(MOVE_RETRY_DELAY_SECS * (attempt + 1))
    raise OSError(f"{what}: {last}")


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        _retry(lambda: shutil.rmtree(path), f"remove {path.name}")
    elif path.exists() or path.is_symlink():
        _retry(path.unlink, f"remove {path.name}")


def _move(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    _retry(lambda: shutil.move(str(src), str(dst)), f"move {src.name}")


def rollback(app_root: Path, backup_dir: Path, journal: dict) -> None:
    """Undoes every move recorded in the journal, newest first."""
    for step in reversed(journal.get("moved", [])):
        name = step["name"]
        target = app_root / name
        saved = backup_dir / name
        if step.get("had_old"):
            if not saved.exists():
                continue  # interrupted before this entry was moved aside: the original is still in place
            if target.exists() or target.is_symlink():
                _remove(target)  # the partly or fully installed new version
            _move(saved, target)
        elif target.exists() or target.is_symlink():
            _remove(target)  # an entry that did not exist before the update


def recover_interrupted_update(app_root: Path) -> bool:
    """
    Called when the app starts. If a previous update was cut short (crash, power loss) while
    files were being swapped, restores the backup. Returns True when it restored something.
    """
    update_dir = app_root / ".update"
    journal = _read_json(update_dir / JOURNAL_NAME)
    if not journal or journal.get("status") not in (STATUS_APPLYING,):
        return False
    if pid_alive(journal.get("helper_pid")):
        return False  # the helper is still working on it
    try:
        rollback(app_root, Path(journal["backup"]), journal)
    except Exception as e:  # leave the journal in place so the problem stays visible
        sys.stderr.write(f"[Updater] Could not restore the backup of an interrupted update: {e}\n")
        return False
    journal["status"] = STATUS_ROLLED_BACK
    journal["error"] = "The update was interrupted; the previous version was restored."
    _write_json_atomic(update_dir / JOURNAL_NAME, journal)
    _write_json_atomic(update_dir / RESULT_NAME, {
        "status": STATUS_ROLLED_BACK,
        "from": journal.get("from_version"),
        "to": journal.get("to_version"),
        "at": _now(),
        "error": journal["error"],
    })
    return True


def _launch(command, cwd, log_path: Path):
    log = open(log_path, "ab")
    kwargs = dict(cwd=cwd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, close_fds=True)
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        return subprocess.Popen(command, **kwargs)
    finally:
        log.close()


def _wait_healthy(port: int, version, proc, timeout: float) -> bool:
    """True once the server on `port` answers /api/health (with `version` when given)."""
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/api/health"
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            return False  # it crashed on start
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get("status") == "ok" and (version is None or data.get("version") == version):
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _stop(proc) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _prune_backups(update_dir: Path, keep: int) -> None:
    backups = sorted((p for p in update_dir.glob("backup-*") if p.is_dir()), key=lambda p: p.name)
    for old in backups[:-keep] if keep else backups:
        shutil.rmtree(old, ignore_errors=True)


def run(plan_path: Path) -> int:
    plan = _read_json(plan_path)
    if not plan:
        sys.stderr.write(f"[Updater] Unreadable plan: {plan_path}\n")
        return 2

    app_root = Path(plan["app_root"])
    update_dir = Path(plan["update_dir"])
    staging = Path(plan["staging"])
    backup_dir = Path(plan["backup"])
    port = int(plan.get("port") or 0)
    to_version = plan.get("to_version")
    journal_path = update_dir / JOURNAL_NAME
    journal = {
        "status": STATUS_WAITING,
        "helper_pid": os.getpid(),
        "from_version": plan.get("from_version"),
        "to_version": to_version,
        "backup": str(backup_dir),
        "moved": [],
        "started_at": _now(),
    }

    def save():
        _write_json_atomic(journal_path, journal)

    def finish(status: str, error: str = ""):
        journal["status"] = status
        if error:
            journal["error"] = error
        save()
        _write_json_atomic(update_dir / RESULT_NAME, {
            "status": "updated" if status == STATUS_DONE else status,
            "from": plan.get("from_version"),
            "to": to_version,
            "at": _now(),
            "error": error,
        })

    save()

    # 1. The old server must be gone before its files are replaced
    deadline = time.time() + WAIT_FOR_EXIT_SECS
    while pid_alive(plan.get("old_pid")) and time.time() < deadline:
        time.sleep(0.3)
    if pid_alive(plan.get("old_pid")):
        finish(STATUS_FAILED, "The running app did not shut down in time, so nothing was changed.")
        return 1

    log_path = update_dir / SERVER_LOG_NAME
    new_proc = None
    try:
        # 2. Swap the files, remembering every step so it can be undone
        journal["status"] = STATUS_APPLYING
        save()
        backup_dir.mkdir(parents=True, exist_ok=True)
        for name in plan["entries"]:
            current = app_root / name
            step = {"name": name, "had_old": current.exists() or current.is_symlink()}
            journal["moved"].append(step)
            save()
            if step["had_old"]:
                _move(current, backup_dir / name)
            _move(staging / name, current)

        # 3. Start the new version and make sure it really works
        journal["status"] = STATUS_LAUNCHING
        save()
        new_proc = _launch(plan["command"], plan.get("cwd") or str(app_root), log_path)
        if not _wait_healthy(port, to_version, new_proc, HEALTH_TIMEOUT_SECS):
            raise RuntimeError(f"Version {to_version} did not start correctly (see {log_path.name}).")
    except Exception as e:
        error = str(e)
        _stop(new_proc)
        try:
            rollback(app_root, backup_dir, journal)
            restored = _launch(plan["command"], plan.get("cwd") or str(app_root), log_path)
            _wait_healthy(port, plan.get("from_version"), restored, HEALTH_TIMEOUT_SECS)
            finish(STATUS_ROLLED_BACK, error)
        except Exception as rb_error:
            finish(STATUS_FAILED, f"{error}. Restoring the previous version also failed: {rb_error}. "
                                  f"Your previous files are in {backup_dir}.")
        return 1

    finish(STATUS_DONE)
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(update_dir / "download", ignore_errors=True)
    _prune_backups(update_dir, KEEP_BACKUPS)
    return 0


if __name__ == "__main__":
    sys.exit(run(Path(sys.argv[1])) if len(sys.argv) > 1 else 2)
