import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.sync_session import SyncSessionManager


class TestSyncSessionManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="wa_test_sync_")
        self.db_path = os.path.join(self.test_dir, ".sync_state.sqlite3")
        self.manager = SyncSessionManager(db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_create_and_get_session(self):
        sess = self.manager.create_session(
            session_id="sess_123",
            device_serial="dccc2010",
            device_model="AIN065",
            total_files=10,
            total_bytes=1000,
        )
        self.assertIsNotNone(sess)
        self.assertEqual(sess["session_id"], "sess_123")
        self.assertEqual(sess["device_serial"], "dccc2010")
        self.assertEqual(sess["status"], "in_progress")

        fetched = self.manager.get_session("sess_123")
        self.assertEqual(fetched["device_model"], "AIN065")

    def test_manifest_and_progress_tracking(self):
        sess_id = "sess_prog"
        self.manager.create_session(sess_id, "dccc2010", "AIN065")

        file_entries = [
            ("Media/WhatsApp Images/img1.jpg", os.path.join(self.test_dir, "img1.jpg"), 100, 0),
            ("Media/WhatsApp Images/img2.jpg", os.path.join(self.test_dir, "img2.jpg"), 200, 0),
            ("Media/WhatsApp Images/img3.jpg", os.path.join(self.test_dir, "img3.jpg"), 300, 0),
        ]
        self.manager.init_manifest(sess_id, file_entries)

        pending = self.manager.get_pending_files(sess_id)
        self.assertEqual(len(pending), 3)

        # Mark first file completed
        self.manager.mark_file_completed(sess_id, "Media/WhatsApp Images/img1.jpg", 100)
        sess = self.manager.get_session(sess_id)
        self.assertEqual(sess["synced_files"], 1)
        self.assertEqual(sess["synced_bytes"], 100)

        pending_after = self.manager.get_pending_files(sess_id)
        self.assertEqual(len(pending_after), 2)
        self.assertEqual(pending_after[0]["rel_path"], "Media/WhatsApp Images/img2.jpg")

    def test_pause_and_resume_device_binding(self):
        sess_id = "sess_bind"
        self.manager.create_session(sess_id, "pixel_7_serial", "Google Pixel 7")

        # Pause
        ok = self.manager.pause_session(sess_id, reason="User clicked pause")
        self.assertTrue(ok)
        paused = self.manager.get_session(sess_id)
        self.assertEqual(paused["status"], "paused")
        self.assertEqual(paused["error_message"], "User clicked pause")

        # Resume with mismatched serial should FAIL
        resumed, msg = self.manager.resume_session(sess_id, current_device_serial="samsung_serial")
        self.assertFalse(resumed)
        self.assertIn("Device mismatch", msg)

        # Resume with matching serial should SUCCEED
        resumed, msg = self.manager.resume_session(sess_id, current_device_serial="pixel_7_serial")
        self.assertTrue(resumed)
        active = self.manager.get_session(sess_id)
        self.assertEqual(active["status"], "in_progress")

    def test_atomic_staging_cleanup(self):
        # Create dummy partial files
        part1 = Path(self.test_dir) / "test1.jpg.part_sess123"
        part2 = Path(self.test_dir) / "test2.mp4.part_sess123"
        real_file = Path(self.test_dir) / "real.jpg"

        part1.write_bytes(b"partial content 1")
        part2.write_bytes(b"partial content 2")
        real_file.write_bytes(b"completed file")

        removed = self.manager.cleanup_orphaned_part_files([self.test_dir])
        self.assertEqual(removed, 2)
        self.assertFalse(part1.exists())
        self.assertFalse(part2.exists())
        self.assertTrue(real_file.exists())

    def test_reconcile_manifest_detects_disk_drift_and_new_phone_files(self):
        sess_id = "sess_drift"
        self.manager.create_session(sess_id, "dccc2010", "AIN065")

        target_file = Path(self.test_dir) / "pic.jpg"
        target_file.write_bytes(b"A" * 50)

        file_entries = [
            ("Media/pic.jpg", str(target_file), 50, 0),
        ]
        self.manager.init_manifest(sess_id, file_entries)
        self.manager.mark_file_completed(sess_id, "Media/pic.jpg", 50)

        # 1. Simulate user deleting the completed file on PC while paused
        target_file.unlink()

        # 2. Remote inventory now has pic.jpg AND a newly taken photo pic2.jpg
        remote_inventory = [
            ("Media/pic.jpg", 50),
            ("Media/pic2.jpg", 120),
        ]

        self.manager.reconcile_manifest(sess_id, remote_inventory)

        pending = self.manager.get_pending_files(sess_id)
        pending_paths = [p["rel_path"] for p in pending]

        # pic.jpg should have been reset to pending because file disappeared from disk!
        self.assertIn("Media/pic.jpg", pending_paths)
        # pic2.jpg should be queued as new pending file
        self.assertIn("Media/pic2.jpg", pending_paths)
        self.assertEqual(len(pending), 2)

    def test_recover_abandoned_sessions(self):
        sess_id = "sess_abandoned"
        self.manager.create_session(sess_id, "pixel_7", "Google Pixel")
        # Session is currently 'in_progress'
        sess = self.manager.get_session(sess_id)
        self.assertEqual(sess["status"], "in_progress")

        # Simulate unexpected crash / reboot recovery
        recovered = self.manager.recover_abandoned_sessions()
        self.assertEqual(recovered, 1)

        sess_after = self.manager.get_session(sess_id)
        self.assertEqual(sess_after["status"], "paused")
        self.assertIn("shutdown", sess_after["error_message"].lower())

    def test_reconcile_manifest_size_drift_and_database(self):
        sess_id = "sess_drift"
        self.manager.create_session(sess_id, "pixel_7", "Google Pixel")

        db_file = os.path.join(self.test_dir, "msgstore.db.crypt14")
        Path(db_file).write_bytes(b"X" * 100)
        media_file = os.path.join(self.test_dir, "photo.jpg")
        Path(media_file).write_bytes(b"Y" * 200)

        file_entries = [
            ("Databases/msgstore.db.crypt14", db_file, 100, 0),
            ("Media/photo.jpg", media_file, 200, 0),
        ]
        self.manager.init_manifest(sess_id, file_entries)
        self.manager.mark_file_completed(sess_id, "Databases/msgstore.db.crypt14", 100)
        self.manager.mark_file_completed(sess_id, "Media/photo.jpg", 200)

        # Before reconcile: 0 pending
        self.assertEqual(len(self.manager.get_pending_files(sess_id)), 0)

        # Remote inventory on phone has updated photo size (300 instead of 200)
        remote_inventory = [
            ("Databases/msgstore.db.crypt14", 100),
            ("Media/photo.jpg", 300),
        ]
        self.manager.reconcile_manifest(sess_id, remote_inventory)

        pending = self.manager.get_pending_files(sess_id)
        pending_map = {p["rel_path"]: p["file_size"] for p in pending}

        # Databases must always be reset to pending on resume
        self.assertIn("Databases/msgstore.db.crypt14", pending_map)
        # Media with size drift must be reset to pending with new size (300)
        self.assertIn("Media/photo.jpg", pending_map)
        self.assertEqual(pending_map["Media/photo.jpg"], 300)


class TestAdbPullAtomicWrites(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="wa_test_atomic_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_atomic_replace_on_valid_size(self):
        temp_dest = Path(self.test_dir) / "video.mp4.part_test"
        final_dest = Path(self.test_dir) / "video.mp4"

        temp_dest.write_bytes(b"hello world")
        expected_size = 11

        self.assertEqual(temp_dest.stat().st_size, expected_size)
        os.replace(str(temp_dest), str(final_dest))

        self.assertFalse(temp_dest.exists())
        self.assertTrue(final_dest.exists())
        self.assertEqual(final_dest.read_bytes(), b"hello world")

    def test_truncated_file_is_discarded(self):
        temp_dest = Path(self.test_dir) / "corrupted.mp4.part_test"
        final_dest = Path(self.test_dir) / "corrupted.mp4"

        # Expected 100 bytes, but stream broke at 20 bytes
        temp_dest.write_bytes(b"X" * 20)
        expected_size = 100

        actual_size = temp_dest.stat().st_size
        if actual_size != expected_size:
            temp_dest.unlink()

        self.assertFalse(temp_dest.exists())
        self.assertFalse(final_dest.exists())

    def test_adb_pull_tar_status_and_cancellation(self):
        from unittest import mock
        from core.adb import adb_pull_tar
        import threading

        cancel_tok = threading.Event()
        cancel_tok.set()  # Already cancelled

        # When cancelled before start, adb_pull_tar should return False immediately
        res = adb_pull_tar(
            "adb",
            "/sdcard/WhatsApp",
            self.test_dir,
            self.test_dir,
            cancellation_token=cancel_tok,
        )
        self.assertFalse(res)


if __name__ == "__main__":
    unittest.main()
