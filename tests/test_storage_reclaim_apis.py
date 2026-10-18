"""
Automated Verification Suite for Storage Reclaim & Restore REST Endpoints:
- GET /api/phone/storage
- POST /api/clean/plan
- POST /api/clean/execute
- POST /api/restore/chat
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest import mock
import urllib.request
import urllib.parse
import urllib.error
from http.server import ThreadingHTTPServer

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT))

import core.server as srv
from core.gallery import generate_gallery
from core.clean_planner import CleanProfile


class TestStorageReclaimAPIs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp(prefix="wa_test_reclaim_apis_")
        cls.output_dir = Path(cls.temp_dir) / "output"
        cls.output_dir.mkdir(parents=True, exist_ok=True)

        # Create mock organized media files
        alice_dir = cls.output_dir / "Alice_Smith" / "2024-05"
        alice_dir.mkdir(parents=True, exist_ok=True)
        img_file = alice_dir / "IMG-20240501-WA0001.jpg"
        with open(img_file, "wb") as f:
            f.write(b"SAMPLE_IMAGE_ALICE")

        video_dir = cls.output_dir / "Old_Group" / "2024-01"
        video_dir.mkdir(parents=True, exist_ok=True)
        vid_file = video_dir / "VID-20240101-WA0002.mp4"
        with open(vid_file, "wb") as f:
            f.write(b"V" * 1024 * 100)  # 100KB

        sample_items = [
            {
                "chat_jid": "alice@s.whatsapp.net",
                "chat_name": "Alice Smith",
                "filename": "IMG-20240501-WA0001.jpg",
                "rel_path": "Alice_Smith/2024-05/IMG-20240501-WA0001.jpg",
                "phone_path": "/storage/emulated/0/WhatsApp/Media/WhatsApp Images/IMG-20240501-WA0001.jpg",
                "size_bytes": 18,
                "mime_type": "image/jpeg",
                "received_at": "2024-05-01 12:00:00",
                "sender_jid": "alice@s.whatsapp.net",
                "starred": 0,
                "chat_archived": 0,
                "chat_last_active_ts": 1714564800000,
            },
            {
                "chat_jid": "oldgroup@g.us",
                "chat_name": "Old Group",
                "filename": "VID-20240101-WA0002.mp4",
                "rel_path": "Old_Group/2024-01/VID-20240101-WA0002.mp4",
                "phone_path": "/storage/emulated/0/WhatsApp/Media/WhatsApp Video/VID-20240101-WA0002.mp4",
                "size_bytes": 1024 * 100,
                "mime_type": "video/mp4",
                "received_at": "2024-01-01 10:00:00",
                "sender_jid": "friend@s.whatsapp.net",
                "starred": 0,
                "chat_archived": 0,
                "chat_last_active_ts": 1704100000000,  # long inactive
            },
        ]
        generate_gallery(sample_items, str(cls.output_dir))

        cls.port = srv.find_open_port(preferred_port=8870, host="127.0.0.1")

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

    def test_01_api_phone_storage(self):
        """Verify GET /api/phone/storage calls get_device_storage_info and returns storage metrics."""
        with mock.patch("core.server.get_device_storage_info") as mock_storage:
            mock_storage.return_value = {
                "success": True,
                "free_bytes": 35666132 * 1024,
                "total_bytes": 121087132 * 1024,
                "free_gb": 34.0,
                "total_gb": 115.5,
                "percent_used": 70.5,
                "error": None,
            }
            status, data, _ = self._get("/api/phone/storage")
            self.assertEqual(status, 200)
            self.assertEqual(data["status"], "success")
            self.assertIn("storage", data)
            self.assertEqual(data["storage"]["free_gb"], 34.0)
            self.assertEqual(data["storage"]["percent_used"], 70.5)

    def test_02_api_clean_plan_generation(self):
        """Verify POST /api/clean/plan creates a 3-point verified clean plan."""
        # 1. Invalid profile should error
        status, err_data = self._post("/api/clean/plan", {"profile": "invalid_mode"})
        self.assertEqual(status, 400)

        # 2. Video offload profile
        status, data = self._post("/api/clean/plan", {"profile": "video_offload"})
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "success")
        self.assertIn("plan", data)
        plan = data["plan"]
        self.assertIn("plan_id", plan)
        self.assertEqual(plan["profile"], "video_offload")
        self.assertIn("reclaimable_files_count", plan)
        self.assertIn("breakdown", plan)

        # 3. Store plan_id for execution test
        self.__class__.created_plan_id = plan["plan_id"]

    def test_03_api_clean_plan_execution(self):
        """Verify POST /api/clean/execute executes the generated plan."""
        # 1. Missing plan_id
        status, err = self._post("/api/clean/execute", {})
        self.assertEqual(status, 400)

        # 2. Non-existent plan_id
        status, not_found = self._post("/api/clean/execute", {"plan_id": "missing-uuid-1234"})
        self.assertEqual(status, 404)

        # 3. Valid plan_id execution
        plan_id = getattr(self.__class__, "created_plan_id", None)
        self.assertIsNotNone(plan_id)

        with mock.patch("core.server.check_adb_device") as mock_dev, \
             mock.patch("core.server.execute_clean_plan") as mock_exec:
            mock_dev.return_value = mock.Mock(connected=True, authorized=True)
            mock_exec.return_value = {
                "success": True,
                "deleted_count": 1,
                "failed_count": 0,
                "freed_bytes": 102400,
                "errors": [],
            }
            status, exec_res = self._post("/api/clean/execute", {"plan_id": plan_id})
            self.assertEqual(status, 200)
            self.assertEqual(exec_res["status"], "success")
            self.assertEqual(exec_res["result"]["deleted_count"], 1)

    def test_04_api_restore_chat(self):
        """Verify POST /api/restore/chat triggers safe chat media restoration."""
        # 1. Missing chat_jid
        status, err = self._post("/api/restore/chat", {})
        self.assertEqual(status, 400)

        # 2. Valid chat_jid
        with mock.patch("core.server.check_adb_device") as mock_dev, \
             mock.patch("core.server.restore_chat_to_phone") as mock_restore:
            mock_dev.return_value = mock.Mock(connected=True, authorized=True)
            mock_restore.return_value = {
                "success": True,
                "restored_count": 1,
                "total_attempted": 1,
                "restored_bytes": 18,
                "errors": [],
            }
            status, res = self._post("/api/restore/chat", {"chat_jid": "alice@s.whatsapp.net"})
            self.assertEqual(status, 200)
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["result"]["restored_count"], 1)

    def test_05_api_restore_cancel(self):
        """Verify POST /api/restore/cancel requests cancellation."""
        status, res = self._post("/api/restore/cancel", {})
        self.assertEqual(status, 200)
        self.assertEqual(res["status"], "success")
        self.assertIn("cancellation", res["message"].lower())


if __name__ == "__main__":
    unittest.main()
