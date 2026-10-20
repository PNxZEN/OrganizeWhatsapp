"""
Tests for incremental live-sync flushes of gallery_data.js (core.gallery.update_gallery_data_live):
- the file written incrementally is byte-identical to a full json.dumps of the dataset
- changes written by another writer between flushes are picked up, not overwritten
- the per-chat media API sees new media and brand-new chats right after a flush
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.gallery import (
    get_chat_media,
    get_chats_summary,
    parse_gallery_data_js,
    update_gallery_data_js,
    update_gallery_data_live,
)


def make_item(chat, idx, size=1000):
    return {
        "chat_jid": f"{chat}@s.whatsapp.net",
        "chat_name": chat,
        "filename": f"IMG-{idx:04d}.jpg",
        "rel_path": f"{chat}/2024-01/IMG-{idx:04d}.jpg",
        "size_bytes": size,
        "mime_type": "image/jpeg",
        "received_at": "2024-01-01 10:00:00",
    }


class TestLiveGalleryFlush(unittest.TestCase):
    def setUp(self):
        self.out = Path(tempfile.mkdtemp(prefix="wa_test_live_"))
        self.data_path = self.out / "gallery_data.js"

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def read(self):
        return parse_gallery_data_js(self.data_path.read_text(encoding="utf-8"))

    def test_01_incremental_output_matches_full_serialization(self):
        update_gallery_data_live([make_item("alice", i) for i in range(5)], str(self.out))
        update_gallery_data_live([make_item("bob", i, 5000) for i in range(3)], str(self.out))
        update_gallery_data_live([make_item("alice", i) for i in range(5, 8)], str(self.out))
        raw = self.data_path.read_text(encoding="utf-8")
        data = self.read()
        self.assertEqual(raw, f"const GALLERY_DATA = {json.dumps(data)};")
        sizes = {c["name"]: (c["file_count"], c["total_size"]) for c in data["chats"]}
        self.assertEqual(sizes["alice"], (8, 8000))
        self.assertEqual(sizes["bob"], (3, 15000))
        self.assertEqual([c["name"] for c in data["chats"]], ["bob", "alice"], "sorted by total size")

    def test_02_duplicate_rel_paths_are_ignored(self):
        update_gallery_data_live([make_item("alice", 1)], str(self.out))
        added = update_gallery_data_live([make_item("alice", 1), make_item("alice", 2)], str(self.out))
        self.assertEqual(added, 1)
        self.assertEqual(self.read()["chats"][0]["file_count"], 2)

    def test_03_external_writes_between_flushes_are_preserved(self):
        update_gallery_data_live([make_item("alice", 1)], str(self.out))
        # e.g. a transcode finishing mid-sync records a preview path through another writer
        update_gallery_data_js(str(self.out), "alice/2024-01/IMG-0001.jpg", ".cache/preview.mp4")
        update_gallery_data_live([make_item("alice", 2)], str(self.out))
        media = {m["rel_path"]: m for m in self.read()["chats"][0]["media"]}
        self.assertEqual(media["alice/2024-01/IMG-0001.jpg"]["preview_path"], ".cache/preview.mp4")
        self.assertIn("alice/2024-01/IMG-0002.jpg", media)

    def test_04_media_api_sees_new_items_and_new_chats(self):
        update_gallery_data_live([make_item("alice", 1)], str(self.out))
        self.assertEqual(len(get_chat_media(str(self.out), "alice@s.whatsapp.net")["media"]), 1)
        update_gallery_data_live([make_item("alice", 2), make_item("carol", 1)], str(self.out))
        self.assertEqual(len(get_chat_media(str(self.out), "alice@s.whatsapp.net")["media"]), 2)
        carol = get_chat_media(str(self.out), "carol@s.whatsapp.net")
        self.assertIsNotNone(carol, "a chat created during the sync must be served immediately")
        self.assertEqual(len(carol["media"]), 1)
        self.assertEqual({c["jid"] for c in get_chats_summary(str(self.out))},
                         {"alice@s.whatsapp.net", "carol@s.whatsapp.net"})


if __name__ == "__main__":
    unittest.main()
