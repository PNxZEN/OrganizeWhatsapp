"""
WhatsApp Media Organizer - Background "Import Older Media" job.

Runs core.migrator.execute_import_folder in a worker thread so the HTTP request returns
immediately and the gallery can poll real, byte-accurate progress and cancel the import.
Only one import runs at a time per server process.
"""

import threading
import time
from typing import Any, Callable, Dict, Optional

from core.migrator import IMPORT_MODE_COPY, execute_import_folder

JOB_IDLE = "idle"
JOB_RUNNING = "running"
JOB_DONE = "done"
JOB_CANCELLED = "cancelled"
JOB_ERROR = "error"


class ImportJobManager:
    def __init__(self, runner: Callable[..., Dict[str, Any]] = execute_import_folder):
        self._runner = runner
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._state: Dict[str, Any] = {"state": JOB_IDLE}

    def is_running(self) -> bool:
        with self._lock:
            return self._state.get("state") == JOB_RUNNING

    def start(self, source_dir: str, target_dir: str, mode: str = IMPORT_MODE_COPY,
              import_key: bool = True, on_finished: Optional[Callable[[Dict[str, Any]], None]] = None,
              replace_key: bool = False) -> bool:
        """Starts an import. Returns False if one is already running."""
        with self._lock:
            if self._state.get("state") == JOB_RUNNING:
                return False
            self._cancel.clear()
            self._state = {
                "state": JOB_RUNNING,
                "source_dir": source_dir,
                "mode": mode,
                "started_at": time.time(),
                "finished_at": None,
                "progress": {"phase": "starting", "percent": 0},
                "result": None,
                "error": "",
            }
            self._thread = threading.Thread(
                target=self._run, args=(source_dir, target_dir, mode, import_key, on_finished, replace_key), daemon=True
            )
            self._thread.start()
        return True

    def _on_progress(self, update: Dict[str, Any]) -> None:
        with self._lock:
            progress = dict(self._state.get("progress") or {})
            progress.update(update)
            self._state["progress"] = progress

    def _run(self, source_dir, target_dir, mode, import_key, on_finished, replace_key=False) -> None:
        try:
            kwargs = dict(progress_callback=self._on_progress, import_key=import_key, mode=mode, cancel_event=self._cancel)
            if replace_key:
                kwargs["replace_key"] = True
            result = self._runner(source_dir, target_dir, **kwargs)
            status = result.get("status")
            final = JOB_DONE if status == "success" else JOB_CANCELLED if status == "cancelled" else JOB_ERROR
            error = result.get("message", "") if final == JOB_ERROR else ""
        except Exception as e:  # never leave the job stuck in "running"
            result, final, error = None, JOB_ERROR, f"Import failed: {e}"
        with self._lock:
            self._state.update({"state": final, "result": result, "error": error, "finished_at": time.time()})
            snapshot = dict(self._state)
        if on_finished:
            try:
                on_finished(snapshot)
            except Exception:
                pass

    def cancel(self) -> bool:
        with self._lock:
            if self._state.get("state") != JOB_RUNNING:
                return False
            self._cancel.set()
            return True

    def status(self) -> Dict[str, Any]:
        with self._lock:
            snap = dict(self._state)
            snap["progress"] = dict(snap.get("progress") or {})
            if snap.get("state") == JOB_RUNNING:
                snap["cancel_requested"] = self._cancel.is_set()
            return snap

    def wait(self, timeout: Optional[float] = None) -> None:
        thread = self._thread
        if thread:
            thread.join(timeout)
