"""Servers starting at the same moment must not crash on the shared sync database (CI failure)."""

import multiprocessing as mp
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _open(path, barrier, results):
    sys.path.insert(0, str(ROOT))
    from core.sync_session import SyncSessionManager

    barrier.wait()
    try:
        SyncSessionManager(path)
        results.put("ok")
    except Exception as e:  # reported to the test
        results.put(repr(e))


class TestSimultaneousStartup(unittest.TestCase):
    def test_many_processes_open_a_new_database_at_once(self):
        # Without the retry this failed a few times per hundred starts ("database is locked")
        ctx = mp.get_context("spawn")
        failures = []
        for _ in range(15):
            tmp = tempfile.mkdtemp()
            try:
                path = os.path.join(tmp, ".sync_state.sqlite3")
                barrier, results = ctx.Barrier(6), ctx.Queue()
                procs = [ctx.Process(target=_open, args=(path, barrier, results)) for _ in range(6)]
                for p in procs:
                    p.start()
                outcomes = [results.get(timeout=60) for _ in procs]
                for p in procs:
                    p.join(timeout=60)
                failures += [o for o in outcomes if o != "ok"]
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(failures, [])

    def test_a_locked_database_is_retried_until_it_frees_up(self):
        import sqlite3
        from unittest import mock

        from core.sync_session import SyncSessionManager

        conn = mock.Mock()
        conn.execute.side_effect = [sqlite3.OperationalError("database is locked")] * 3 + [None]
        with mock.patch("core.sync_session.time.sleep"):
            SyncSessionManager._enable_wal(conn)
        self.assertEqual(conn.execute.call_count, 4)

    def test_other_errors_are_not_retried(self):
        import sqlite3
        from unittest import mock

        from core.sync_session import SyncSessionManager

        conn = mock.Mock()
        conn.execute.side_effect = sqlite3.OperationalError("disk I/O error")
        with self.assertRaises(sqlite3.OperationalError):
            SyncSessionManager._enable_wal(conn)
        self.assertEqual(conn.execute.call_count, 1)


if __name__ == "__main__":
    unittest.main()
