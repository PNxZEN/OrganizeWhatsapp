"""
Unit test suite for Duplicate Recycle Bin and Staged Quarantine features.
"""

import json
import os
import shutil
import tempfile
import unittest
import urllib.parse
import urllib.request
from pathlib import Path

from gallery_sources import read_gallery_bundle

from core.gallery import (
    list_recycled_items,
    recycle_media_items,
    restore_media_items,
)


class TestDuplicateRecycle(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="wa_test_recycle_")
        self.out_path = Path(self.tmp_dir)

        # Create dummy chat folder structure
        self.chat_dir = self.out_path / "Test_Chat" / "2025-09"
        self.chat_dir.mkdir(parents=True, exist_ok=True)

        self.primary_file = self.chat_dir / "IMG-20250915-WA0040.jpg"
        self.primary_file.write_bytes(b"X" * 1000)

        self.duplicate_file = self.chat_dir / "IMG-20250915-WA0038.jpg"
        self.duplicate_file.write_bytes(b"Y" * 200)

        self.dup_rel = "Test_Chat/2025-09/IMG-20250915-WA0038.jpg"
        self.prim_rel = "Test_Chat/2025-09/IMG-20250915-WA0040.jpg"

        # Create dummy gallery_data.js
        gallery_data = {
            "chats": [
                {
                    "jid": "123@s.whatsapp.net",
                    "name": "Test_Chat",
                    "total_size": 1200,
                    "file_count": 2,
                    "media": [
                        {
                            "filename": "IMG-20250915-WA0040.jpg",
                            "rel_path": self.prim_rel,
                            "size_bytes": 1000,
                            "is_duplicate": False,
                        },
                        {
                            "filename": "IMG-20250915-WA0038.jpg",
                            "rel_path": self.dup_rel,
                            "size_bytes": 200,
                            "is_duplicate": True,
                            "duplicate_primary": "IMG-20250915-WA0040.jpg",
                        },
                    ],
                }
            ]
        }
        with open(self.out_path / "gallery_data.js", "w", encoding="utf-8") as f:
            f.write(f"const GALLERY_DATA = {json.dumps(gallery_data)};")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_01_recycle_and_restore_cycle(self):
        """Verify recycling moves file to staged quarantine and updating gallery_data.js."""
        res = recycle_media_items(self.out_path, [self.dup_rel])
        self.assertEqual(res.get("status"), "success")
        self.assertEqual(res.get("recycled_count"), 1)
        self.assertEqual(res.get("reclaimed_bytes"), 200)

        # Original file should no longer exist in chat folder
        self.assertFalse(self.duplicate_file.exists())
        self.assertTrue(self.primary_file.exists())

        # Recycled file should exist in .duplicates_recycle_bin
        recycled_file = self.out_path / ".duplicates_recycle_bin" / self.dup_rel
        self.assertTrue(recycled_file.exists())

        # Check list_recycled_items
        items = list_recycled_items(self.out_path)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["filename"], "IMG-20250915-WA0038.jpg")

        # Check gallery_data.js
        with open(self.out_path / "gallery_data.js", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("IMG-20250915-WA0038.jpg", content)
        self.assertIn("IMG-20250915-WA0040.jpg", content)

        # Restore file
        restore_res = restore_media_items(self.out_path, [self.dup_rel])
        self.assertEqual(restore_res.get("status"), "success")
        self.assertEqual(restore_res.get("restored_count"), 1)

        # File should be back in original place
        self.assertTrue(self.duplicate_file.exists())
        self.assertFalse(recycled_file.exists())

    def test_02_server_recycle_apis(self):
        """Verify /api/duplicates/recycle-bin, /api/duplicates/recycle, and /api/duplicates/restore."""
        import core.server as srv
        import urllib.request
        from http.server import ThreadingHTTPServer
        import threading
        import time

        port = srv.find_open_port(preferred_port=8895, host="127.0.0.1")

        class BoundHandler(srv.GalleryHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(self.out_path), **kwargs)

        out_path = self.out_path
        class TestBoundHandler(srv.GalleryHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(out_path), **kwargs)

        httpd = ThreadingHTTPServer(("127.0.0.1", port), TestBoundHandler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.3)

        try:
            # 1. GET /api/duplicates/recycle-bin (should be empty initially)
            url_list = f"http://127.0.0.1:{port}/api/duplicates/recycle-bin"
            req = urllib.request.Request(url_list)
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data.get("status"), "success")
                self.assertEqual(len(data.get("items", [])), 0)

            # 2. POST /api/duplicates/recycle
            url_recycle = f"http://127.0.0.1:{port}/api/duplicates/recycle"
            payload = json.dumps({"rel_paths": [self.dup_rel]}).encode("utf-8")
            req = urllib.request.Request(url_recycle, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data.get("status"), "success")
                self.assertEqual(data.get("recycled_count"), 1)

            # 3. GET /api/duplicates/recycle-bin (should have 1 item now)
            req = urllib.request.Request(url_list)
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(len(data.get("items", [])), 1)

            # 4. POST /api/duplicates/restore
            url_restore = f"http://127.0.0.1:{port}/api/duplicates/restore"
            payload = json.dumps({"rel_paths": [self.dup_rel]}).encode("utf-8")
            req = urllib.request.Request(url_restore, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data.get("status"), "success")
                self.assertEqual(data.get("restored_count"), 1)

            # File restored
            self.assertTrue(self.duplicate_file.exists())

            # 5. Recycle again and test /api/duplicates/empty-recycle-bin
            req = urllib.request.Request(url_recycle, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data.get("recycled_count"), 1)

            url_empty = f"http://127.0.0.1:{port}/api/duplicates/empty-recycle-bin"
            req = urllib.request.Request(url_empty, data=b"{}", headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data.get("status"), "success")
                self.assertEqual(data.get("deleted_count"), 1)

            # Check GET /api/duplicates/recycle-bin is now empty
            req = urllib.request.Request(url_list)
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(len(data.get("items", [])), 0)
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_03_unicode_backup_download_and_cancellation(self):
        """Verify downloading backups with Unicode filenames (\u2026) and cancelling backups."""
        import core.server as srv
        from http.server import ThreadingHTTPServer
        import threading
        import time

        port = srv.find_open_port(preferred_port=8896, host="127.0.0.1")
        out_path = self.out_path
        class TestBoundHandler(srv.GalleryHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(out_path), **kwargs)

        httpd = ThreadingHTTPServer(("127.0.0.1", port), TestBoundHandler)
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        time.sleep(0.3)

        try:
            # 1. Create a dummy backup file with Unicode ellipsis (\u2026)
            backups_dir = self.out_path / "backups"
            backups_dir.mkdir(parents=True, exist_ok=True)
            unicode_name = "Andi mandi shandi , jisne photo nahi bheje vo\u2026_20261008_065007.zip"
            test_zip = backups_dir / unicode_name
            test_zip.write_bytes(b"PK\x03\x04" + b"dummy_zip_content")

            # 2. GET /api/download-backup with urlencoded Unicode filename
            enc_file = urllib.parse.quote(unicode_name)
            url_dl = f"http://127.0.0.1:{port}/api/download-backup?file={enc_file}"
            req = urllib.request.Request(url_dl)
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 200)
                self.assertEqual(resp.headers.get("Content-Type"), "application/zip")
                cd = resp.headers.get("Content-Disposition", "")
                self.assertIn("filename*=", cd)
                self.assertIn("UTF-8''", cd)
                data = resp.read()
                self.assertTrue(data.startswith(b"PK\x03\x04"))

            # 3. POST /api/backup/cancel
            url_cancel = f"http://127.0.0.1:{port}/api/backup/cancel"
            req_c = urllib.request.Request(url_cancel, data=b"{}", headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req_c) as resp:
                self.assertEqual(resp.status, 200)
                res = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(res.get("status"), "cancelled")
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_04_kept_both_elements_and_undo_handlers(self):
        """Verify Keep Both reversibility elements, tabs, and undo handlers in gallery.html."""
        gallery_path = Path(__file__).resolve().parent.parent / "gallery.html"
        self.assertTrue(gallery_path.exists())
        content = read_gallery_bundle()

        # HTML elements
        self.assertIn('id="tabBtnIgnored"', content)
        self.assertIn('id="dupViewIgnored"', content)
        self.assertIn('id="ignoredTabCount"', content)
        self.assertIn('id="ignoredTotalCount"', content)
        self.assertIn('id="btnResetAllIgnored"', content)
        self.assertIn('id="ignoredList"', content)
        self.assertIn('id="btnDupCmpUndo"', content)

        # JavaScript functions
        self.assertIn("function undoDismissDuplicate(", content)
        self.assertIn("function updateDupUndoButtonUI(", content)
        self.assertIn("function renderIgnoredPairsContent(", content)
        self.assertIn("function restoreIgnoredDupItem(", content)
        self.assertIn("function executeResetAllIgnored(", content)
        self.assertIn("function applyFiltersAndRender(", content)

        # Keyboard shortcuts
        self.assertIn("(e.key === 'z' || e.key === 'Z')", content)

        # Zero banned characters
    def test_05_video_duplicate_detection_backend(self):
        """Verify video duplicate detection: exact MD5, collision, WhatsApp quality pairs, and cross-media isolation."""
        from core.duplicates import detect_quality_duplicates

        # 1. Exact MD5 video duplicate
        items = [
            {
                "filename": "VID-20250915-WA0001.mp4",
                "rel_path": "chat1/VID-20250915-WA0001.mp4",
                "size_bytes": 5000000,
                "width": 1920,
                "height": 1080,
                "media_duration": 15.0,
                "md5": "abc123vid",
                "chat_jid": "chat1@s.whatsapp.net",
                "mime_type": "video/mp4",
            },
            {
                "filename": "VID-20250915-WA0001_dup1.mp4",
                "rel_path": "chat1/VID-20250915-WA0001_dup1.mp4",
                "size_bytes": 5000000,
                "width": 1920,
                "height": 1080,
                "media_duration": 15.0,
                "md5": "abc123vid",
                "chat_jid": "chat1@s.whatsapp.net",
                "mime_type": "video/mp4",
            },
        ]
        detect_quality_duplicates(items, str(self.out_path))
        dup = next(it for it in items if it["filename"] == "VID-20250915-WA0001_dup1.mp4")
        prim = next(it for it in items if it["filename"] == "VID-20250915-WA0001.mp4")
        self.assertTrue(dup["is_duplicate"])
        self.assertFalse(prim["is_duplicate"])
        self.assertEqual(dup["duplicate_primary"], prim["filename"])
        self.assertEqual(dup["duplicate_reason"], "exact")

        # 2. WhatsApp video quality pair (close counters, matching duration <= 0.5s, size ratio >= 1.25x)
        items_wa = [
            {
                "filename": "VID-20250915-WA0010.mp4",
                "rel_path": "chat2/VID-20250915-WA0010.mp4",
                "size_bytes": 10000000,
                "width": 1920,
                "height": 1080,
                "media_duration": 20.0,
                "chat_jid": "chat2@s.whatsapp.net",
                "mime_type": "video/mp4",
            },
            {
                "filename": "VID-20250915-WA0011.mp4",
                "rel_path": "chat2/VID-20250915-WA0011.mp4",
                "size_bytes": 4000000,
                "width": 848,
                "height": 480,
                "media_duration": 20.1,
                "chat_jid": "chat2@s.whatsapp.net",
                "mime_type": "video/mp4",
            },
        ]
        detect_quality_duplicates(items_wa, str(self.out_path))
        prim_wa = next(it for it in items_wa if it["filename"] == "VID-20250915-WA0010.mp4")
        dup_wa = next(it for it in items_wa if it["filename"] == "VID-20250915-WA0011.mp4")
        self.assertTrue(dup_wa["is_duplicate"])
        self.assertFalse(prim_wa["is_duplicate"])
        self.assertEqual(dup_wa["duplicate_primary"], "VID-20250915-WA0010.mp4")
        self.assertEqual(dup_wa["duplicate_reason"], "quality")

        # 3. Guard: Distinct videos recorded on same day (different duration > 0.5s) must NOT cluster
        items_diff = [
            {
                "filename": "VID-20250915-WA0020.mp4",
                "rel_path": "chat3/VID-20250915-WA0020.mp4",
                "size_bytes": 10000000,
                "media_duration": 12.0,
                "chat_jid": "chat3@s.whatsapp.net",
                "mime_type": "video/mp4",
            },
            {
                "filename": "VID-20250915-WA0021.mp4",
                "rel_path": "chat3/VID-20250915-WA0021.mp4",
                "size_bytes": 4000000,
                "media_duration": 45.0,  # distinct video!
                "chat_jid": "chat3@s.whatsapp.net",
                "mime_type": "video/mp4",
            },
        ]
        detect_quality_duplicates(items_diff, str(self.out_path))
        for it in items_diff:
            self.assertFalse(it["is_duplicate"])

        # 4. Guard: Cross-media isolation (image and video must NEVER pair)
        items_cross = [
            {
                "filename": "IMG-20250915-WA0030.jpg",
                "rel_path": "chat4/IMG-20250915-WA0030.jpg",
                "size_bytes": 2000000,
                "chat_jid": "chat4@s.whatsapp.net",
                "mime_type": "image/jpeg",
            },
            {
                "filename": "VID-20250915-WA0030.mp4",
                "rel_path": "chat4/VID-20250915-WA0030.mp4",
                "size_bytes": 5000000,
                "chat_jid": "chat4@s.whatsapp.net",
                "mime_type": "video/mp4",
            },
        ]
        detect_quality_duplicates(items_cross, str(self.out_path))
        for it in items_cross:
            self.assertFalse(it["is_duplicate"])

    def test_06_video_duplicate_frontend_features(self):
        """Verify video duplicate detection frontend implementation in gallery.html."""
        gallery_path = Path(__file__).resolve().parent.parent / "gallery.html"
        content = read_gallery_bundle()

        # 3-frame hash engine and comparison
        self.assertIn("function computeVideo3FrameHash(", content)
        self.assertIn("function compareVideo3FrameHashes(", content)
        self.assertIn("function queueVideoCandidateHashing(", content)
        self.assertIn("function processNextVideoHashJob(", content)
        self.assertIn("function updateGridDuplicateBadges(", content)

        # Synchronized video playback in lightbox
        self.assertIn("dupVidKeeper", content)
        self.assertIn("dupVidDup", content)
        self.assertIn("vidK.onseeked", content)
        self.assertIn("vidD.onseeked", content)

        # Active chat priority queueing
        self.assertIn("queueVideoCandidateHashing(chat, true);", content)

        # Zero banned characters
        self.assertEqual(content.count('\u2014'), 0)
        self.assertEqual(content.count('\u2013'), 0)
        self.assertEqual(content.count('\u26a0'), 0)


if __name__ == "__main__":
    unittest.main()


