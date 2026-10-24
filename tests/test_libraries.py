"""
One library per WhatsApp account (core/libraries.py): settings kept apart in config.json, folders
of its own, one sync on the phone at a time, and its own gallery server in its own tab.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import core.server as srv  # noqa: E402
from core import libraries  # noqa: E402
from core.config import load_config, save_config, set_active_profile  # noqa: E402

ACC = "/storage/emulated/0/Android/media/com.whatsapp/WhatsApp/accounts/1002"
BIZ = "/storage/emulated/0/Android/media/com.whatsapp.w4b/WhatsApp Business"


class InTempApp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wa_libs_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cwd = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, self.cwd)
        self.addCleanup(set_active_profile, None)
        (self.tmp / "output").mkdir()
        save_config({"hex_key": "a" * 64, "selected_account_path": ACC, "selected_account_label": "WhatsApp (account 1002)",
                     "auto_check_updates": True, "primary_output_dir": str(self.tmp / "output")})


class ProfilesKeepAccountsApart(InTempApp):
    def test_an_account_library_sees_its_own_settings_and_the_shared_ones(self):
        libraries.ensure_library({"path": BIZ, "app_type": "whatsapp_business", "phone_number": "+15550001", "phone_verified": True})
        set_active_profile(BIZ)
        cfg = load_config()
        self.assertEqual(cfg["hex_key"], "")
        self.assertEqual(cfg["selected_account_path"], BIZ)
        self.assertEqual(cfg["selected_account_label"], "WhatsApp Business (+15550001)")
        self.assertTrue(cfg["auto_check_updates"])  # app-wide
        save_config({"hex_key": "b" * 64, "exclude_jids": ["x@g.us"], "auto_check_updates": False})
        set_active_profile(None)
        cfg = load_config()
        self.assertEqual(cfg["hex_key"], "a" * 64)
        self.assertNotIn("x@g.us", cfg.get("exclude_jids") or [])
        self.assertFalse(cfg["auto_check_updates"])  # app-wide: changed for every library
        stored = json.loads((self.tmp / "config.json").read_text())
        self.assertEqual(stored["profiles"][BIZ]["hex_key"], "b" * 64)
        self.assertFalse((self.tmp / "config.json.lock").exists())

    def test_a_remembered_key_comes_with_a_new_library(self):
        save_config({"account_keys": {BIZ: "c" * 64}})
        libraries.ensure_library({"path": BIZ, "app_type": "whatsapp_business"})
        set_active_profile(BIZ)
        self.assertEqual(load_config()["hex_key"], "c" * 64)

    def test_library_folders_sit_beside_the_first_and_never_collide(self):
        a = libraries.ensure_library({"path": BIZ, "app_type": "whatsapp_business", "phone_number": "+1 555/0001", "phone_verified": True})
        self.assertEqual(Path(a["output_dir"]), self.tmp / "output - WhatsApp Business (+1 5550001)")
        self.assertTrue(Path(a["output_dir"]).is_dir())
        other = "/storage/emulated/95/Android/media/com.whatsapp.w4b/WhatsApp Business"
        b = libraries.ensure_library({"path": other, "app_type": "whatsapp_business", "phone_number": "+1 555/0001", "phone_verified": True})
        self.assertNotEqual(a["output_dir"], b["output_dir"])
        self.assertEqual(libraries.ensure_library({"path": BIZ})["output_dir"], a["output_dir"])  # once
        labels = [lib["label"] for lib in libraries.list_libraries(self.tmp / "output")]
        self.assertEqual(labels[0], "WhatsApp (account 1002)")
        self.assertEqual(len(labels), 3)

    def test_a_guessed_number_does_not_name_a_library(self):
        # The SIM's number, offered for every account the scan could not identify
        lib = libraries.ensure_library({"path": ACC.replace("1002", "1003"), "account_id": "1003",
                                        "app_type": "whatsapp", "phone_number": "+15550009"})
        self.assertEqual(lib["label"], "WhatsApp (account 1003)")

    def test_a_library_is_listed_under_its_confirmed_number_after_a_sync(self):
        libraries.ensure_library({"path": BIZ, "app_type": "whatsapp_business"})
        set_active_profile(BIZ)
        save_config({"selected_account_label": "WhatsApp Business (+15550001)"})  # what a sync records
        set_active_profile(None)
        labels = {lib["account"]: lib["label"] for lib in libraries.list_libraries(self.tmp / "output")}
        self.assertEqual(labels[BIZ], "WhatsApp Business (+15550001)")

    def test_the_first_library_must_have_its_account_first(self):
        save_config({"selected_account_path": ""})
        with self.assertRaises(ValueError):
            libraries.ensure_library({"path": BIZ})


class OneSyncOnThePhoneAtATime(InTempApp):
    def other_process(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(proc.kill)
        return proc

    def test_another_tabs_sync_holds_the_phone(self):
        proc = self.other_process()
        Path(libraries.PHONE_LOCK).write_text(json.dumps({"pid": proc.pid, "label": "WhatsApp Business"}))
        self.assertEqual(libraries.acquire_phone("me", "output")["label"], "WhatsApp Business")
        self.assertFalse(srv._start_background_sync(str(self.tmp / "output")))
        payload = srv._sync_busy_payload()
        self.assertEqual(payload["status"], "phone_busy")
        self.assertIn("WhatsApp Business", payload["message"])
        self.assertFalse(srv.sync_status.get("active"))

    def test_a_lock_left_by_a_closed_tab_is_ignored(self):
        proc = self.other_process()
        proc.kill()
        proc.wait()
        Path(libraries.PHONE_LOCK).write_text(json.dumps({"pid": proc.pid, "label": "gone"}))
        self.assertIsNone(libraries.acquire_phone("me", "output"))
        self.assertEqual(json.loads(Path(libraries.PHONE_LOCK).read_text())["pid"], os.getpid())
        libraries.release_phone()
        self.assertFalse(Path(libraries.PHONE_LOCK).exists())


class AccountChoice(InTempApp):
    def test_a_library_with_chats_keeps_its_account(self):
        out = self.tmp / "output"
        self.assertIsNone(srv._account_choice_refusal(out, BIZ))  # nothing synced yet: free to choose
        (out / "media_index.csv").write_text("rel_path\n")
        self.assertEqual(srv._account_choice_refusal(out, BIZ)["status"], "own_library")
        self.assertIsNone(srv._account_choice_refusal(out, ACC))

    def test_an_account_with_its_own_library_is_not_chosen_for_another(self):
        save_config({"selected_account_path": ""})
        save_config({"selected_account_path": ACC})
        libraries.ensure_library({"path": BIZ, "app_type": "whatsapp_business"})
        save_config({"selected_account_path": ""})  # a fresh first library, nothing synced yet
        refusal = srv._account_choice_refusal(self.tmp / "output", BIZ)
        self.assertEqual(refusal["status"], "own_library")

    def test_deleting_the_key_in_an_accounts_tab_keeps_the_first_accounts_key_file(self):
        (self.tmp / "encrypted_backup.key").write_bytes(b"first")
        libraries.ensure_library({"path": BIZ, "app_type": "whatsapp_business"})
        set_active_profile(BIZ)
        own = Path(load_config()["key_file"])
        own.write_bytes(b"biz")
        srv.purge_all_backup_keys(output_dir=load_config()["output_dir"], key_file=str(own))
        self.assertFalse(own.exists())
        self.assertTrue((self.tmp / "encrypted_backup.key").exists())

    def test_an_account_library_is_bound_from_the_start(self):
        libraries.ensure_library({"path": BIZ, "app_type": "whatsapp_business"})
        set_active_profile(BIZ)
        self.assertEqual(srv.library_bound_account(self.tmp / "x"), BIZ)
        self.assertEqual(srv._account_choice_refusal(self.tmp / "x", ACC)["status"], "own_library")


class EachLibraryHasItsOwnServer(InTempApp):
    """A real library server, started like Accounts › Open in a new tab starts it."""

    def get(self, port, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
            return json.loads(r.read().decode())

    def post(self, port, path, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body or {}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def stop_quietly(self, port):
        try:
            self.post(port, "/api/shutdown")
        except OSError:
            pass  # stopped already

    def test_open_starts_a_server_for_the_account_on_its_own_port(self):
        result = libraries.open_library({"path": BIZ, "app_type": "whatsapp_business", "phone_number": "+15550001", "phone_verified": True},
                                        idle_timeout=0, preferred_port=8731)
        port = result["port"]
        self.addCleanup(self.stop_quietly, port)
        self.assertTrue(result["started"])
        self.assertTrue(result["url"].endswith("/gallery.html"))
        health = self.get(port, "/api/health")
        self.assertEqual(health["library"], "account")
        info = self.get(port, "/api/libraries")
        self.assertEqual(info["this"]["account"], BIZ)
        self.assertTrue(info["this"]["bound"])
        self.assertFalse(info["this"]["primary"])
        current = [lib for lib in info["libraries"] if lib["current"]]
        self.assertEqual([lib["account"] for lib in current], [BIZ])
        # The app folder is updated from the first window only
        status, body = self.post(port, "/api/update/download")
        self.assertEqual((status, body["code"]), (409, "library_server"))
        # Opening it again finds the running server
        again = libraries.open_library({"path": BIZ}, idle_timeout=0, preferred_port=8731)
        self.assertEqual((again["port"], again["started"]), (port, False))
        # Quitting the app from the first window stops it
        self.assertEqual(libraries.stop_other_libraries(), 1)
        deadline = time.time() + 10
        while time.time() < deadline and libraries._running(result["output_dir"]):
            time.sleep(0.2)
        self.assertIsNone(libraries._running(result["output_dir"]))


if __name__ == "__main__":
    unittest.main()
