"""
Unit and Integration Tests for ADB Storage Info, Batch Delete, and Chat Restore Engine.
Tests:
- get_device_storage_info parsing and fallback handling
- broadcast_media_scan intent firing and chunking
- batch_delete_phone_files path safety guard, quoting, and cancellation
- restore_chat_to_phone pre-flight storage buffer check (+20% safety buffer + 500MB)
- restore_chat_to_phone push orchestration and media scanning
"""

import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from core.adb import (
    get_device_storage_info,
    get_remote_file_sizes,
    broadcast_media_scan,
    batch_delete_phone_files,
    restore_chat_to_phone,
)


class TestRestoreAndAdbClean(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="wa_test_adb_clean_")
        self.out_p = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @mock.patch("core.adb.find_adb_binary", return_value="adb")
    @mock.patch("subprocess.run")
    def test_get_device_storage_info_success(self, mock_run, mock_adb):
        # Mock standard df -k output
        mock_output = (
            "Filesystem     1K-blocks      Used Available Use% Mounted on\n"
            "/data/media    121087132  85421000  35666132  71% /storage/emulated/0\n"
        )
        mock_run.return_value = mock.Mock(returncode=0, stdout=mock_output, stderr="")

        res = get_device_storage_info()
        self.assertTrue(res["success"])
        self.assertAlmostEqual(res["total_gb"], 121087132 * 1024 / (1024**3), places=1)
        self.assertAlmostEqual(res["free_gb"], 35666132 * 1024 / (1024**3), places=1)
        self.assertEqual(res["percent_used"], 70.5)

    @mock.patch("core.adb.find_adb_binary", return_value="adb")
    @mock.patch("subprocess.run")
    def test_get_device_storage_info_failure(self, mock_run, mock_adb):
        mock_run.return_value = mock.Mock(returncode=1, stdout="", stderr="device offline")

        res = get_device_storage_info()
        self.assertFalse(res["success"])
        self.assertEqual(res["total_bytes"], 0)
        self.assertEqual(res["free_bytes"], 0)

    @mock.patch("core.adb.find_adb_binary", return_value="adb")
    @mock.patch("subprocess.run")
    def test_broadcast_media_scan(self, mock_run, mock_adb):
        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        paths = [
            "/storage/emulated/0/WhatsApp/Media/WhatsApp Images/photo1.jpg",
            "/storage/emulated/0/WhatsApp/Media/WhatsApp Video/video1.mp4",
        ]
        count = broadcast_media_scan(paths)
        self.assertEqual(count, 2)
        mock_run.assert_called_once()
        cmd_args = mock_run.call_args[0][0]
        self.assertIn("am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE", " ".join(cmd_args))

    @mock.patch("core.adb.check_adb_device")
    @mock.patch("core.adb.find_adb_binary", return_value="adb")
    @mock.patch("subprocess.run")
    def test_batch_delete_phone_files_guards_and_execution(self, mock_run, mock_adb, mock_dev):
        mock_dev.return_value = mock.Mock(connected=True, authorized=True)
        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        paths = [
            "/storage/emulated/0/WhatsApp/Media/WhatsApp Video/old_vid.mp4",
            "/storage/emulated/0/Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images/pic.jpg",
            "/system/bin/sh",  # Ineligible: forbidden root guard!
            "/data/system/users/0.xml",  # Ineligible: forbidden root guard!
        ]

        progress_calls = []

        def on_progress(done, total):
            progress_calls.append((done, total))

        res = batch_delete_phone_files(
            paths,
            base_path="/storage/emulated/0/WhatsApp/Media",
            progress_callback=on_progress,
        )
        self.assertTrue(res["success"])
        # Only the 2 safe WhatsApp paths should have been deleted
        self.assertEqual(res["deleted_count"], 2)
        self.assertEqual(res["failed_count"], 0)
        self.assertTrue(len(progress_calls) > 0)

        # Check command executed
        mock_run.assert_called_once()
        cmd_str = " ".join(mock_run.call_args[0][0])
        self.assertIn("rm -f", cmd_str)
        self.assertIn("old_vid.mp4", cmd_str)
        self.assertNotIn("/system/bin/sh", cmd_str)

    @mock.patch("core.adb.find_adb_binary", return_value="adb")
    @mock.patch("subprocess.run")
    def test_batch_delete_cancellation(self, mock_run, mock_adb):
        cancel_evt = threading.Event()
        cancel_evt.set()

        paths = ["/storage/emulated/0/WhatsApp/Media/WhatsApp Video/vid.mp4"]
        res = batch_delete_phone_files(paths, cancel_event=cancel_evt)
        self.assertEqual(res["deleted_count"], 0)
        self.assertIn("cancelled", res["errors"][0])

    @mock.patch("core.adb.check_adb_device")
    @mock.patch("core.adb.find_adb_binary", return_value="adb")
    @mock.patch("subprocess.run")
    def test_batch_delete_mid_transfer_disconnect(self, mock_run, mock_adb, mock_dev):
        mock_dev.return_value = mock.Mock(connected=True, authorized=True)
        mock_run.return_value = mock.Mock(returncode=1, stdout="", stderr="error: device offline")

        paths = ["/storage/emulated/0/WhatsApp/Media/WhatsApp Video/vid.mp4"]
        res = batch_delete_phone_files(paths)
        self.assertFalse(res["success"])
        self.assertTrue(any("disconnected" in err.lower() for err in res["errors"]))

    def _setup_mock_chat_gallery(self):
        # Create local file on PC disk
        chat_folder = self.out_p / "Alice"
        chat_folder.mkdir(parents=True, exist_ok=True)
        local_file = chat_folder / "pic.jpg"
        with open(local_file, "wb") as f:
            f.write(b"MOCK_IMAGE_DATA_100_BYTES" * 10)  # 250 bytes

        gal_data = {
            "chats": [
                {
                    "jid": "alice@s.whatsapp.net",
                    "name": "Alice",
                    "media": [
                        {
                            "rel_path": "Alice/pic.jpg",
                            "mime_type": "image/jpeg",
                            "size_bytes": 250,
                        }
                    ],
                }
            ]
        }
        with open(self.out_p / "gallery_data.js", "w", encoding="utf-8") as f:
            f.write("window.GALLERY_DATA = " + json.dumps(gal_data) + ";")

    def test_restore_chat_not_found(self):
        self._setup_mock_chat_gallery()
        res = restore_chat_to_phone("bob@s.whatsapp.net", output_dir=str(self.out_p))
        self.assertFalse(res["success"])
        self.assertIn("not found", res["error"])

    @mock.patch("core.adb.check_adb_device")
    def test_restore_chat_device_disconnected_upfront(self, mock_dev):
        self._setup_mock_chat_gallery()
        mock_dev.return_value = mock.Mock(connected=False, authorized=False, error="No device connected")
        res = restore_chat_to_phone("alice@s.whatsapp.net", output_dir=str(self.out_p))
        self.assertFalse(res["success"])
        self.assertTrue(res["disconnected"])
        self.assertIn("Phone not connected", res["error"])

    @mock.patch("core.adb.check_adb_device")
    def test_restore_chat_device_unauthorized(self, mock_dev):
        self._setup_mock_chat_gallery()
        mock_dev.return_value = mock.Mock(connected=True, authorized=False)
        res = restore_chat_to_phone("alice@s.whatsapp.net", output_dir=str(self.out_p))
        self.assertFalse(res["success"])
        self.assertIn("unauthorized", res["error"])

    @mock.patch("core.adb.check_adb_device")
    @mock.patch("core.adb.find_adb_binary", return_value="adb")
    @mock.patch("subprocess.run")
    def test_restore_chat_no_whatsapp_installed(self, mock_run, mock_adb, mock_dev):
        self._setup_mock_chat_gallery()
        mock_dev.return_value = mock.Mock(connected=True, authorized=True)
        # pm path fails, and directory test fails
        mock_run.return_value = mock.Mock(returncode=1, stdout="", stderr="package not found")

        res = restore_chat_to_phone("alice@s.whatsapp.net", output_dir=str(self.out_p))
        self.assertFalse(res["success"])
        self.assertIn("WhatsApp is not installed", res["error"])

    @mock.patch("subprocess.run")
    @mock.patch("core.adb.check_adb_device")
    @mock.patch("core.adb.get_device_storage_info")
    def test_restore_chat_insufficient_storage(self, mock_storage, mock_dev, mock_run):
        self._setup_mock_chat_gallery()
        mock_dev.return_value = mock.Mock(connected=True, authorized=True)
        mock_run.return_value = mock.Mock(returncode=0, stdout="package:/data/app/com.whatsapp/base.apk", stderr="")
        # Mock device with only 10MB free (< required buffer of 500MB + 20%)
        mock_storage.return_value = {
            "success": True,
            "free_bytes": 10 * 1024 * 1024,
            "total_bytes": 64 * 1024 * 1024 * 1024,
        }

        res = restore_chat_to_phone("alice@s.whatsapp.net", output_dir=str(self.out_p), base_path="/storage/emulated/0/WhatsApp")
        self.assertFalse(res["success"])
        self.assertIn("Insufficient phone storage", res["error"])

    @mock.patch("core.adb.check_adb_device")
    @mock.patch("core.adb.get_device_storage_info")
    @mock.patch("core.adb.find_adb_binary", return_value="adb")
    @mock.patch("subprocess.run")
    def test_restore_chat_mkdir_base_failure(self, mock_run, mock_adb, mock_storage, mock_dev):
        self._setup_mock_chat_gallery()
        mock_dev.return_value = mock.Mock(connected=True, authorized=True)
        mock_storage.return_value = {
            "success": True,
            "free_bytes": 10 * 1024 * 1024 * 1024,
            "total_bytes": 64 * 1024 * 1024 * 1024,
        }

        def fake_run(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd)
            if "pm path" in cmd_str:
                return mock.Mock(returncode=0, stdout="package:/data/app/com.whatsapp/base.apk", stderr="")
            if "mkdir -p" in cmd_str:
                return mock.Mock(returncode=1, stdout="", stderr="mkdir: '/storage/emulated/0': Read-only file system")
            return mock.Mock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = fake_run
        res = restore_chat_to_phone("alice@s.whatsapp.net", output_dir=str(self.out_p))
        self.assertFalse(res["success"])
        self.assertIn("Failed to access or create WhatsApp media directory", res["error"])

    @mock.patch("core.adb.check_adb_device")
    @mock.patch("core.adb.broadcast_media_scan")
    @mock.patch("core.adb.get_device_storage_info")
    @mock.patch("core.adb.find_adb_binary", return_value="adb")
    @mock.patch("subprocess.run")
    def test_restore_chat_mid_transfer_disconnect(self, mock_run, mock_adb, mock_storage, mock_scan, mock_dev):
        self._setup_mock_chat_gallery()
        mock_dev.return_value = mock.Mock(connected=True, authorized=True)
        mock_storage.return_value = {
            "success": True,
            "free_bytes": 10 * 1024 * 1024 * 1024,
            "total_bytes": 64 * 1024 * 1024 * 1024,
        }

        def fake_run(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd)
            if "pm path" in cmd_str:
                return mock.Mock(returncode=0, stdout="package:/data/app/com.whatsapp/base.apk", stderr="")
            if "push" in cmd_str:
                return mock.Mock(returncode=1, stdout="", stderr="error: device offline")
            return mock.Mock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = fake_run
        res = restore_chat_to_phone("alice@s.whatsapp.net", output_dir=str(self.out_p))
        self.assertFalse(res["success"])
        self.assertTrue(res["disconnected"])
        self.assertTrue(any("disconnected" in err.lower() for err in res["errors"]))

    @mock.patch("core.adb.check_adb_device")
    @mock.patch("core.adb.broadcast_media_scan")
    @mock.patch("core.adb.get_device_storage_info")
    @mock.patch("core.adb.find_adb_binary", return_value="adb")
    @mock.patch("subprocess.run")
    def test_restore_chat_user_cancellation(self, mock_run, mock_adb, mock_storage, mock_scan, mock_dev):
        self._setup_mock_chat_gallery()
        mock_dev.return_value = mock.Mock(connected=True, authorized=True)
        mock_storage.return_value = {
            "success": True,
            "free_bytes": 10 * 1024 * 1024 * 1024,
            "total_bytes": 64 * 1024 * 1024 * 1024,
        }
        mock_run.return_value = mock.Mock(returncode=0, stdout="package:com.whatsapp\n", stderr="")

        cancel_evt = threading.Event()
        cancel_evt.set()

        res = restore_chat_to_phone(
            "alice@s.whatsapp.net",
            output_dir=str(self.out_p),
            cancel_event=cancel_evt,
        )
        self.assertTrue(res["cancelled"])
        self.assertIn("cancelled", res["errors"][0].lower())

    @mock.patch("core.adb.check_adb_device")
    @mock.patch("core.adb.broadcast_media_scan")
    @mock.patch("core.adb.get_device_storage_info")
    @mock.patch("core.adb.find_adb_binary", return_value="adb")
    @mock.patch("subprocess.run")
    def test_restore_chat_success(self, mock_run, mock_adb, mock_storage, mock_scan, mock_dev):
        self._setup_mock_chat_gallery()
        mock_dev.return_value = mock.Mock(connected=True, authorized=True)
        # Mock phone with 10GB free
        mock_storage.return_value = {
            "success": True,
            "free_bytes": 10 * 1024 * 1024 * 1024,
            "total_bytes": 64 * 1024 * 1024 * 1024,
        }
        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        progress_calls = []

        def on_prog(done, total):
            progress_calls.append((done, total))

        res = restore_chat_to_phone(
            "alice@s.whatsapp.net",
            output_dir=str(self.out_p),
            progress_callback=on_prog,
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["restored_count"], 1)
        self.assertEqual(res["total_attempted"], 1)
        mock_scan.assert_called_once()
        self.assertTrue(len(progress_calls) > 0)

    @mock.patch("core.adb.find_adb_binary", return_value="adb")
    @mock.patch("subprocess.run")
    def test_get_remote_file_sizes_batch_parsing(self, mock_run, mock_adb):
        mock_output = (
            "SZ 12345 /storage/emulated/0/Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images/img1.jpg\n"
            "SZ 67890 /storage/emulated/0/Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Video/vid1.mp4\n"
        )
        mock_run.return_value = mock.Mock(returncode=0, stdout=mock_output, stderr="")
        paths = [
            "/storage/emulated/0/Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images/img1.jpg",
            "/storage/emulated/0/Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Video/vid1.mp4",
        ]
        sizes = get_remote_file_sizes(paths)
        self.assertEqual(sizes.get(paths[0]), 12345)
        self.assertEqual(sizes.get(paths[1]), 67890)

    @mock.patch("core.adb.check_adb_device")
    @mock.patch("core.adb.broadcast_media_scan")
    @mock.patch("core.adb.get_device_storage_info")
    @mock.patch("core.adb.find_adb_binary", return_value="adb")
    @mock.patch("subprocess.run")
    def test_restore_chat_skips_existing_identical_file(self, mock_run, mock_adb, mock_storage, mock_scan, mock_dev):
        self._setup_mock_chat_gallery()
        mock_dev.return_value = mock.Mock(connected=True, authorized=True)
        mock_storage.return_value = {
            "success": True,
            "connected": True,
            "authorized": True,
            "free_bytes": 10 * 1024 * 1024 * 1024,
            "total_bytes": 64 * 1024 * 1024 * 1024,
        }

        # The mock photo created in _setup_mock_chat_gallery is pic.jpg with 250 bytes
        def side_effect(cmd, **kwargs):
            cmd_str = " ".join(cmd)
            if "stat -c %s" in cmd_str:
                target = "/storage/emulated/0/Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images/pic.jpg"
                return mock.Mock(returncode=0, stdout=f"SZ 250 {target}\n", stderr="")
            return mock.Mock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect

        res = restore_chat_to_phone(
            "alice@s.whatsapp.net",
            output_dir=str(self.out_p),
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["restored_count"], 0)
        self.assertEqual(res["skipped_count"], 1)
        self.assertEqual(res["total_attempted"], 1)
        self.assertEqual(res["skipped_bytes"], 250)

    @mock.patch("core.adb.check_adb_device")
    @mock.patch("core.adb.broadcast_media_scan")
    @mock.patch("core.adb.get_device_storage_info")
    @mock.patch("core.adb.find_adb_binary", return_value="adb")
    @mock.patch("subprocess.run")
    def test_restore_chat_multi_account_accounts_1002_resolution(self, mock_run, mock_adb, mock_storage, mock_scan, mock_dev):
        self._setup_mock_chat_gallery()
        mock_dev.return_value = mock.Mock(connected=True, authorized=True)
        mock_storage.return_value = {
            "success": True,
            "connected": True,
            "authorized": True,
            "free_bytes": 10 * 1024 * 1024 * 1024,
            "total_bytes": 64 * 1024 * 1024 * 1024,
        }
        pushed_targets = []
        def side_effect(cmd, **kwargs):
            cmd_str = " ".join(cmd)
            if "push" in cmd_str:
                pushed_targets.append(cmd[-1])
            return mock.Mock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect
        multi_base = "/storage/emulated/0/Android/media/com.whatsapp/WhatsApp/accounts/1002"
        res = restore_chat_to_phone(
            "alice@s.whatsapp.net",
            output_dir=str(self.out_p),
            base_path=multi_base,
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["restored_count"], 1)
        self.assertTrue(len(pushed_targets) > 0)
        self.assertEqual(
            pushed_targets[0],
            f"{multi_base}/Media/WhatsApp Images/pic.jpg",
        )

    @mock.patch("core.adb.check_adb_device")
    @mock.patch("core.adb.broadcast_media_scan")
    @mock.patch("core.adb.get_device_storage_info")
    @mock.patch("core.adb.find_adb_binary", return_value="adb")
    @mock.patch("subprocess.run")
    def test_restore_chat_whatsapp_business_resolution(self, mock_run, mock_adb, mock_storage, mock_scan, mock_dev):
        self._setup_mock_chat_gallery()
        mock_dev.return_value = mock.Mock(connected=True, authorized=True)
        mock_storage.return_value = {
            "success": True,
            "connected": True,
            "authorized": True,
            "free_bytes": 10 * 1024 * 1024 * 1024,
            "total_bytes": 64 * 1024 * 1024 * 1024,
        }
        pushed_targets = []
        def side_effect(cmd, **kwargs):
            cmd_str = " ".join(cmd)
            if "push" in cmd_str:
                pushed_targets.append(cmd[-1])
            return mock.Mock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect
        w4b_base = "/storage/emulated/0/Android/media/com.whatsapp.w4b/WhatsApp Business"
        res = restore_chat_to_phone(
            "alice@s.whatsapp.net",
            output_dir=str(self.out_p),
            base_path=w4b_base,
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["restored_count"], 1)
        self.assertTrue(len(pushed_targets) > 0)
        self.assertEqual(
            pushed_targets[0],
            f"{w4b_base}/Media/WhatsApp Business Images/pic.jpg",
        )

    @mock.patch("core.adb.check_adb_device")
    @mock.patch("core.adb.broadcast_media_scan")
    @mock.patch("core.adb.get_device_storage_info")
    @mock.patch("core.adb.find_adb_binary", return_value="adb")
    @mock.patch("subprocess.run")
    def test_restore_chat_sent_folder_resolution(self, mock_run, mock_adb, mock_storage, mock_scan, mock_dev):
        # Setup mock with from_me=True
        chat_folder = self.out_p / "Alice"
        chat_folder.mkdir(parents=True, exist_ok=True)
        local_file = chat_folder / "sent_pic.jpg"
        local_file.write_bytes(b"SENT_BYTES" * 20)

        gal_data = {
            "chats": [
                {
                    "jid": "alice@s.whatsapp.net",
                    "name": "Alice",
                    "media": [
                        {
                            "rel_path": "Alice/sent_pic.jpg",
                            "mime_type": "image/jpeg",
                            "size_bytes": local_file.stat().st_size,
                            "from_me": True,
                        }
                    ],
                }
            ]
        }
        with open(self.out_p / "gallery_data.js", "w", encoding="utf-8") as f:
            f.write("window.GALLERY_DATA = " + json.dumps(gal_data) + ";")

        mock_dev.return_value = mock.Mock(connected=True, authorized=True)
        mock_storage.return_value = {
            "success": True,
            "connected": True,
            "authorized": True,
            "free_bytes": 10 * 1024 * 1024 * 1024,
            "total_bytes": 64 * 1024 * 1024 * 1024,
        }
        pushed_targets = []
        def side_effect(cmd, **kwargs):
            cmd_str = " ".join(cmd)
            if "push" in cmd_str:
                pushed_targets.append(cmd[-1])
            return mock.Mock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect
        res = restore_chat_to_phone(
            "alice@s.whatsapp.net",
            output_dir=str(self.out_p),
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["restored_count"], 1)
        self.assertTrue(len(pushed_targets) > 0)
        self.assertIn("/WhatsApp Images/Sent/sent_pic.jpg", pushed_targets[0])

    @mock.patch("core.adb.check_adb_device")
    @mock.patch("core.adb.find_adb_binary", return_value="adb")
    def test_batch_delete_safety_guard_rejects_dcim(self, mock_adb, mock_dev):
        mock_dev.return_value = mock.Mock(connected=True, authorized=True)
        unsafe_paths = [
            "/storage/emulated/0/DCIM/Camera/IMG_2026.jpg",
            "/storage/emulated/0/Download/bank_statement.pdf",
            "/storage/emulated/0/Documents/resume.docx",
        ]
        res = batch_delete_phone_files(unsafe_paths)
        self.assertTrue(res["success"])
        self.assertEqual(res["deleted_count"], 0)
        self.assertIn("No eligible paths to delete", res["errors"][0])


if __name__ == "__main__":
    unittest.main()
