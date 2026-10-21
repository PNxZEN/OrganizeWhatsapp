"""
Importing an older output folder must never resurrect deleted media or silently swap keys:
- the older folder's own recycle bin is not imported as a chat
- media waiting in the current Recycle Bin is not brought back; nothing is remembered about media deleted for good
- a different backup key is only installed when the user explicitly confirms it
- the same folder reached through another path (symlink, mapped drive, ...) is refused
- gallery entries are only added for files that really arrived (cancel, failures, deletions)
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.migrator as migrator
from core.config import load_config, save_config
from core.gallery import deleted_media_index, empty_recycle_bin, recycle_media_items
from core.migrator import analyze_import_folder, execute_import_folder, validate_paths

KEY_A = "a" * 64
KEY_B = "b" * 64


def gallery_chats(folder: Path):
    text = (folder / "gallery_data.js").read_text(encoding="utf-8")
    return json.loads(text[text.index("{"): text.rindex("}") + 1])["chats"]


class ImportSafetyBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wa_test_import_safety_"))
        self.cwd = os.getcwd()
        os.chdir(self.tmp)  # config.json and encrypted_backup.key live in the working directory
        self.old = self.tmp / "older_output"
        self.cur = self.tmp / "output"
        self.cur.mkdir()
        self.files = {}
        for name, size in (("IMG-1.jpg", 100), ("IMG-2.jpg", 200), ("IMG-3.jpg", 300)):
            rel = f"Alice/2024-01/{name}"
            self.add_old(rel, size)
        self.write_old_gallery()

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add_old(self, rel, size):
        p = self.old / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(os.urandom(size))
        self.files[rel] = size

    def write_old_gallery(self):
        media = [{"filename": Path(r).name, "rel_path": r, "size_bytes": s} for r, s in self.files.items()
                 if not r.startswith(".")]
        data = {"chats": [{"jid": "alice@s.whatsapp.net", "name": "Alice", "media": media,
                           "file_count": len(media), "total_size": sum(m["size_bytes"] for m in media)}]}
        (self.old / "gallery_data.js").write_text("const GALLERY_DATA = " + json.dumps(data) + ";", encoding="utf-8")

    def import_all(self, **kw):
        res = execute_import_folder(str(self.old), str(self.cur), **kw)
        self.assertEqual(res["status"], "success", res)
        return res


class TestDeletedMediaStaysDeleted(ImportSafetyBase):
    def test_01_older_recycle_bin_is_not_imported(self):
        self.add_old(".duplicates_recycle_bin/Alice/2024-01/IMG-DELETED.jpg", 50)
        (self.old / ".duplicates_recycle_bin" / "manifest.json").write_text("{}")
        self.assertEqual(analyze_import_folder(str(self.old), str(self.cur))["files_to_import"], 3)
        self.import_all(import_key=False)
        self.assertFalse((self.cur / ".duplicates_recycle_bin" / "Alice").exists())
        self.assertEqual([c["name"] for c in gallery_chats(self.cur)], ["Alice"])

    def test_02_recycled_media_is_not_brought_back(self):
        self.import_all(import_key=False)
        recycle_media_items(str(self.cur), ["Alice/2024-01/IMG-2.jpg"])
        analysis = analyze_import_folder(str(self.old), str(self.cur))
        self.assertEqual(analysis["previously_deleted_count"], 1)
        self.assertEqual(analysis["files_to_import"], 0)
        res = self.import_all(import_key=False)
        self.assertEqual(res["previously_deleted_count"], 1)
        self.assertFalse((self.cur / "Alice/2024-01/IMG-2.jpg").exists())
        rels = {m["rel_path"] for c in gallery_chats(self.cur) for m in c["media"]}
        self.assertNotIn("Alice/2024-01/IMG-2.jpg", rels)

    def test_03_nothing_is_remembered_about_permanently_deleted_media(self):
        self.import_all(import_key=False)
        recycle_media_items(str(self.cur), ["Alice/2024-01/IMG-3.jpg"])
        empty_recycle_bin(str(self.cur))
        self.assertEqual(deleted_media_index(str(self.cur)), {})
        leftovers = [p for p in self.cur.rglob("*") if p.is_file() and p.suffix not in (".js", ".jpg", ".json", ".sqlite3")]
        self.assertEqual(leftovers, [])
        for p in self.cur.rglob("*"):
            if p.is_file() and p.suffix in (".js", ".json"):
                self.assertNotIn("IMG-3.jpg", p.read_text(encoding="utf-8", errors="ignore"), p.name)

    def test_04_a_different_file_at_the_same_path_is_still_imported(self):
        self.import_all(import_key=False)
        recycle_media_items(str(self.cur), ["Alice/2024-01/IMG-1.jpg"])
        (self.old / "Alice/2024-01/IMG-1.jpg").write_bytes(os.urandom(999))  # not what was deleted
        res = self.import_all(import_key=False)
        self.assertEqual(res["previously_deleted_count"], 0)
        self.assertEqual((self.cur / "Alice/2024-01/IMG-1.jpg").stat().st_size, 999)


class TestBackupKeyIsNeverSwappedSilently(ImportSafetyBase):
    def put_key_in_old(self, key):
        (self.old / "config.json").write_text(json.dumps({"hex_key": key}))

    def test_10_different_key_is_kept_unless_confirmed(self):
        save_config({"hex_key": KEY_A})
        self.put_key_in_old(KEY_B)
        self.assertEqual(analyze_import_folder(str(self.old), str(self.cur))["key_status"], "different")
        res = self.import_all()
        self.assertFalse(res["imported_key"])
        self.assertTrue(res["key_kept"])
        self.assertEqual(load_config()["hex_key"], KEY_A)

    def test_11_confirmed_replacement_installs_the_new_key(self):
        save_config({"hex_key": KEY_A})
        self.put_key_in_old(KEY_B)
        res = self.import_all(replace_key=True)
        self.assertTrue(res["imported_key"])
        self.assertEqual(load_config()["hex_key"], KEY_B)

    def test_12_key_is_adopted_when_none_is_set(self):
        save_config({"hex_key": ""})
        self.put_key_in_old(KEY_B)
        self.assertEqual(analyze_import_folder(str(self.old), str(self.cur))["key_status"], "new")
        self.assertTrue(self.import_all()["imported_key"])
        self.assertEqual(load_config()["hex_key"], KEY_B)

    def test_13_same_key_changes_nothing(self):
        save_config({"hex_key": KEY_A})
        self.put_key_in_old(KEY_A)
        self.assertEqual(analyze_import_folder(str(self.old), str(self.cur))["key_status"], "same")
        res = self.import_all()
        self.assertFalse(res["imported_key"])
        self.assertFalse(res["key_kept"])


class TestSameFolderAndPartialImports(ImportSafetyBase):
    @unittest.skipIf(os.name == "nt", "creating symlinks needs extra rights on Windows")
    def test_20_same_folder_through_another_path_is_refused(self):
        alias = self.tmp / "alias_of_output"
        alias.symlink_to(self.cur, target_is_directory=True)
        with mock.patch.object(Path, "resolve", lambda self, strict=False: Path(os.path.abspath(self))):
            valid, err, _, _ = validate_paths(str(alias), str(self.cur))
        self.assertFalse(valid)
        self.assertIn("own output folder", err)

    @unittest.skipIf(os.name == "nt", "creating symlinks needs extra rights on Windows")
    def test_21_parent_through_another_path_is_refused(self):
        alias = self.tmp / "alias_of_tmp"
        alias.symlink_to(self.tmp, target_is_directory=True)
        with mock.patch.object(Path, "resolve", lambda self, strict=False: Path(os.path.abspath(self))):
            valid, err, _, _ = validate_paths(str(alias), str(self.cur))
        self.assertFalse(valid)
        self.assertIn("inside the selected folder", err)

    def test_22_cancelled_import_lists_only_files_that_arrived(self):
        cancel = threading.Event()
        real = migrator._transfer_file

        def transfer_then_cancel(*a, **kw):
            real(*a, **kw)
            cancel.set()

        with mock.patch("core.migrator._transfer_file", side_effect=transfer_then_cancel):
            res = execute_import_folder(str(self.old), str(self.cur), import_key=False, cancel_event=cancel)
        self.assertEqual(res["status"], "cancelled")
        listed = {m["rel_path"] for c in gallery_chats(self.cur) for m in c["media"]}
        on_disk = {p.relative_to(self.cur).as_posix() for p in self.cur.rglob("*.jpg")}
        self.assertEqual(listed, on_disk, "the gallery must not point at files that were never copied")

    def test_23_merge_does_not_overwrite_a_concurrent_change(self):
        """The merge holds the gallery lock for its whole read-modify-write."""
        from core.gallery import gallery_data_lock

        self.import_all(import_key=False)
        entered = threading.Event()
        release = threading.Event()

        def hold_lock():
            with gallery_data_lock:
                entered.set()
                release.wait(5)

        t = threading.Thread(target=hold_lock)
        t.start()
        entered.wait(5)
        reads = []
        real_parse = migrator.__dict__.get("_merge_gallery_data_locked")
        with mock.patch.object(migrator, "_merge_gallery_data_locked",
                               side_effect=lambda *a: reads.append(1) or real_parse(*a)):
            merger = threading.Thread(target=migrator._merge_gallery_data, args=(self.old, self.cur, {}))
            merger.start()
            merger.join(0.3)
            self.assertEqual(reads, [], "the merge must wait for the lock before reading")
            release.set()
            merger.join(5)
        t.join(5)
        self.assertEqual(reads, [1])


if __name__ == "__main__":
    unittest.main()
