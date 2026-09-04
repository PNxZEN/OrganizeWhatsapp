"""
Verification test for local server video streaming and API responses.
Starts ThreadingHTTPServer on an ephemeral port, sends requests, verifies HTTP 206, then stops.
"""

import threading
import time
import unittest
import urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(WORKSPACE_ROOT))

import core.server as srv
import urllib.parse


class TestServerStreaming(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output_dir = Path("./output").resolve()
        cls.port = srv.find_open_port(preferred_port=8850, host="127.0.0.1")

        class BoundHandler(srv.GalleryHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(cls.output_dir), **kwargs)

        cls.httpd = ThreadingHTTPServer(("127.0.0.1", cls.port), BoundHandler)
        cls.server_thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.server_thread.start()
        time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_01_health_endpoint(self):
        url = f"http://127.0.0.1:{self.port}/api/health"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = resp.read().decode("utf-8")
            self.assertIn("ok", data)

    def test_02_sync_status_endpoint(self):
        url = f"http://127.0.0.1:{self.port}/api/sync-status"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = resp.read().decode("utf-8")
            self.assertIn("phase", data)

    def test_03_gallery_html_served(self):
        url = f"http://127.0.0.1:{self.port}/gallery.html"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/html", resp.headers.get("Content-Type", ""))

    def test_04_range_request_streaming(self):
        # Find a real media file in output
        sample_file = None
        for p in self.output_dir.rglob("*.mp4"):
            if p.is_file() and p.stat().st_size > 1024:
                sample_file = p
                break

        if not sample_file:
            self.skipTest("No MP4 file found in output for range test")

        rel_path = sample_file.relative_to(self.output_dir).as_posix()
        url = f"http://127.0.0.1:{self.port}/{urllib.parse.quote(rel_path)}"

        # Send Range request: first 500 bytes
        req = urllib.request.Request(url, headers={"Range": "bytes=0-499"})
        try:
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 206)
                self.assertEqual(len(resp.read()), 500)
                self.assertIn("bytes 0-499/", resp.headers.get("Content-Range", ""))
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 206)


    def test_05_heartbeat_and_tab_closed(self):
        import json
        url_hb = f"http://127.0.0.1:{self.port}/api/heartbeat"
        data_a = json.dumps({"tab_id": "test_tab_a"}).encode("utf-8")
        req_a = urllib.request.Request(url_hb, data=data_a, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req_a) as resp:
            self.assertEqual(resp.status, 200)
            res = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(res["status"], "ok")
            self.assertGreaterEqual(res["active_tabs"], 1)

        data_b = json.dumps({"tab_id": "test_tab_b"}).encode("utf-8")
        req_b = urllib.request.Request(url_hb, data=data_b, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req_b) as resp:
            self.assertEqual(resp.status, 200)
            res = json.loads(resp.read().decode("utf-8"))
            self.assertGreaterEqual(res["active_tabs"], 2)

        url_close = f"http://127.0.0.1:{self.port}/api/tab-closed"
        req_close_a = urllib.request.Request(url_close, data=data_a, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req_close_a) as resp:
            self.assertEqual(resp.status, 200)
            res = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(res["status"], "tab_closed")
            self.assertGreaterEqual(res["remaining_tabs"], 1)


if __name__ == "__main__":
    unittest.main()

