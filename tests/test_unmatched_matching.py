"""
Unit tests for unmatched media matching improvements:
- Eliminating .nomedia and .Links/ web preview icons
- Preserving real human-readable media_name for documents
- Matching stickers via hash
- Routing sticker packs to output/Stickers/Sticker Packs/
- Unambiguous exact byte size fallback matching
- Reorganizing existing unmatched media
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from core.organizer import (
    StreamingMediaRouter,
    reorganize_unmatched_media,
    sanitize_filename,
    sanitize_folder_name,
)
from core.adb import is_skippable_system_path


class TestUnmatchedMediaMatching(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="wa_test_unmatched_")
        self.output_dir = Path(self.test_dir) / "output"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_skippable_system_paths(self):
        """Verify .nomedia and .Links/ thumbnail previews are identified as skippable."""
        self.assertTrue(is_skippable_system_path(".nomedia"))
        self.assertTrue(is_skippable_system_path("Media/.nomedia"))
        self.assertTrue(is_skippable_system_path("Media/WhatsApp Images/.nomedia"))
        self.assertTrue(is_skippable_system_path("Media/.Links/0022dd85e42985e1ad9d816fa76b3182"))
        self.assertTrue(is_skippable_system_path(".Links/abcd1234efgh"))
        
        # Real media should NOT be skippable
        self.assertFalse(is_skippable_system_path("Media/WhatsApp Images/IMG-20241026-WA0035.jpg"))
        self.assertFalse(is_skippable_system_path("Media/WhatsApp Documents/cbjescss08.pdf"))

    def test_router_skips_nomedia_and_links(self):
        """Verify resolve_destination returns (None, None) for .nomedia and .Links/."""
        router = StreamingMediaRouter(self.output_dir, media_rows=[])
        
        dest_p, row = router.resolve_destination(".nomedia", 0)
        self.assertIsNone(dest_p)
        self.assertIsNone(row)

        dest_p, row = router.resolve_destination("Media/.Links/0022dd85e42985e1ad9d816fa76b3182", 1520)
        self.assertIsNone(dest_p)
        self.assertIsNone(row)

    def test_document_media_name_preservation(self):
        """Verify real document media_name is prioritized over internal .Shared paths."""
        media_rows = [
            {
                "chat_jid": "919876543210@s.whatsapp.net",
                "chat_name": "Class Group",
                "filename": "cbjescss08.pdf",
                "media_name": "cbjescss08.pdf",
                "file_path": "/data/user/0/com.whatsapp/files/.Shared/3e459a93f18b31a28a3f8902d",
                "size_bytes": 1048576,
                "mime_type": "application/pdf",
                "received_at": "2024-11-15 10:30:00",
                "message_type": 9,
            }
        ]
        router = StreamingMediaRouter(self.output_dir, media_rows=media_rows)

        # Incoming file matches by real filename
        dest_p, matched_row = router.resolve_destination("Media/WhatsApp Documents/cbjescss08.pdf", 1048576)
        self.assertIsNotNone(matched_row)
        self.assertIsNotNone(dest_p)
        self.assertEqual(dest_p.name, "cbjescss08.pdf")
        self.assertIn("Class Group", dest_p.as_posix())
        self.assertIn("2024-11", dest_p.as_posix())

    def test_sticker_hash_matching(self):
        """Verify stickers match against Base64 SHA-256 hash or hex hash."""
        media_rows = [
            {
                "chat_jid": "919999999999@s.whatsapp.net",
                "chat_name": "Alice",
                "filename": "+ZWEcA7wLz9l1Qx=.webp",
                "file_hash": "+ZWEcA7wLz9l1Qx=",
                "enc_file_hash": "enc_hash_123",
                "size_bytes": 45000,
                "mime_type": "image/webp",
                "received_at": "2024-10-01 12:00:00",
                "message_type": 20,
            }
        ]
        router = StreamingMediaRouter(self.output_dir, media_rows=media_rows)

        # Phone file has the hash as filename
        dest_p, matched_row = router.resolve_destination("Media/WhatsApp Stickers/+ZWEcA7wLz9l1Qx=.webp", 45000)
        self.assertIsNotNone(matched_row)
        self.assertIn("Alice", dest_p.as_posix())
        self.assertIn("2024-10", dest_p.as_posix())

    def test_sticker_pack_routing(self):
        """Verify downloaded sticker pack assets route to Stickers/Sticker Packs/."""
        router = StreamingMediaRouter(self.output_dir, media_rows=[])
        dest_p, matched_row = router.resolve_destination(
            "Media/WhatsApp Backup Excluded Stickers/pack_item_001.webp", 12345
        )
        self.assertIsNone(matched_row)
        self.assertIn("Stickers/Sticker Packs", dest_p.as_posix())

    def test_unambiguous_exact_size_matching(self):
        """Verify unambiguous exact byte size matches when filename was modified or orphaned."""
        media_rows = [
            {
                "chat_jid": "918888888888@s.whatsapp.net",
                "chat_name": "Bob",
                "filename": "camera_capture_unique.jpg",
                "file_path": "/data/user/0/com.whatsapp/files/camera_capture_unique.jpg",
                "size_bytes": 987654,
                "mime_type": "image/jpeg",
                "received_at": "2024-08-20 18:45:00",
                "message_type": 1,
            }
        ]
        router = StreamingMediaRouter(self.output_dir, media_rows=media_rows)

        # Phone file has a different name (e.g. from in-app camera or internal cache)
        dest_p, matched_row = router.resolve_destination("Media/IMG-20240820-WA0001.jpg", 987654)
        self.assertIsNotNone(matched_row)
        self.assertEqual(matched_row["chat_name"], "Bob")
        self.assertIn("Bob", dest_p.as_posix())

    def test_reorganize_unmatched_media(self):
        """Verify reorganize_unmatched_media purges junk and rematches media in output/_unmatched/."""
        unmatched_dir = self.output_dir / "_unmatched"
        unmatched_dir.mkdir(parents=True, exist_ok=True)

        # 1. Create junk .nomedia and .Links
        (unmatched_dir / ".nomedia").touch()
        links_dir = unmatched_dir / ".Links"
        links_dir.mkdir(parents=True, exist_ok=True)
        (links_dir / "icon_hash123").write_bytes(b"preview_data")

        # 2. Create sticker pack file
        sticker_pack_dir = unmatched_dir / "WhatsApp Backup Excluded Stickers"
        sticker_pack_dir.mkdir(parents=True, exist_ok=True)
        sticker_file = sticker_pack_dir / "sticker1.webp"
        sticker_file.write_bytes(b"sticker_pack_asset")

        # 3. Create a matchable media file (by exact filename or size)
        images_dir = unmatched_dir / "WhatsApp Images"
        images_dir.mkdir(parents=True, exist_ok=True)
        media_file = images_dir / "IMG-20241026-WA0035.jpg"
        media_file.write_bytes(b"sample_image_data_32564")

        # 4. Create an unmatchable file (orphaned deleted chat)
        orphan_file = images_dir / "IMG-orphan-no-db.jpg"
        orphan_file.write_bytes(b"orphan_image_content")

        # Create mock gallery_data.js
        gallery_data_js = self.output_dir / "gallery_data.js"
        mock_data = {
            "chats": [
                {
                    "jid": "_unmatched",
                    "name": "_unmatched",
                    "total_size": 1000,
                    "file_count": 5,
                    "media": [
                        {"filename": ".nomedia", "rel_path": "_unmatched/.nomedia", "size_bytes": 0},
                        {"filename": "icon_hash123", "rel_path": "_unmatched/.Links/icon_hash123", "size_bytes": 12},
                        {"filename": "IMG-20241026-WA0035.jpg", "rel_path": "_unmatched/WhatsApp Images/IMG-20241026-WA0035.jpg", "size_bytes": len(b"sample_image_data_32564")},
                    ],
                }
            ]
        }
        gallery_data_js.write_text(f"const GALLERY_DATA = {json.dumps(mock_data)};", encoding="utf-8")

        media_rows = [
            {
                "chat_jid": "group123@g.us",
                "chat_name": "Lost and Found",
                "filename": "IMG-20241026-WA0035.jpg",
                "size_bytes": len(b"sample_image_data_32564"),
                "mime_type": "image/jpeg",
                "received_at": "2024-10-26 14:00:00",
                "message_type": 1,
            }
        ]

        summary = reorganize_unmatched_media(
            output_dir=str(self.output_dir),
            media_rows=media_rows,
        )

        # Verify summary counts
        self.assertEqual(summary["deleted_nomedia"], 1)
        self.assertEqual(summary["deleted_links"], 1)
        self.assertEqual(summary["rematched"], 1)
        self.assertEqual(summary["sticker_packs"], 1)
        self.assertEqual(summary["still_unmatched"], 1)

        # Verify files on disk
        self.assertFalse((unmatched_dir / ".nomedia").exists())
        self.assertFalse(links_dir.exists())
        self.assertFalse(sticker_file.exists())
        self.assertTrue((self.output_dir / "Stickers" / "Sticker Packs" / "sticker1.webp").is_file())
        self.assertTrue((self.output_dir / "Lost and Found" / "2024-10" / "IMG-20241026-WA0035.jpg").is_file())
        self.assertTrue(orphan_file.is_file())

        # Verify gallery_data.js was cleaned and updated
        with open(gallery_data_js, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn(".nomedia", content)
        self.assertNotIn(".Links", content)
        self.assertIn("Lost and Found", content)

    def test_sanitize_folder_name_trailing_space_and_reserved_names(self):
        """Verify folder names truncated at max_len strip trailing spaces/dots and escape reserved names."""
        # Exact chat name from the user's error log that previously truncated with a trailing space at char 60
        long_name = "Krishaay IIT Mandi Intern Thapar Btech CSE 27 Curly Hair On The Way"
        sanitized = sanitize_folder_name(long_name, max_len=60)
        self.assertFalse(sanitized.endswith(" "), f"Sanitized folder name must not end with space: {repr(sanitized)}")
        self.assertFalse(sanitized.endswith("."), f"Sanitized folder name must not end with dot: {repr(sanitized)}")
        self.assertEqual(sanitized, "Krishaay IIT Mandi Intern Thapar Btech CSE 27 Curly Hair On")

        # Test Windows reserved names
        for res_name in ["CON", "PRN", "AUX", "NUL", "COM1", "LPT1"]:
            safe_folder = sanitize_folder_name(res_name)
            self.assertTrue(safe_folder.startswith("_"), f"Reserved folder name {res_name} must be escaped")
            safe_file = sanitize_filename(f"{res_name}.txt")
            self.assertTrue(safe_file.startswith("_"), f"Reserved filename {res_name}.txt must be escaped")

        # Test that router successfully creates the folder and resolves destination without WinError 3
        router = StreamingMediaRouter(
            self.output_dir,
            media_rows=[
                {
                    "chat_jid": "krishaay@s.whatsapp.net",
                    "chat_name": long_name,
                    "filename": "test_photo.jpg",
                    "size_bytes": 1234,
                    "received_at": "2026-06-15 10:00:00",
                }
            ],
        )
        dest_p, row = router.resolve_destination("test_photo.jpg", 1234)
        self.assertIsNotNone(dest_p)
        self.assertTrue(dest_p.parent.exists())


if __name__ == "__main__":
    unittest.main()

