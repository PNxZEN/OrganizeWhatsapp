"""
tests/test_migrator.py - Unit tests for core/migrator.py
"""

import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.migrator import analyze_import_folder, execute_import_folder, validate_paths


class TestMigrator(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="wa_test_migrator_")
        self.src_dir = Path(self.temp_dir) / "older_output"
        self.tgt_dir = Path(self.temp_dir) / "current_output"
        self.src_dir.mkdir(parents=True)
        self.tgt_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_validate_paths(self):
        # Nonexistent source
        valid, err, _, _ = validate_paths(str(self.src_dir / "nonexistent"), str(self.tgt_dir))
        self.assertFalse(valid)
        self.assertIn("does not exist", err)

        # Same folder
        valid, err, _, _ = validate_paths(str(self.tgt_dir), str(self.tgt_dir))
        self.assertFalse(valid)
        self.assertIn("cannot be the same", err)

        # Valid distinct folders
        valid, err, s, t = validate_paths(str(self.src_dir), str(self.tgt_dir))
        self.assertTrue(valid)
        self.assertEqual(err, "")

    def test_02_migration_files_and_databases(self):
        # 1. Setup older output structure
        src_chat1 = self.src_dir / "Alice_Smith" / "2024-05"
        src_chat1.mkdir(parents=True)
        img1 = src_chat1 / "IMG-20240501-WA0001.jpg"
        img1.write_bytes(b"ALICE_IMAGE_DATA_123456789")

        src_chat2 = self.src_dir / "Bob_Jones" / "2024-05"
        src_chat2.mkdir(parents=True)
        vid1 = src_chat2 / "VID-20240502-WA0002.mp4"
        vid1.write_bytes(b"BOB_VIDEO_DATA_987654321")

        # Source gallery_data.js
        src_gallery = {
            "chats": [
                {
                    "jid": "alice@s.whatsapp.net",
                    "name": "Alice Smith",
                    "total_size": len(b"ALICE_IMAGE_DATA_123456789"),
                    "file_count": 1,
                    "media": [
                        {
                            "filename": "IMG-20240501-WA0001.jpg",
                            "rel_path": "Alice_Smith/2024-05/IMG-20240501-WA0001.jpg",
                            "size_bytes": len(b"ALICE_IMAGE_DATA_123456789"),
                            "mime_type": "image/jpeg",
                            "received_at": "2024-05-01 10:00:00",
                        }
                    ],
                }
            ]
        }
        (self.src_dir / "gallery_data.js").write_text(
            f"window.GALLERY_DATA = {json.dumps(src_gallery)};\n", encoding="utf-8"
        )

        # Source .hashes_cache.sqlite3
        src_hash_db = self.src_dir / ".hashes_cache.sqlite3"
        conn = sqlite3.connect(str(src_hash_db))
        conn.execute(
            """
            CREATE TABLE file_hashes (
                filepath TEXT PRIMARY KEY,
                mtime REAL,
                size INTEGER,
                md5 TEXT,
                phash TEXT,
                fast_hash TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO file_hashes VALUES (?, ?, ?, ?, ?, ?)",
            (
                str((src_chat1 / "IMG-20240501-WA0001.jpg").resolve()),
                1700000000.0,
                len(b"ALICE_IMAGE_DATA_123456789"),
                "alice_md5_hash",
                "alice_phash",
                None,
            ),
        )
        conn.commit()
        conn.close()

        # Source .sync_state.sqlite3
        src_sync_db = self.src_dir / ".sync_state.sqlite3"
        conn = sqlite3.connect(str(src_sync_db))
        conn.execute(
            """
            CREATE TABLE sync_sessions (
                session_id TEXT PRIMARY KEY,
                device_serial TEXT,
                device_model TEXT,
                status TEXT,
                current_phase TEXT,
                created_at REAL,
                updated_at REAL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE sync_manifest (
                session_id TEXT,
                rel_path TEXT,
                target_path TEXT,
                file_size INTEGER,
                file_mtime INTEGER,
                status TEXT,
                synced_bytes INTEGER,
                synced_at REAL,
                error_message TEXT,
                PRIMARY KEY (session_id, rel_path)
            )
            """
        )
        conn.execute(
            "INSERT INTO sync_sessions VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("sess_old", "DEV123", "Pixel 8", "completed", "completed", 1000.0, 1000.0),
        )
        conn.execute(
            "INSERT INTO sync_manifest VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("sess_old", "Alice_Smith/2024-05/IMG-20240501-WA0001.jpg", "target", len(b"ALICE_IMAGE_DATA_123456789"), 1700000000, "completed", len(b"ALICE_IMAGE_DATA_123456789"), 1000.0, None),
        )
        conn.commit()
        conn.close()

        # 2. Setup existing target with another chat
        tgt_chat3 = self.tgt_dir / "Charlie_Brown" / "2024-06"
        tgt_chat3.mkdir(parents=True)
        img3 = tgt_chat3 / "IMG-20240601-WA0001.jpg"
        img3.write_bytes(b"CHARLIE_DATA")

        tgt_gallery = {
            "chats": [
                {
                    "jid": "charlie@s.whatsapp.net",
                    "name": "Charlie Brown",
                    "total_size": len(b"CHARLIE_DATA"),
                    "file_count": 1,
                    "media": [
                        {
                            "filename": "IMG-20240601-WA0001.jpg",
                            "rel_path": "Charlie_Brown/2024-06/IMG-20240601-WA0001.jpg",
                            "size_bytes": len(b"CHARLIE_DATA"),
                            "mime_type": "image/jpeg",
                            "received_at": "2024-06-01 10:00:00",
                        }
                    ],
                }
            ]
        }
        (self.tgt_dir / "gallery_data.js").write_text(
            f"window.GALLERY_DATA = {json.dumps(tgt_gallery)};\n", encoding="utf-8"
        )

        # 3. Pre-flight Analysis
        analysis = analyze_import_folder(str(self.src_dir), str(self.tgt_dir))
        self.assertTrue(analysis["valid"])
        self.assertEqual(analysis["media_count"], 2)
        self.assertEqual(analysis["new_files_count"], 2)
        self.assertEqual(analysis["already_exists_count"], 0)
        self.assertTrue(analysis["has_gallery_data"])
        self.assertTrue(analysis["has_hashes_db"])
        self.assertTrue(analysis["has_sync_db"])

        # 4. Execute Migration
        res = execute_import_folder(str(self.src_dir), str(self.tgt_dir))
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["copied_count"], 2)
        self.assertEqual(res["skipped_count"], 0)

        # Verify files now exist in target
        self.assertTrue((self.tgt_dir / "Alice_Smith" / "2024-05" / "IMG-20240501-WA0001.jpg").is_file())
        self.assertTrue((self.tgt_dir / "Bob_Jones" / "2024-05" / "VID-20240502-WA0002.mp4").is_file())
        self.assertTrue((self.tgt_dir / "Charlie_Brown" / "2024-06" / "IMG-20240601-WA0001.jpg").is_file())

        # Verify merged gallery_data.js has both Alice and Charlie and synthesized Bob
        from core.gallery import parse_gallery_data_js
        with open(self.tgt_dir / "gallery_data.js", "r", encoding="utf-8") as f:
            merged_data = parse_gallery_data_js(f.read())

        chat_names = {c["name"] for c in merged_data["chats"]}
        self.assertIn("Alice Smith", chat_names)
        self.assertIn("Charlie Brown", chat_names)
        self.assertIn("Bob_Jones", chat_names)

        # Verify merged .hashes_cache.sqlite3
        tgt_hash_db = self.tgt_dir / ".hashes_cache.sqlite3"
        self.assertTrue(tgt_hash_db.is_file())
        t_conn = sqlite3.connect(str(tgt_hash_db))
        cur = t_conn.cursor()
        cur.execute("SELECT md5 FROM file_hashes WHERE md5 = 'alice_md5_hash'")
        self.assertIsNotNone(cur.fetchone())
        t_conn.close()

        # Verify merged .sync_state.sqlite3
        tgt_sync_db = self.tgt_dir / ".sync_state.sqlite3"
        self.assertTrue(tgt_sync_db.is_file())
        s_conn = sqlite3.connect(str(tgt_sync_db))
        cur = s_conn.cursor()
        cur.execute("SELECT status FROM sync_manifest WHERE rel_path LIKE '%IMG-20240501-WA0001.jpg'")
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "completed")
        s_conn.close()

    def test_03_collision_and_skip_behavior(self):
        # Setup duplicate file with same size (should skip)
        src_chat = self.src_dir / "Test_Chat" / "2024-01"
        src_chat.mkdir(parents=True)
        (src_chat / "same.jpg").write_bytes(b"IDENTICAL_CONTENT")

        # Setup duplicate file with different size (should rename with _imported)
        (src_chat / "diff.jpg").write_bytes(b"OLDER_DIFFERENT_CONTENT")

        tgt_chat = self.tgt_dir / "Test_Chat" / "2024-01"
        tgt_chat.mkdir(parents=True)
        (tgt_chat / "same.jpg").write_bytes(b"IDENTICAL_CONTENT")
        (tgt_chat / "diff.jpg").write_bytes(b"NEWER_TARGET_CONTENT_LONGER_BYTES")

        analysis = analyze_import_folder(str(self.src_dir), str(self.tgt_dir))
        self.assertEqual(analysis["media_count"], 2)
        self.assertEqual(analysis["already_exists_count"], 1)
        self.assertEqual(analysis["collision_count"], 1)

        res = execute_import_folder(str(self.src_dir), str(self.tgt_dir))
        self.assertEqual(res["copied_count"], 1)
        self.assertEqual(res["skipped_count"], 1)

        # Original diff.jpg in target must be preserved untouched
        self.assertEqual((tgt_chat / "diff.jpg").read_bytes(), b"NEWER_TARGET_CONTENT_LONGER_BYTES")
        # Colliding file from source must be safely saved as _imported_1
        self.assertTrue((tgt_chat / "diff_imported_1.jpg").is_file())
        self.assertEqual((tgt_chat / "diff_imported_1.jpg").read_bytes(), b"OLDER_DIFFERENT_CONTENT")


if __name__ == "__main__":
    unittest.main()
