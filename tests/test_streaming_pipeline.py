"""
tests/test_streaming_pipeline.py - Unit tests for Single-Pass Streaming Organization.
Tests StreamingMediaRouter, reverse phone_path traceability, and direct tar extraction.
"""

import csv
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from core.organizer import StreamingMediaRouter
from core.sync_session import SyncSessionManager


class TestStreamingMediaRouter(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="wa_test_streaming_")
        self.output_dir = os.path.join(self.test_dir, "output")
        os.makedirs(self.output_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_router_matched_routing(self):
        media_rows = [
            {
                "filename": "IMG-20240101-WA0001.jpg",
                "chat_jid": "alice@s.whatsapp.net",
                "chat_name": "Alice Smith",
                "received_at": "2024-01-01T15:30:00",
                "is_doc": False,
                "starred": 1,
                "from_me": 0,
                "forward_score": 0,
            }
        ]
        router = StreamingMediaRouter(self.output_dir, media_rows=media_rows)
        phone_path = "Media/WhatsApp Images/IMG-20240101-WA0001.jpg"
        dest_p, matched = router.resolve_destination(phone_path, 1024)

        # Dest should be output/Alice Smith/2024-01/IMG-20240101-WA0001.jpg
        self.assertIsNotNone(matched)
        rel_posix = dest_p.relative_to(self.output_dir).as_posix()
        self.assertEqual(rel_posix, "Alice Smith/2024-01/IMG-20240101-WA0001.jpg")

        # Commit file
        dest_p.write_bytes(b"X" * 1024)
        router.record_committed_file(phone_path, dest_p, 1024, matched)

        summary, organized = router.flush_all(export_csv=True)
        self.assertEqual(len(organized), 1)
        item = organized[0]
        self.assertEqual(item["chat_name"], "Alice Smith")
        self.assertEqual(item["phone_path"], phone_path)
        self.assertEqual(item["starred"], 1)

        # Verify CSV has phone_path column
        csv_path = Path(self.output_dir) / "media_index.csv"
        self.assertTrue(csv_path.is_file())
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            self.assertEqual(len(reader), 1)
            self.assertEqual(reader[0]["phone_path"], phone_path)
            self.assertEqual(reader[0]["rel_path"], "Alice Smith/2024-01/IMG-20240101-WA0001.jpg")

    def test_router_unmatched_routing_and_traceability(self):
        router = StreamingMediaRouter(self.output_dir, media_rows=[])
        phone_path = "Media/WhatsApp Audio/Sent/AUD-20231201-WA0002.opus"
        dest_p, matched = router.resolve_destination(phone_path, 2048)

        self.assertIsNone(matched)
        rel_posix = dest_p.relative_to(self.output_dir).as_posix()
        self.assertEqual(rel_posix, "_unmatched/WhatsApp Audio/Sent/AUD-20231201-WA0002.opus")

        dest_p.parent.mkdir(parents=True, exist_ok=True)
        dest_p.write_bytes(b"Y" * 2048)
        router.record_committed_file(phone_path, dest_p, 2048, matched)

        summary, organized = router.flush_all(export_csv=True)
        self.assertEqual(len(organized), 1)
        self.assertEqual(organized[0]["chat_name"], "_unmatched")
        self.assertEqual(organized[0]["phone_path"], phone_path)

    def test_router_collision_resolution(self):
        router = StreamingMediaRouter(self.output_dir, media_rows=[])
        phone_path = "Media/WhatsApp Images/photo.jpg"

        # First file with size 500
        dest_1, _ = router.resolve_destination(phone_path, 500)
        dest_1.parent.mkdir(parents=True, exist_ok=True)
        dest_1.write_bytes(b"A" * 500)
        router.record_committed_file(phone_path, dest_1, 500)

        # Second file with same name but size 800
        dest_2, _ = router.resolve_destination(phone_path, 800)
        self.assertNotEqual(dest_1.name, dest_2.name)
        self.assertEqual(dest_2.name, "photo_dup1.jpg")


class TestSyncManifestTraceability(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="wa_test_manifest_")
        self.db_path = os.path.join(self.test_dir, ".sync_state.sqlite3")
        self.manager = SyncSessionManager(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_target_path_tracking(self):
        sess_id = "test_trace"
        self.manager.create_session(sess_id, "pixel_8", "Pixel 8")

        phone_p = "Media/WhatsApp Images/photo.jpg"
        init_target = "./Media/WhatsApp Images/photo.jpg"
        self.manager.init_manifest(sess_id, [(phone_p, init_target, 1024, 0)])

        # Mark completed with direct output target_path
        final_target = "output/Family Group/2024-05/photo.jpg"
        self.manager.mark_file_completed(sess_id, phone_p, 1024, target_path=final_target)

        # Check DB
        with self.manager._get_connection() as conn:
            cur = conn.execute(
                "SELECT rel_path, target_path, status FROM sync_manifest WHERE session_id = ?",
                (sess_id,),
            )
            row = cur.fetchone()
            self.assertEqual(row["rel_path"], phone_p)
            self.assertEqual(row["target_path"], final_target)
            self.assertEqual(row["status"], "completed")

    def test_contact_and_sender_resolution_in_streaming(self):
        output_dir = Path(self.test_dir) / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        contacts = {"919876543210@s.whatsapp.net": "Alice Smith"}
        lid_to_phone = {"12345678901234@lid": "919876543210@s.whatsapp.net"}
        chat_names = {"919876543210@s.whatsapp.net": "Alice Smith"}

        media_rows = [
            {
                "filename": "IMG_001.jpg",
                "chat_jid": "919876543210@s.whatsapp.net",
                "chat_name": "Alice Smith",
                "received_at": "2024-05-10 12:00:00",
                "sender_jid": "12345678901234@lid",
                "size_bytes": 2048,
                "mime_type": "image/jpeg",
            }
        ]

        router = StreamingMediaRouter(
            output_dir=output_dir,
            media_rows=media_rows,
            contacts=contacts,
            lid_to_phone=lid_to_phone,
            chat_names=chat_names,
        )

        dest, _ = router.resolve_destination("Media/WhatsApp Images/IMG_001.jpg", 2048)
        self.assertIn("Alice Smith", str(dest))

        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"test" * 512)
        router.record_committed_file("Media/WhatsApp Images/IMG_001.jpg", dest, 2048)

        summary, all_items = router.flush_all(export_csv=True)
        self.assertEqual(len(all_items), 1)

        from core.gallery import load_gallery_data
        data = load_gallery_data(output_dir)
        self.assertEqual(len(data["chats"]), 1)
        chat = data["chats"][0]
        self.assertEqual(chat["name"], "Alice Smith")
        media = chat["media"][0]
        self.assertEqual(media["sender_name"], "Alice Smith")

    @mock.patch("core.pipeline.adb_pull")
    def test_skip_db_pull_bypasses_phase1(self, mock_adb_pull):
        """Verify that skip_db_pull=True skips Phase 1 database downloading."""
        from core.pipeline import run_streaming_pipeline

        temp_out = Path(tempfile.mkdtemp(prefix="test_skip_db_"))
        try:
            # When skip_db_pull=True and skip_pull=True, adb_pull should not be called at all
            run_streaming_pipeline(
                output_dir=str(temp_out),
                skip_pull=True,
                skip_db_pull=True,
                skip_decrypt=True,
            )
            mock_adb_pull.assert_not_called()
        finally:
            shutil.rmtree(str(temp_out), ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
