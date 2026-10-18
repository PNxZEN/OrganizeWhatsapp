"""
Unit and Integration Tests for Clean Planner & Storage Reclaim Engine.
Tests:
- Media type categorization
- Age & inactivity calculations
- 3-Point Pre-Purge local backup verification
- Smart Reclaim, Video Offload, and Custom profiles
- Protection shields (<30d floor, starred favorites, excluded chats)
- Plan execution orchestration
"""

import hashlib
import os
import shutil
import tempfile
import time
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest import mock

from core.clean_planner import (
    CleanProfile,
    categorize_media_type,
    calculate_item_age_days,
    calculate_inactivity_days,
    verify_local_backup,
    generate_clean_plan,
    execute_clean_plan,
    _ACTIVE_PLANS,
)


class TestCleanPlanner(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="wa_test_planner_")
        self.out_p = Path(self.temp_dir)
        _ACTIVE_PLANS.clear()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        _ACTIVE_PLANS.clear()

    def test_categorize_media_type(self):
        self.assertEqual(categorize_media_type("sticker.webp"), "stickers")
        self.assertEqual(categorize_media_type("animated_sticker_123.bin"), "stickers")
        self.assertEqual(categorize_media_type("report.pdf"), "documents")
        self.assertEqual(categorize_media_type("file.bin", is_doc=True), "documents")
        self.assertEqual(categorize_media_type("clip.mp4"), "videos")
        self.assertEqual(categorize_media_type("clip.unknown", mime_type="video/mp4"), "videos")
        self.assertEqual(categorize_media_type("photo.jpg"), "photos")
        self.assertEqual(categorize_media_type("image.png", mime_type="image/png"), "photos")
        self.assertEqual(categorize_media_type("voice.opus"), "audio")
        self.assertEqual(categorize_media_type("track.mp3", mime_type="audio/mpeg"), "audio")
        self.assertEqual(categorize_media_type("unknown.xyz"), "other")

    def test_calculate_item_age_days(self):
        now_dt = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)
        now_s = now_dt.timestamp()

        # 10 days ago
        ten_days_ago = (now_dt - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
        age = calculate_item_age_days(ten_days_ago, now_epoch_s=now_s)
        self.assertAlmostEqual(age, 10.0, places=1)

        # 100 days ago
        hundred_days_ago = (now_dt - timedelta(days=100)).strftime("%Y-%m-%d %H:%M:%S")
        age = calculate_item_age_days(hundred_days_ago, now_epoch_s=now_s)
        self.assertAlmostEqual(age, 100.0, places=1)

        # Future date floored to 0
        future = (now_dt + timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
        self.assertEqual(calculate_item_age_days(future, now_epoch_s=now_s), 0.0)

        # Invalid/empty date returns fallback 9999.0
        self.assertEqual(calculate_item_age_days("", now_epoch_s=now_s), 9999.0)
        self.assertEqual(calculate_item_age_days("not-a-date", now_epoch_s=now_s), 9999.0)

    def test_calculate_inactivity_days(self):
        now_ms = 1791400000000  # fixed epoch ms

        # 20 days inactive (20 * 86400 * 1000 = 1728000000 ms)
        twenty_days_ms = now_ms - (20 * 86400 * 1000)
        self.assertAlmostEqual(calculate_inactivity_days(twenty_days_ms, now_epoch_ms=now_ms), 20.0, places=1)

        # 200 days inactive
        two_hundred_days_ms = now_ms - (200 * 86400 * 1000)
        self.assertAlmostEqual(calculate_inactivity_days(two_hundred_days_ms, now_epoch_ms=now_ms), 200.0, places=1)

        # 0 or None returns 9999.0
        self.assertEqual(calculate_inactivity_days(0, now_epoch_ms=now_ms), 9999.0)
        self.assertEqual(calculate_inactivity_days(None, now_epoch_ms=now_ms), 9999.0)

    def test_verify_local_backup(self):
        rel_path = "Alice/photo.jpg"
        full_path = self.out_p / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)

        content = b"TEST_IMAGE_BYTES_12345"
        size = len(content)
        md5_hash = hashlib.md5(content).hexdigest()

        with open(full_path, "wb") as f:
            f.write(content)

        # 1. Valid file, size matches, hash matches
        ok, err = verify_local_backup(self.out_p, rel_path, size, md5_hash)
        self.assertTrue(ok)
        self.assertIsNone(err)

        # 2. Missing file
        ok, err = verify_local_backup(self.out_p, "Nonexistent/img.jpg", 100)
        self.assertFalse(ok)
        self.assertIn("Local backup copy missing", err)

        # 3. Size mismatch
        ok, err = verify_local_backup(self.out_p, rel_path, size + 50)
        self.assertFalse(ok)
        self.assertIn("Size mismatch", err)

        # 4. Hash mismatch
        ok, err = verify_local_backup(self.out_p, rel_path, size, "00000000000000000000000000000000")
        self.assertFalse(ok)
        self.assertIn("Cryptographic hash mismatch", err)

        # 5. Empty file
        empty_rel = "Alice/empty.jpg"
        empty_path = self.out_p / empty_rel
        empty_path.touch()
        ok, err = verify_local_backup(self.out_p, empty_rel, 0)
        self.assertFalse(ok)
        self.assertIn("empty", err)

    def _create_mock_media(self, rel_path: str, size: int) -> dict:
        full = self.out_p / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        with open(full, "wb") as f:
            f.write(b"X" * size)
        md5 = hashlib.md5(b"X" * size).hexdigest()
        return {
            "full_path": full,
            "md5": md5,
            "size": size,
        }

    def test_generate_clean_plan_smart_reclaim(self):
        now_dt = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)
        now_ms = int(now_dt.timestamp() * 1000)

        # Candidate 1: Large video >15MB, 120 days old (Eligible for smart reclaim)
        f1 = self._create_mock_media("ChatA/big_video.mp4", 16 * 1024 * 1024)
        c1_ts = (now_dt - timedelta(days=120)).strftime("%Y-%m-%d %H:%M:%S")

        # Candidate 2: Media in archived chat, 80 days old (Eligible)
        f2 = self._create_mock_media("ArchivedChat/photo.jpg", 2 * 1024 * 1024)
        c2_ts = (now_dt - timedelta(days=80)).strftime("%Y-%m-%d %H:%M:%S")

        # Candidate 3: Media in inactive group (last active 200 days ago), 90 days old (Eligible)
        f3 = self._create_mock_media("OldGroup/meme.jpg", 1 * 1024 * 1024)
        c3_ts = (now_dt - timedelta(days=90)).strftime("%Y-%m-%d %H:%M:%S")

        # Protected 1: Recent video <30 days old (10 days old) -> SHIELDED
        f4 = self._create_mock_media("ChatA/recent_big.mp4", 20 * 1024 * 1024)
        c4_ts = (now_dt - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")

        # Protected 2: Starred photo in archived chat -> SHIELDED
        f5 = self._create_mock_media("ArchivedChat/favorite.jpg", 3 * 1024 * 1024)
        c5_ts = (now_dt - timedelta(days=90)).strftime("%Y-%m-%d %H:%M:%S")

        # Protected 3: Excluded chat item -> SHIELDED
        f6 = self._create_mock_media("FamilyGroup/clip.mp4", 25 * 1024 * 1024)
        c6_ts = (now_dt - timedelta(days=120)).strftime("%Y-%m-%d %H:%M:%S")

        records = [
            {
                "rel_path": "ChatA/big_video.mp4",
                "phone_path": "/storage/emulated/0/WhatsApp/Media/WhatsApp Video/big_video.mp4",
                "filename": "big_video.mp4",
                "size_bytes": f1["size"],
                "md5": f1["md5"],
                "mime_type": "video/mp4",
                "received_at": c1_ts,
                "chat_jid": "chata@s.whatsapp.net",
                "chat_name": "Chat A",
                "starred": 0,
                "chat_archived": 0,
                "chat_last_active_ts": now_ms,
            },
            {
                "rel_path": "ArchivedChat/photo.jpg",
                "phone_path": "/storage/emulated/0/WhatsApp/Media/WhatsApp Images/photo.jpg",
                "filename": "photo.jpg",
                "size_bytes": f2["size"],
                "md5": f2["md5"],
                "mime_type": "image/jpeg",
                "received_at": c2_ts,
                "chat_jid": "archived@s.whatsapp.net",
                "chat_name": "Archived Chat",
                "starred": 0,
                "chat_archived": 1,
                "chat_last_active_ts": now_ms - (90 * 86400 * 1000),
            },
            {
                "rel_path": "OldGroup/meme.jpg",
                "phone_path": "/storage/emulated/0/WhatsApp/Media/WhatsApp Images/meme.jpg",
                "filename": "meme.jpg",
                "size_bytes": f3["size"],
                "md5": f3["md5"],
                "mime_type": "image/jpeg",
                "received_at": c3_ts,
                "chat_jid": "oldgroup@g.us",
                "chat_name": "Old Group",
                "starred": 0,
                "chat_archived": 0,
                "chat_last_active_ts": now_ms - (200 * 86400 * 1000),  # >180d inactive
                "is_group": True,
            },
            {
                "rel_path": "ChatA/recent_big.mp4",
                "phone_path": "/storage/emulated/0/WhatsApp/Media/WhatsApp Video/recent_big.mp4",
                "filename": "recent_big.mp4",
                "size_bytes": f4["size"],
                "md5": f4["md5"],
                "mime_type": "video/mp4",
                "received_at": c4_ts,
                "chat_jid": "chata@s.whatsapp.net",
                "chat_name": "Chat A",
                "starred": 0,
                "chat_archived": 0,
                "chat_last_active_ts": now_ms,
            },
            {
                "rel_path": "ArchivedChat/favorite.jpg",
                "phone_path": "/storage/emulated/0/WhatsApp/Media/WhatsApp Images/favorite.jpg",
                "filename": "favorite.jpg",
                "size_bytes": f5["size"],
                "md5": f5["md5"],
                "mime_type": "image/jpeg",
                "received_at": c5_ts,
                "chat_jid": "archived@s.whatsapp.net",
                "chat_name": "Archived Chat",
                "starred": 1,  # STARRED
                "chat_archived": 1,
                "chat_last_active_ts": now_ms - (90 * 86400 * 1000),
            },
            {
                "rel_path": "FamilyGroup/clip.mp4",
                "phone_path": "/storage/emulated/0/WhatsApp/Media/WhatsApp Video/clip.mp4",
                "filename": "clip.mp4",
                "size_bytes": f6["size"],
                "md5": f6["md5"],
                "mime_type": "video/mp4",
                "received_at": c6_ts,
                "chat_jid": "family@g.us",
                "chat_name": "Family Group",
                "starred": 0,
                "chat_archived": 0,
                "chat_last_active_ts": now_ms,
            },
        ]

        plan = generate_clean_plan(
            output_dir=str(self.out_p),
            profile=CleanProfile.SMART_RECLAIM,
            custom_config={"exclude_jids": ["family@g.us"]},
            media_rows=records,
            now_epoch_ms=now_ms,
        )

        self.assertEqual(plan["reclaimable_files_count"], 3)
        self.assertEqual(plan["protected_files_count"], 3)
        self.assertEqual(plan["profile"], CleanProfile.SMART_RECLAIM)
        self.assertEqual(plan["reclaimable_bytes"], f1["size"] + f2["size"] + f3["size"])

        # Check candidate reasons
        candidate_reasons = {c["filename"]: c["reason"] for c in plan["candidates"]}
        self.assertEqual(candidate_reasons["big_video.mp4"], "large_videos")
        self.assertEqual(candidate_reasons["photo.jpg"], "archived_chats")
        self.assertEqual(candidate_reasons["meme.jpg"], "inactive_groups")

        # Verify plan is cached in active plans
        self.assertIn(plan["plan_id"], _ACTIVE_PLANS)

    def test_generate_clean_plan_video_offload(self):
        now_dt = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)
        now_ms = int(now_dt.timestamp() * 1000)

        # 40 days old video -> Candidate
        f1 = self._create_mock_media("Alice/old_video.mp4", 5 * 1024 * 1024)
        c1_ts = (now_dt - timedelta(days=40)).strftime("%Y-%m-%d %H:%M:%S")

        # 10 days old video -> Protected (<30d)
        f2 = self._create_mock_media("Alice/new_video.mp4", 5 * 1024 * 1024)
        c2_ts = (now_dt - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")

        # 50 days old photo -> Protected (Only videos offloaded in this profile)
        f3 = self._create_mock_media("Alice/old_photo.jpg", 2 * 1024 * 1024)
        c3_ts = (now_dt - timedelta(days=50)).strftime("%Y-%m-%d %H:%M:%S")

        records = [
            {
                "rel_path": "Alice/old_video.mp4",
                "phone_path": "/storage/emulated/0/WhatsApp/Media/WhatsApp Video/old_video.mp4",
                "filename": "old_video.mp4",
                "size_bytes": f1["size"],
                "md5": f1["md5"],
                "mime_type": "video/mp4",
                "received_at": c1_ts,
                "chat_jid": "alice@s.whatsapp.net",
                "chat_name": "Alice",
            },
            {
                "rel_path": "Alice/new_video.mp4",
                "phone_path": "/storage/emulated/0/WhatsApp/Media/WhatsApp Video/new_video.mp4",
                "filename": "new_video.mp4",
                "size_bytes": f2["size"],
                "md5": f2["md5"],
                "mime_type": "video/mp4",
                "received_at": c2_ts,
                "chat_jid": "alice@s.whatsapp.net",
                "chat_name": "Alice",
            },
            {
                "rel_path": "Alice/old_photo.jpg",
                "phone_path": "/storage/emulated/0/WhatsApp/Media/WhatsApp Images/old_photo.jpg",
                "filename": "old_photo.jpg",
                "size_bytes": f3["size"],
                "md5": f3["md5"],
                "mime_type": "image/jpeg",
                "received_at": c3_ts,
                "chat_jid": "alice@s.whatsapp.net",
                "chat_name": "Alice",
            },
        ]

        plan = generate_clean_plan(
            output_dir=str(self.out_p),
            profile=CleanProfile.VIDEO_OFFLOAD,
            media_rows=records,
            now_epoch_ms=now_ms,
        )

        self.assertEqual(plan["reclaimable_files_count"], 1)
        self.assertEqual(plan["candidates"][0]["filename"], "old_video.mp4")
        self.assertEqual(plan["protected_files_count"], 1)  # recent video protected

    def test_generate_clean_plan_custom_profile(self):
        now_dt = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)
        now_ms = int(now_dt.timestamp() * 1000)

        # 45 days old photo in target archived chat
        f1 = self._create_mock_media("ArchivedChat/doc.pdf", 4 * 1024 * 1024)
        c1_ts = (now_dt - timedelta(days=45)).strftime("%Y-%m-%d %H:%M:%S")

        # 45 days old photo in normal chat
        f2 = self._create_mock_media("NormalChat/pic.jpg", 1 * 1024 * 1024)
        c2_ts = (now_dt - timedelta(days=45)).strftime("%Y-%m-%d %H:%M:%S")

        records = [
            {
                "rel_path": "ArchivedChat/doc.pdf",
                "phone_path": "/storage/emulated/0/WhatsApp/Media/WhatsApp Documents/doc.pdf",
                "filename": "doc.pdf",
                "size_bytes": f1["size"],
                "md5": f1["md5"],
                "is_doc": True,
                "received_at": c1_ts,
                "chat_jid": "archived@s.whatsapp.net",
                "chat_name": "Archived Chat",
                "chat_archived": 1,
            },
            {
                "rel_path": "NormalChat/pic.jpg",
                "phone_path": "/storage/emulated/0/WhatsApp/Media/WhatsApp Images/pic.jpg",
                "filename": "pic.jpg",
                "size_bytes": f2["size"],
                "md5": f2["md5"],
                "mime_type": "image/jpeg",
                "received_at": c2_ts,
                "chat_jid": "normal@s.whatsapp.net",
                "chat_name": "Normal Chat",
                "chat_archived": 0,
            },
        ]

        # Custom config: Target only documents, archived chats only, min age 30
        custom_cfg = {
            "media_types": ["documents"],
            "min_age_days": 30,
            "target_archived": True,
            "target_inactive_groups": False,
        }

        plan = generate_clean_plan(
            output_dir=str(self.out_p),
            profile=CleanProfile.CUSTOM,
            custom_config=custom_cfg,
            media_rows=records,
            now_epoch_ms=now_ms,
        )

        self.assertEqual(plan["reclaimable_files_count"], 1)
        self.assertEqual(plan["candidates"][0]["filename"], "doc.pdf")

    def test_execute_clean_plan(self):
        # 1. Invalid plan id
        res = execute_clean_plan("non-existent-id", output_dir=str(self.out_p))
        self.assertFalse(res["success"])
        self.assertIn("not found", res["error"])

        # 2. Valid plan execution with mocked batch_delete_phone_files
        now_dt = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)
        f1 = self._create_mock_media("ChatA/video.mp4", 5 * 1024 * 1024)
        c1_ts = (now_dt - timedelta(days=60)).strftime("%Y-%m-%d %H:%M:%S")

        records = [
            {
                "rel_path": "ChatA/video.mp4",
                "phone_path": "/storage/emulated/0/WhatsApp/Media/WhatsApp Video/video.mp4",
                "filename": "video.mp4",
                "size_bytes": f1["size"],
                "md5": f1["md5"],
                "mime_type": "video/mp4",
                "received_at": c1_ts,
                "chat_jid": "chata@s.whatsapp.net",
                "chat_name": "Chat A",
            }
        ]

        plan = generate_clean_plan(
            output_dir=str(self.out_p),
            profile=CleanProfile.VIDEO_OFFLOAD,
            media_rows=records,
            now_epoch_ms=int(now_dt.timestamp() * 1000),
        )
        plan_id = plan["plan_id"]

        with mock.patch("core.adb.batch_delete_phone_files") as mock_del:
            mock_del.return_value = {
                "success": True,
                "deleted_count": 1,
                "failed_count": 0,
                "errors": [],
            }
            exec_res = execute_clean_plan(plan_id, output_dir=str(self.out_p))
            self.assertTrue(exec_res["success"])
            self.assertEqual(exec_res["deleted_count"], 1)
            mock_del.assert_called_once()


if __name__ == "__main__":
    unittest.main()
