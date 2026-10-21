"""
"Show in File Explorer / Finder / Files" must open the folder WITH the file selected, also for
chat folders whose names contain commas or emoji (Explorer splits /select, at commas).
"""

import ctypes
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.reveal as reveal


class Fn:
    def __init__(self, result):
        self.result = result
        self.calls = []
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        self.calls.append(args)
        return self.result


class TestReveal(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wa_test_reveal_"))
        folder = self.tmp / "Andi mandi shandi , jisne photo nahi bheje vo" / "2023-08"
        folder.mkdir(parents=True)
        self.file = folder / "STK-20230807-WA0003.webp"
        self.file.write_bytes(b"x")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fake_windll(self, pidl=0x7FF000001000, open_result=0):
        return types.SimpleNamespace(
            shell32=types.SimpleNamespace(ILCreateFromPathW=Fn(pidl), SHOpenFolderAndSelectItems=Fn(open_result),
                                          ILFree=Fn(None)),
            ole32=types.SimpleNamespace(CoInitialize=Fn(0), CoUninitialize=Fn(None)),
        )

    def test_01_windows_selects_through_the_shell_api(self):
        dll = self.fake_windll()
        with mock.patch.object(reveal.platform, "system", return_value="Windows"), \
             mock.patch.object(ctypes, "windll", dll, create=True), \
             mock.patch.object(reveal.subprocess, "Popen") as popen:
            self.assertEqual(reveal.reveal_in_file_manager(self.file), "shell")
        popen.assert_not_called()
        self.assertIn(", jisne", dll.shell32.ILCreateFromPathW.calls[0][0], "the full path, comma included")
        self.assertEqual(dll.shell32.SHOpenFolderAndSelectItems.calls[0][0], 0x7FF000001000)
        self.assertEqual(dll.shell32.ILCreateFromPathW.restype, ctypes.c_void_p, "64-bit pointer must not be truncated")
        self.assertEqual(len(dll.shell32.ILFree.calls), 1, "the item list is freed")
        self.assertEqual(len(dll.ole32.CoUninitialize.calls), 1)

    def test_02_windows_falls_back_to_explorer(self):
        dll = self.fake_windll(pidl=0)
        with mock.patch.object(reveal.platform, "system", return_value="Windows"), \
             mock.patch.object(ctypes, "windll", dll, create=True), \
             mock.patch.object(reveal.subprocess, "Popen") as popen:
            self.assertEqual(reveal.reveal_in_file_manager(self.file), "explorer")
        cmd = popen.call_args[0][0]
        self.assertTrue(cmd.startswith('explorer /select,"') and cmd.endswith('STK-20230807-WA0003.webp"'), cmd)

    def test_03_macos_reveals_in_finder(self):
        with mock.patch.object(reveal.platform, "system", return_value="Darwin"), \
             mock.patch.object(reveal.subprocess, "Popen") as popen:
            self.assertEqual(reveal.reveal_in_file_manager(self.file), "finder")
        self.assertEqual(popen.call_args[0][0], ["open", "-R", str(self.file)])

    def test_04_linux_selects_through_the_file_manager_dbus_api(self):
        ran = []

        def fake_run(cmd, **kw):
            ran.append(cmd)
            return types.SimpleNamespace(returncode=0)

        with mock.patch.object(reveal.platform, "system", return_value="Linux"), \
             mock.patch.object(reveal.shutil, "which", lambda name: "/usr/bin/gdbus" if name == "gdbus" else None), \
             mock.patch.object(reveal.subprocess, "run", fake_run), \
             mock.patch.object(reveal.subprocess, "Popen") as popen:
            self.assertEqual(reveal.reveal_in_file_manager(self.file), "dbus")
        popen.assert_not_called()
        arg = ran[0][ran[0].index("org.freedesktop.FileManager1.ShowItems") + 1]
        self.assertIn("%2C", arg, "the URI is percent-encoded, so the comma cannot break the call")
        self.assertTrue(arg.startswith("['file://") and arg.endswith("STK-20230807-WA0003.webp']"))

    def test_05_linux_without_a_file_manager_service_opens_the_folder(self):
        with mock.patch.object(reveal.platform, "system", return_value="Linux"), \
             mock.patch.object(reveal.shutil, "which", return_value=None), \
             mock.patch.object(reveal.subprocess, "Popen") as popen:
            self.assertEqual(reveal.reveal_in_file_manager(self.file), "xdg-open")
        self.assertEqual(popen.call_args[0][0], ["xdg-open", str(self.file.parent)])


if __name__ == "__main__":
    unittest.main()
