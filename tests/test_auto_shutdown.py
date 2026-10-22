"""
Closing the browser must never cut off work that cannot be resumed:
- the last tab closing shuts the app down only when nothing is running
- an import, ZIP backup, phone cleanup or restore is allowed to finish first
- a phone sync is paused safely (it resumes next time), as before
- a reload within the grace period keeps the app running
- --idle-timeout 0 disables automatic shutdown (live mode relies on this)
- a browser that disappears without closing its tabs still lets the app close after idle_timeout
"""

import json
import sys
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock
import tempfile
import shutil

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.server as srv
from core.activity import activity


class FakeServer:
    def __init__(self):
        self.shutdowns = 0

    def shutdown(self):
        self.shutdowns += 1


class AutoShutdownBase(unittest.TestCase):
    def setUp(self):
        self.patches = [
            mock.patch.object(srv, "_TAB_CLOSE_GRACE_SECS", 0.05),
            mock.patch.object(srv, "_SHUTDOWN_RETRY_SECS", 0.05),
            mock.patch.dict(srv._server_runtime, {"idle_timeout": 45}),
            mock.patch.object(srv, "_has_had_browser_tab", True),
        ]
        for p in self.patches:
            p.start()
        srv._active_tabs.clear()
        srv.sync_status["active"] = False
        self.server = FakeServer()

    def tearDown(self):
        if srv._tab_shutdown_timer:
            srv._tab_shutdown_timer.cancel()
        for p in reversed(self.patches):
            p.stop()
        srv._active_tabs.clear()
        srv.sync_status["active"] = False

    def closed_all_tabs(self):
        srv._schedule_auto_shutdown(self.server, "All browser tabs closed", srv._TAB_CLOSE_GRACE_SECS)

    def wait_shutdown(self, expected, timeout=2.0):
        deadline = time.time() + timeout
        while time.time() < deadline and self.server.shutdowns < expected:
            time.sleep(0.02)
        time.sleep(0.7)  # _perform_clean_shutdown calls server.shutdown after 0.5 s
        return self.server.shutdowns


class TestAutoShutdown(AutoShutdownBase):
    def test_01_idle_app_closes_after_the_last_tab(self):
        self.closed_all_tabs()
        self.assertEqual(self.wait_shutdown(1), 1)

    def test_02_running_import_is_allowed_to_finish(self):
        running = {"value": True}
        with mock.patch.object(srv._import_job, "is_running", lambda: running["value"]):
            self.closed_all_tabs()
            self.assertEqual(self.wait_shutdown(1, timeout=0.5), 0, "must not close during an import")
            running["value"] = False
            self.assertEqual(self.wait_shutdown(1), 1, "closes once the import finished")

    def test_03_zip_backup_cleanup_and_restore_are_allowed_to_finish(self):
        for label in ("ZIP backup", "phone storage cleanup", "restore to phone"):
            self.server = FakeServer()
            done = threading.Event()
            started = threading.Event()

            def work():
                with activity.track(label):
                    started.set()
                    done.wait(5)

            t = threading.Thread(target=work)
            t.start()
            started.wait(2)
            self.closed_all_tabs()
            self.assertEqual(self.wait_shutdown(1, timeout=0.4), 0, label)
            done.set()
            t.join(2)
            self.assertEqual(self.wait_shutdown(1), 1, label)

    def test_04_sync_is_paused_not_waited_for(self):
        srv.sync_status.update(active=True, session_id="s1")
        with mock.patch.object(srv._session_manager, "pause_session") as pause:
            self.closed_all_tabs()
            self.assertEqual(self.wait_shutdown(1), 1)
        pause.assert_called_once()
        self.assertFalse(srv.sync_status["active"])
        self.assertEqual(srv.sync_status["status"], "paused")

    def test_05_a_reload_keeps_the_app_running(self):
        self.closed_all_tabs()
        srv._active_tabs["tab-reloaded"] = time.time()
        self.assertEqual(self.wait_shutdown(1, timeout=0.4), 0)

    def test_06_idle_timeout_zero_disables_automatic_shutdown(self):
        srv._server_runtime["idle_timeout"] = 0
        self.closed_all_tabs()
        self.assertEqual(self.wait_shutdown(1, timeout=0.4), 0)

    def test_07_vanished_browser_closes_after_idle_timeout(self):
        srv._server_runtime["idle_timeout"] = 0.001  # minutes
        srv._last_tab_seen["at"] = time.time() - 60
        with mock.patch.object(srv, "_IDLE_WATCH_INTERVAL_SECS", 0.05):
            t = threading.Thread(target=srv._idle_watchdog, args=(self.server,), daemon=True)
            t.start()
            self.assertEqual(self.wait_shutdown(1), 1)

    def test_08_watchdog_waits_for_running_work_too(self):
        srv._server_runtime["idle_timeout"] = 0.001
        srv._last_tab_seen["at"] = time.time() - 60
        running = {"value": True}
        with mock.patch.object(srv, "_IDLE_WATCH_INTERVAL_SECS", 0.05), \
             mock.patch.object(srv._import_job, "is_running", lambda: running["value"]):
            threading.Thread(target=srv._idle_watchdog, args=(self.server,), daemon=True).start()
            self.assertEqual(self.wait_shutdown(1, timeout=0.4), 0)
            running["value"] = False
            self.assertEqual(self.wait_shutdown(1), 1)


class TestTabClosedEndpoint(AutoShutdownBase):
    """The real HTTP flow: heartbeat, then the tab-closed beacon."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="wa_test_shutdown_")
        out = self.tmp
        srv._ensure_frontend_installed(Path(out).resolve())  # not inside the first (timed) request

        class Handler(srv.GalleryHTTPRequestHandler):
            def __init__(self, *a, **kw):
                super().__init__(*a, directory=out, **kw)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.calls = []
        self.p = mock.patch.object(srv, "_perform_clean_shutdown", lambda server, reason="": self.calls.append(reason))
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.httpd.shutdown()
        self.httpd.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:  # a cold CI runner can be slow on the first request
            return json.loads(r.read())

    def test_10_last_tab_closing_waits_for_an_import(self):
        self.post("/api/heartbeat", {"tab_id": "t1"})
        running = {"value": True}
        with mock.patch.object(srv._import_job, "is_running", lambda: running["value"]):
            self.post("/api/tab-closed", {"tab_id": "t1"})
            time.sleep(0.4)
            self.assertEqual(self.calls, [])
            running["value"] = False
            deadline = time.time() + 2
            while time.time() < deadline and not self.calls:
                time.sleep(0.02)
        self.assertEqual(self.calls, ["All browser tabs closed"])

    def test_11_closing_one_of_two_tabs_keeps_the_app_running(self):
        self.post("/api/heartbeat", {"tab_id": "t1"})
        self.post("/api/heartbeat", {"tab_id": "t2"})
        self.assertEqual(self.post("/api/tab-closed", {"tab_id": "t1"})["remaining_tabs"], 1)
        time.sleep(0.3)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
