"""ADB download and ffmpeg lookup for the macOS / Linux package (core/platform_tools.py)."""

import io
import shutil
import sys
import tempfile
import types
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import config, platform_tools  # noqa: E402
from core.updater import unmet_requirements  # noqa: E402

POSIX = sys.platform != "win32"


def make_zip(path: Path, adb_exit_code=0, extra=()):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("platform-tools/adb", f"#!/bin/sh\nexit {adb_exit_code}\n")
        zf.writestr("platform-tools/lib64/libc++.so", "lib")
        zf.writestr("platform-tools/fastboot", "not needed")
        for name in extra:
            zf.writestr(name, "evil")
    return path.as_uri()


class PlatformToolsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.app = self.tmp / "app"
        self.app.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_01_download_url_per_computer(self):
        self.assertIn("darwin", platform_tools.platform_tools_url("Darwin", "arm64"))
        self.assertIn("darwin", platform_tools.platform_tools_url("Darwin", "x86_64"))
        self.assertIn("linux", platform_tools.platform_tools_url("Linux", "x86_64"))
        self.assertIsNone(platform_tools.platform_tools_url("Linux", "aarch64"))  # Google has no build

    def test_02_only_adb_and_its_libraries_are_extracted(self):
        wanted = platform_tools._wanted_member
        self.assertEqual(wanted("platform-tools/adb"), Path("platform-tools/adb"))
        self.assertEqual(wanted("platform-tools/lib64/libc++.so"), Path("platform-tools/lib64/libc++.so"))
        for bad in ("platform-tools/fastboot", "platform-tools/../evil", "../platform-tools/adb",
                    "platform-tools/lib64/../../evil", "other/adb", "/platform-tools/adb", "platform-tools/lib64/a/b"):
            self.assertIsNone(wanted(bad), bad)

    @unittest.skipUnless(POSIX, "the fake adb is a shell script")
    def test_03_install_adb(self):
        url = make_zip(self.tmp / "pt.zip", extra=("platform-tools/../escaped",))
        adb = platform_tools.install_adb(self.app, url=url)
        self.assertEqual(adb, self.app / "bin" / "platform-tools" / "adb")
        self.assertTrue(adb.stat().st_mode & 0o111)
        self.assertTrue((self.app / "bin" / "platform-tools" / "lib64" / "libc++.so").is_file())
        self.assertFalse((self.app / "bin" / "platform-tools" / "fastboot").exists())
        self.assertFalse((self.app / "bin" / "escaped").exists())
        self.assertEqual([p.name for p in (self.app / "bin").iterdir()], ["platform-tools"])  # no temp left
        self.assertEqual(platform_tools.find_adb(self.app), str(adb))

    @unittest.skipUnless(POSIX, "the fake adb is a shell script")
    def test_04_an_adb_that_does_not_run_is_not_installed(self):
        url = make_zip(self.tmp / "pt.zip", adb_exit_code=1)
        with self.assertRaises(RuntimeError):
            platform_tools.install_adb(self.app, url=url)
        self.assertEqual(list((self.app / "bin").iterdir()), [])

    def test_05_a_failed_download_never_stops_setup(self):
        with mock.patch.object(platform_tools, "find_adb", return_value=None), \
                mock.patch.object(platform_tools, "platform_tools_url", return_value="https://example.invalid/x.zip"), \
                mock.patch.object(platform_tools, "install_adb", side_effect=OSError("offline")), \
                mock.patch.object(platform_tools, "find_ffmpeg", return_value="/x/ffmpeg"):
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(platform_tools.main(["--setup"]), 0)
        self.assertIn("Could not download ADB: offline", out.getvalue())
        self.assertIn("install it yourself", out.getvalue())

    def test_06_a_normal_launch_never_downloads(self):
        with mock.patch.object(platform_tools, "find_adb", return_value=None), \
                mock.patch.object(platform_tools, "install_adb") as install, \
                mock.patch.object(platform_tools, "find_ffmpeg", return_value=None):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(platform_tools.main([]), 0)
        install.assert_not_called()

    def test_07_ffmpeg_from_imageio_when_none_is_installed(self):
        fake_exe = self.tmp / "ffmpeg-from-pip"
        fake_exe.write_text("")
        fake = types.SimpleNamespace(get_ffmpeg_exe=lambda: str(fake_exe))
        with mock.patch.dict(sys.modules, {"imageio_ffmpeg": fake}), \
                mock.patch("shutil.which", return_value=None), \
                mock.patch.object(Path, "is_file", lambda p: str(p) == str(fake_exe)):
            self.assertEqual(config.find_ffmpeg_binary(), str(fake_exe))

    def test_08_a_system_ffmpeg_still_wins(self):
        fake = types.SimpleNamespace(get_ffmpeg_exe=lambda: "/pip/ffmpeg")
        with mock.patch.dict(sys.modules, {"imageio_ffmpeg": fake}), \
                mock.patch("shutil.which", return_value="/usr/local/bin/ffmpeg"), \
                mock.patch.object(Path, "is_file", lambda p: False):
            self.assertEqual(config.find_ffmpeg_binary(), "/usr/local/bin/ffmpeg")

    def test_09_optional_tools_do_not_block_an_in_app_update(self):
        old = "pycryptodomex>=3.20.0\npillow>=10.0.0\npillow_heif>=0.16.0\nImageHash>=4.3.1\nwa-crypt-tools>=0.1.0\n"
        new = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("-r core/requirements-optional.txt", new)
        self.assertTrue((ROOT / "core" / "requirements-optional.txt").is_file())
        # imageio-ffmpeg is not installed yet in a 1.2.2 venv; the update must still be allowed
        installed = lambda name: None if "imageio" in name else "99"
        self.assertEqual(unmet_requirements(old, new, installed_version=installed), [])


if __name__ == "__main__":
    unittest.main()
