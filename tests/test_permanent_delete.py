"""
Deleting media for good leaves nothing behind that reveals it:
- the file, its gallery entry, its media_index.csv row
- its thumbnails and video previews
- its rows in the duplicate hash index and the sync manifest (with the freed space wiped)
- no list of deleted names, sizes or fingerprints is kept
Works for single Recycle Bin items, emptying the bin, and deleting straight from the gallery.
"""

import csv
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.server as srv
from core.gallery import (
    delete_media_permanently,
    empty_recycle_bin,
    get_chat_media,
    purge_recycled_items,
    recycle_media_items,
    update_gallery_data_live,
)
from core.thumbnail import get_or_create_thumbnail

SECRET = "IMG-20250911-WA0011"


class DeleteBase(unittest.TestCase):
    def setUp(self):
        from PIL import Image

        self.out = Path(tempfile.mkdtemp(prefix="wa_test_delete_"))
        self.rels = [f"VPN/2025-09/{SECRET}.jpg", "VPN/2025-09/IMG-20250911-WA0012.jpg", "VPN/2025-09/VID-20250911-WA0001.mp4"]
        items = []
        for i, rel in enumerate(self.rels):
            p = self.out / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if rel.endswith(".jpg"):
                Image.new("RGB", (64, 64), (i * 60, 10, 10)).save(p, "JPEG")
            else:
                p.write_bytes(os.urandom(2000))
            items.append({"chat_jid": "vpn@g.us", "chat_name": "VPN", "filename": p.name, "rel_path": rel,
                          "size_bytes": p.stat().st_size, "mime_type": "image/jpeg", "received_at": "2025-09-11 10:00:00"})
        update_gallery_data_live(items, str(self.out))
        for rel in self.rels[:2]:
            self.assertIsNotNone(get_or_create_thumbnail(str(self.out), rel))
        video = Path(self.rels[2])
        for derived in (self.out / ".cache" / video.parent / f"{video.name}_preview.mp4",
                        self.out / ".thumbnails" / video.parent / f"{video.name}.jpg"):
            derived.parent.mkdir(parents=True, exist_ok=True)
            derived.write_bytes(b"derived")
        with open(self.out / "media_index.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["rel_path", "size_bytes", "phone_path"])
            w.writeheader()
            for rel in self.rels:
                w.writerow({"rel_path": rel, "size_bytes": 1, "phone_path": f"/sdcard/WhatsApp/{Path(rel).name}"})
        with sqlite3.connect(self.out / ".hashes_cache.sqlite3") as c:
            c.execute("CREATE TABLE file_hashes (filepath TEXT PRIMARY KEY, mtime REAL, size INTEGER, md5 TEXT, phash TEXT, fast_hash TEXT)")
            for rel in self.rels:
                c.execute("INSERT INTO file_hashes VALUES (?,?,?,?,?,?)", (str((self.out / rel).resolve()), 1, 1, "m", "p", "f"))
                c.execute("INSERT INTO file_hashes VALUES (?,?,?,?,?,?)", (rel, 1, 1, "m", "p", "f"))
        with sqlite3.connect(self.out / ".sync_state.sqlite3") as c:
            c.execute("CREATE TABLE sync_manifest (session_id TEXT, rel_path TEXT, target_path TEXT, file_size INTEGER, status TEXT)")
            for rel in self.rels:
                c.execute("INSERT INTO sync_manifest VALUES (?,?,?,?,?)",
                          ("s", f"Media/WhatsApp Images/{Path(rel).name}", str((self.out / rel).resolve()), 1, "completed"))

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def assert_no_trace(self, needle=SECRET):
        for p in self.out.rglob("*"):
            if p.is_file():
                self.assertNotIn(needle.encode(), p.read_bytes(), f"{needle} is still readable in {p.relative_to(self.out)}")
            self.assertNotIn(needle, p.name, f"left behind: {p.relative_to(self.out)}")

    def media(self):
        return {m["rel_path"] for m in get_chat_media(str(self.out), "vpn@g.us")["media"]}


class TestPermanentDelete(DeleteBase):
    def test_01_delete_from_gallery_leaves_no_trace(self):
        res = delete_media_permanently(str(self.out), [self.rels[0]])
        self.assertEqual(res["deleted_count"], 1)
        self.assertEqual(self.media(), set(self.rels[1:]))
        self.assert_no_trace()
        # the other media keep their thumbnails and index rows
        self.assertTrue((self.out / ".thumbnails" / f"{self.rels[1]}.thumb.jpg").is_file())
        with sqlite3.connect(self.out / ".hashes_cache.sqlite3") as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM file_hashes").fetchone()[0], 4)

    def test_02_video_previews_are_removed_too(self):
        delete_media_permanently(str(self.out), [self.rels[2]])
        self.assert_no_trace("VID-20250911-WA0001")

    def test_03_single_recycle_bin_item(self):
        recycle_media_items(str(self.out), self.rels[:2])
        # the Recycle Bin view creates thumbnails of the recycled files
        get_or_create_thumbnail(str(self.out), f".duplicates_recycle_bin/{self.rels[0]}")
        res = purge_recycled_items(str(self.out), [self.rels[0]])
        self.assertEqual(res["deleted_count"], 1)
        self.assert_no_trace()
        manifest = json.loads((self.out / ".duplicates_recycle_bin" / "manifest.json").read_text())
        self.assertEqual(list(manifest), [self.rels[1]], "the other item stays in the bin")
        self.assertTrue((self.out / ".duplicates_recycle_bin" / self.rels[1]).is_file())

    def test_04_emptying_the_bin_leaves_no_trace_and_no_list(self):
        recycle_media_items(str(self.out), self.rels)
        (self.out / ".deleted_media.json").write_text(json.dumps({self.rels[0]: 1}))  # from an earlier build
        res = empty_recycle_bin(str(self.out))
        self.assertEqual(res["deleted_count"], 3)
        for rel in self.rels:
            self.assert_no_trace(Path(rel).stem)
        self.assertFalse((self.out / ".deleted_media.json").exists())

    def test_07_names_are_wiped_even_where_sqlite_keeps_deleted_rows(self):
        """Windows and macOS Python builds keep deleted rows readable unless secure_delete is on."""
        from unittest import mock

        real_connect = sqlite3.connect

        def connect_like_windows(*a, **kw):
            conn = real_connect(*a, **kw)
            conn.execute("PRAGMA secure_delete = OFF")
            return conn

        with mock.patch("sqlite3.connect", connect_like_windows):
            delete_media_permanently(str(self.out), [self.rels[0]])
        self.assert_no_trace()

    def test_05_paths_outside_the_gallery_are_refused(self):
        outside = self.out.parent / "keep_me.jpg"
        outside.write_bytes(b"x")
        try:
            self.assertEqual(delete_media_permanently(str(self.out), ["../keep_me.jpg"])["deleted_count"], 0)
            self.assertEqual(purge_recycled_items(str(self.out), ["../../keep_me.jpg"])["deleted_count"], 0)
            self.assertTrue(outside.exists())
        finally:
            outside.unlink()

    def test_06_bin_items_cannot_be_deleted_through_the_gallery_route(self):
        recycle_media_items(str(self.out), [self.rels[0]])
        res = delete_media_permanently(str(self.out), [f".duplicates_recycle_bin/{self.rels[0]}"])
        self.assertEqual(res["deleted_count"], 0)


class TestDeleteApi(DeleteBase):
    def setUp(self):
        super().setUp()
        out = str(self.out)

        class Handler(srv.GalleryHTTPRequestHandler):
            def __init__(self, *a, **kw):
                super().__init__(*a, directory=out, **kw)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        srv.sync_status["active"] = False
        super().tearDown()

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_10_endpoints(self):
        v0 = srv._library_version["n"]
        self.assertEqual(self.post("/api/media/delete", {})[0], 400)
        srv.sync_status["active"] = True
        self.assertEqual(self.post("/api/media/delete", {"rel_paths": [self.rels[0]]})[0], 409)
        srv.sync_status["active"] = False
        status, data = self.post("/api/media/delete", {"rel_paths": [self.rels[0]]})
        self.assertEqual((status, data["deleted_count"]), (200, 1))
        self.post("/api/duplicates/recycle", {"rel_paths": [self.rels[1]]})
        status, data = self.post("/api/duplicates/purge-items", {"rel_paths": [self.rels[1]]})
        self.assertEqual((status, data["deleted_count"]), (200, 1))
        self.assertGreaterEqual(srv._library_version["n"], v0 + 3, "other tabs are told")


if __name__ == "__main__":
    unittest.main()
