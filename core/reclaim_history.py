"""
A record of every phone cleanup (Reclaim Space), kept in <output>/.cleanup_history/.

Each run has a summary (<run_id>.json) and one line per file (<run_id>.jsonl), written as the phone
confirms each batch and flushed to disk then, so a crash, a closed app or an unplugged phone
leaves an exact record up to that point. A run whose summary still says "running" when it is
read, and is not running in this app now, was interrupted.

File statuses (see core.adb.batch_delete_phone_files):
  deleted, not_on_phone, duplicate (listed twice: counted once), skipped, failed, not_done, unknown
"""

import csv
import io
import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

HISTORY_DIR = ".cleanup_history"
STATUSES = ("deleted", "not_on_phone", "duplicate", "skipped", "failed", "not_done", "unknown")
_running: Dict[str, "CleanupRun"] = {}
_lock = threading.Lock()


def _dir(output_dir) -> Path:
    return Path(output_dir) / HISTORY_DIR


class CleanupRun:
    def __init__(self, output_dir, meta: dict):
        self.dir = _dir(output_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.summary = {
            "run_id": self.run_id, "status": "running", "started_at": time.time(), "finished_at": None,
            "pid": os.getpid(), **meta,
            "counts": {s: 0 for s in STATUSES}, "bytes": {s: 0 for s in STATUSES},
        }
        self._files = open(self.dir / f"{self.run_id}.jsonl", "a", encoding="utf-8")
        self._save()
        with _lock:
            _running[self.run_id] = self

    def _save(self):
        tmp = self.dir / f"{self.run_id}.json.tmp"
        tmp.write_text(json.dumps(self.summary, indent=1), encoding="utf-8")
        os.replace(tmp, self.dir / f"{self.run_id}.json")

    def record(self, entries: List[dict]):
        """entries: {"status", "name", "chat", "rel_path", "phone_path", "size", "reason"}; one batch."""
        if not entries:
            return
        for e in entries:
            st = e.get("status")
            if st in self.summary["counts"]:
                self.summary["counts"][st] += 1
                self.summary["bytes"][st] += int(e.get("size") or 0)
            self._files.write(json.dumps(e, ensure_ascii=False) + "\n")
        self._files.flush()
        try:
            os.fsync(self._files.fileno())
        except OSError:
            pass
        self._save()

    def finish(self, status: str, **extra):
        self.summary.update(extra)
        self.summary["status"] = status
        self.summary["finished_at"] = time.time()
        self._save()
        try:
            self._files.close()
        except OSError:
            pass
        with _lock:
            _running.pop(self.run_id, None)


def _load_summary(path: Path) -> Optional[dict]:
    try:
        s = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if s.get("status") == "running" and s.get("run_id") not in _running:
        s["status"] = "interrupted"  # the app stopped (or the PC turned off) during it
    return s


def list_runs(output_dir) -> List[dict]:
    d = _dir(output_dir)
    if not d.is_dir():
        return []
    runs = [s for s in (_load_summary(p) for p in d.glob("*.json")) if s]
    return sorted(runs, key=lambda s: s.get("started_at") or 0, reverse=True)


def read_run(output_dir, run_id: str, status: Optional[str] = None, offset: int = 0, limit: int = 200,
             query: str = "") -> Optional[dict]:
    if not run_id or "/" in run_id or "\\" in run_id or ".." in run_id:
        return None
    d = _dir(output_dir)
    summary = _load_summary(d / f"{run_id}.json")
    if not summary:
        return None
    files, matched = [], 0
    q = (query or "").lower()
    try:
        with open(d / f"{run_id}.jsonl", "r", encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue  # a line cut off by a crash
                if status and e.get("status") != status:
                    continue
                if q and q not in (e.get("name") or "").lower() and q not in (e.get("chat") or "").lower():
                    continue
                if offset <= matched < offset + limit:
                    files.append(e)
                matched += 1
    except OSError:
        pass
    return {"summary": summary, "files": files, "matched": matched, "offset": offset, "limit": limit}


def run_csv(output_dir, run_id: str) -> Optional[str]:
    data = read_run(output_dir, run_id, limit=10 ** 9)
    if not data:
        return None
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["status", "file", "chat", "size_bytes", "phone_path", "pc_path", "reason"])
    for e in data["files"]:
        w.writerow([e.get("status"), e.get("name"), e.get("chat"), e.get("size"), e.get("phone_path"),
                    e.get("rel_path"), e.get("reason") or ""])
    return buf.getvalue()
