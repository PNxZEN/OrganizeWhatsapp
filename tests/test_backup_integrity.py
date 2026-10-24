"""
A WhatsApp backup that is cut off (WhatsApp still writing it, an interrupted copy) or damaged must
never be used as the chat database: real crypt15 files are made with wa-crypt-tools and then cut
or altered.
"""

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import core.pipeline as pipeline  # noqa: E402
from core.decrypt import BackupIncompleteError, create_key_file, decrypt_db  # noqa: E402

HEX_KEY = "a1b2c3d4" * 8


def _make_db(path, rows):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE message (_id INTEGER PRIMARY KEY, text_data TEXT)")
    con.executemany(
        "INSERT INTO message (text_data) VALUES (?)",
        [(f"message {i} " + os.urandom(24).hex(),) for i in range(rows)],
    )
    con.commit()
    con.close()


def _rows(path):
    con = sqlite3.connect(path)
    try:
        return con.execute("SELECT count(*) FROM message").fetchone()[0]
    finally:
        con.close()


class BackupIntegrityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp(prefix="wa_backup_"))
        cls.key = cls.dir / "key"
        create_key_file(HEX_KEY, str(cls.key))
        plain = cls.dir / "msgstore.db"
        _make_db(plain, 6000)
        cls.single = cls.dir / "msgstore.db.crypt15"
        proc = subprocess.run(
            [sys.executable, "-m", "wa_crypt_tools.waencrypt", str(cls.key), str(plain), str(cls.single)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0 or not cls.single.is_file():
            raise unittest.SkipTest(f"waencrypt unavailable: {proc.stderr[-200:]}")
        cls.data = cls.single.read_bytes()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(dir=self.dir))

    def _backup(self, data, name="msgstore.db.crypt15"):
        p = self.work / name
        p.write_bytes(data)
        return p

    def _decrypt(self, data):
        out = self.work / "out.db"
        decrypt_db(str(self.key), str(self._backup(data)), str(out), reuse_unchanged=False)
        return out

    def test_whole_backup_is_used(self):
        self.assertEqual(_rows(self._decrypt(self.data)), 6000)

    def test_multi_file_layout_is_used(self):
        # Multi-file backups end with data then the tag, without the MD5
        self.assertEqual(_rows(self._decrypt(self.data[:-16])), 6000)

    def test_cut_off_backups_are_refused(self):
        for cut in (len(self.data) // 3, int(len(self.data) * 0.97), len(self.data) - 20):
            with self.subTest(cut=cut), self.assertRaises(BackupIncompleteError):
                self._decrypt(self.data[:cut])
            self.assertFalse((self.work / "out.db").exists())
            self.assertEqual(list(self.work.glob("*.tmp_*")), [])

    def test_altered_byte_is_refused(self):
        data = bytearray(self.data)
        data[len(data) // 2] ^= 0x01
        with self.assertRaises(BackupIncompleteError):
            self._decrypt(bytes(data))

    def test_damaged_backup_keeps_previous_database(self):
        out = self.work / "msgstore.db"
        _make_db(out, 10)
        pipeline.sync_status["warnings"] = []
        used = pipeline.decrypt_or_keep_previous(
            str(self.key), str(self._backup(self.data[:-20])), str(out), reuse_unchanged=False
        )
        self.assertFalse(used)
        self.assertEqual(_rows(out), 10)
        self.assertEqual(len(pipeline.sync_status["warnings"]), 1)
        self.assertIn("previous sync", pipeline.sync_status["warnings"][0])

    def test_damaged_backup_without_previous_database_stops_the_sync(self):
        out = self.work / "msgstore.db"
        with self.assertRaises(BackupIncompleteError):
            pipeline.decrypt_or_keep_previous(
                str(self.key), str(self._backup(self.data[: len(self.data) // 2])), str(out), reuse_unchanged=False
            )
        self.assertFalse(out.exists())

    def test_damaged_contacts_backup_is_skipped(self):
        out = self.work / "wa.db"
        used = pipeline.decrypt_or_keep_previous(
            str(self.key), str(self._backup(self.data[:-20], "wa.db.crypt15")), str(out),
            required=False, reuse_unchanged=False,
        )
        self.assertFalse(used)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
