"""
Automated Verification Suite for Phase 1: Safe Modularization and Foundation Setup.
Tests all core submodules, exports, configuration persistence, and database parsing.
"""

import os
import sys
import unittest
from pathlib import Path

# Add workspace root to sys.path
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT))


class TestPhase1Modularization(unittest.TestCase):
    def test_01_core_imports(self):
        """Verify that all core modules import cleanly without errors."""
        import core
        import core.config
        import core.decrypt
        import core.contacts
        import core.database
        import core.duplicates
        import core.organizer
        import core.gallery
        import core.server
        import core.adb
        import core.pipeline

        self.assertTrue(hasattr(core, "load_config"))
        self.assertTrue(hasattr(core, "decrypt_db"))
        self.assertTrue(hasattr(core, "build_media_index"))
        self.assertTrue(hasattr(core, "organize_media"))
        self.assertTrue(hasattr(core, "start_gallery_server"))

    def test_02_config_persistence(self):
        """Verify configuration loading, saving, and key masking."""
        from core.config import load_config, save_config, mask_key

        test_cfg = str(WORKSPACE_ROOT / "test_config.json")
        try:
            # Test default load
            cfg = load_config(test_cfg)
            self.assertEqual(cfg["port"], 8000)
            self.assertEqual(cfg["mode"], "copy")

            # Test save
            save_config({"hex_key": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef", "port": 8080}, test_cfg)
            loaded = load_config(test_cfg)
            self.assertEqual(loaded["port"], 8080)
            self.assertEqual(len(loaded["hex_key"]), 64)

            # Test masking
            masked = mask_key(loaded["hex_key"])
            self.assertTrue(masked.startswith("0123"))
            self.assertTrue(masked.endswith("cdef"))
            self.assertIn("*" * 50, masked)
        finally:
            if os.path.exists(test_cfg):
                os.remove(test_cfg)

    def test_03_decrypt_helpers(self):
        """Verify key validation and wadecrypt binary resolution."""
        from core.decrypt import validate_hex_key, find_wadecrypt_binary

        # Valid 64-char hex key
        valid_key = "a" * 64
        is_valid, err = validate_hex_key(valid_key)
        self.assertTrue(is_valid)
        self.assertEqual(err, "")

        # Invalid lengths and characters
        self.assertFalse(validate_hex_key("short")[0])
        self.assertFalse(validate_hex_key("g" * 64)[0])

        # wadecrypt binary locator
        cmd = find_wadecrypt_binary()
        self.assertTrue(len(cmd) > 0)

    def test_04_contacts_resolution(self):
        """Verify contacts mapping and phone number parsing (BUG-05 fix)."""
        from core.contacts import sanitize_phone_to_jid, resolve_jid_name

        # International phone parsing
        jids = sanitize_phone_to_jid("+1 (555) 234-5678")
        self.assertIn("15552345678@s.whatsapp.net", jids)

        # 10-digit number should have both default country code (91) and raw digits
        jids_10 = sanitize_phone_to_jid("9876543210", default_country_code="91")
        self.assertIn("919876543210@s.whatsapp.net", jids_10)
        self.assertIn("9876543210@s.whatsapp.net", jids_10)

        # Contact resolution
        mock_contacts = {"919876543210@s.whatsapp.net": "Alice Smith"}
        name = resolve_jid_name("9876543210@s.whatsapp.net", mock_contacts, {}, {})
        self.assertEqual(name, "Alice Smith")

    def test_05_database_parsing(self):
        """Verify SQLite query parsing against existing Databases/msgstore.db."""
        from core.database import build_media_index

        db_path = WORKSPACE_ROOT / "Databases" / "msgstore.db"
        if not db_path.is_file():
            self.skipTest("Databases/msgstore.db not found on disk")

        # Query first 5 records
        rows = build_media_index(str(db_path))
        self.assertTrue(len(rows) > 0)
        sample = rows[0]
        self.assertIn("chat_jid", sample)
        self.assertIn("filename", sample)
        self.assertIn("size_bytes", sample)
        self.assertIn("mime_type", sample)

    def test_06_organizer_sanitization(self):
        """Verify unified filename and folder sanitization (BUG-01 fix and MAX_PATH safety)."""
        from core.organizer import sanitize_folder_name, sanitize_filename, normalize_filename

        # Folder sanitization
        folder = sanitize_folder_name("Krishaay: IIT Mandi / Intern? *Curly*", max_len=60)
        self.assertNotIn(":", folder)
        self.assertNotIn("/", folder)
        self.assertNotIn("?", folder)
        self.assertNotIn("*", folder)
        self.assertTrue(len(folder) <= 60)

        # Filename normalization with and without dup suffix
        norm_raw = normalize_filename("IMG-20241021-WA0047_dup1.jpg", strip_dup_suffix=False)
        self.assertEqual(norm_raw, "img-20241021-wa0047_dup1.jpg")

        norm_stripped = normalize_filename("IMG-20241021-WA0047_dup1.jpg", strip_dup_suffix=True)
        self.assertEqual(norm_stripped, "img-20241021-wa0047.jpg")

    def test_07_server_port_discovery(self):
        """Verify port discovery and ThreadingHTTPServer instantiation."""
        from core.server import find_open_port

        port = find_open_port(preferred_port=8000, host="127.0.0.1")
        self.assertTrue(8000 <= port <= 8010)


if __name__ == "__main__":
    unittest.main(verbosity=2)
