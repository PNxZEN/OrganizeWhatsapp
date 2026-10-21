"""
Tests for the in-app updater (core.version, core.activity, core.updater, core.update_helper):
- version parsing and comparison
- checking GitHub: newer / current / offline / rate limited / unusual tags / no package
- downloading: checksum verification, safe extraction, package validation, cancel, no-space
- the idle gate: nothing is installed while work is running, and nothing new starts while installing
- a real end-to-end install with the detached helper: files swapped, config untouched, new version
  started and health-checked; a broken new version is rolled back automatically
- recovery of an update that was interrupted half-way
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import core.update_helper as helper
import core.updater as updater
from core.activity import ActivityTracker, MaintenanceActive
from core.updater import (
    STATE_ERROR,
    STATE_IDLE,
    STATE_READY,
    UpdateError,
    UpdateManager,
    extract_package,
    parse_requirements,
    unmet_requirements,
)
from core.version import is_newer, parse_version
from update_fixtures import FakeGitHub, build_archive, free_port, make_app_files


class TestVersion(unittest.TestCase):
    def test_01_parse_and_compare(self):
        self.assertEqual(parse_version("v1.0.5.1"), (1, 0, 5, 1))
        self.assertIsNone(parse_version("v2.0.0-beta"))
        self.assertIsNone(parse_version(""))
        self.assertTrue(is_newer("v1.2.1", "1.2.0"))
        self.assertTrue(is_newer("1.10.0", "1.9.9"), "versions compare numerically, not as text")
        self.assertTrue(is_newer("1.0.5.1", "1.0.5"))
        self.assertFalse(is_newer("1.2", "1.2.0"))
        self.assertFalse(is_newer("1.1.9", "1.2.0"))
        self.assertFalse(is_newer("v2.0.0-beta", "1.2.0"), "pre-releases are never offered")

    def test_02_installed_version_matches_a_plain_release_number(self):
        from core.version import __version__
        self.assertIsNotNone(parse_version(__version__))


class TestActivityTracker(unittest.TestCase):
    def test_03_block_refuses_while_work_runs_and_leaves_no_flag(self):
        tracker = ActivityTracker()
        with tracker.track("ZIP backup"):
            self.assertEqual(tracker.block("updating"), ["ZIP backup"])
            self.assertIsNone(tracker.maintenance_message(), "a refused block must not leave maintenance on")
        self.assertEqual(tracker.block("updating"), [])
        self.assertEqual(tracker.maintenance_message(), "updating")

    def test_04_new_work_is_refused_during_maintenance(self):
        tracker = ActivityTracker()
        tracker.block("updating")
        with self.assertRaises(MaintenanceActive):
            with tracker.track("restore to phone"):
                pass
        tracker.unblock()
        with tracker.track("restore to phone"):
            self.assertEqual(tracker.running(), ["restore to phone"])

    def test_05_extra_busy_sources_are_counted(self):
        tracker = ActivityTracker()
        self.assertEqual(tracker.block("updating", extra_busy=lambda: ["phone sync"]), ["phone sync"])
        self.assertIsNone(tracker.maintenance_message())


class TestRequirements(unittest.TestCase):
    def test_06_only_new_or_changed_unmet_requirements_block(self):
        old = "pillow>=10.0.0\nImageHash>=4.3.1  # hashing\n"
        installed = {"pillow": "11.1.0", "imagehash": "4.3.1", "newlib": "2.0.0"}.get
        self.assertEqual(unmet_requirements(old, old, installed), [])
        self.assertEqual(unmet_requirements(old, old + "newlib>=1.0\n", installed), [], "already satisfied")
        self.assertEqual(unmet_requirements(old, old + "missing>=1.0\n", installed), ["missing>=1.0"])
        self.assertEqual(unmet_requirements(old, "pillow>=12.0.0\n", installed), ["pillow>=12.0.0"])
        self.assertEqual(parse_requirements("Pillow_HEIF >= 0.16\n-r other\n# c\n"), {"pillow-heif": ">=0.16"})


class UpdaterTestBase(unittest.TestCase):
    CURRENT = "1.0.0"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wa_test_update_"))
        self.root = self.tmp / "app"
        self.root.mkdir()
        for rel, text in make_app_files(self.CURRENT).items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        (self.root / "config.json").write_text('{"user": "settings"}', encoding="utf-8")
        (self.root / "output").mkdir()
        (self.root / "output" / "keep.txt").write_text("my media", encoding="utf-8")
        self.github = FakeGitHub()
        self.tracker = ActivityTracker()
        self.busy = []
        self.manager = self.make_manager()
        self.spawned = []

    def make_manager(self, **kw):
        m = UpdateManager(
            root=self.root, repo=self.github.repo, api_base=self.github.base,
            current_version=self.CURRENT, tracker=self.tracker, busy_probe=lambda: list(self.busy),
            allowed_hosts=("127.0.0.1",), **kw)
        m._hard_exit = lambda code: None
        return m

    def tearDown(self):
        self.github.close()
        for pid in self.spawned + self.app_processes():
            try:
                os.kill(pid, 9)
            except OSError:
                pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def app_processes(self):
        """Servers started from the throw-away app folder (including ones the helper launched)."""
        if not os.path.isdir("/proc"):
            return []
        found = []
        for entry in os.listdir("/proc"):
            if entry.isdigit():
                try:
                    cmdline = Path(f"/proc/{entry}/cmdline").read_bytes().decode(errors="ignore")
                except OSError:
                    continue
                if str(self.root) in cmdline and int(entry) != os.getpid():
                    found.append(int(entry))
        return found

    def wait_for(self, states, timeout=15):
        deadline = time.time() + timeout
        while time.time() < deadline:
            st = self.manager.status()
            if st["state"] in states:
                return st
            time.sleep(0.02)
        self.fail(f"update state stayed {self.manager.status()['state']}, expected one of {states}")

    def download(self):
        self.manager.start_download()
        return self.wait_for((STATE_READY, STATE_ERROR, STATE_IDLE))


class TestCheck(UpdaterTestBase):
    def test_10_newer_release_is_reported_with_notes(self):
        self.github.publish("1.1.0", notes="- faster\n- safer")
        res = self.manager.check()
        self.assertTrue(res["update_available"])
        self.assertEqual(res["latest_version"], "1.1.0")
        self.assertIn("faster", res["release"]["notes"])
        self.assertTrue(res["has_package"])

    def test_11_same_or_older_release_is_not_an_update(self):
        self.github.publish("1.0.0")
        self.assertFalse(self.manager.check()["update_available"])
        self.github.publish("0.9.0")
        self.assertFalse(self.manager.check(force=True)["update_available"])
        with self.assertRaises(UpdateError) as ctx:
            self.manager.start_download()
        self.assertEqual(ctx.exception.code, "up_to_date")

    def test_12_results_are_cached_unless_forced(self):
        self.github.publish("1.1.0")
        self.manager.check()
        self.manager.check()
        self.assertEqual(sum("releases/latest" in r for r in self.github.requests), 1)
        self.manager.check(force=True)
        self.assertEqual(sum("releases/latest" in r for r in self.github.requests), 2)

    def test_13_offline_is_a_friendly_error(self):
        self.github.close()
        with self.assertRaises(UpdateError) as ctx:
            self.manager.check()
        self.assertEqual(ctx.exception.code, "offline")
        self.github = FakeGitHub()  # so tearDown has something to close

    def test_14_rate_limit_and_missing_release(self):
        self.github.api_status = 403
        self.github.api_headers = {"X-RateLimit-Remaining": "0"}
        with self.assertRaises(UpdateError) as ctx:
            self.manager.check()
        self.assertEqual(ctx.exception.code, "rate_limited")
        self.github.api_status = 404
        with self.assertRaises(UpdateError) as ctx:
            self.manager.check(force=True)
        self.assertEqual(ctx.exception.code, "not_found")

    def test_15_unusual_tag_and_missing_package(self):
        self.github.publish("1.1.0", tag="nightly")
        with self.assertRaises(UpdateError) as ctx:
            self.manager.check()
        self.assertEqual(ctx.exception.code, "bad_release")
        self.github.publish("1.1.0")
        self.github.release["assets"] = []
        res = self.manager.check(force=True)
        self.assertFalse(res["has_package"])
        with self.assertRaises(UpdateError) as ctx:
            self.manager.start_download()
        self.assertEqual(ctx.exception.code, "no_package")

    def test_16_only_github_hosts_are_contacted(self):
        strict = UpdateManager(root=self.root, repo="o/r", api_base="https://evil.example.com",
                               current_version=self.CURRENT, tracker=self.tracker)
        with self.assertRaises(UpdateError) as ctx:
            strict.check()
        self.assertEqual(ctx.exception.code, "blocked_host")

    def test_17_git_checkouts_do_not_self_update(self):
        (self.root / ".git").mkdir()
        self.github.publish("1.1.0")
        info = self.manager.install_info()
        self.assertEqual(info["kind"], "git")
        self.assertFalse(info["can_self_update"])
        with self.assertRaises(UpdateError) as ctx:
            self.manager.start_download()
        self.assertEqual(ctx.exception.code, "unsupported_install")


class TestDownload(UpdaterTestBase):
    def test_20_download_verifies_and_stages_only_application_files(self):
        self.github.publish("1.1.0")
        st = self.download()
        self.assertEqual(st["state"], STATE_READY, st)
        staging = self.root / ".update" / "staging"
        self.assertTrue((staging / "core" / "version.py").is_file())
        self.assertTrue((staging / "gallery_assets" / "js" / "app.js").is_file())
        self.assertFalse((staging / "config.json").exists(), "the config template must never be installed")
        self.assertFalse((self.root / ".update" / "download" / "WhatsAppMediaOrganizer-v1.1.0-Unix-Source.tar.gz").exists())
        # the running installation is untouched until the user restarts
        self.assertIn(self.CURRENT, (self.root / "core" / "version.py").read_text())

    def test_21_download_uses_checksum_file_when_api_has_no_digest(self):
        self.github.publish("1.1.0", with_digest=False)
        self.assertEqual(self.download()["state"], STATE_READY)

    def test_22_tampered_download_is_rejected_and_discarded(self):
        self.github.publish("1.1.0", bad_checksum=True)
        st = self.download()
        self.assertEqual(st["state"], STATE_ERROR)
        self.assertEqual(st["error"]["code"], "checksum_mismatch")
        self.assertFalse((self.root / ".update" / "staging").exists())
        self.assertFalse(any((self.root / ".update" / "download").glob("*")) if (self.root / ".update" / "download").exists() else False)

    def test_23_release_without_any_checksum_is_refused(self):
        self.github.publish("1.1.0", with_digest=False, with_checksum_file=False)
        st = self.download()
        self.assertEqual(st["error"]["code"], "no_checksum")

    def test_24_digest_and_checksum_file_must_agree(self):
        self.github.publish("1.1.0")
        name = "WhatsAppMediaOrganizer-v1.1.0-Unix-Source.tar.gz"
        self.github.assets[f"/dl/{name}.sha256"] = (b"0" * 64) + b"  x\n"
        st = self.download()
        self.assertEqual(st["error"]["code"], "checksum_mismatch")

    def test_25_package_with_wrong_version_is_rejected(self):
        self.github.publish("1.1.0", archive=build_archive("1.1.0", make_app_files("1.0.7")))
        st = self.download()
        self.assertEqual(st["error"]["code"], "bad_package")
        self.assertIn("1.0.7", st["error"]["message"])

    def test_26_package_with_broken_python_is_rejected(self):
        files = make_app_files("1.1.0")
        files["core/broken.py"] = "def oops(:\n"
        self.github.publish("1.1.0", archive=build_archive("1.1.0", files))
        self.assertEqual(self.download()["error"]["code"], "bad_package")

    def test_27_incomplete_package_is_rejected(self):
        files = make_app_files("1.1.0")
        del files["gallery.html"]
        self.github.publish("1.1.0", archive=build_archive("1.1.0", files))
        st = self.download()
        self.assertEqual(st["error"]["code"], "bad_package")
        self.assertIn("gallery.html", st["error"]["message"])

    def test_28_new_dependencies_block_the_in_app_update(self):
        files = make_app_files("1.1.0")
        files["requirements.txt"] = "pillow>=10.0.0\nsurely-not-installed-package>=9\n"
        self.github.publish("1.1.0", archive=build_archive("1.1.0", files))
        st = self.download()
        self.assertEqual(st["error"]["code"], "needs_reinstall")
        self.assertIn("surely-not-installed-package", st["error"]["message"])

    def test_29_cancel_during_download_leaves_nothing_behind(self):
        gate = threading.Event()
        self.github.slow_download = gate
        self.github.publish("1.1.0")
        self.manager.start_download()
        self.wait_for(("downloading",))
        time.sleep(0.2)
        self.manager.cancel()
        gate.set()
        st = self.wait_for((STATE_IDLE,))
        self.assertEqual(st["state"], STATE_IDLE)
        self.assertFalse((self.root / ".update" / "staging").exists())

    def test_30_second_download_while_one_runs_is_refused(self):
        gate = threading.Event()
        self.github.slow_download = gate
        self.github.publish("1.1.0")
        self.manager.start_download()
        self.wait_for(("downloading",))
        with self.assertRaises(UpdateError) as ctx:
            self.manager.start_download()
        self.assertEqual(ctx.exception.code, "busy")
        gate.set()
        self.wait_for((STATE_READY,))

    def test_31_not_enough_disk_space(self):
        self.github.publish("1.1.0")
        with mock.patch("core.updater.shutil.disk_usage", return_value=mock.Mock(free=1024)):
            st = self.download()
        self.assertEqual(st["error"]["code"], "no_space")

    def test_32_discarding_a_ready_update_cleans_up(self):
        self.github.publish("1.1.0")
        self.assertEqual(self.download()["state"], STATE_READY)
        self.manager.cancel()
        self.assertEqual(self.manager.status()["state"], STATE_IDLE)
        self.assertFalse((self.root / ".update" / "staging").exists())


class TestExtractionSafety(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wa_test_extract_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def extract(self, data):
        archive = self.tmp / "a.tar.gz"
        archive.write_bytes(data)
        return extract_package(archive, self.tmp / "out")

    def add(self, name, data=b"x", type_=None, linkname=""):
        import io
        import tarfile

        def mutate(tar, top):
            info = tarfile.TarInfo(name.replace("{top}", top))
            if type_:
                info.type = type_
                info.linkname = linkname
            else:
                info.size = len(data)
            tar.addfile(info, io.BytesIO(data) if not type_ else None)
        return mutate

    def test_40_path_traversal_is_rejected(self):
        for name in ("{top}/core/../../evil.py", "{top}/../evil.py"):
            with self.assertRaises(UpdateError, msg=name):
                self.extract(build_archive("1.1.0", mutate=self.add(name)))
        self.assertFalse((self.tmp / "evil.py").exists())

    def test_41_links_and_special_files_are_rejected(self):
        import tarfile
        with self.assertRaises(UpdateError):
            self.extract(build_archive("1.1.0", mutate=self.add("{top}/core/link", type_=tarfile.SYMTYPE, linkname="/etc/passwd")))
        with self.assertRaises(UpdateError):
            self.extract(build_archive("1.1.0", mutate=self.add("{top}/core/dev", type_=tarfile.CHRTYPE)))

    def test_42_user_data_and_unknown_entries_are_never_extracted(self):
        mutate = self.add("{top}/output/keep.jpg")
        self.extract(build_archive("1.1.0", mutate=mutate))
        out = self.tmp / "out"
        self.assertFalse((out / "output").exists())
        self.assertFalse((out / "config.json").exists())

    def test_43_executable_bit_survives_for_shell_scripts(self):
        files = make_app_files("1.1.0")
        files["start_gallery.sh"] = "#!/bin/sh\n"
        self.extract(build_archive("1.1.0", files))
        if os.name != "nt":
            self.assertTrue(os.access(self.tmp / "out" / "start_gallery.sh", os.X_OK))

    def test_44_garbage_is_not_an_archive(self):
        with self.assertRaises(UpdateError) as ctx:
            self.extract(b"this is not a tar file")
        self.assertEqual(ctx.exception.code, "bad_package")


class TestApplyGate(UpdaterTestBase):
    def test_50_apply_needs_a_downloaded_update(self):
        with self.assertRaises(UpdateError) as ctx:
            self.manager.apply(lambda: None, 8000, "out")
        self.assertEqual(ctx.exception.code, "not_ready")

    def test_51_apply_is_refused_while_anything_runs(self):
        self.github.publish("1.1.0")
        self.assertEqual(self.download()["state"], STATE_READY)
        self.busy = ["phone sync"]
        self.assertEqual(self.manager.status()["busy"], ["phone sync"])
        with self.assertRaises(UpdateError) as ctx:
            self.manager.apply(lambda: self.fail("must not shut down"), 8000, "out")
        self.assertEqual(ctx.exception.code, "busy")
        self.assertIn("phone sync", ctx.exception.message)
        self.assertIsNone(self.tracker.maintenance_message())

        self.busy = []
        with self.tracker.track("ZIP backup"):
            with self.assertRaises(UpdateError):
                self.manager.apply(lambda: None, 8000, "out")
        self.assertEqual(self.manager.status()["state"], STATE_READY, "a refused install keeps the download")

    def test_52_failure_to_start_the_installer_reopens_the_app(self):
        self.github.publish("1.1.0")
        self.download()
        with mock.patch.object(UpdateManager, "_spawn_helper", side_effect=OSError("no process for you")):
            with self.assertRaises(UpdateError) as ctx:
                self.manager.apply(lambda: self.fail("must not shut down"), 8000, "out")
        self.assertEqual(ctx.exception.code, "apply_failed")
        self.assertIsNone(self.tracker.maintenance_message(), "the app must accept work again")
        self.assertEqual(self.manager.status()["state"], STATE_READY)

    def test_53_installing_blocks_new_work_and_asks_for_shutdown(self):
        self.github.publish("1.1.0")
        self.download()
        shutdowns = []
        with mock.patch.object(UpdateManager, "_spawn_helper") as spawn:
            self.manager.apply(lambda: shutdowns.append(1), 8000, "out")
        self.assertEqual(shutdowns, [1])
        self.assertEqual(spawn.call_count, 1)
        self.assertEqual(self.manager.status()["state"], "applying")
        with self.assertRaises(MaintenanceActive):
            with self.tracker.track("ZIP backup"):
                pass
        with self.assertRaises(UpdateError):
            self.manager.cancel()

    def test_54_relaunch_command_is_plain_server_mode(self):
        cmd = updater.build_relaunch_command("/py", Path("/app"), "/data/out", 8005, 0, True)
        self.assertEqual(cmd[:3], ["/py", str(Path("/app/wa_media_organizer.py")), "--serve"])
        self.assertIn("--allow-lan", cmd)
        self.assertEqual(cmd[cmd.index("--port") + 1], "8005")
        self.assertNotIn("--auto-open", cmd)
        self.assertNotIn("--live", cmd)


class EndToEndBase(UpdaterTestBase):
    """Runs the real detached helper against a throw-away application folder."""

    def install(self, new_files=None, expect_status=None, version="1.1.0"):
        self.github.publish(version, archive=build_archive(version, new_files) if new_files else None)
        self.assertEqual(self.download()["state"], STATE_READY)

        port = free_port()
        old = subprocess.Popen([sys.executable, str(self.root / "wa_media_organizer.py"), "--serve", "--port", str(port)])
        self.spawned.append(old.pid)
        self.wait_health(port, self.CURRENT)

        self.manager._pid = old.pid
        self.manager.apply(lambda: (old.terminate(), old.wait(10)), port, str(self.root / "output"))
        self.wait_result(expect_status)
        return port

    def wait_health(self, port, version, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as r:
                    data = json.loads(r.read())
                if data["version"] == version:
                    self.spawned.append(data["pid"])
                    return data
            except Exception:
                pass
            time.sleep(0.2)
        self.fail(f"no healthy server with version {version} on port {port}")

    def wait_result(self, expect_status, timeout=60):
        path = self.root / ".update" / "last_result.json"
        deadline = time.time() + timeout
        while time.time() < deadline:
            if path.exists():
                result = json.loads(path.read_text())
                self.assertEqual(result["status"], expect_status, result)
                return result
            time.sleep(0.2)
        self.fail("the update helper never reported a result")


class TestEndToEndInstall(EndToEndBase):
    def test_60_update_swaps_files_keeps_user_data_and_restarts(self):
        port = self.install(expect_status="updated")
        self.wait_health(port, "1.1.0")
        self.assertIn("1.1.0", (self.root / "core" / "version.py").read_text())
        self.assertIn("1.1.0", (self.root / "gallery_assets" / "js" / "app.js").read_text())
        self.assertEqual((self.root / "config.json").read_text(), '{"user": "settings"}', "settings must survive")
        self.assertEqual((self.root / "output" / "keep.txt").read_text(), "my media")
        backups = list((self.root / ".update").glob("backup-*"))
        self.assertEqual(len(backups), 1)
        self.assertIn("1.0.0", (backups[0] / "core" / "version.py").read_text())
        self.assertFalse((self.root / ".update" / "staging").exists())
        # the one-time notice for the UI
        result = self.manager.consume_last_result()
        self.assertEqual((result["status"], result["from"], result["to"]), ("updated", "1.0.0", "1.1.0"))
        self.assertIsNone(self.manager.consume_last_result(), "the notice is shown once")

    def test_61_files_removed_in_the_new_version_do_not_linger(self):
        (self.root / "gallery_assets" / "js" / "old_feature.js").write_text("// removed upstream")
        self.install(expect_status="updated")
        self.assertFalse((self.root / "gallery_assets" / "js" / "old_feature.js").exists())

    def test_62_new_version_that_fails_to_start_is_rolled_back(self):
        files = make_app_files("1.1.0", extra="# CRASH_ON_START\n")
        port = self.install(new_files=files, expect_status="rolled_back")
        self.wait_health(port, "1.0.0")  # the previous version is running again
        self.assertIn("1.0.0", (self.root / "core" / "version.py").read_text())
        self.assertIn("1.0.0", (self.root / "gallery_assets" / "js" / "app.js").read_text())
        self.assertEqual((self.root / "config.json").read_text(), '{"user": "settings"}')
        result = json.loads((self.root / ".update" / "last_result.json").read_text())
        self.assertIn("did not start", result["error"])


class TestHelperEdgeCases(UpdaterTestBase):
    def plan(self, **over):
        udir = self.root / ".update"
        staging = udir / "staging"
        for rel, text in make_app_files("1.1.0").items():
            if rel != "config.json":
                p = staging / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text)
        plan = {
            "app_root": str(self.root), "update_dir": str(udir), "staging": str(staging),
            "backup": str(udir / "backup-test"), "entries": ["core", "gallery_assets", "gallery.html"],
            "from_version": "1.0.0", "to_version": "1.1.0", "old_pid": 0, "port": free_port(),
            "cwd": str(self.root), "command": [sys.executable, str(self.root / "wa_media_organizer.py")],
        }
        plan.update(over)
        path = udir / "plan.json"
        path.write_text(json.dumps(plan))
        return path

    def test_70_old_server_that_will_not_exit_leaves_everything_untouched(self):
        sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(sleeper.kill)
        path = self.plan(old_pid=sleeper.pid)
        with mock.patch.object(helper, "WAIT_FOR_EXIT_SECS", 1):
            self.assertEqual(helper.run(path), 1)
        self.assertIn("1.0.0", (self.root / "core" / "version.py").read_text())
        result = json.loads((self.root / ".update" / "last_result.json").read_text())
        self.assertEqual(result["status"], "failed")

    def test_71_failure_midway_restores_every_moved_entry(self):
        path = self.plan()
        real_move = helper._move
        calls = {"n": 0}

        def flaky_move(src, dst):
            calls["n"] += 1
            if calls["n"] == 4:  # while installing the second entry
                raise OSError("disk exploded")
            return real_move(src, dst)

        with mock.patch.object(helper, "_move", flaky_move), \
             mock.patch.object(helper, "MOVE_RETRIES", 1), \
             mock.patch.object(helper, "_launch", return_value=mock.Mock(poll=lambda: 0)), \
             mock.patch.object(helper, "_wait_healthy", return_value=True):
            helper.run(path)
        self.assertIn("1.0.0", (self.root / "core" / "version.py").read_text())
        self.assertIn("1.0.0", (self.root / "gallery_assets" / "js" / "app.js").read_text())
        self.assertIn("1.0.0", (self.root / "gallery.html").read_text())
        result = json.loads((self.root / ".update" / "last_result.json").read_text())
        self.assertEqual(result["status"], "rolled_back")

    def test_72_interrupted_update_is_rolled_back_on_next_start(self):
        udir = self.root / ".update"
        backup = udir / "backup-x"
        backup.mkdir(parents=True)
        shutil.move(str(self.root / "core"), str(backup / "core"))  # half-way: old core saved...
        (self.root / "core").mkdir()                                # ...new core partially in place
        (self.root / "core" / "version.py").write_text('__version__ = "1.1.0"\n')
        (udir / "journal.json").write_text(json.dumps({
            "status": "applying", "helper_pid": 2 ** 22 + 12345, "backup": str(backup),
            "from_version": "1.0.0", "to_version": "1.1.0",
            "moved": [{"name": "core", "had_old": True}, {"name": "gallery.html", "had_old": True}],
        }))
        self.assertTrue(helper.recover_interrupted_update(self.root))
        self.assertIn("1.0.0", (self.root / "core" / "version.py").read_text())
        self.assertIn("1.0.0", (self.root / "gallery.html").read_text())
        self.assertEqual(json.loads((udir / "last_result.json").read_text())["status"], "rolled_back")
        self.assertFalse(helper.recover_interrupted_update(self.root), "recovery runs only once")

    def test_73_recovery_leaves_a_live_helper_alone(self):
        udir = self.root / ".update"
        udir.mkdir(exist_ok=True)
        (udir / "journal.json").write_text(json.dumps({
            "status": "applying", "helper_pid": os.getpid(), "backup": str(udir / "b"), "moved": []}))
        self.assertFalse(helper.recover_interrupted_update(self.root))


if __name__ == "__main__":
    unittest.main()
