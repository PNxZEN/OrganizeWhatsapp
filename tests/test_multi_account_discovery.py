"""
Unit tests for WhatsApp and WhatsApp Business Multi-Account Discovery,
Phone Number Resolution via dumpsys account, and Sticky Account Selection.
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.adb import (
    discover_android_base_path,
    discover_whatsapp_accounts,
    get_registered_whatsapp_accounts,
)
from core.config import load_config, save_config


SAMPLE_DUMPSYS_ACCOUNT_OUTPUT = """
User UserInfo{0:Owner:13}:
  Accounts: 3
    Account {name=919876543210, type=com.whatsapp}
    Account {name=919123456789, type=com.whatsapp.w4b}
    Account {name=test@gmail.com, type=com.google}

User UserInfo{95:Dual Messenger:30}:
  Accounts: 1
    Account {name=919988776655, type=com.whatsapp}
"""


class TestMultiAccountDiscovery(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="wa_test_multiacc_")
        self.orig_cwd = os.getcwd()
        os.chdir(self.test_dir)
        self.config_path = os.path.join(self.test_dir, "config.json")

    def tearDown(self):
        os.chdir(self.orig_cwd)
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("subprocess.run")
    def test_01_get_registered_whatsapp_accounts(self, mock_run):
        """Verify dumpsys account extracts phone numbers, user profiles, and app types."""
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = SAMPLE_DUMPSYS_ACCOUNT_OUTPUT
        mock_run.return_value = mock_res

        accounts = get_registered_whatsapp_accounts()
        self.assertEqual(len(accounts), 3)

        # Primary WhatsApp
        self.assertEqual(accounts[0]["phone_number"], "+919876543210")
        self.assertEqual(accounts[0]["package"], "com.whatsapp")
        self.assertEqual(accounts[0]["user_id"], "0")
        self.assertEqual(accounts[0]["app_type"], "whatsapp")

        # WhatsApp Business
        self.assertEqual(accounts[1]["phone_number"], "+919123456789")
        self.assertEqual(accounts[1]["package"], "com.whatsapp.w4b")
        self.assertEqual(accounts[1]["app_type"], "whatsapp_business")

        # Samsung Dual Messenger
        self.assertEqual(accounts[2]["phone_number"], "+919988776655")
        self.assertEqual(accounts[2]["user_id"], "95")

    @patch("core.adb.get_registered_whatsapp_accounts")
    @patch("subprocess.run")
    def test_02_discover_whatsapp_accounts_samsung_beta_structure(self, mock_run, mock_get_reg):
        """Simulate the beta tester's Samsung phone where accounts/1002 has Crypt15 and root has stale Crypt14."""
        mock_get_reg.return_value = [
            {
                "phone_number": "+919876543210",
                "raw_name": "919876543210",
                "package": "com.whatsapp",
                "user_id": "0",
                "app_type": "whatsapp",
            }
        ]

        # Probe shell output simulating:
        # 1. Root folder with May 1st crypt14
        # 2. accounts/1002 folder with Sept 6th crypt15
        probe_stdout = (
            "ACC|/storage/emulated/0/Android/media/com.whatsapp/WhatsApp|1|1|msgstore.db.crypt14|1746057600|84291840\n"
            "ACC|/storage/emulated/0/Android/media/com.whatsapp/WhatsApp/accounts/1002|1|1|msgstore.db.crypt15|1788679260|91283712\n"
        )
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = probe_stdout
        mock_run.return_value = mock_res

        accounts = discover_whatsapp_accounts(hex_key="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")
        self.assertEqual(len(accounts), 2)

        # Top ranked MUST be accounts/1002
        top = accounts[0]
        self.assertEqual(top["path"], "/storage/emulated/0/Android/media/com.whatsapp/WhatsApp/accounts/1002")
        self.assertEqual(top["account_id"], "1002")
        self.assertEqual(top["crypt_version"], 15)
        self.assertEqual(top["phone_number"], "+919876543210")
        self.assertTrue(top["is_active_recommendation"])

        # Second ranked is root
        second = accounts[1]
        self.assertEqual(second["path"], "/storage/emulated/0/Android/media/com.whatsapp/WhatsApp")
        self.assertEqual(second["crypt_version"], 14)
        self.assertFalse(second["is_active_recommendation"])

    @patch("core.adb.get_registered_whatsapp_accounts")
    @patch("subprocess.run")
    def test_03_discover_whatsapp_business(self, mock_run, mock_get_reg):
        """Verify WhatsApp Business package com.whatsapp.w4b is detected with correct labels."""
        mock_get_reg.return_value = [
            {
                "phone_number": "+15551234567",
                "raw_name": "15551234567",
                "package": "com.whatsapp.w4b",
                "user_id": "0",
                "app_type": "whatsapp_business",
            }
        ]

        probe_stdout = (
            "ACC|/storage/emulated/0/Android/media/com.whatsapp.w4b/WhatsApp Business|1|1|msgstore.db.crypt15|1788679260|45000000\n"
        )
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = probe_stdout
        mock_run.return_value = mock_res

        accounts = discover_whatsapp_accounts()
        self.assertEqual(len(accounts), 1)
        biz = accounts[0]
        self.assertEqual(biz["app_type"], "whatsapp_business")
        self.assertEqual(biz["app_label"], "WhatsApp Business")
        self.assertEqual(biz["package"], "com.whatsapp.w4b")
        self.assertEqual(biz["phone_number"], "+15551234567")
        self.assertIn("+15551234567", biz["label"])

    @patch("core.adb.discover_whatsapp_accounts")
    @patch("subprocess.run")
    def test_04_discover_android_base_path_sticky_selection(self, mock_run, mock_discover_accs):
        """Verify that discover_android_base_path sticks to selected_account_path from config."""
        saved_path = "/storage/emulated/0/Android/media/com.whatsapp/WhatsApp/accounts/1002"
        save_config({"selected_account_path": saved_path}, config_path=self.config_path)

        # Mock ADB check confirming directory exists
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = "FOUND\n"
        mock_run.return_value = mock_res

        # Even if discover_whatsapp_accounts would suggest a different account
        mock_discover_accs.return_value = [
            {"path": "/storage/emulated/0/Android/media/com.whatsapp/WhatsApp/accounts/9999"}
        ]

        resolved = discover_android_base_path()
        self.assertEqual(resolved, saved_path)
        # Should NOT call discover_whatsapp_accounts when sticky path exists
        mock_discover_accs.assert_not_called()

    @patch("core.adb.discover_whatsapp_accounts")
    @patch("subprocess.run")
    def test_05_discover_android_base_path_dynamic_resolution(self, mock_run, mock_discover_accs):
        """Verify that discover_android_base_path calls dynamic discovery when no config is saved."""
        mock_res = MagicMock()
        mock_res.returncode = 1
        mock_res.stdout = ""
        mock_run.return_value = mock_res

        target_acc_path = "/storage/emulated/0/Android/media/com.whatsapp/WhatsApp/accounts/1002"
        mock_discover_accs.return_value = [{"path": target_acc_path}]

        resolved = discover_android_base_path()
        self.assertEqual(resolved, target_acc_path)
        mock_discover_accs.assert_called_once()

    @patch("subprocess.run")
    def test_06_dumpsys_account_syntax_variations(self, mock_run):
        """Verify dumpsys account parsing succeeds across different OEM syntax (colons, quotes, whitespace)."""
        variations = """
        User UserInfo{0:Owner:13}:
          Account {name: 919876543210, type: com.whatsapp}
          Account {name="919123456789", type="com.whatsapp.w4b"}
          Account { name = '919988776655' , type = com.whatsapp }
        """
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = variations
        mock_run.return_value = mock_res

        accounts = get_registered_whatsapp_accounts()
        self.assertEqual(len(accounts), 3)
        self.assertEqual(accounts[0]["phone_number"], "+919876543210")
        self.assertEqual(accounts[1]["phone_number"], "+919123456789")
        self.assertEqual(accounts[1]["app_type"], "whatsapp_business")
        self.assertEqual(accounts[2]["phone_number"], "+919988776655")

    def test_07_run_pipeline_signature_check(self):
        """Verify run_pipeline signature accepts adb_path and handles skip_pull cleanly without NameError."""
        from core.pipeline import run_pipeline
        # Running with skip_pull=True and empty db_dir should complete without raising NameError
        empty_db = os.path.join(self.test_dir, "empty_db")
        empty_out = os.path.join(self.test_dir, "empty_out")
        os.makedirs(empty_db, exist_ok=True)
        os.makedirs(empty_out, exist_ok=True)
        result = run_pipeline(
            db_dir=empty_db,
            output_dir=empty_out,
            media_dir=empty_out,
            skip_pull=True,
            skip_decrypt=True,
            adb_path="adb",
        )
        self.assertIsNotNone(result)


    @patch("subprocess.run")
    def test_08_dumpsys_sanitizes_literal_whatsapp_name(self, mock_run):
        """Verify dumpsys account with literal Account {name=WhatsApp} sets phone_number to empty string."""
        sample_samsung = """
User UserInfo{0:Owner:13}:
  Accounts: 2
    Account {name=WhatsApp, type=com.whatsapp}
    Account {name=WhatsApp Business, type=com.whatsapp.w4b}
"""
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = sample_samsung
        mock_run.return_value = mock_res

        accounts = get_registered_whatsapp_accounts()
        self.assertEqual(len(accounts), 2)
        self.assertEqual(accounts[0]["phone_number"], "")
        self.assertEqual(accounts[0]["raw_name"], "WhatsApp")
        self.assertEqual(accounts[1]["phone_number"], "")
        self.assertEqual(accounts[1]["raw_name"], "WhatsApp Business")

    @patch("subprocess.run")
    def test_09_adb_pull_tar_media_union_folder_detection(self, mock_run):
        """Verify adb_pull_tar checks companion account Media and parent Media folders."""
        from core.adb import adb_pull_tar

        # Mock ls -d checks
        def mock_subproc(cmd, *args, **kwargs):
            m = MagicMock()
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "ls -d" in cmd_str:
                m.returncode = 0
                m.stdout = "found\n"
            elif "find" in cmd_str:
                # Return empty to finish without tar stream
                m.returncode = 0
                m.stdout = ""
            else:
                m.returncode = 0
                m.stdout = ""
            return m

        mock_run.side_effect = mock_subproc

        base = "/storage/emulated/0/Android/media/com.whatsapp/WhatsApp/accounts/1002"
        mock_sess_mgr = MagicMock()
        mock_sess_mgr.cleanup_orphaned_part_files.return_value = None
        # Calling adb_pull_tar for media should probe both accounts/1002/Media and parent Media
        result = adb_pull_tar(
            adb_path="adb",
            base=base,
            dest_db="./Databases",
            dest_media="./output",
            folders_filter=["Media"],
            session_manager=mock_sess_mgr,
        )
        # Verify subprocess was called with union folders in find
        find_calls = [
            " ".join(c[0][0])
            for c in mock_run.call_args_list
            if len(c[0]) > 0 and isinstance(c[0][0], list) and any("find" in str(x) for x in c[0][0])
        ]
        self.assertTrue(len(find_calls) > 0)
        found_union = any("accounts/1002/Media" in call and "Media" in call for call in find_calls)
        self.assertTrue(found_union, f"Did not find union in find calls: {find_calls}")

    def test_10_thumbnail_api_no_ffmpeg_returns_404(self):
        """Verify /api/thumbnail returns 404 when ffmpeg is unavailable."""
        from http.client import HTTPConnection
        from threading import Thread
        from core.server import GalleryHTTPRequestHandler, ThreadingHTTPServer

        class CustomHandler(GalleryHTTPRequestHandler):
            output_dir = Path(self.test_dir)

        server = ThreadingHTTPServer(("127.0.0.1", 0), CustomHandler)
        port = server.server_port
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch("core.thumbnail.get_or_create_thumbnail", return_value=None), \
                 patch("core.server.is_ffmpeg_available", return_value=False):
                conn = HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("GET", "/api/thumbnail?path=some_video.mp4")
                resp = conn.getresponse()
                self.assertEqual(resp.status, 404)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data.get("error"), "ffmpeg_not_available")
                conn.close()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()

