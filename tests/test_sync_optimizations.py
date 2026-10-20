"""
Tests for sync pipeline optimizations:
- select_database_files: only the current msgstore backup is transferred, not WhatsApp's
  dated daily copies (falls back to the newest dated copy when no current one exists)
- decrypt_db reuse: an unchanged backup + key + untouched output skips re-decryption, while
  a new backup, another key or a modified/corrupt output always decrypts again
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.decrypt as decrypt
import os

from core.adb import already_pulled_roots, select_database_files


class TestDatabaseFileSelection(unittest.TestCase):
    FILES = [
        ("Databases/msgstore-2026-10-14.1.db.crypt15", 900),
        ("Databases/msgstore-2026-10-19.1.db.crypt15", 950),
        ("Databases/msgstore-2026-10-19.2.db.crypt15", 960),
        ("Databases/msgstore.db.crypt15", 990),
        ("Databases/msgstore.db.crypt14", 800),
        ("Databases/wa.db.crypt15", 10),
        ("Databases/chatsettingsbackup.db.crypt15", 3),
    ]

    def test_01_skips_dated_daily_copies(self):
        picked = {p for p, _ in select_database_files(self.FILES)}
        self.assertEqual(picked, {
            "Databases/msgstore.db.crypt15",
            "Databases/msgstore.db.crypt14",
            "Databases/wa.db.crypt15",
            "Databases/chatsettingsbackup.db.crypt15",
        })

    def test_02_keeps_newest_dated_copy_when_current_is_missing(self):
        files = [f for f in self.FILES if "/msgstore.db" not in f[0]]
        picked = {p for p, _ in select_database_files(files)}
        self.assertIn("Databases/msgstore-2026-10-19.2.db.crypt15", picked)
        self.assertNotIn("Databases/msgstore-2026-10-19.1.db.crypt15", picked)
        self.assertNotIn("Databases/msgstore-2026-10-14.1.db.crypt15", picked)
        self.assertIn("Databases/wa.db.crypt15", picked)


class TestDecryptReuse(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="wa_test_decrypt_"))
        self.key = self.dir / "encrypted_backup.key"
        self.key.write_bytes(b"K" * 64)
        self.crypt = self.dir / "msgstore.db.crypt15"
        self.crypt.write_bytes(b"HEADER-A" + b"x" * 3_000_000)
        self.out = self.dir / "msgstore.db"
        self.calls = 0

        def fake_decrypt(key_file, crypt_path, out_path, cancellation_token=None, progress_callback=None):
            self.calls += 1
            Path(out_path).write_bytes(b"SQLite format 3\x00" + Path(crypt_path).read_bytes()[:64])
            return str(out_path)

        patcher = mock.patch.object(decrypt, "_decrypt_db_uncached", side_effect=fake_decrypt)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_decrypt(self, **kw):
        return decrypt.decrypt_db(self.key, self.crypt, self.out, **kw)

    def test_03_unchanged_backup_is_not_decrypted_twice(self):
        self.run_decrypt()
        progress = []
        self.run_decrypt(progress_callback=lambda done, total: progress.append((done, total)))
        self.assertEqual(self.calls, 1)
        self.assertEqual(progress[-1][0], progress[-1][1], "reuse must still report completion")

    def test_04_new_backup_is_decrypted(self):
        self.run_decrypt()
        self.crypt.write_bytes(b"HEADER-B" + b"x" * 3_000_000)  # same size, new random header
        self.run_decrypt()
        self.assertEqual(self.calls, 2)

    def test_05_other_key_is_decrypted(self):
        self.run_decrypt()
        self.key.write_bytes(b"Z" * 64)
        self.run_decrypt()
        self.assertEqual(self.calls, 2)

    def test_06_modified_or_corrupt_output_is_decrypted(self):
        self.run_decrypt()
        self.out.write_bytes(b"not a database at all, but same-ish length")
        self.run_decrypt()
        self.assertEqual(self.calls, 2)

    def test_07_cancelled_decryption_is_not_recorded(self):
        cancel = mock.Mock()
        cancel.is_set.return_value = True
        self.run_decrypt(cancellation_token=cancel)
        self.run_decrypt()
        self.assertEqual(self.calls, 2)

    def test_08_reuse_can_be_disabled(self):
        self.run_decrypt()
        self.run_decrypt(reuse_unchanged=False)
        self.assertEqual(self.calls, 2)


class TestAlreadyPulledRoots(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="wa_test_roots_"))
        self.cwd = os.getcwd()
        os.chdir(self.dir)
        (self.dir / "output" / "Media").mkdir(parents=True)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_09_default_output_does_not_walk_app_root(self):
        self.assertEqual(already_pulled_roots("./output"), [str((self.dir / "output").resolve())])

    def test_10_nested_media_folder_is_covered_by_output(self):
        self.assertEqual(already_pulled_roots("./output/Media"), [str((self.dir / "output").resolve())])

    def test_11_separate_output_is_walked_too(self):
        other = self.dir / "elsewhere"
        other.mkdir()
        self.assertEqual(sorted(already_pulled_roots(str(other))),
                         sorted([str((self.dir / "output").resolve()), str(other.resolve())]))


if __name__ == "__main__":
    unittest.main()
