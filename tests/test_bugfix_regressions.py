"""
Regression tests for bugs found in a review of the backend: each test reproduces the reported
failure and checks the fix.
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import core.server as srv  # noqa: E402
from core.config import load_config, save_config  # noqa: E402
from core.gallery import get_chats_summary  # noqa: E402
from core.organizer import StreamingMediaRouter  # noqa: E402
from core.sync_session import SyncSessionManager  # noqa: E402


class TmpDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wa_regress_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)


class IncrementalSyncKeepsTheLibrary(TmpDirTest):
    """A sync only handles the files it transferred; the gallery must keep the earlier ones."""

    ROWS = [{"filename": f"IMG-2024010{i}-WA0001.jpg", "chat_name": "Family", "chat_jid": "fam@g.us",
             "received_at": f"2024-01-0{i} 10:00:00", "size_bytes": 100 + i} for i in range(1, 4)]

    def sync(self, rows):
        router = StreamingMediaRouter(str(self.tmp), media_rows=self.ROWS)
        for row in rows:
            phone_path = f"Media/WhatsApp Images/{row['filename']}"
            dest, matched = router.resolve_destination(phone_path, row["size_bytes"])
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"x" * row["size_bytes"])
            router.record_committed_file(phone_path, dest, row["size_bytes"], matched)
        router.flush_all(export_csv=True)

    def counts(self):
        return {c["name"]: c["file_count"] for c in get_chats_summary(self.tmp)}

    def test_second_sync_adds_to_the_gallery(self):
        self.sync(self.ROWS[:2])
        self.assertEqual(self.counts(), {"Family": 2})
        self.sync(self.ROWS[2:])  # the two earlier photos are skipped by the transfer
        self.assertEqual(self.counts(), {"Family": 3})

    def test_a_sync_with_nothing_new_changes_nothing(self):
        self.sync(self.ROWS)
        before = (self.tmp / "gallery_data.js").read_text(encoding="utf-8")
        self.sync([])
        self.assertEqual((self.tmp / "gallery_data.js").read_text(encoding="utf-8"), before)


class ConfigSavesDoNotLoseTheKey(TmpDirTest):
    def test_concurrent_saves(self):
        path = self.tmp / "config.json"
        save_config({"hex_key": "a" * 64}, config_path=str(path))

        def writer(i):
            for j in range(150):
                save_config({f"k{i}": "x" * (j % 40)}, config_path=str(path))

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(load_config(str(path))["hex_key"], "a" * 64)
        json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["config.json"], "no temporary files left")


class PartFileCleanupKeepsRealDocuments(TmpDirTest):
    def test_only_transfer_staging_files_go(self):
        chat = self.tmp / "Study Group" / "2024-05"
        chat.mkdir(parents=True)
        keep = [chat / "Thesis.part_1.pdf", chat / "notes.part_two.docx", chat / "IMG-1.jpg"]
        gone = [chat / "IMG-2.jpg.part_ab12cd34", chat / "VID-3.mp4.part_sync"]
        for p in keep + gone:
            p.write_bytes(b"x")
        manager = SyncSessionManager(str(self.tmp / ".sync_state.sqlite3"))
        self.assertEqual(manager.cleanup_orphaned_part_files([str(self.tmp)]), 2)
        self.assertTrue(all(p.exists() for p in keep))
        self.assertFalse(any(p.exists() for p in gone))


class OneSyncAtATime(unittest.TestCase):
    def test_a_sync_is_not_started_while_the_previous_worker_still_stops(self):
        release = threading.Event()
        old = threading.Thread(target=release.wait, args=(5,), daemon=True)
        old.start()
        saved = dict(srv.sync_status), dict(srv._sync_worker)
        try:
            srv.sync_status["active"] = False  # cancel already said "idle"
            srv._sync_worker["thread"] = old
            with mock.patch.object(srv, "check_adb_device") as adb:
                self.assertFalse(srv._start_background_sync("/nonexistent"))
                adb.assert_not_called()
            self.assertFalse(srv.sync_status["active"])
        finally:
            release.set()
            old.join()
            srv.sync_status.clear()
            srv.sync_status.update(saved[0])
            srv._sync_worker.clear()
            srv._sync_worker.update(saved[1])


class LocalServerTests(TmpDirTest):
    """The local web server: other websites are refused, private files are never served."""

    def setUp(self):
        super().setUp()
        self.out = self.tmp / "output"
        (self.out / "Family" / "2024-01").mkdir(parents=True)
        self.media = self.out / "Family" / "2024-01" / "IMG-1.jpg"
        self.media.write_bytes(bytes(range(256)) * 4)  # 1024 bytes
        (self.out / "encrypted_backup.key").write_bytes(b"secret key")
        (self.out / "gallery_data.js").write_text('const GALLERY_DATA = {"chats": []};', encoding="utf-8")
        out = self.out

        class Handler(srv.GalleryHTTPRequestHandler):
            def __init__(self, *a, **kw):
                super().__init__(*a, directory=str(out), **kw)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def call(self, path, method="GET", headers=None, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method,
                                     headers=headers or {}, data=body)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def test_no_cors_grant_for_other_websites(self):
        status, headers, _ = self.call("/api/chats")
        self.assertEqual(status, 200)
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(self.call("/api/chats", "OPTIONS")[0], 403)

    def test_requests_from_other_websites_are_refused(self):
        evil = {"Origin": "https://evil.example"}
        self.assertEqual(self.call("/api/chats", headers=evil)[0], 403)
        # a "simple" cross-site POST (text/plain: no preflight) must not delete anything
        status, _, _ = self.call("/api/media/delete", "POST", body=b'{"rel_paths": ["Family/2024-01/IMG-1.jpg"]}',
                                 headers={**evil, "Content-Type": "text/plain"})
        self.assertEqual(status, 403)
        self.assertTrue(self.media.exists())
        self.assertEqual(self.call("/api/chats", headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "cors"})[0], 403)
        # DNS rebinding: a website's own domain pointed at 127.0.0.1
        self.assertEqual(self.call("/api/chats", headers={"Host": f"evil.example:{self.port}"})[0], 403)

    def test_the_gallerys_own_pages_still_work(self):
        same = {"Origin": f"http://127.0.0.1:{self.port}", "Sec-Fetch-Site": "same-origin"}
        self.assertEqual(self.call("/api/chats", headers=same)[0], 200)
        self.assertEqual(self.call("/gallery_data.js")[0], 200)
        # opening the gallery from a link elsewhere (a navigation) is fine
        nav = {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate"}
        self.assertEqual(self.call("/gallery_data.js", headers=nav)[0], 200)
        self.assertEqual(self.call("/api/chats", headers={"Host": f"localhost:{self.port}"})[0], 200)

    def test_private_files_are_never_served(self):
        self.assertEqual(self.call("/encrypted_backup.key")[0], 404)
        self.assertEqual(self.call("/encrypted_backup.key", "HEAD")[0], 404)
        for name in ("config.json", "encrypted_backup.key", "../config.json"):
            self.assertEqual(self.call(f"/api/media?path={name}")[0], 404, name)
        self.assertEqual(self.call("/api/transcode?rel_path=/etc/hostname")[0], 404)
        self.assertFalse((self.out / ".cache" / "etc").exists())
        self.assertEqual(self.call("/api/media?path=Family/2024-01/IMG-1.jpg")[0], 200)

    def test_range_requests_past_the_end_are_clamped(self):
        status, headers, body = self.call("/api/media?path=Family/2024-01/IMG-1.jpg", headers={"Range": "bytes=900-1999"})
        self.assertEqual((status, headers.get("Content-Range"), len(body)), (206, "bytes 900-1023/1024", 124))
        status, headers, body = self.call("/api/media?path=Family/2024-01/IMG-1.jpg", headers={"Range": "bytes=-100"})
        self.assertEqual((status, headers.get("Content-Range"), len(body)), (206, "bytes 924-1023/1024", 100))

    def test_bad_input_gets_an_answer_not_a_dropped_connection(self):
        self.assertEqual(self.call("/api/chats/fam%40g.us/media?offset=abc")[0], 400)
        status, _, body = self.call("/api/media/delete", "POST", body=b"[1, 2]", headers={"Content-Type": "application/json"})
        self.assertEqual(status, 400)
        self.assertIn(b"rel_paths", body)

    def test_recycling_waits_for_a_running_sync(self):
        with mock.patch.dict(srv.sync_status, {"active": True}):
            status, _, body = self.call("/api/duplicates/recycle", "POST", headers={"Content-Type": "application/json"},
                                        body=json.dumps({"rel_paths": ["Family/2024-01/IMG-1.jpg"]}).encode())
        self.assertEqual(status, 409)
        self.assertTrue(self.media.exists())


class PrivateFileRules(unittest.TestCase):
    def test_rules(self):
        private = ["config.json", "encrypted_backup.key", "Databases/msgstore.db", "msgstore.db.crypt15",
                   ".sync_state.sqlite3", "wa.db", "venv/bin/python"]
        public = ["gallery_data.js", "gallery.html", "media_index.csv", "gallery_assets/js/app.js",
                  "Family/2024-01/backup.db", "Family/2024-01/house.key", "Databases Group/x.jpg"]
        for p in private:
            self.assertTrue(srv.is_private_file(p), p)
        for p in public:
            self.assertFalse(srv.is_private_file(p), p)


if __name__ == "__main__":
    unittest.main()


class UnmatchedMediaFindsItsChat(TmpDirTest):
    """_unmatched files are matched by name with a newer database, and by their contents (SHA-256)."""

    def setUp(self):
        super().setUp()
        from core.organizer import file_sha256_b64
        self.sha = file_sha256_b64
        self.um = self.tmp / "_unmatched" / "WhatsApp Images"
        self.um.mkdir(parents=True)

    def put(self, name, data):
        p = self.um / name
        p.write_bytes(data)
        return p

    def row(self, filename, chat, data=None, when="2024-03-05 10:00:00", **extra):
        import base64
        import hashlib
        r = {"filename": filename, "media_name": filename, "file_path": f"Media/WhatsApp Images/{filename}",
             "chat_name": chat, "chat_jid": chat.lower() + "@s.whatsapp.net", "received_at": when,
             "size_bytes": len(data) if data else 0}
        if data is not None:
            r["file_hash"] = base64.b64encode(hashlib.sha256(data).digest()).decode()
        r.update(extra)
        return r

    def run_recheck(self, rows):
        from core.organizer import reorganize_unmatched_media
        return reorganize_unmatched_media(str(self.tmp), media_rows=rows, contacts={}, lid_to_phone={}, chat_names={})

    def test_a_newer_database_places_files_by_name(self):
        self.put("IMG-20240305-WA0007.jpg", b"photo")
        res = self.run_recheck([self.row("IMG-20240305-WA0007.jpg", "Mom", b"photo")])
        self.assertEqual(res["rematched"], 1)
        self.assertTrue((self.tmp / "Mom" / "2024-03" / "IMG-20240305-WA0007.jpg").is_file())
        self.assertFalse((self.um / "IMG-20240305-WA0007.jpg").exists())
        self.assertEqual({c["name"]: c["file_count"] for c in get_chats_summary(self.tmp)}, {"Mom": 1})

    def test_a_renamed_file_is_recognised_by_its_contents(self):
        data = b"\xff\xd8 holiday photo bytes"
        self.put("IMG_1234 (edited name).jpg", data)
        rows = [self.row("IMG-20240305-WA0001.jpg", "Dad", data), self.row("IMG-20240305-WA0002.jpg", "Mom", b"other")]
        res = self.run_recheck(rows)
        self.assertEqual((res["rematched"], res["by_content"]), (1, 1))
        self.assertTrue((self.tmp / "Dad" / "2024-03" / "IMG_1234 (edited name).jpg").is_file())

    def test_sent_media_by_its_original_hash(self):
        import base64
        import hashlib
        original = b"full size original"
        self.put("IMG-20240305-WA0003.jpg.bak", original)
        rows = [self.row("IMG-20240305-WA0003.jpg", "Team", b"compressed",
                         original_file_hash=base64.b64encode(hashlib.sha256(original).digest()).decode())]
        self.assertEqual(self.run_recheck(rows)["by_content"], 1)

    def test_same_size_but_different_contents_is_never_guessed(self):
        self.put("unknown.jpg", b"AAAAA")
        res = self.run_recheck([self.row("IMG-20240305-WA0009.jpg", "Boss", b"BBBBB")])
        self.assertEqual((res["rematched"], res["still_unmatched"]), (0, 1))
        self.assertTrue((self.um / "unknown.jpg").is_file())

    def test_same_size_still_matches_when_whatsapp_kept_no_hash(self):
        self.put("unknown.jpg", b"AAAAA")
        old_row = self.row("IMG-20240305-WA0009.jpg", "Old chat")
        old_row["size_bytes"] = 5
        self.assertEqual(self.run_recheck([old_row])["rematched"], 1)

    def test_a_file_forwarded_to_several_chats_goes_to_the_oldest_message(self):
        data = b"meme"
        self.put("meme.jpg", data)
        rows = [self.row("A.jpg", "Later chat", data, when="2024-05-01 10:00:00"),
                self.row("B.jpg", "First chat", data, when="2024-02-01 10:00:00")]
        self.run_recheck(rows)
        self.assertTrue((self.tmp / "First chat" / "2024-02" / "meme.jpg").is_file())

    def test_contents_are_hashed_once(self):
        self.put("still-unknown.jpg", b"nothing knows me")
        rows = [self.row("IMG-1.jpg", "Mom", b"other")]
        from core import organizer
        with mock.patch.object(organizer, "file_sha256_b64", wraps=organizer.file_sha256_b64) as h:
            self.run_recheck(rows)
            self.run_recheck(rows)
        self.assertEqual(h.call_count, 1, "the second sync reuses the remembered hash")

    def test_media_index_follows_the_move(self):
        import csv
        self.put("IMG-20240305-WA0007.jpg", b"photo")
        with open(self.tmp / "media_index.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["rel_path", "phone_path", "chat_name"])
            w.writeheader()
            w.writerow({"rel_path": "_unmatched/WhatsApp Images/IMG-20240305-WA0007.jpg",
                        "phone_path": "Media/WhatsApp Images/IMG-20240305-WA0007.jpg", "chat_name": "_unmatched"})
        self.run_recheck([self.row("IMG-20240305-WA0007.jpg", "Mom", b"photo")])
        with open(self.tmp / "media_index.csv", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual([(r["rel_path"], r["phone_path"], r["chat_name"]) for r in rows],
                         [("Mom/2024-03/IMG-20240305-WA0007.jpg", "Media/WhatsApp Images/IMG-20240305-WA0007.jpg", "Mom")])

    def test_streaming_never_guesses_by_size_when_a_hash_can_tell(self):
        router = StreamingMediaRouter(str(self.tmp), media_rows=[self.row("IMG-1.jpg", "Boss", b"BBBBB")])
        dest, row = router.resolve_destination("Media/WhatsApp Images/random.jpg", 5)
        self.assertIsNone(row)
        self.assertIn("_unmatched", dest.as_posix())


class MediaKinds(TmpDirTest):
    """Stickers, GIFs and voice notes get their own category (WhatsApp's message type, folder, then name)."""

    def test_kinds(self):
        from core.organizer import media_kind
        self.assertEqual(media_kind("Media/WhatsApp Images/IMG-1.jpg", "IMG-1.jpg", "image/jpeg", 20), "sticker")
        self.assertEqual(media_kind("Media/WhatsApp Video/VID-1.mp4", "VID-1.mp4", "video/mp4", 13), "gif")
        self.assertEqual(media_kind("Media/WhatsApp Animated Gifs/VID-20240101-WA0001.mp4", "VID-20240101-WA0001.mp4", "video/mp4"), "gif")
        self.assertEqual(media_kind("Media/WhatsApp Stickers/STK-20240101-WA0001.webp", "STK-20240101-WA0001.webp", "image/webp"), "sticker")
        self.assertEqual(media_kind("Media/WhatsApp Voice Notes/202401/PTT-20240101-WA0001.opus", "PTT-20240101-WA0001.opus", "audio/ogg"), "voice")
        self.assertEqual(media_kind("", "STK-x.webp", "image/webp"), "sticker")
        self.assertIsNone(media_kind("Media/WhatsApp Images/IMG-1.jpg", "IMG-1.jpg", "image/jpeg", 1))
        self.assertIsNone(media_kind("Media/WhatsApp Documents/report.pdf", "report.pdf", "application/pdf", "9"))

    def test_the_gallery_carries_the_kind(self):
        router = StreamingMediaRouter(str(self.tmp), media_rows=[
            {"filename": "STK-20240101-WA0001.webp", "chat_name": "Friends", "chat_jid": "f@g.us",
             "received_at": "2024-01-01 10:00:00", "size_bytes": 3, "message_type": 20}])
        dest, row = router.resolve_destination("Media/WhatsApp Stickers/STK-20240101-WA0001.webp", 3)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"abc")
        router.record_committed_file("Media/WhatsApp Stickers/STK-20240101-WA0001.webp", dest, 3, row)
        router.flush_all(export_csv=False)
        from core.gallery import load_gallery_data
        media = load_gallery_data(str(self.tmp))["chats"][0]["media"]
        self.assertEqual(media[0]["media_kind"], "sticker")
