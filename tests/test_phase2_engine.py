"""
Automated Verification Suite for Phase 2: Resolving TODO.txt and Critical Engine Bug Fixes.
Tests wait_for_adb_device, nested Databases cleanup, SQLite HashCache, composite cache invalidation,
and two-tier duplicate checking.
"""

import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT))

from core.adb import DeviceStatus, cleanup_nested_databases_folder, wait_for_adb_device
from core.contacts import load_contacts_mapping
from core.duplicates import (
    HashCache,
    analyze_duplicates,
    compute_fast_hash,
    compute_file_md5,
)


class TestPhase2Engine(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="wa_test_phase2_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_cleanup_nested_databases_folder(self):
        """Verify BUG-02 fix: cleans up nested Databases/Databases without data loss."""
        db_dir = os.path.join(self.test_dir, "Databases")
        nested_dir = os.path.join(db_dir, "Databases")
        os.makedirs(nested_dir, exist_ok=True)

        # Create nested crypt15 file
        nested_file = os.path.join(nested_dir, "msgstore.db.crypt15")
        with open(nested_file, "wb") as f:
            f.write(b"SAMPLE_ENCRYPTED_DB_CONTENT")

        # Run cleanup
        moved = cleanup_nested_databases_folder(db_dir)
        self.assertEqual(moved, 1)

        # Check file moved to db_dir
        expected_file = os.path.join(db_dir, "msgstore.db.crypt15")
        self.assertTrue(os.path.isfile(expected_file))
        self.assertFalse(os.path.exists(nested_dir))

    def test_02_wait_for_adb_device_success(self):
        """Verify TODO 1: wait_for_adb_device polls and resolves when authorized."""
        call_count = [0]
        status_updates = []

        def mock_check(adb_path=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return True, False, "Device is unauthorized", "DEVICE123", "Pixel 8"
            return True, True, "", "DEVICE123", "Pixel 8"

        def mock_callback(status):
            status_updates.append(status)

        with patch("core.adb.check_adb_device", side_effect=mock_check):
            ready, msg, serial, model = wait_for_adb_device(
                timeout=10, poll_interval=0.1, status_callback=mock_callback
            )

            self.assertTrue(ready)
            self.assertEqual(serial, "DEVICE123")
            self.assertEqual(model, "Pixel 8")
            self.assertTrue(len(status_updates) >= 2)
            self.assertEqual(status_updates[0]["status"], "unauthorized")
            self.assertEqual(status_updates[-1]["status"], "device")

    def test_03_wait_for_adb_device_timeout(self):
        """Verify TODO 1: wait_for_adb_device times out cleanly if device never authorized."""
        def mock_check(adb_path=None):
            return True, False, "Device is unauthorized", "DEVICE123", "Pixel 8"

        with patch("core.adb.check_adb_device", side_effect=mock_check):
            ready, msg, serial, model = wait_for_adb_device(
                timeout=0.3, poll_interval=0.1
            )
            self.assertFalse(ready)
            self.assertIn("Timed out", msg)

    def test_04_sqlite_hash_cache_migration_and_invalidation(self):
        """Verify TODO 2 & BUG-03: JSON migration, O(1) lookups, and (mtime, size) invalidation."""
        json_path = os.path.join(self.test_dir, ".hashes_cache.json")
        sqlite_path = os.path.join(self.test_dir, ".hashes_cache.sqlite3")

        # Create dummy file
        test_file = os.path.join(self.test_dir, "sample.jpg")
        with open(test_file, "wb") as f:
            f.write(b"IMAGE_CONTENT_SAMPLE_1234567890")

        st = os.stat(test_file)
        real_mtime = st.st_mtime
        real_size = st.st_size

        # Create JSON cache with 1 valid entry and 1 other entry
        import json
        json_data = {
            test_file: {
                "mtime": real_mtime,
                "size": real_size,
                "md5": "abc123md5",
                "phash": "fedcba9876543210",
            },
            "dummy_file": {
                "mtime": 1000.0,
                "size": 500,
                "md5": "dummy_md5",
                "phash": None,
            },
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f)

        # Initialize SQLite cache (should auto-migrate from JSON)
        cache = HashCache(sqlite_path, json_fallback_path=json_path)

        # Test valid cache hit
        hit = cache.get(test_file, stat_mtime=real_mtime, stat_size=real_size)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["md5"], "abc123md5")
        self.assertEqual(hit["phash"], "fedcba9876543210")

        # Test BUG-03 fix: mtime mismatch invalidates cache
        miss_mtime = cache.get(test_file, stat_mtime=real_mtime + 5.0, stat_size=real_size)
        self.assertIsNone(miss_mtime)

        # Test BUG-03 fix: size mismatch invalidates cache
        miss_size = cache.get(test_file, stat_mtime=real_mtime, stat_size=real_size + 10)
        self.assertIsNone(miss_size)

        cache.close()

    def test_05_compute_fast_hash(self):
        """Verify fast head/tail hash ignores middle bytes and detects header/footer changes."""
        test_file = os.path.join(self.test_dir, "large_file.dat")
        # Create a 64KB file
        data = bytearray(b"H" * 16384 + b"M" * 32768 + b"T" * 16384)
        with open(test_file, "wb") as f:
            f.write(data)

        h1 = compute_fast_hash(test_file)
        self.assertIsNotNone(h1)

        # Mutate byte in the middle (offset 25000)
        data[25000] = ord("X")
        with open(test_file, "wb") as f:
            f.write(data)

        h2 = compute_fast_hash(test_file)
        self.assertEqual(h1, h2, "Fast hash should remain identical when middle bytes change")

        # Mutate byte in the header (offset 10)
        data[10] = ord("Z")
        with open(test_file, "wb") as f:
            f.write(data)

        h3 = compute_fast_hash(test_file)
        self.assertNotEqual(h1, h3, "Fast hash must change when header bytes change")

    def test_06_two_tier_duplicate_analysis(self):
        """Verify two-tier duplicate checking groups by size and identifies collisions."""
        sqlite_cache = os.path.join(self.test_dir, "test_cache.sqlite3")

        # File 1: 20KB content
        f1_path = os.path.join(self.test_dir, "file1.bin")
        content1 = b"CONTENT_A" * 2000
        with open(f1_path, "wb") as f:
            f.write(content1)

        # File 2: 30KB content (unique size)
        f2_path = os.path.join(self.test_dir, "file2.bin")
        content2 = b"CONTENT_B" * 3000
        with open(f2_path, "wb") as f:
            f.write(content2)

        # File 3: exact duplicate of File 1
        f3_path = os.path.join(self.test_dir, "file3_dup.bin")
        with open(f3_path, "wb") as f:
            f.write(content1)

        file_index = {
            "file1.bin": f1_path,
            "file2.bin": f2_path,
            "file3_dup.bin": f3_path,
        }

        md5_map, phash_map, file_hashes = analyze_duplicates(
            file_index, skip_imagehash=True, cache_path=sqlite_cache
        )

        # File 1 and File 3 must share the same MD5
        h1 = file_hashes["file1.bin"][0]
        h3 = file_hashes["file3_dup.bin"][0]
        self.assertEqual(h1, h3)
        self.assertEqual(len(md5_map[h1]), 2)
        self.assertIn("file1.bin", md5_map[h1])
        self.assertIn("file3_dup.bin", md5_map[h1])

        # File 2 has unique size and should not be duplicate
        h2 = file_hashes["file2.bin"][0]
        self.assertEqual(len(md5_map[h2]), 1)

    def test_07_load_contacts_device_checker_unpacking(self):
        """Verify load_contacts_mapping handles 5-element DeviceStatus without unpacking error."""
        dummy_cache = os.path.join(self.test_dir, "contacts_cache.json")

        # Test with 5-element DeviceStatus tuple (disconnected)
        checker_status = DeviceStatus(False, False, "device offline", "serial123", "Pixel 6")
        contacts = load_contacts_mapping(
            cache_path=dummy_cache,
            adb_path="dummy_adb",
            skip_pull=False,
            force_pull=True,
            device_checker=lambda _: checker_status,
        )
        self.assertEqual(contacts, {})

        # Test with standard 5-tuple
        checker_5tuple = (False, False, "offline", "s1", "m1")
        contacts = load_contacts_mapping(
            cache_path=dummy_cache,
            adb_path="dummy_adb",
            skip_pull=False,
            force_pull=True,
            device_checker=lambda _: checker_5tuple,
        )
        self.assertEqual(contacts, {})

        # Test with 3-tuple legacy format
        checker_3tuple = (False, False, "offline")
        contacts = load_contacts_mapping(
            cache_path=dummy_cache,
            adb_path="dummy_adb",
            skip_pull=False,
            force_pull=True,
            device_checker=lambda _: checker_3tuple,
        )
        self.assertEqual(contacts, {})

        # Test with bool format
        contacts = load_contacts_mapping(
            cache_path=dummy_cache,
            adb_path="dummy_adb",
            skip_pull=False,
            force_pull=True,
            device_checker=lambda _: False,
        )
        self.assertEqual(contacts, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)

