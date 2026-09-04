"""
core/sync_session.py - Persistent SQLite-backed session management for WhatsApp ADB sync.

Features:
- ACID-compliant SQLite session state (.sync_state.sqlite3)
- Device serial binding to prevent cross-device collisions
- Per-file manifest tracking ('pending', 'syncing', 'completed', 'failed', 'skipped')
- Graceful cooperative pause and emergency pause handling
- Atomic staging file cleanup (.part_{session_id})
- Manifest reconciliation when resuming with new device media
"""

import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class SyncSessionManager:
    """
    Manages persistent state for WhatsApp sync sessions in a local SQLite database.
    Survives server restarts, browser reloads, and computer reboots.
    """

    def __init__(self, db_path: str = "./output/.sync_state.sqlite3"):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def set_db_path(self, db_path: str):
        """Switches target database file and initializes schema if missing."""
        with self._lock:
            self.db_path = Path(db_path).resolve()
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._init_db()

    def _ensure_schema(self, conn: sqlite3.Connection):
        """Guarantees table schema exists even if database file was moved or recreated."""
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sync_sessions (
                session_id TEXT PRIMARY KEY,
                device_serial TEXT NOT NULL,
                device_model TEXT,
                status TEXT NOT NULL,
                current_phase TEXT NOT NULL,
                total_files INTEGER DEFAULT 0,
                synced_files INTEGER DEFAULT 0,
                total_bytes INTEGER DEFAULT 0,
                synced_bytes INTEGER DEFAULT 0,
                created_at REAL NOT NULL,
                paused_at REAL,
                updated_at REAL NOT NULL,
                error_message TEXT
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sync_manifest (
                session_id TEXT NOT NULL,
                rel_path TEXT NOT NULL,
                target_path TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                file_mtime INTEGER DEFAULT 0,
                status TEXT NOT NULL,
                synced_bytes INTEGER DEFAULT 0,
                synced_at REAL,
                error_message TEXT,
                PRIMARY KEY (session_id, rel_path),
                FOREIGN KEY (session_id) REFERENCES sync_sessions(session_id) ON DELETE CASCADE
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_manifest_status ON sync_manifest(session_id, status);"
        )
        conn.commit()

    @contextmanager
    def _get_connection(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        self._ensure_schema(conn)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._lock, self._get_connection() as conn:
            pass

    def create_session(
        self,
        session_id: str,
        device_serial: str,
        device_model: str = "",
        total_files: int = 0,
        total_bytes: int = 0,
    ) -> dict:
        now = time.time()
        with self._lock, self._get_connection() as conn:
            # Check if there is already an in_progress session for this device and pause it
            conn.execute(
                """
                UPDATE sync_sessions
                SET status = 'paused', paused_at = ?, updated_at = ?
                WHERE device_serial = ? AND status = 'in_progress'
                """,
                (now, now, device_serial),
            )
            conn.execute(
                """
                INSERT INTO sync_sessions (
                    session_id, device_serial, device_model, status, current_phase,
                    total_files, synced_files, total_bytes, synced_bytes,
                    created_at, updated_at
                ) VALUES (?, ?, ?, 'in_progress', 'inventory', ?, 0, ?, 0, ?, ?)
                """,
                (
                    session_id,
                    device_serial,
                    device_model,
                    total_files,
                    total_bytes,
                    now,
                    now,
                ),
            )
            conn.commit()
        return self.get_session(session_id)

    def get_session(self, session_id: str) -> Optional[dict]:
        with self._lock, self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM sync_sessions WHERE session_id = ?", (session_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_latest_paused_session(self, device_serial: Optional[str] = None) -> Optional[dict]:
        with self._lock, self._get_connection() as conn:
            if device_serial:
                cur = conn.execute(
                    """
                    SELECT * FROM sync_sessions
                    WHERE device_serial = ? AND status = 'paused'
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    (device_serial,),
                )
            else:
                cur = conn.execute(
                    """
                    SELECT * FROM sync_sessions
                    WHERE status = 'paused'
                    ORDER BY updated_at DESC LIMIT 1
                    """
                )
            row = cur.fetchone()
            return dict(row) if row else None

    def recover_abandoned_sessions(self) -> int:
        """
        Transitions any sessions left in 'in_progress' status (e.g. from an
        abrupt process termination, PC reboot, or power outage) into 'paused'
        so they can be safely resumed from their checkpoint.
        Returns number of recovered sessions.
        """
        now = time.time()
        with self._lock, self._get_connection() as conn:
            cur = conn.execute(
                """
                UPDATE sync_sessions
                SET status = 'paused',
                    paused_at = ?,
                    updated_at = ?,
                    error_message = 'Session interrupted by application shutdown'
                WHERE status = 'in_progress'
                """,
                (now, now),
            )
            count = cur.rowcount
            conn.commit()
            return count

    def init_manifest(self, session_id: str, file_entries: List[Tuple[str, str, int, int]]):
        """
        Populates manifest with entries: (rel_path, target_path, file_size, file_mtime).
        """
        with self._lock, self._get_connection() as conn:
            conn.executemany(
                """
                INSERT OR IGNORE INTO sync_manifest (
                    session_id, rel_path, target_path, file_size, file_mtime, status
                ) VALUES (?, ?, ?, ?, ?, 'pending')
                """,
                [
                    (session_id, rel, target, size, mtime)
                    for rel, target, size, mtime in file_entries
                ],
            )
            total_files = len(file_entries)
            total_bytes = sum(e[2] for e in file_entries)
            conn.execute(
                """
                UPDATE sync_sessions
                SET total_files = ?, total_bytes = ?, current_phase = 'adb_pull', updated_at = ?
                WHERE session_id = ?
                """,
                (total_files, total_bytes, time.time(), session_id),
            )
            conn.commit()

    def get_pending_files(self, session_id: str) -> List[dict]:
        with self._lock, self._get_connection() as conn:
            cur = conn.execute(
                """
                SELECT rel_path, target_path, file_size, file_mtime
                FROM sync_manifest
                WHERE session_id = ? AND status IN ('pending', 'failed')
                ORDER BY file_size ASC
                """,
                (session_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def mark_file_completed(self, session_id: str, rel_path: str, synced_bytes: int, target_path: Optional[str] = None):
        now = time.time()
        with self._lock, self._get_connection() as conn:
            if target_path:
                conn.execute(
                    """
                    UPDATE sync_manifest
                    SET status = 'completed', synced_bytes = ?, synced_at = ?, target_path = ?, error_message = NULL
                    WHERE session_id = ? AND rel_path = ?
                    """,
                    (synced_bytes, now, target_path, session_id, rel_path),
                )
            else:
                conn.execute(
                    """
                    UPDATE sync_manifest
                    SET status = 'completed', synced_bytes = ?, synced_at = ?, error_message = NULL
                    WHERE session_id = ? AND rel_path = ?
                    """,
                    (synced_bytes, now, session_id, rel_path),
                )
            # Update aggregate counter in session
            conn.execute(
                """
                UPDATE sync_sessions
                SET synced_files = (SELECT COUNT(*) FROM sync_manifest WHERE session_id = ? AND status = 'completed'),
                    synced_bytes = (SELECT COALESCE(SUM(synced_bytes), 0) FROM sync_manifest WHERE session_id = ? AND status = 'completed'),
                    updated_at = ?
                WHERE session_id = ?
                """,
                (session_id, session_id, now, session_id),
            )
            conn.commit()

    def mark_files_completed_batch(self, session_id: str, items: List[Tuple[str, int]]):
        """
        Efficiently marks a batch of files as completed in a single SQLite transaction.
        Used to instantly reconcile already organized files in output/ on new sync runs.
        """
        if not items:
            return
        now = time.time()
        with self._lock, self._get_connection() as conn:
            conn.executemany(
                """
                UPDATE sync_manifest
                SET status = 'completed', synced_bytes = ?, synced_at = ?, error_message = NULL
                WHERE session_id = ? AND rel_path = ? AND status != 'completed'
                """,
                [(sz, now, session_id, rel_p) for rel_p, sz in items],
            )
            conn.execute(
                """
                UPDATE sync_sessions
                SET synced_files = (SELECT COUNT(*) FROM sync_manifest WHERE session_id = ? AND status = 'completed'),
                    synced_bytes = (SELECT COALESCE(SUM(synced_bytes), 0) FROM sync_manifest WHERE session_id = ? AND status = 'completed'),
                    updated_at = ?
                WHERE session_id = ?
                """,
                (session_id, session_id, now, session_id),
            )
            conn.commit()

    def mark_file_failed(self, session_id: str, rel_path: str, error_message: str):
        now = time.time()
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                UPDATE sync_manifest
                SET status = 'failed', error_message = ?
                WHERE session_id = ? AND rel_path = ?
                """,
                (error_message, session_id, rel_path),
            )
            conn.execute(
                "UPDATE sync_sessions SET updated_at = ? WHERE session_id = ?",
                (now, session_id),
            )
            conn.commit()

    def pause_session(self, session_id: str, reason: str = "User requested pause") -> bool:
        now = time.time()
        with self._lock, self._get_connection() as conn:
            cur = conn.execute(
                """
                UPDATE sync_sessions
                SET status = 'paused', paused_at = ?, updated_at = ?, error_message = ?
                WHERE session_id = ? AND status = 'in_progress'
                """,
                (now, now, reason, session_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def resume_session(self, session_id: str, current_device_serial: str) -> Tuple[bool, str]:
        """
        Validates that current connected device serial matches the session, and sets status to in_progress.
        """
        with self._lock, self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM sync_sessions WHERE session_id = ?", (session_id,))
            row = cur.fetchone()
            if not row:
                return False, f"Session {session_id} not found."
            if row["device_serial"] != current_device_serial:
                return (
                    False,
                    f"Device mismatch: paused session belongs to serial {row['device_serial']}, "
                    f"but connected device is {current_device_serial}.",
                )

            now = time.time()
            conn.execute(
                """
                UPDATE sync_sessions
                SET status = 'in_progress', error_message = NULL, updated_at = ?
                WHERE session_id = ?
                """,
                (now, session_id),
            )
            conn.commit()
            return True, "Session resumed."

    def complete_session(self, session_id: str):
        now = time.time()
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                UPDATE sync_sessions
                SET status = 'completed', current_phase = 'done', updated_at = ?
                WHERE session_id = ?
                """,
                (now, session_id),
            )
            conn.commit()

    def cancel_session(self, session_id: str) -> bool:
        now = time.time()
        with self._lock, self._get_connection() as conn:
            cur = conn.execute(
                """
                UPDATE sync_sessions
                SET status = 'cancelled', updated_at = ?
                WHERE session_id = ?
                """,
                (now, session_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def cleanup_orphaned_part_files(self, base_dirs: List[str]):
        """
        Scans base directories for leftover .part_* files from interrupted transfers
        and removes them to maintain filesystem cleanliness and prevent corruption.
        """
        removed_count = 0
        for b in base_dirs:
            p = Path(b)
            if not p.is_dir():
                continue
            for part_file in p.rglob("*.part_*"):
                try:
                    if part_file.is_file():
                        part_file.unlink(missing_ok=True)
                        removed_count += 1
                except Exception:
                    pass
        return removed_count

    def reconcile_manifest(
        self,
        session_id: str,
        remote_inventory: List[Tuple[str, int]],
        dest_db: str = "./Databases",
        dest_media: str = "./Media",
    ):
        """
        Reconciles the paused manifest against a new remote inventory (taken on resume).
        - Any remote files not in manifest are added as 'pending'.
        - Verifies that completed files actually exist locally with matching sizes.
        """
        with self._lock, self._get_connection() as conn:
            # 1. Fetch completed rows and check disk
            cur = conn.execute(
                "SELECT rel_path, target_path, file_size FROM sync_manifest WHERE session_id = ? AND status = 'completed'",
                (session_id,),
            )
            completed_rows = cur.fetchall()
            for r in completed_rows:
                # Databases should always be refreshed on resume so fresh messages are captured
                if r["rel_path"].startswith("Databases/"):
                    conn.execute(
                        "UPDATE sync_manifest SET status = 'pending', synced_bytes = 0 WHERE session_id = ? AND rel_path = ?",
                        (session_id, r["rel_path"]),
                    )
                    continue

                local_f = Path(r["target_path"])
                if not local_f.is_file() or local_f.stat().st_size != r["file_size"]:
                    # File was deleted or altered while paused: reset to pending!
                    conn.execute(
                        "UPDATE sync_manifest SET status = 'pending', synced_bytes = 0 WHERE session_id = ? AND rel_path = ?",
                        (session_id, r["rel_path"]),
                    )

            # 2. Reconcile remote inventory: check size changes and insert new files
            cur_all = conn.execute("SELECT rel_path, file_size FROM sync_manifest WHERE session_id = ?", (session_id,))
            manifest_map = {row["rel_path"]: row["file_size"] for row in cur_all.fetchall()}

            new_entries = []
            for rel_p, sz in remote_inventory:
                if rel_p not in manifest_map:
                    parts = rel_p.split("/")
                    if parts[0] == "Databases":
                        target = os.path.join(dest_db, *parts[1:])
                    elif parts[0] == "Media":
                        target = os.path.join(dest_media, *parts[1:])
                    elif parts[0] == "Backups":
                        target = os.path.join("./Backups", *parts[1:])
                    else:
                        target = os.path.join(".", *parts)
                    new_entries.append((session_id, rel_p, target, sz, 0, "pending"))
                elif manifest_map[rel_p] != sz:
                    # Remote file size changed on phone (e.g. updated database or modified media)
                    conn.execute(
                        """
                        UPDATE sync_manifest
                        SET file_size = ?, synced_bytes = 0, status = 'pending'
                        WHERE session_id = ? AND rel_path = ?
                        """,
                        (sz, session_id, rel_p),
                    )

            if new_entries:
                conn.executemany(
                    """
                    INSERT INTO sync_manifest (session_id, rel_path, target_path, file_size, file_mtime, status)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    new_entries,
                )

            # 3. Update totals
            now = time.time()
            conn.execute(
                """
                UPDATE sync_sessions
                SET total_files = (SELECT COUNT(*) FROM sync_manifest WHERE session_id = ?),
                    total_bytes = (SELECT COALESCE(SUM(file_size), 0) FROM sync_manifest WHERE session_id = ?),
                    synced_files = (SELECT COUNT(*) FROM sync_manifest WHERE session_id = ? AND status = 'completed'),
                    synced_bytes = (SELECT COALESCE(SUM(synced_bytes), 0) FROM sync_manifest WHERE session_id = ? AND status = 'completed'),
                    updated_at = ?
                WHERE session_id = ?
                """,
                (session_id, session_id, session_id, session_id, now, session_id),
            )
            conn.commit()
