"""
Automated Verification Suite for Phase 4: Frontend UI Control Center.
Tests gallery.html structural integrity, Control Center elements, zero alerts,
absence of em dashes/emojis, and live server rendering.
"""

import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT))

import core.server as srv


class TestPhase4UI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gallery_path = WORKSPACE_ROOT / "gallery.html"
        cls.html_content = cls.gallery_path.read_text(encoding="utf-8")

        # Start live server on ephemeral port to test HTTP delivery
        cls.port = srv.find_open_port(preferred_port=8870, host="127.0.0.1")

        class BoundHandler(srv.GalleryHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(WORKSPACE_ROOT / "output"), **kwargs)

        cls.httpd = ThreadingHTTPServer(("127.0.0.1", cls.port), BoundHandler)
        cls.server_thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.server_thread.start()
        time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.httpd.shutdown()
            cls.httpd.server_close()
        except Exception:
            pass

    def test_01_no_em_dashes(self):
        """Verify strict formatting rule: zero em dashes or en dashes in gallery.html."""
        matches = list(re.finditer(r"[\u2014\u2013]", self.html_content))
        self.assertEqual(len(matches), 0, f"Found {len(matches)} em/en dashes in gallery.html")

    def test_02_no_warning_emojis(self):
        """Verify strict formatting rule: zero warning emojis in gallery.html."""
        self.assertNotIn("⚠️", self.html_content)

    def test_03_zero_terminal_alerts(self):
        """Verify BUG-08 fix: command-line terminal alerts are removed from backup actions."""
        self.assertNotIn("python wa_media_organizer.py --backup-list", self.html_content)
        self.assertNotIn("python wa_media_organizer.py --skip-pull", self.html_content)

    def test_04_control_center_dom_elements(self):
        """Verify all Control Center header, pill, and modal elements exist."""
        required_elements = [
            'id="controlCenterBar"',
            'id="deviceStatusPill"',
            'id="deviceDot"',
            'id="deviceText"',
            'id="btnControlSync"',
            'id="btnControlKey"',
            'id="btnControlExit"',
            'id="keyIndicator"',
            'id="modalDevice"',
            'id="modalKey"',
            'id="modalSync"',
            'id="modalExit"',
            'id="btnExecuteExit"',
            'id="toastContainer"',
            'id="btnZipBackup"',
            'id="btnActionSelected"',
            'id="chatList"',
            'id="galleryContent"',
        ]
        for elem in required_elements:
            self.assertIn(elem, self.html_content, f"Required element {elem} missing from gallery.html")

    def test_05_http_server_serves_updated_gallery(self):
        """Verify the server serves gallery.html with 200 OK containing Control Center bar."""
        url = f"http://127.0.0.1:{self.port}/gallery.html"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            served_text = resp.read().decode("utf-8")
            self.assertIn('id="controlCenterBar"', served_text)
            self.assertIn('id="deviceStatusPill"', served_text)
            self.assertIn('id="modalKey"', served_text)

    def test_06_sync_summary_and_inflight_dom_elements(self):
        """Verify the pre-sync summary, in-flight skip DB, and exit warning elements."""
        required_elements = [
            'id="syncViewSummary"',
            'id="syncViewProgress"',
            'id="syncSummaryStatsBox"',
            'id="syncSummarySkipDbContainer"',
            'id="syncSummaryChkSkipDb"',
            'id="btnStartSyncNow"',
            'id="syncInFlightSkipContainer"',
            'id="btnInFlightSkipDb"',
            'id="syncBackgroundTip"',
            'id="exitSyncWarning"',
        ]
        for elem in required_elements:
            self.assertIn(elem, self.html_content, f"Required element {elem} missing from gallery.html")

    def test_07_no_skip_db_in_settings_modal(self):
        """Verify skip_db_pull was removed from Settings modal (per user requirement)."""
        self.assertNotIn('id="chkSkipDbPull"', self.html_content)

    def test_08_sync_button_animation_css(self):
        """Verify syncing animation classes and keyframes are present."""
        self.assertIn('.control-btn-syncing', self.html_content)
        self.assertIn('@keyframes syncBtnPulse', self.html_content)
        self.assertIn('.btn-highlight-pulse', self.html_content)

    def test_09_live_chat_storage_sync(self):
        """Verify chat storage real-time sync updates without hard reload."""
        self.assertIn("function getChatsArray()", self.html_content)
        self.assertIn("const rawChats = getChatsArray();", self.html_content)
        self.assertIn("activeChat.total_size = found.total_size;", self.html_content)
        self.assertIn("activeChat.file_count = found.file_count;", self.html_content)
        self.assertIn("activeChat.total_size = data.total_size;", self.html_content)
        self.assertIn("getChatsArray().find(c => c.jid === state.activeChatJid)", self.html_content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
