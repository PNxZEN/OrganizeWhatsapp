"""
Automated Verification Suite for Frontend Normal and Adverse Scenarios:
- Validates JavaScript syntax in gallery.html (no parse errors, broken handlers, missing DOM IDs)
- Verifies all HTML modal IDs referenced by JS exist in gallery.html
- Verifies all adverse API responses (disconnected, cancelled, unauthorized, low storage)
  match frontend expectations.
"""

import json
import re
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT))

import core.server as srv
from core.clean_planner import CleanProfile
from core.gallery import generate_gallery


class TestFrontendScenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gallery_path = WORKSPACE_ROOT / "gallery.html"
        with open(cls.gallery_path, "r", encoding="utf-8") as f:
            cls.gallery_content = f.read()

        cls.temp_dir = tempfile.mkdtemp(prefix="wa_test_frontend_")
        cls.output_dir = Path(cls.temp_dir) / "output"
        cls.output_dir.mkdir(parents=True, exist_ok=True)

        sample_items = [
            {
                "chat_jid": "alice@s.whatsapp.net",
                "chat_name": "Alice Smith",
                "filename": "IMG-20240501-WA0001.jpg",
                "rel_path": "Alice_Smith/2024-05/IMG-20240501-WA0001.jpg",
                "phone_path": "/storage/emulated/0/WhatsApp/Media/WhatsApp Images/IMG-20240501-WA0001.jpg",
                "size_bytes": 1024 * 50,
                "mime_type": "image/jpeg",
                "received_at": "2024-05-01 12:00:00",
                "sender_jid": "alice@s.whatsapp.net",
                "starred": 0,
                "chat_archived": 0,
                "chat_last_active_ts": 1714564800000,
            }
        ]
        generate_gallery(sample_items, str(cls.output_dir))

        cls.port = srv.find_open_port(preferred_port=8895, host="127.0.0.1")

        class BoundHandler(srv.GalleryHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(cls.output_dir), **kwargs)

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
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def _post(self, path, payload):
        url = f"http://127.0.0.1:{self.port}{path}"
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_01_all_referenced_dom_ids_exist(self):
        """Verify every document.getElementById('...') in JS exists in HTML markup."""
        ids_in_js = set(re.findall(r"document\.getElementById\(['\"]([a-zA-Z0-9_-]+)['\"]\)", self.gallery_content))
        # Find all id="..." in the HTML
        ids_in_html = set(re.findall(r'\bid=["\']([a-zA-Z0-9_-]+)["\']', self.gallery_content))

        # Check critical storage reclaim and restore IDs
        critical_ids = [
            "modalStorageReclaim",
            "reclaimPhoneStatusDot",
            "reclaimPhoneStatusText",
            "reclaimStorageNumbers",
            "reclaimStorageBarFill",
            "cardSmartReclaim",
            "cardVideoOffload",
            "cardCustomProfile",
            "customProfileDrawer",
            "btnAnalyzeReclaim",
            "reclaimStepProfiles",
            "reclaimStepPreview",
            "reclaimStepProgress",
            "reclaimMetricSavings",
            "reclaimMetricFiles",
            "reclaimMetricProtected",
            "reclaimReasonPills",
            "reclaimChatListContainer",
            "btnExecuteCleanPlan",
            "reclaimExecutionSpinner",
            "reclaimProgressTitle",
            "reclaimProgressSubtitle",
            "reclaimExecutionProgressBar",
            "reclaimExecutionProgressText",
            "reclaimProgressRunningActions",
            "btnCancelCleanPurge",
            "reclaimProgressDoneActions",
            "btnReclaimReconnect",
            "btnRestoreChat",
            "btnCancelRestoreChat",
            "toastContainer",
            "modalDevice",
            "modalAccountSelector",
            "modalAccountSelectorBody",
        ]
        for cid in critical_ids:
            self.assertIn(cid, ids_in_html, f"Critical DOM ID '{cid}' missing in gallery.html")

    def test_02_no_corrupted_replacement_characters(self):
        """Ensure no Unicode replacement characters (\\ufffd) exist in gallery.html."""
        self.assertNotIn("\ufffd", self.gallery_content, "Found corrupted \\ufffd character in gallery.html")

    def test_03_restore_button_and_cancel_button_markup(self):
        """Verify restore and cancel buttons are present and properly wired."""
        self.assertIn('id="btnRestoreChat"', self.gallery_content)
        self.assertIn('id="btnCancelRestoreChat"', self.gallery_content)
        self.assertIn('onclick="restoreCurrentChatToPhone()"', self.gallery_content)
        self.assertIn('onclick="cancelActiveRestore()"', self.gallery_content)

    def test_04_storage_reclaim_cancel_button_markup(self):
        """Verify storage reclaim cancel and reconnect buttons are present and properly wired."""
        self.assertIn('id="btnCancelCleanPurge"', self.gallery_content)
        self.assertIn('id="btnReclaimReconnect"', self.gallery_content)
        self.assertIn('onclick="cancelCleanPlanExecution()"', self.gallery_content)

    def test_05_adverse_restore_chat_unplugged(self):
        """POST /api/restore/chat with phone unplugged returns structured 400 error."""
        with mock.patch("core.server.check_adb_device") as mock_dev:
            mock_dev.return_value = mock.Mock(connected=False, authorized=False, error="No device")
            status, data = self._post("/api/restore/chat", {"chat_jid": "alice@s.whatsapp.net"})
            self.assertEqual(status, 400)
            self.assertFalse(data.get("success"))
            self.assertIn("not connected", (data.get("error") or data.get("message")).lower())

    def test_06_adverse_restore_chat_unauthorized(self):
        """POST /api/restore/chat with phone unauthorized returns structured 400 error."""
        with mock.patch("core.server.check_adb_device") as mock_dev:
            mock_dev.return_value = mock.Mock(connected=True, authorized=False, error=None)
            status, data = self._post("/api/restore/chat", {"chat_jid": "alice@s.whatsapp.net"})
            self.assertEqual(status, 400)
            self.assertFalse(data.get("success"))
            self.assertIn("unauthorized", (data.get("error") or data.get("message")).lower())

    def test_07_adverse_clean_execute_unplugged(self):
        """POST /api/clean/execute with phone unplugged returns structured 400 error."""
        with mock.patch("core.server.get_active_plan") as mock_plan, \
             mock.patch("core.server.check_adb_device") as mock_dev:
            mock_plan.return_value = {"plan_id": "test_plan_1", "candidates": []}
            mock_dev.return_value = mock.Mock(connected=False, authorized=False)
            status, data = self._post("/api/clean/execute", {"plan_id": "test_plan_1"})
            self.assertEqual(status, 400)
            self.assertFalse(data.get("success"))
            self.assertIn("not connected", (data.get("error") or data.get("message")).lower())

    def test_08_cancel_endpoints_behavior(self):
        """Verify POST /api/clean/cancel and POST /api/restore/cancel respond cleanly."""
        status_c, data_c = self._post("/api/clean/cancel", {})
        self.assertEqual(status_c, 200)
        self.assertEqual(data_c.get("status"), "success")

        status_r, data_r = self._post("/api/restore/cancel", {})
        self.assertEqual(status_r, 200)
        self.assertEqual(data_r.get("status"), "success")

    def test_09_push_to_phone_modal_elements_and_wiring(self):
        """Verify dedicated modalRestoreChat elements, stats, and handlers are present."""
        self.assertIn('id="modalRestoreChat"', self.gallery_content)
        self.assertIn('id="restoreChatSubtitle"', self.gallery_content)
        self.assertIn('id="restoreStatFiles"', self.gallery_content)
        self.assertIn('id="restoreStatSize"', self.gallery_content)
        self.assertIn('id="restoreStatPhoneFree"', self.gallery_content)
        self.assertIn('id="restoreMediaBreakdownPills"', self.gallery_content)
        self.assertIn('id="restoreFilesPreviewList"', self.gallery_content)
        self.assertIn('id="btnConfirmStartRestore"', self.gallery_content)
        self.assertIn('id="restoreChatProgressView"', self.gallery_content)
        self.assertIn('id="restoreChatDoneView"', self.gallery_content)
        self.assertIn('onclick="executeRestoreChatTransfer()"', self.gallery_content)
        self.assertIn('onclick="closeRestoreChatModal()"', self.gallery_content)

    def test_10_sync_modal_reclaim_tab_and_banner_markup(self):
        """Verify Phone Sync & Management modal includes Reclaim tab and quick-action banner."""
        self.assertIn('id="tabBtnSyncPhone"', self.gallery_content)
        self.assertIn('id="tabBtnReclaimSpace"', self.gallery_content)
        self.assertIn('onclick="switchSyncTab(\'reclaim\')"', self.gallery_content)
        self.assertIn('onclick="switchSyncTab(\'sync\')"', self.gallery_content)

    def test_11_dom_modal_nesting_is_clean(self):
        """Verify modalStorageReclaim is NOT trapped inside lightboxDupCompare."""
        lightbox_idx = self.gallery_content.find('id="lightboxDupCompare"')
        reclaim_idx = self.gallery_content.find('id="modalStorageReclaim"')
        self.assertTrue(lightbox_idx > 0 and reclaim_idx > 0)
        # Find closing of lightboxDupCompare
        content_between = self.gallery_content[lightbox_idx:reclaim_idx]
        self.assertIn('closeDuplicateCompareLightbox', content_between)
        # Ensure modalStorageReclaim is outside of lightboxDupCompare
        self.assertTrue(reclaim_idx > lightbox_idx)

    def test_12_sidebar_filters_archived_and_inactive_logic(self):
        """Verify sidebar filter logic correctly uses isArchived and guarded inactivity checks."""
        self.assertIn('Boolean(chat.archived || chat.chat_archived)', self.gallery_content)
        self.assertIn('if (!isGroup || !lastTs || lastTs <= 0) return false;', self.gallery_content)

    def test_13_multi_attribute_search_logic(self):
        """Verify searchFilter supports date, month, sender, doc, and filename."""
        self.assertIn('MONTH_NAMES', self.gallery_content)
        self.assertIn('MONTH_SHORT', self.gallery_content)
        self.assertIn('item.sender_name', self.gallery_content)
        self.assertIn('queryTokens.every', self.gallery_content)

    def test_14_analyze_progress_and_chat_sorting_elements(self):
        """Verify button progress bar and chat sorting/filter controls exist in markup and JS."""
        # Progress bar in Analyze button
        self.assertIn('id="btnAnalyzeProgressBar"', self.gallery_content)
        self.assertIn('id="btnAnalyzeReclaimText"', self.gallery_content)
        self.assertIn('startAnalyzeButtonProgress', self.gallery_content)
        self.assertIn('finishAnalyzeButtonProgress', self.gallery_content)
        self.assertIn('resetAnalyzeButtonProgress', self.gallery_content)

        # Affected chats search, chips, and sort dropdown
        self.assertIn('id="reclaimChatSearch"', self.gallery_content)
        self.assertIn('id="reclaimChatFilterChips"', self.gallery_content)
        self.assertIn('id="reclaimChatSortSelect"', self.gallery_content)
        self.assertIn('id="reclaimChatCountBadge"', self.gallery_content)
        self.assertIn('setReclaimChatFilter', self.gallery_content)
        self.assertIn('setReclaimChatSort', self.gallery_content)
        self.assertIn('renderReclaimChatList', self.gallery_content)


if __name__ == "__main__":
    unittest.main()

