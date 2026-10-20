"""
Tests for importing older media (core.migrator + core.import_job):
- copy keeps the source, move empties it (rename on the same drive)
- byte-accurate progress that ends at 100 %
- atomic copies: a failed copy never leaves a truncated file behind
- cancel stops mid-way and still merges what was transferred
- the job manager runs one import at a time and reports its final state
- the Windows folder picker declares 64-bit pointer types for every Win32 call
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.migrator as migrator
from core.import_job import JOB_DONE, ImportJobManager
from core.migrator import (
    IMPORT_MODE_COPY,
    IMPORT_MODE_MOVE,
    PICK_CANCELLED,
    PICK_SELECTED,
    analyze_import_folder,
    execute_import_folder,
)


class ImportTestBase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="wa_test_import_")
        self.src = Path(self.temp_dir) / "older_output"
        self.tgt = Path(self.temp_dir) / "current_output"
        self.tgt.mkdir(parents=True)
        self.files = {}
        media = []
        for i, size in enumerate([300_000, 50_000, 9_000_000, 1_000]):
            rel = f"Alice Smith/2024-0{i + 1}/IMG-2024010{i + 1}-WA000{i + 1}.jpg"
            p = self.src / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(os.urandom(size))
            self.files[rel] = p.read_bytes()
            media.append({"filename": p.name, "rel_path": rel, "size_bytes": size, "mime_type": "image/jpeg"})
        data = {"chats": [{"jid": "alice@s.whatsapp.net", "name": "Alice Smith", "media": media,
                           "file_count": len(media), "total_size": sum(m["size_bytes"] for m in media)}]}
        (self.src / "gallery_data.js").write_text("const GALLERY_DATA = " + json.dumps(data) + ";", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)


class TestImportEngine(ImportTestBase):
    def test_01_analysis_reports_bytes_and_same_volume(self):
        res = analyze_import_folder(str(self.src), str(self.tgt))
        self.assertTrue(res["valid"])
        self.assertEqual(res["files_to_import"], 4)
        self.assertEqual(res["bytes_to_import"], sum(len(b) for b in self.files.values()))
        self.assertTrue(res["same_volume"])

    def test_02_copy_keeps_source_and_reports_byte_progress(self):
        updates = []
        res = execute_import_folder(str(self.src), str(self.tgt), progress_callback=updates.append, import_key=False)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["copied_count"], 4)
        for rel, data in self.files.items():
            self.assertEqual((self.tgt / rel).read_bytes(), data)
            self.assertTrue((self.src / rel).is_file(), "copy must keep the source")
        transfer = [u for u in updates if u.get("phase") == "transferring"]
        self.assertTrue(transfer, "transfer progress must be reported")
        self.assertEqual(transfer[-1]["bytes_done"], transfer[-1]["bytes_total"])
        percents = [u["percent"] for u in updates if "percent" in u]
        self.assertEqual(percents, sorted(percents), "progress must never go backwards")
        self.assertEqual(updates[-1]["percent"], 100)
        self.assertFalse(list(self.tgt.rglob("*.importing")), "no temp files may remain")

    def test_03_move_empties_source_and_merges_gallery(self):
        res = execute_import_folder(str(self.src), str(self.tgt), import_key=False, mode=IMPORT_MODE_MOVE)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["copied_count"], 4)
        for rel, data in self.files.items():
            self.assertEqual((self.tgt / rel).read_bytes(), data)
            self.assertFalse((self.src / rel).exists(), "move must remove the source file")
        gallery = (self.tgt / "gallery_data.js").read_text(encoding="utf-8")
        for rel in self.files:
            self.assertIn(rel, gallery)

    def test_04_move_across_drives_falls_back_to_verified_copy(self):
        real_rename = os.rename

        def cross_device(src, dst):
            if str(src).startswith(str(self.src)):
                raise OSError(18, "Invalid cross-device link")
            return real_rename(src, dst)

        with mock.patch("core.migrator.os.rename", side_effect=cross_device):
            res = execute_import_folder(str(self.src), str(self.tgt), import_key=False, mode=IMPORT_MODE_MOVE)
        self.assertEqual(res["copied_count"], 4)
        for rel, data in self.files.items():
            self.assertEqual((self.tgt / rel).read_bytes(), data)
            self.assertFalse((self.src / rel).exists())

    def test_05_failed_copy_leaves_no_partial_file_and_keeps_source(self):
        big_rel = "Alice Smith/2024-03/IMG-20240103-WA0003.jpg"
        real_copystat = shutil.copystat

        def failing_copystat(src, dst, *a, **kw):
            if Path(src).name == Path(big_rel).name:
                raise OSError("disk full")
            return real_copystat(src, dst, *a, **kw)

        def cross_device(src, dst):
            raise OSError(18, "Invalid cross-device link")

        # Cross-drive move: copy + verify + delete, where the copy of one file fails midway
        with mock.patch("core.migrator.shutil.copystat", side_effect=failing_copystat), \
             mock.patch("core.migrator.os.rename", side_effect=cross_device):
            res = execute_import_folder(str(self.src), str(self.tgt), import_key=False, mode=IMPORT_MODE_MOVE)
        self.assertEqual(res["failed_count"], 1)
        self.assertEqual(res["copied_count"], 3)
        self.assertFalse((self.tgt / big_rel).exists(), "a failed copy must not leave a truncated file")
        self.assertFalse(list(self.tgt.rglob("*.importing")))
        self.assertTrue((self.src / big_rel).is_file(), "the source of a failed move must be kept")

    def test_06_cancel_stops_and_merges_transferred_files(self):
        cancel = threading.Event()
        real_transfer = migrator._transfer_file

        def transfer_then_cancel(*args, **kwargs):
            real_transfer(*args, **kwargs)
            cancel.set()  # user presses Cancel while the first file is being copied

        with mock.patch("core.migrator._transfer_file", side_effect=transfer_then_cancel):
            res = execute_import_folder(str(self.src), str(self.tgt), import_key=False, cancel_event=cancel)
        self.assertEqual(res["status"], "cancelled")
        self.assertEqual(res["copied_count"], 1)
        gallery = (self.tgt / "gallery_data.js").read_text(encoding="utf-8")
        copied = [rel for rel in self.files if (self.tgt / rel).is_file()]
        for rel in copied:
            self.assertIn(rel, gallery, "transferred files must be merged even after cancel")
        self.assertFalse(list(self.tgt.rglob("*.importing")))

    def test_07_rerun_skips_already_imported_files(self):
        execute_import_folder(str(self.src), str(self.tgt), import_key=False)
        res = execute_import_folder(str(self.src), str(self.tgt), import_key=False)
        self.assertEqual(res["copied_count"], 0)
        self.assertEqual(res["skipped_count"], 4)


class TestImportJobManager(ImportTestBase):
    def test_08_job_runs_in_background_and_reports_result(self):
        job = ImportJobManager()
        finished = []
        self.assertTrue(job.start(str(self.src), str(self.tgt), mode=IMPORT_MODE_COPY,
                                  import_key=False, on_finished=finished.append))
        job.wait(30)
        status = job.status()
        self.assertEqual(status["state"], JOB_DONE)
        self.assertEqual(status["result"]["copied_count"], 4)
        self.assertEqual(status["progress"]["percent"], 100)
        self.assertEqual(len(finished), 1)

    def test_09_only_one_import_at_a_time(self):
        gate = threading.Event()

        def slow_runner(*args, **kwargs):
            gate.wait(5)
            return {"status": "success"}

        job = ImportJobManager(runner=slow_runner)
        self.assertTrue(job.start("a", "b"))
        self.assertFalse(job.start("a", "b"), "a second import must be refused while one runs")
        self.assertTrue(job.cancel())
        gate.set()
        job.wait(5)
        self.assertFalse(job.is_running())


class TestWindowsFolderPicker(unittest.TestCase):
    def test_10_win32_calls_declare_pointer_sized_types(self):
        """SHBrowseForFolderW must return c_void_p: a default int return truncates 64-bit PIDLs."""
        import ctypes

        class Fn:
            def __init__(self, result):
                self.result = result
                self.argtypes = None
                self.restype = None

            def __call__(self, *args):
                return self.result(*args) if callable(self.result) else self.result

        def fill_path(pidl, buf):
            buf.value = str(Path(tempfile.gettempdir()))
            return 1

        dll = types.SimpleNamespace(
            ole32=types.SimpleNamespace(CoInitialize=Fn(0), CoUninitialize=Fn(None), CoTaskMemFree=Fn(None)),
            shell32=types.SimpleNamespace(SHBrowseForFolderW=Fn(0x7FF0_0000_1000), SHGetPathFromIDListW=Fn(fill_path)),
            user32=types.SimpleNamespace(GetForegroundWindow=Fn(0), SendMessageW=Fn(0)),
        )
        with mock.patch.object(ctypes, "windll", dll, create=True), \
             mock.patch.object(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE, create=True):
            status, path = migrator._pick_folder_windows_ctypes()
        self.assertEqual(dll.shell32.SHBrowseForFolderW.restype, ctypes.c_void_p)
        self.assertEqual(dll.shell32.SHGetPathFromIDListW.argtypes[0], ctypes.c_void_p)
        self.assertEqual(dll.ole32.CoTaskMemFree.argtypes, [ctypes.c_void_p])
        self.assertEqual((status, path), (PICK_SELECTED, str(Path(tempfile.gettempdir()).resolve())))

        dll.shell32.SHBrowseForFolderW.result = None
        with mock.patch.object(ctypes, "windll", dll, create=True):
            self.assertEqual(migrator._pick_folder_windows_ctypes(), (PICK_CANCELLED, None))


if __name__ == "__main__":
    unittest.main()
