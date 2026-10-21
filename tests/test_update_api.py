"""
Tests for the updater's HTTP API and its privacy guarantees:
- nothing goes online unless the user presses "Check for updates" or opted in to automatic checks
- an automatic check is refused by the server when it is disabled or not due (once a day)
- starting work is refused while an update installs, and installing is refused while work runs
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import core.server as srv
from core.activity import ActivityTracker, activity
from core.config import load_config, save_config
from core.updater import UpdateManager
from core.version import __version__
from update_fixtures import FakeGitHub, make_app_files


class TestUpdateApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="wa_test_update_api_"))
        cls.cwd = os.getcwd()
        os.chdir(cls.tmp)  # config.json lives in the working directory
        cls.root = cls.tmp / "app"
        for rel, text in make_app_files("99.0.0").items():
            p = cls.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        cls.output = cls.tmp / "output"
        cls.output.mkdir()
        cls.github = FakeGitHub()
        cls.github.publish("99.1.0")
        cls.manager = UpdateManager(
            root=cls.root, repo=cls.github.repo, api_base=cls.github.base, current_version="99.0.0",
            busy_probe=srv._updater_busy_probe, allowed_hosts=("127.0.0.1",))
        cls.manager._hard_exit = lambda code: None
        cls.patches = [mock.patch.object(srv, "_update_manager", cls.manager)]
        for p in cls.patches:
            p.start()

        class Handler(srv.GalleryHTTPRequestHandler):
            def __init__(self, *a, **kw):
                super().__init__(*a, directory=str(cls.output), **kw)

        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        for p in cls.patches:
            p.stop()
        cls.github.close()
        os.chdir(cls.cwd)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        save_config({"auto_check_updates": False, "last_update_check": 0})
        self.github.requests.clear()
        srv.sync_status["active"] = False
        activity.unblock()

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    # ----- privacy

    def test_01_opening_the_app_never_goes_online(self):
        self.call("GET", "/api/version?consume=1")
        self.call("GET", "/api/update/status")
        self.call("GET", "/api/health")
        self.assertEqual(self.github.requests, [])

    def test_02_version_reports_installed_version_and_defaults(self):
        status, data = self.call("GET", "/api/version")
        self.assertEqual(status, 200)
        self.assertEqual(data["version"], __version__)
        self.assertFalse(data["auto_check_updates"], "automatic checks must be off by default")
        self.assertFalse(data["auto_check_due"])
        self.assertEqual(self.call("GET", "/api/health")[1]["version"], __version__)

    def test_03_automatic_check_is_refused_unless_enabled(self):
        status, data = self.call("POST", "/api/update/check", {"auto": True})
        self.assertEqual((status, data["status"]), (200, "skipped"))
        self.assertEqual(self.github.requests, [], "a disabled setting must not cause any request")

    def test_04_enabled_automatic_check_runs_once_a_day(self):
        self.assertEqual(self.call("POST", "/api/update/settings", {"auto_check": True})[0], 200)
        self.assertTrue(load_config()["auto_check_updates"])
        self.assertTrue(self.call("GET", "/api/version")[1]["auto_check_due"])
        status, data = self.call("POST", "/api/update/check", {"auto": True, "force": True})
        self.assertEqual(data["status"], "success")
        self.assertTrue(data["update_available"])
        self.assertGreater(load_config()["last_update_check"], time.time() - 60)
        self.assertFalse(self.call("GET", "/api/version")[1]["auto_check_due"])
        before = len(self.github.requests)
        self.assertEqual(self.call("POST", "/api/update/check", {"auto": True})[1]["status"], "skipped")
        self.assertEqual(len(self.github.requests), before)
        save_config({"last_update_check": time.time() - 25 * 3600})
        self.assertTrue(self.call("GET", "/api/version")[1]["auto_check_due"], "due again after a day")

    def test_05_turning_the_setting_off_stops_checks(self):
        self.call("POST", "/api/update/settings", {"auto_check": True})
        self.call("POST", "/api/update/settings", {"auto_check": False})
        self.assertEqual(self.call("POST", "/api/update/check", {"auto": True})[1]["status"], "skipped")

    def test_06_settings_are_validated(self):
        self.assertEqual(self.call("POST", "/api/update/settings", {"auto_check": "yes"})[0], 400)
        self.assertEqual(self.call("POST", "/api/update/settings", {})[0], 400)

    def test_07_manual_check_always_works(self):
        status, data = self.call("POST", "/api/update/check", {"force": True})
        self.assertEqual(status, 200)
        self.assertEqual(data["latest_version"], "99.1.0")
        self.assertEqual(len([r for r in self.github.requests if "releases/latest" in r]), 1)

    def test_08_requests_carry_no_version_or_identifiers(self):
        seen = []
        real = self.manager._urlopen

        def spy(req, timeout=None):
            seen.append(dict(req.header_items()))
            return real(req, timeout=timeout)

        self.manager._urlopen = spy
        try:
            self.call("POST", "/api/update/check", {"force": True})
        finally:
            self.manager._urlopen = real
        self.assertTrue(seen)
        for headers in seen:
            blob = json.dumps(headers).lower()
            self.assertNotIn(__version__, blob)
            self.assertNotIn("cookie", blob)
            self.assertNotIn("authorization", blob)

    # ----- idle gating

    def test_10_download_then_install_is_refused_while_a_sync_runs(self):
        self.call("POST", "/api/update/check", {"force": True})
        self.assertEqual(self.call("POST", "/api/update/download")[0], 202)
        deadline = time.time() + 15
        while time.time() < deadline and self.call("GET", "/api/update/status")[1]["state"] != "ready":
            time.sleep(0.1)
        self.assertEqual(self.call("GET", "/api/update/status")[1]["state"], "ready")

        srv.sync_status["active"] = True
        status, data = self.call("GET", "/api/update/status")
        self.assertEqual(data["busy"], ["phone sync"])
        status, data = self.call("POST", "/api/update/apply")
        self.assertEqual(status, 409)
        self.assertEqual(data["code"], "busy")
        self.assertIn("phone sync", data["busy"])
        self.assertIsNone(activity.maintenance_message(), "a refused install must leave the app usable")
        srv.sync_status["active"] = False

    def test_11_work_is_refused_while_installing(self):
        activity.block("Installing an update. Please wait…")
        try:
            status, data = self.call("POST", "/api/sync", {})
            self.assertEqual((status, data["status"]), (409, "updating"))
            status, data = self.call("POST", "/api/import/execute", {"source_path": "x"})
            self.assertEqual((status, data["status"]), (409, "updating"))
            status, data = self.call("POST", "/api/heartbeat", {"tab_id": "t1"})
            self.assertEqual(data["maintenance"], "Installing an update. Please wait…", "other tabs learn about it")
        finally:
            activity.unblock()
        self.assertIsNone(self.call("POST", "/api/heartbeat", {"tab_id": "t1"})[1]["maintenance"])

    def test_12_error_codes_map_to_http_statuses(self):
        self.manager._release = None
        self.manager._checked_at = 0
        self.github.api_status = 404
        try:
            status, data = self.call("POST", "/api/update/check", {"force": True})
        finally:
            self.github.api_status = 200
        self.assertEqual((status, data["code"]), (502, "not_found"))

    def test_99_install_hands_over_and_asks_for_shutdown(self):
        """Last: the request shuts the test server down, exactly like the real thing."""
        self.call("POST", "/api/update/check", {"force": True})
        if self.call("GET", "/api/update/status")[1]["state"] != "ready":
            self.call("POST", "/api/update/download")
            deadline = time.time() + 15
            while time.time() < deadline and self.call("GET", "/api/update/status")[1]["state"] != "ready":
                time.sleep(0.1)
        with mock.patch.object(UpdateManager, "_spawn_helper") as spawn:
            status, data = self.call("POST", "/api/update/apply")
        self.assertEqual((status, data["status"]), (202, "restarting"))
        self.assertEqual(spawn.call_count, 1)
        plan = json.loads((self.root / ".update" / "plan.json").read_text())
        self.assertEqual(plan["to_version"], "99.1.0")
        self.assertEqual(plan["port"], self.httpd.server_address[1])
        self.assertIn("--serve", plan["command"])
        self.assertIsNotNone(activity.maintenance_message())
        activity.unblock()


if __name__ == "__main__":
    unittest.main()


class TestRestartPort(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "TIME_WAIT probing differs on Windows")
    def test_restarted_server_gets_its_old_port_back(self):
        """A server that just exited leaves connections in TIME_WAIT; the restart must still get the same port."""
        import socket

        server = socket.socket()
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        client = socket.create_connection(("127.0.0.1", port))
        conn, _ = server.accept()
        conn.close()   # the side that closes first keeps the TIME_WAIT entry
        client.close()
        server.close()
        self.assertEqual(srv.find_open_port(preferred_port=port), port)
