"""
Tracks long-running operations so the app can tell whether it is idle, and lets the updater
close the door on new ones while it swaps files.

Sync and import keep their own state; short blocking operations (phone cleanup, restore to
phone, ZIP backups) register through track(). The updater calls block() which first raises
the maintenance flag and only then looks at what is running, so an operation can never slip
in between "was idle" and "now updating".
"""

import threading
from contextlib import contextmanager
from typing import Callable, Dict, Iterable, List, Optional


class MaintenanceActive(Exception):
    """Raised when a new operation is refused because the app is updating."""


class ActivityTracker:
    def __init__(self):
        self._lock = threading.RLock()
        self._active: Dict[int, str] = {}
        self._next_id = 0
        self._maintenance: Optional[str] = None

    @contextmanager
    def track(self, label: str):
        with self._lock:
            if self._maintenance:
                raise MaintenanceActive(self._maintenance)
            self._next_id += 1
            token = self._next_id
            self._active[token] = label
        try:
            yield
        finally:
            with self._lock:
                self._active.pop(token, None)

    def running(self) -> List[str]:
        with self._lock:
            return sorted(set(self._active.values()))

    def maintenance_message(self) -> Optional[str]:
        return self._maintenance

    def block(self, reason: str, extra_busy: Optional[Callable[[], Iterable[str]]] = None) -> List[str]:
        """
        Enters maintenance mode when nothing is running. Returns [] on success, otherwise the
        labels of what is still running (and maintenance mode is NOT left on).
        """
        with self._lock:
            self._maintenance = reason
            busy = list(self._active.values())
            if extra_busy:
                busy.extend(extra_busy())
            if busy:
                self._maintenance = None
                return sorted(set(busy))
            return []

    def unblock(self) -> None:
        with self._lock:
            self._maintenance = None


activity = ActivityTracker()
