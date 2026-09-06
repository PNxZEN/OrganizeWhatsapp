"""
Automated unit tests for tutorial endpoints and offline USB key transfer portal.
"""

import json
import os
import shutil
import tempfile
import unittest
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread

from core.server import GalleryHTTPRequestHandler, ThreadingHTTPServer
from core.config import save_config, DEFAULT_CONFIG_FILE


class TestTutorialAPIs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="wa_test_tutorial_")
        cls.out_dir = Path(cls.test_dir) / "output"
        cls.out_dir.mkdir(parents=True, exist_ok=True)
        (cls.out_dir / "gallery.html").write_text("<html>Test</html>", encoding="utf-8")

        # Copy tutorial assets to out_dir for static fallback testing
        core_assets = Path(__file__).parent.parent / "core" / "assets" / "tutorial"
        if core_assets.exists():
            shutil.copytree(core_assets, cls.out_dir / "assets" / "tutorial", dirs_exist_ok=True)

        class CustomHandler(GalleryHTTPRequestHandler):
            output_dir = cls.out_dir

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), CustomHandler)
        cls.port = cls.server.server_port
        cls.server_thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_01_get_paste_key_page(self):
        conn = HTTPConnection("127.0.0.1", self.port)
        conn.request("GET", "/paste-key")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        self.assertIn("text/html", resp.getheader("Content-Type", ""))
        body = resp.read().decode("utf-8")
        self.assertIn("Send 64-Digit Key to PC", body)
        self.assertIn("handlePasteFromClipboard", body)
        self.assertIn("onKeyChange", body)

    def test_02_get_tutorial_assets(self):
        conn = HTTPConnection("127.0.0.1", self.port)
        for i in range(12):
            asset_path = f"/assets/tutorial/wa_step{i}.webp"
            conn.request("GET", asset_path)
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200, f"Failed to fetch {asset_path}")
            self.assertIn("image/webp", resp.getheader("Content-Type", ""))
            data = resp.read()
            self.assertGreater(len(data), 1000, f"Asset {asset_path} is empty or too small")

    def test_03_get_phone_oem(self):
        conn = HTTPConnection("127.0.0.1", self.port)
        conn.request("GET", "/api/phone/oem")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        data = json.loads(resp.read().decode("utf-8"))
        self.assertIn("oem_key", data)
        self.assertIn("brand", data)

    def test_04_submit_key_invalid(self):
        conn = HTTPConnection("127.0.0.1", self.port)
        conn.request("POST", "/api/submit-key", body=json.dumps({"hex_key": "short123"}), headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 400)

    def test_05_submit_key_valid(self):
        test_key = "a" * 64
        conn = HTTPConnection("127.0.0.1", self.port)
        conn.request("POST", "/api/submit-key", body=json.dumps({"hex_key": test_key}), headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        res = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(res.get("status"), "success")

        # Check key-status: key is staged in memory, NOT auto-saved to config.json!
        conn.request("GET", "/api/key-status")
        resp2 = conn.getresponse()
        self.assertEqual(resp2.status, 200)
        res2 = json.loads(resp2.read().decode("utf-8"))
        self.assertEqual(res2.get("latest_received_key"), test_key)
        self.assertEqual(res2.get("received_key"), test_key)
        # Verify that submitting key did not persist it as active hex_key in config
        from core.config import load_config
        self.assertNotEqual(load_config().get("hex_key"), test_key)

    def test_06_onboarding_complete(self):
        conn = HTTPConnection("127.0.0.1", self.port)
        conn.request("POST", "/api/onboarding/complete", body=b"{}", headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)

    def test_07_delete_key(self):
        test_key = "b" * 64
        conn = HTTPConnection("127.0.0.1", self.port)
        # First save key via /api/config
        conn.request("POST", "/api/config", body=json.dumps({"hex_key": test_key}), headers={"Content-Type": "application/json"})
        resp0 = conn.getresponse()
        self.assertEqual(resp0.status, 200)

        # Verify key is configured
        conn.request("GET", "/api/key-status")
        self.assertTrue(json.loads(conn.getresponse().read().decode("utf-8")).get("hex_key_set"))

        # Delete key via /api/delete-key
        conn.request("POST", "/api/delete-key", body=b"{}", headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        res = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(res.get("status"), "success")
        self.assertEqual(res.get("masked_key"), "")

        # Verify key-status reflects deleted key
        conn.request("GET", "/api/key-status")
        resp2 = conn.getresponse()
        self.assertEqual(resp2.status, 200)
        res2 = json.loads(resp2.read().decode("utf-8"))
        self.assertFalse(res2.get("hex_key_set"))
        self.assertIsNone(res2.get("latest_received_key"))
        self.assertFalse(os.path.exists("encrypted_backup.key"))

    def test_08_clear_received_key(self):
        test_key = "c" * 64
        conn = HTTPConnection("127.0.0.1", self.port)
        conn.request("POST", "/api/submit-key", body=json.dumps({"hex_key": test_key}), headers={"Content-Type": "application/json"})
        self.assertEqual(conn.getresponse().status, 200)

        # Clear staged received key
        conn.request("POST", "/api/phone/clear-received-key", body=b"{}", headers={"Content-Type": "application/json"})
        self.assertEqual(conn.getresponse().status, 200)

        # Verify key-status has None
        conn.request("GET", "/api/key-status")
        res = json.loads(conn.getresponse().read().decode("utf-8"))
        self.assertIsNone(res.get("latest_received_key"))
        self.assertIsNone(res.get("received_key"))


if __name__ == "__main__":
    unittest.main()
