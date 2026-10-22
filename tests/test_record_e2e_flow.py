"""The WhatsApp setup recording script (scripts/record_e2e_flow.py) keeps nothing personal."""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import record_e2e_flow as rec  # noqa: E402

KEY_BLOCKS = ["a1b2", "c3d4", "e5f6", "0718", "293a", "4b5c", "6d7e", "8f90",
              "1a2b", "3c4d", "5e6f", "7081", "92a3", "b4c5", "d6e7", "f809"]


def layout(*nodes):
    body = "".join(
        f'<node index="0" text="{t}" resource-id="{rid}" class="android.widget.TextView" '
        f'package="com.whatsapp" content-desc="{d}" clickable="{str(c).lower()}" bounds="[0,0][10,10]" />'
        for t, rid, d, c in nodes)
    return f'<?xml version="1.0"?><hierarchy rotation="0">{body}</hierarchy>'


class PureTests(unittest.TestCase):
    def test_01_foreground_from_both_dumpsys_formats(self):
        self.assertEqual(rec.parse_foreground(
            "  topResumedActivity=ActivityRecord{8c1 u0 com.whatsapp/.settings.SettingsChat t42}"),
            "com.whatsapp/.settings.SettingsChat")
        self.assertEqual(rec.parse_foreground(
            "  mResumedActivity: ActivityRecord{1 u0 com.whatsapp/com.whatsapp.HomeActivity t3}"),
            "com.whatsapp/com.whatsapp.HomeActivity")
        self.assertEqual(rec.parse_foreground(
            "  mCurrentFocus=Window{4 u0 com.whatsapp/com.whatsapp.backup.encryptedbackup.EncBackupMainActivity}"),
            "com.whatsapp/com.whatsapp.backup.encryptedbackup.EncBackupMainActivity")
        self.assertEqual(rec.parse_foreground("nothing here"), "")

    def test_02_private_screens_are_never_treated_as_settings(self):
        self.assertTrue(rec.is_settings_screen("com.whatsapp/.settings.SettingsChat"))
        self.assertTrue(rec.is_settings_screen("com.whatsapp/com.whatsapp.backup.encryptedbackup.EncBackupMainActivity"))
        for private in ("com.whatsapp/com.whatsapp.HomeActivity", "com.whatsapp/.Main",
                        "com.whatsapp/.Conversation", "com.whatsapp/.profile.ProfileInfoActivity",
                        "com.whatsapp/.contact.ContactPicker"):
            self.assertFalse(rec.is_settings_screen(private), private)

    def test_03_only_known_setup_labels_survive(self):
        self.assertEqual(rec.mask_label("Chat backup"), "Chat backup")
        self.assertEqual(rec.mask_label("Use 64-digit encryption key"), "Use #-digit encryption key")
        self.assertEqual(rec.mask_label("More options"), "More options")
        self.assertEqual(rec.mask_label("Yash Gawande"), "<text>")            # profile name
        self.assertEqual(rec.mask_label("Hey there! I am using WhatsApp."), "<text>")
        self.assertEqual(rec.mask_label("someone@gmail.com"), "<email>")
        self.assertEqual(rec.mask_label("+91 98765 43210"), "<text>")
        self.assertNotIn("4.2", rec.mask_label("Backup size: 4.2 GB"))
        self.assertEqual(rec.mask_label("a1b2"), "<text>")
        self.assertEqual(rec.mask_label("".join(KEY_BLOCKS)), "<key>")
        self.assertEqual(rec.mask_label(" ".join(KEY_BLOCKS)), "<key>")

    def test_03b_home_pages_keep_only_exact_button_words(self):
        self.assertEqual(rec.mask_strict("Settings"), "Settings")
        self.assertEqual(rec.mask_strict("Settings, tab 5 of 5"), "Settings, tab 5 of 5")
        self.assertEqual(rec.mask_strict("You"), "You")
        self.assertEqual(rec.mask_strict("Settings \u2022"), "Settings \u2022")
        for private in ("Mom", "Chat with John", "Settings for John's party", "+91 98765 43210", "a@b.c", "Hey!"):
            self.assertEqual(rec.mask_strict(private), "<text>", private)

    def test_04_key_visibility_without_storing_it(self):
        self.assertEqual(rec.key_visibility(KEY_BLOCKS), (16, True))
        self.assertEqual(rec.key_visibility([" ".join(KEY_BLOCKS)]), (0, True))
        self.assertEqual(rec.key_visibility(["Chats", "beef"]), (1, False))

    def test_05_layout_summary_keeps_no_key_or_name(self):
        nodes = [("Yash Gawande", "com.whatsapp:id/profile_info_name", "", True),
                 ("Chat backup", "com.whatsapp:id/title", "", True)]
        nodes += [(b, "com.whatsapp:id/code", "", False) for b in KEY_BLOCKS]
        summary = rec.summarize_layout(layout(*nodes), keep_text=True)
        dumped = json.dumps(summary)
        for block in KEY_BLOCKS:
            self.assertNotIn(block, dumped)
        self.assertNotIn("Yash", dumped)
        self.assertIn("Chat backup", dumped)
        self.assertTrue(summary["key_readable_from_screen"])
        self.assertIn("com.whatsapp:id/code", summary["ids"])

        bare = rec.summarize_layout(layout(*nodes), keep_text=False)
        self.assertNotIn("Chat backup", json.dumps(bare))
        self.assertTrue(bare["nodes"][0]["has_text"])
        self.assertIsNone(rec.summarize_layout("not xml", keep_text=True))

    def test_06_openable_activities_only_from_the_activity_table(self):
        dump = """Activity Resolver Table:
  Non-Data Actions:
      android.intent.action.MAIN:
        5c1b2f3 com.whatsapp/.Main filter 1a2b3c
          Action: "android.intent.action.MAIN"
          Category: "android.intent.category.LAUNCHER"
      com.whatsapp.intent.action.BACKUP_SETTINGS:
        77aa com.whatsapp/.backup.google.SettingsGoogleDrive filter 99
          Action: "com.whatsapp.intent.action.BACKUP_SETTINGS"
        88bb com.other/.Thing filter 11
          Action: "x.y"

Receiver Resolver Table:
  Non-Data Actions:
      android.intent.action.BOOT_COMPLETED:
        11 com.whatsapp/.BackupReceiver filter 22
          Action: "android.intent.action.BOOT_COMPLETED"

Packages:
  Package [com.whatsapp] (abc):
"""
        found = rec.resolver_candidates(dump, "com.whatsapp")
        self.assertEqual(set(found), {"com.whatsapp/.Main", "com.whatsapp/.backup.google.SettingsGoogleDrive"})
        self.assertEqual(found["com.whatsapp/.backup.google.SettingsGoogleDrive"], ["com.whatsapp.intent.action.BACKUP_SETTINGS"])


FAKE_ADB = r'''#!/usr/bin/env python3
import sys, os, json
state_file = os.environ["FAKE_ADB_STATE"]
state = json.load(open(state_file)) if os.path.exists(state_file) else {"polls": 0}
args = sys.argv[1:]
if args[:2] == ["-s", "SER1"]:
    args = args[2:]
cmd = " ".join(args)
screens = ["com.whatsapp/com.whatsapp.HomeActivity", "com.whatsapp/.settings.SettingsChat",
           "com.whatsapp/com.whatsapp.backup.encryptedbackup.EncBackupMainActivity"]
if args == ["devices"]:
    print("List of devices attached\nSER1\tdevice\n")
elif "getprop" in cmd:
    print({"ro.product.manufacturer": "Xiaomi", "ro.product.model": "Redmi Note 12", "ro.build.version.release": "14"}.get(args[-1].split()[-1], ""))
elif "dumpsys package" in cmd:
    print("Activity Resolver Table:\n  Non-Data Actions:\n      a:\n        1 com.whatsapp/.Main filter 2\n          Action: \"android.intent.action.MAIN\"\nPackages:\n    versionName=2.24.20.76")
elif "dumpsys activity" in cmd:
    i = min(state["polls"] // 2, len(screens) - 1)
    state["polls"] += 1
    print("  topResumedActivity=ActivityRecord{1 u0 %s t1}" % screens[i])
elif args[:2] == ["exec-out", "uiautomator"]:
    i = min(max(state["polls"] - 1, 0) // 2, len(screens) - 1)
    blocks = ''.join('<node text="%s" resource-id="com.whatsapp:id/code" class="x" clickable="false" bounds="" />' % b
                     for b in ["a1b2","c3d4","e5f6","0718","293a","4b5c","6d7e","8f90","1a2b","3c4d","5e6f","7081","92a3","b4c5","d6e7","f809"])
    name = '<node text="Yash Gawande" resource-id="com.whatsapp:id/name" class="x" clickable="true" bounds="" />'
    print('<?xml version="1.0"?><hierarchy rotation="0">%s</hierarchy>UI hierchary dumped to: /dev/tty' % (blocks + name if i == 2 else name))
json.dump(state, open(state_file, "w"))
'''


@unittest.skipIf(sys.platform == "win32", "the fake adb is a POSIX script")
class EndToEndWithFakePhone(unittest.TestCase):
    def test_10_records_screens_and_saves_a_clean_report(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            adb = tmp / "adb"
            adb.write_text(FAKE_ADB)
            adb.chmod(adb.stat().st_mode | stat.S_IEXEC)
            out = tmp / "report.json"
            env = dict(os.environ, FAKE_ADB_STATE=str(tmp / "state.json"))
            # "n": skip the open test; then let it poll a few times; then quit
            proc = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "record_e2e_flow.py"),
                                     "--adb", str(adb), "--out", str(out)],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, env=env)
            proc.stdin.write("n\n")
            proc.stdin.flush()
            import time
            time.sleep(6)
            proc.stdin.write("q\n")
            proc.stdin.flush()
            output = proc.communicate(timeout=30)[0]
            self.assertEqual(proc.returncode, 0, output)
            report = json.loads(out.read_text(encoding="utf-8"))
            text = out.read_text(encoding="utf-8")
            self.assertEqual(report["device"]["model"], "Redmi Note 12")
            self.assertEqual(report["device"]["whatsapp_version"], "2.24.20.76")
            activities = [s["activity"] for s in report["screens"]]
            self.assertIn("com.whatsapp/com.whatsapp.HomeActivity", activities)
            self.assertIn("com.whatsapp/com.whatsapp.backup.encryptedbackup.EncBackupMainActivity", activities)
            home = next(s for s in report["screens"] if s["activity"].endswith("HomeActivity"))
            self.assertNotIn("layout", home)  # private screen: name only
            self.assertTrue(report["key_readable_on_any_screen"])
            for secret in ("a1b2", "f809", "Yash"):
                self.assertNotIn(secret, text)
            self.assertIn("KEY READABLE", output)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
