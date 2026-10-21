"""
Several tabs (or browsers) on one gallery stay consistent:
- recycling, restoring, emptying the recycle bin, importing and changing settings bump a
  library version that every tab receives in its heartbeat and uses to refresh itself
- the per-chat media list served to a refreshing tab no longer contains recycled files
- the duplicate-detection choice is stored by the app, not per browser
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.server as srv
from core.gallery import update_gallery_data_live


class TestMultiTab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="wa_test_multitab_"))
        cls.cwd = os.getcwd()
        os.chdir(cls.tmp)
        cls.out = cls.tmp / "output"
        items = []
        for i in range(3):
            rel = f"Alice/2024-01/IMG-{i}.jpg"
            (cls.out / rel).parent.mkdir(parents=True, exist_ok=True)
            (cls.out / rel).write_bytes(os.urandom(100 + i))
            items.append({"chat_jid": "alice@s.whatsapp.net", "chat_name": "Alice", "filename": Path(rel).name,
                          "rel_path": rel, "size_bytes": 100 + i, "mime_type": "image/jpeg",
                          "received_at": "2024-01-01 10:00:00"})
        update_gallery_data_live(items, str(cls.out))
        out = str(cls.out)

        class Handler(srv.GalleryHTTPRequestHandler):
            def __init__(self, *a, **kw):
                super().__init__(*a, directory=out, **kw)

        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        os.chdir(cls.cwd)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())

    def version(self):
        return self.call("POST", "/api/heartbeat", {"tab_id": "tab-b"})["data_version"]

    def media(self):
        return {m["rel_path"] for m in self.call("GET", "/api/chats/alice%40s.whatsapp.net/media")["media"]}

    def test_01_recycle_and_restore_reach_other_tabs(self):
        v0 = self.version()
        self.call("POST", "/api/duplicates/recycle", {"rel_paths": ["Alice/2024-01/IMG-1.jpg"]})
        v1 = self.version()
        self.assertGreater(v1, v0, "another tab must learn that the library changed")
        self.assertNotIn("Alice/2024-01/IMG-1.jpg", self.media(), "a refreshing tab must not get the recycled file")
        self.call("POST", "/api/duplicates/restore", {"rel_paths": ["Alice/2024-01/IMG-1.jpg"]})
        self.assertGreater(self.version(), v1)
        self.assertIn("Alice/2024-01/IMG-1.jpg", self.media())

    def test_02_emptying_the_recycle_bin_reaches_other_tabs(self):
        v0 = self.version()
        self.call("POST", "/api/duplicates/empty-recycle-bin", {})
        self.assertGreater(self.version(), v0)

    def test_03_duplicate_setting_is_shared_by_every_tab_and_browser(self):
        self.assertIsNone(self.call("GET", "/api/config")["duplicate_detection"], "not chosen yet")
        v0 = self.version()
        self.call("POST", "/api/config", {"duplicate_detection": False})
        self.assertFalse(self.call("GET", "/api/config")["duplicate_detection"])
        self.assertGreater(self.version(), v0)
        self.call("POST", "/api/config", {"duplicate_detection": True})
        self.assertTrue(self.call("GET", "/api/config")["duplicate_detection"])

    def test_04_heartbeat_without_changes_keeps_the_version(self):
        self.assertEqual(self.version(), self.version())


class TestRestoreBringsMediaBack(unittest.TestCase):
    """Restoring from the Recycle Bin must put the item back in the gallery, not only on disk."""

    def setUp(self):
        self.out = Path(tempfile.mkdtemp(prefix="wa_test_restore_"))
        self.items = []
        for i in range(2):
            rel = f"Bob/2024-02/VID-{i}.mp4"
            (self.out / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.out / rel).write_bytes(os.urandom(500 + i))
            self.items.append({"chat_jid": "bob@s.whatsapp.net", "chat_name": "Bob", "filename": Path(rel).name,
                               "rel_path": rel, "size_bytes": 500 + i, "mime_type": "video/mp4",
                               "received_at": "2024-02-02 09:00:00", "sender_name": "Bob"})
        update_gallery_data_live(self.items, str(self.out))

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def chat_media(self):
        from core.gallery import get_chat_media
        return {m["rel_path"]: m for m in get_chat_media(str(self.out), "bob@s.whatsapp.net")["media"]}

    def test_10_restored_item_returns_with_its_details(self):
        from core.gallery import recycle_media_items, restore_media_items
        rel = "Bob/2024-02/VID-1.mp4"
        before = self.chat_media()[rel]
        recycle_media_items(str(self.out), [rel])
        self.assertNotIn(rel, self.chat_media())
        restore_media_items(str(self.out), [rel])
        after = self.chat_media()
        self.assertIn(rel, after, "restored media must be visible in the gallery again")
        self.assertEqual(after[rel], before, "with the same sender, date and type as before")
        self.assertTrue((self.out / rel).is_file())

    def test_11_items_recycled_by_older_versions_are_restored_too(self):
        from core.gallery import recycle_media_items, restore_media_items
        rel = "Bob/2024-02/VID-0.mp4"
        recycle_media_items(str(self.out), [rel])
        manifest_path = self.out / ".duplicates_recycle_bin" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        for key in ("gallery_entry", "chat_jid", "chat_name", "csv_row"):
            manifest[rel].pop(key, None)  # what an older version wrote
        manifest_path.write_text(json.dumps(manifest))
        restore_media_items(str(self.out), [rel])
        restored = self.chat_media()[rel]
        self.assertEqual((restored["size_bytes"], restored["mime_type"]), (500, "video/mp4"))

    def test_12_restore_all_is_idempotent(self):
        from core.gallery import recycle_media_items, restore_media_items
        recycle_media_items(str(self.out), [m["rel_path"] for m in self.items])
        restore_media_items(str(self.out), restore_all=True)
        restore_media_items(str(self.out), restore_all=True)
        self.assertEqual(len(self.chat_media()), 2)


if __name__ == "__main__":
    unittest.main()
