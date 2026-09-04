"""
Automated Verification Suite for Phase 3: Backend REST API Modernization.
Tests lazy chat loading (/api/chats, /api/chats/<jid>/media), device status, config management,
in-browser ZIP backups, and download streaming.
"""

import json
import os
import shutil
import platform
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import urllib.request
import urllib.parse
import urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT))

import core.server as srv
from core.gallery import generate_gallery


class TestPhase3APIs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp(prefix="wa_test_p3_")
        cls.output_dir = Path(cls.temp_dir) / "output"
        cls.output_dir.mkdir(parents=True, exist_ok=True)

        # Preserve any existing user config and key files
        cls.saved_config = None
        if os.path.exists("config.json"):
            try:
                with open("config.json", "r", encoding="utf-8") as f:
                    cls.saved_config = f.read()
            except Exception:
                pass
        cls.saved_key = None
        if os.path.exists("encrypted_backup.key"):
            try:
                with open("encrypted_backup.key", "rb") as f:
                    cls.saved_key = f.read()
            except Exception:
                pass

        # Create mock organized media and generate sample gallery_data.js
        sample_chat_dir = cls.output_dir / "Alice_Smith" / "2024-05"
        sample_chat_dir.mkdir(parents=True, exist_ok=True)
        sample_file = sample_chat_dir / "IMG-20240501-WA0001.jpg"
        with open(sample_file, "wb") as f:
            f.write(b"SAMPLE_IMAGE_DATA_ALICE")

        sample_items = [
            {
                "chat_jid": "alice@s.whatsapp.net",
                "chat_name": "Alice Smith",
                "filename": "IMG-20240501-WA0001.jpg",
                "rel_path": "Alice_Smith/2024-05/IMG-20240501-WA0001.jpg",
                "size_bytes": 23,
                "mime_type": "image/jpeg",
                "received_at": "2024-05-01T12:00:00",
                "sender_jid": "alice@s.whatsapp.net",
            },
            {
                "chat_jid": "bob@s.whatsapp.net",
                "chat_name": "Bob Jones",
                "filename": "IMG-20240502-WA0002.jpg",
                "rel_path": "Bob_Jones/2024-05/IMG-20240502-WA0002.jpg",
                "size_bytes": 45,
                "mime_type": "image/jpeg",
                "received_at": "2024-05-02T14:00:00",
                "sender_jid": "bob@s.whatsapp.net",
            },
        ]
        generate_gallery(sample_items, str(cls.output_dir))

        cls.port = srv.find_open_port(preferred_port=8860, host="127.0.0.1")

        class BoundHandler(srv.GalleryHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(cls.output_dir), **kwargs)

        cls.httpd = ThreadingHTTPServer(("127.0.0.1", cls.port), BoundHandler)
        cls.server_thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.server_thread.start()
        time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.httpd.shutdown()
            cls.httpd.server_close()
        except Exception:
            pass
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

        # Restore original user config and key files if they were present
        if cls.saved_config is not None:
            try:
                with open("config.json", "w", encoding="utf-8") as f:
                    f.write(cls.saved_config)
            except Exception:
                pass
        elif os.path.exists("config.json"):
            try:
                os.remove("config.json")
            except Exception:
                pass

        if cls.saved_key is not None:
            try:
                with open("encrypted_backup.key", "wb") as f:
                    f.write(cls.saved_key)
            except Exception:
                pass
        elif os.path.exists("encrypted_backup.key"):
            try:
                os.remove("encrypted_backup.key")
            except Exception:
                pass

    def _get(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8")), resp.headers

    def _post(self, path, payload):
        url = f"http://127.0.0.1:{self.port}{path}"
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_01_api_chats_summary(self):
        """Verify GET /api/chats returns compact metadata without media items."""
        status, data, _ = self._get("/api/chats")
        self.assertEqual(status, 200)
        self.assertIn("chats", data)
        chats = data["chats"]
        self.assertEqual(len(chats), 2)

        first = chats[0]
        self.assertIn("jid", first)
        self.assertIn("name", first)
        self.assertIn("total_size", first)
        self.assertIn("file_count", first)
        self.assertNotIn("media", first, "Chats summary must not include full media array")

    def test_02_api_chat_media_and_pagination(self):
        """Verify GET /api/chats/<jid>/media returns media with pagination support."""
        jid = "alice@s.whatsapp.net"
        status, data, _ = self._get(f"/api/chats/{urllib.parse.quote(jid)}/media?offset=0&limit=10")
        self.assertEqual(status, 200)
        self.assertEqual(data["jid"], jid)
        self.assertEqual(data["file_count"], 1)
        self.assertIn("media", data)
        self.assertEqual(len(data["media"]), 1)
        self.assertEqual(data["media"][0]["filename"], "IMG-20240501-WA0001.jpg")

    def test_03_api_device_status(self):
        """Verify GET /api/device-status returns connection metadata."""
        status, data, _ = self._get("/api/device-status")
        self.assertEqual(status, 200)
        self.assertIn("connected", data)
        self.assertIn("authorized", data)

    def test_04_api_config_get_and_post(self):
        """Verify GET /api/config and POST /api/config for key validation and persistence."""
        # 1. Invalid key should return 400
        status, err_resp = self._post("/api/config", {"hex_key": "invalid_too_short"})
        self.assertEqual(status, 400)
        self.assertEqual(err_resp["status"], "error")

        # 2. Valid 64-char key should return 200 with masked key
        valid_key = "1" * 64
        status, ok_resp = self._post("/api/config", {"hex_key": valid_key, "mode": "copy"})
        self.assertEqual(status, 200)
        self.assertEqual(ok_resp["status"], "success")
        self.assertTrue(ok_resp["masked_key"].startswith("1111"))

        # 3. GET /api/config should confirm key is set
        status, get_resp, _ = self._get("/api/config")
        self.assertEqual(status, 200)
        self.assertTrue(get_resp["hex_key_set"])
        self.assertTrue(get_resp["masked_key"].startswith("1111"))

    def test_05_api_backup_chat_and_download(self):
        """Verify POST /api/backup-chat and GET /api/download-backup stream valid ZIP."""
        # Request chat backup
        status, resp = self._post("/api/backup-chat", {"chat_name": "Alice Smith"})
        self.assertEqual(status, 200)
        self.assertEqual(resp["status"], "success")
        self.assertIn("download_url", resp)
        self.assertEqual(resp["file_count"], 1)

        # Download ZIP via returned URL
        dl_url = f"http://127.0.0.1:{self.port}{resp['download_url']}"
        req = urllib.request.Request(dl_url)
        with urllib.request.urlopen(req) as zip_resp:
            self.assertEqual(zip_resp.status, 200)
            self.assertEqual(zip_resp.headers.get("Content-Type"), "application/zip")
            self.assertIn("attachment; filename=", zip_resp.headers.get("Content-Disposition", ""))
            zip_bytes = zip_resp.read()
            self.assertTrue(zip_bytes.startswith(b"PK"), "Downloaded file must be a valid ZIP archive")

    def test_06_api_thumbnail_generation(self):
        """Verify GET /api/thumbnail generates and streams downscaled image thumbnails."""
        from PIL import Image
        test_img_path = self.output_dir / "Alice_Smith" / "2024-05" / "test_real_img.jpg"
        im = Image.new("RGB", (400, 300), color=(16, 185, 129))
        im.save(test_img_path, format="JPEG")

        # Request thumbnail
        rel_param = urllib.parse.quote("Alice_Smith/2024-05/test_real_img.jpg")
        url = f"http://127.0.0.1:{self.port}/api/thumbnail?path={rel_param}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.headers.get("Content-Type"), "image/jpeg")
            self.assertIn("immutable", resp.headers.get("Cache-Control", ""))
            data = resp.read()
            self.assertTrue(len(data) > 0)

        # Missing path parameter should return 400
        url_err = f"http://127.0.0.1:{self.port}/api/thumbnail"
        req_err = urllib.request.Request(url_err)
        try:
            urllib.request.urlopen(req_err)
            self.fail("Expected HTTP 400 for missing path")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)

    @mock.patch("core.server.disable_developer_options")
    def test_07_api_disable_developer_options(self, mock_disable):
        """Verify POST /api/disable-developer-options invokes ADB and returns proper status."""
        # 1. Success case
        mock_disable.return_value = (True, "Developer Options has been disabled on your device.")
        status, resp = self._post("/api/disable-developer-options", {})
        self.assertEqual(status, 200)
        self.assertEqual(resp["status"], "success")
        self.assertIn("disabled", resp["message"])

        # 2. Error case
        mock_disable.return_value = (False, "Device unauthorized")
        status, resp = self._post("/api/disable-developer-options", {})
        self.assertEqual(status, 500)
        self.assertEqual(resp["status"], "error")
        self.assertIn("unauthorized", resp["message"])

    def test_08_api_sync_pause_resume_cancel(self):
        """Verify POST /api/sync/pause, /api/sync/resume, and /api/sync/cancel endpoints."""
        # 1. Pause when no sync is active should return 400
        status, resp = self._post("/api/sync/pause", {})
        self.assertEqual(status, 400)
        self.assertEqual(resp["status"], "error")

        # 2. Cancel should cleanly succeed and reset state
        status, resp = self._post("/api/sync/cancel", {})
        self.assertEqual(status, 200)
        self.assertEqual(resp["status"], "cancelled")

        # 3. GET /api/sync-status
        status, data, _ = self._get("/api/sync-status")
        self.assertEqual(status, 200)
        self.assertIn("status", data)
        self.assertIn("can_resume", data)

    @mock.patch("core.server.load_config")
    @mock.patch("core.server.check_adb_device")
    def test_09_api_sync_preflight_checks(self, mock_device, mock_config):
        """Verify pre-flight guards for disconnected device and missing encryption key."""
        from core.adb import DeviceStatus

        # Case A: Device disconnected
        mock_device.return_value = DeviceStatus(False, False, "No device", None, None, False)
        status, resp = self._post("/api/sync", {})
        self.assertEqual(status, 400)
        self.assertEqual(resp["status"], "device_disconnected")

        # Case B: Device connected but unauthorized
        mock_device.return_value = DeviceStatus(True, False, "Unauthorized", "serial_1", "Pixel", True)
        status, resp = self._post("/api/sync", {})
        self.assertEqual(status, 400)
        self.assertEqual(resp["status"], "device_unauthorized")

        # Case C: Device connected & authorized, but NO key configured
        mock_device.return_value = DeviceStatus(True, True, "", "serial_1", "Pixel", True)
        mock_config.return_value = {"hex_key": "", "key_file": "non_existent_key.key"}
        status, resp = self._post("/api/sync", {})
        self.assertEqual(status, 400)
        self.assertEqual(resp["status"], "key_required")
        self.assertIn("64-character", resp["message"])

    def test_10_api_sync_cancel_clean_state(self):
        """Verify that cancelling sync immediately transitions state to idle and does not revert to paused."""
        srv.sync_status["active"] = True
        srv.sync_status["status"] = "syncing"
        srv.sync_status["phase"] = "syncing"
        srv.sync_status["session_id"] = "test-cancel-session-123"

        status, resp = self._post("/api/sync/cancel", {})
        self.assertEqual(status, 200)
        self.assertEqual(resp["status"], "cancelled")

        # Verify state is idle and can_resume is False
        status, st, _ = self._get("/api/sync-status")
        self.assertEqual(status, 200)
        self.assertEqual(st["status"], "idle")
        self.assertEqual(st["phase"], "idle")
        self.assertFalse(st["can_resume"])
        self.assertFalse(st["active"])

    def test_11_api_config_skip_db_pull(self):
        """Verify that skip_db_pull is not persisted in config, has_local_db is reported, and skip-db works."""
        # 1. Posting skip_db_pull should NOT persist it into config.json
        status, resp = self._post("/api/config", {"skip_db_pull": True})
        self.assertEqual(status, 200)

        status, cfg, _ = self._get("/api/config")
        self.assertEqual(status, 200)
        self.assertNotIn("skip_db_pull", cfg)
        self.assertIn("has_local_db", cfg)
        self.assertIsInstance(cfg["has_local_db"], bool)

        # 2. Check that GET /api/sync-status also returns has_local_db
        status, st, _ = self._get("/api/sync-status")
        self.assertEqual(status, 200)
        self.assertIn("has_local_db", st)
        self.assertIsInstance(st["has_local_db"], bool)

        # 3. POST /api/sync/skip-db should return 400 when sync is idle
        status, skip_err = self._post("/api/sync/skip-db", {})
        self.assertEqual(status, 400)

        # 4. If sync is actively in database phase, /api/sync/skip-db should succeed
        srv.sync_status["active"] = True
        srv.sync_status["phase"] = "database"
        try:
            status, skip_ok = self._post("/api/sync/skip-db", {})
            self.assertEqual(status, 200)
            self.assertEqual(skip_ok["status"], "skipped")
            self.assertTrue(srv._sync_skip_db_token.is_set())
        finally:
            srv.sync_status["active"] = False
            srv.sync_status["phase"] = "idle"
            srv._sync_skip_db_token.clear()

    def test_09_open_folder_api(self):
        # 1. Missing rel_path -> 400
        url = f"http://127.0.0.1:{self.port}/api/open-folder"
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(url)
        self.assertEqual(ctx.exception.code, 400)

        # 2. Directory traversal attempt -> 403
        bad_url = f"http://127.0.0.1:{self.port}/api/open-folder?rel_path=../../outside.txt"
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(bad_url)
        self.assertEqual(ctx.exception.code, 403)

        # 3. Non-existent file -> 404
        missing_url = f"http://127.0.0.1:{self.port}/api/open-folder?rel_path=Alice_Smith/nonexistent.jpg"
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(missing_url)
        self.assertEqual(ctx.exception.code, 404)

        # 4. Existing file -> 200 and triggers explorer /select
        target_rel = "Alice_Smith/2024-05/IMG-20240501-WA0001.jpg"
        ok_url = f"http://127.0.0.1:{self.port}/api/open-folder?rel_path={urllib.parse.quote(target_rel)}"
        with mock.patch("subprocess.Popen") as mock_popen:
            req = urllib.request.Request(ok_url)
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 200)
                self.assertEqual(resp.read(), b"OK")
            self.assertTrue(mock_popen.called)
            called_cmd = mock_popen.call_args[0][0]
            if platform.system() == "Windows":
                self.assertIsInstance(called_cmd, str)
                self.assertTrue(called_cmd.startswith("explorer /select,\""))
                self.assertTrue(called_cmd.endswith(".jpg\""))

    def test_10_api_chats_live_cache_update(self):
        """Verify update_gallery_data_live updates in-memory cache and /api/chats reflects new storage immediately."""
        from core.gallery import update_gallery_data_live
        new_item = {
            "chat_jid": "alice@s.whatsapp.net",
            "chat_name": "Alice Smith",
            "filename": "IMG-20240501-WA0002.jpg",
            "rel_path": "Alice_Smith/2024-05/IMG-20240501-WA0002.jpg",
            "size_bytes": 1000,
            "mime_type": "image/jpeg",
            "received_at": "2024-05-01T15:00:00",
            "sender_jid": "alice@s.whatsapp.net",
        }
        added = update_gallery_data_live([new_item], str(self.output_dir))
        self.assertEqual(added, 1)

        status, data, _ = self._get("/api/chats")
        self.assertEqual(status, 200)
        alice = next(c for c in data["chats"] if c["jid"] == "alice@s.whatsapp.net")
        self.assertEqual(alice["file_count"], 2)
        self.assertEqual(alice["total_size"], 1023)

    def test_11_normalize_filename_trailing_dots(self):
        """Verify trailing dots and spaces from Android WhatsApp filenames are stripped cleanly."""
        from core.organizer import normalize_filename
        # Trailing dot (common in WhatsApp Android raw audio/doc names)
        self.assertEqual(normalize_filename("AUD-20241213-WA0034."), "aud-20241213-wa0034")
        self.assertEqual(normalize_filename("DOC-20260418-WA0011."), "doc-20260418-wa0011")
        # Duplicate counters stripped
        self.assertEqual(normalize_filename("photo_dup1.jpg", strip_dup_suffix=True), "photo.jpg")
        self.assertEqual(normalize_filename("report-2.pdf", strip_dup_suffix=True), "report.pdf")

    def test_12_build_already_pulled_index_cross_referencing(self):
        """Verify build_already_pulled_index indexes disk files, duplicate stripped stems, and media_index.csv."""
        from core.adb import build_already_pulled_index
        import csv

        test_out = Path(self.temp_dir) / "test_index_output"
        test_out.mkdir(parents=True, exist_ok=True)
        chat_folder = test_out / "TestChat" / "2026-04"
        chat_folder.mkdir(parents=True, exist_ok=True)

        # 1. Physical file on disk (e.g. renamed document)
        doc_file = chat_folder / "RenamedSolution.pdf"
        doc_file.write_bytes(b"A" * 500)

        # 2. Write media_index.csv mapping original phone path to renamed file
        csv_p = test_out / "media_index.csv"
        with open(csv_p, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["chat_jid", "chat_name", "filename", "rel_path", "phone_path", "size_bytes"])
            writer.writeheader()
            writer.writerow({
                "chat_jid": "test@s.whatsapp.net",
                "chat_name": "TestChat",
                "filename": "RenamedSolution.pdf",
                "rel_path": "TestChat/2026-04/RenamedSolution.pdf",
                "phone_path": "Media/WhatsApp Documents/Private/DOC-20241021-WA0026.pdf",
                "size_bytes": "500"
            })

        pulled = build_already_pulled_index(str(test_out))
        # Verify physical file is indexed
        self.assertIn(("renamedsolution.pdf", 500), pulled)
        # Verify mapped phone filename from media_index.csv is indexed
        self.assertIn(("doc-20241021-wa0026.pdf", 500), pulled)


if __name__ == "__main__":
    unittest.main(verbosity=2)


