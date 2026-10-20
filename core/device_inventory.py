"""
WhatsApp Media Organizer - Device Inventory Service.

Separates the cheap USB connection check (`adb devices`, ~50 ms) from the expensive
WhatsApp account/backup scan (an `adb shell` probe plus dumpsys / SIM queries, seconds).

- The connection state is shared by concurrent pollers and cached briefly.
- The account scan runs in a background thread, at most one at a time, and its result is
  cached per device serial. While a refresh runs the previous result keeps being served
  (marked stale), so the UI never flips to "no backup found" just because a scan is busy.
- Callers can force a rescan (`refresh=True`) or wait for an in-flight scan (`wait_timeout`).
"""

import threading
import time
from typing import Callable

from core.adb import check_adb_device, discover_whatsapp_accounts

SCAN_IDLE = "idle"          # no authorized device, nothing to scan
SCAN_SCANNING = "scanning"  # a scan is running (accounts may hold the previous, stale result)
SCAN_READY = "ready"        # accounts hold a completed scan for the connected device
SCAN_ERROR = "error"        # the last scan failed; accounts hold the previous result if any


class DeviceInventory:
    def __init__(
        self,
        check_fn: Callable = check_adb_device,
        discover_fn: Callable = discover_whatsapp_accounts,
        accounts_ttl: float = 90.0,
        connection_ttl: float = 1.0,
    ):
        self._check_fn = check_fn
        self._discover_fn = discover_fn
        self._accounts_ttl = accounts_ttl
        self._connection_ttl = connection_ttl

        self._lock = threading.Lock()
        self._conn_lock = threading.Lock()
        self._conn = None
        self._conn_checked_at = 0.0

        self._serial = None
        self._accounts = []
        self._state = SCAN_IDLE
        self._error = ""
        self._started_at = None
        self._finished_at = None
        self._scan_done = threading.Event()
        self._scan_done.set()

    # ------------------------------------------------------------------ connection
    def _connection(self):
        with self._conn_lock:
            now = time.time()
            if self._conn is None or now - self._conn_checked_at >= self._connection_ttl:
                self._conn = self._check_fn()
                self._conn_checked_at = time.time()
            return self._conn

    # ------------------------------------------------------------------ account scan
    def _run_scan(self, serial: str) -> None:
        try:
            accounts = self._discover_fn(device_serial=serial) or []
            error = ""
        except Exception as e:  # pragma: no cover - defensive, discover swallows most errors
            accounts, error = None, str(e)
        with self._lock:
            if self._serial == serial:
                if accounts is not None:
                    self._accounts = accounts
                    self._state = SCAN_READY
                    self._error = ""
                else:
                    self._state = SCAN_ERROR
                    self._error = error
                self._finished_at = time.time()
            self._scan_done.set()

    def _start_scan_locked(self, serial: str) -> None:
        if not self._scan_done.is_set():
            return  # single-flight: a scan is already running
        self._state = SCAN_SCANNING
        self._started_at = time.time()
        self._scan_done.clear()
        threading.Thread(target=self._run_scan, args=(serial,), daemon=True).start()

    def invalidate(self) -> None:
        """Marks cached accounts as expired so the next snapshot triggers a rescan."""
        with self._lock:
            self._finished_at = None

    # ------------------------------------------------------------------ public API
    def snapshot(self, refresh: bool = False, wait_timeout: float = 0.0) -> dict:
        res = self._connection()
        connected, authorized, err_msg, serial, model = res[:5]
        usb_debugging = getattr(res, "usb_debugging", True)
        ready = bool(connected and authorized and serial)

        with self._lock:
            if not ready:
                # Device gone or unauthorized: forget its accounts (a different phone may come next)
                if not connected:
                    self._serial = None
                    self._accounts = []
                    self._finished_at = None
                if self._scan_done.is_set():
                    self._state = SCAN_IDLE
            else:
                if serial != self._serial:
                    self._serial = serial
                    self._accounts = []
                    self._finished_at = None
                expired = self._finished_at is None or (time.time() - self._finished_at) >= self._accounts_ttl
                if refresh or expired:
                    self._start_scan_locked(serial)
            done_event = self._scan_done

        if ready and wait_timeout and wait_timeout > 0:
            done_event.wait(wait_timeout)

        with self._lock:
            now = time.time()
            age = (now - self._finished_at) if self._finished_at else None
            return {
                "connected": connected,
                "authorized": authorized,
                "usb_debugging": usb_debugging,
                "serial": serial,
                "model": model,
                "error": err_msg,
                "accounts": list(self._accounts) if ready else [],
                "accounts_scan": {
                    "state": self._state if ready else SCAN_IDLE,
                    "error": self._error,
                    "started_at": self._started_at,
                    "finished_at": self._finished_at,
                    "age_seconds": round(age, 1) if age is not None else None,
                    "elapsed_seconds": round(now - self._started_at, 1)
                    if (self._state == SCAN_SCANNING and self._started_at)
                    else None,
                    "stale": bool(self._state == SCAN_SCANNING and self._accounts),
                },
            }
