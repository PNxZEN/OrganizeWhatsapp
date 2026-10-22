"""
Guided WhatsApp backup setup (core/wa_guide.py), checked against a real recorded setup
(tests/fixtures/wa_e2e_setup_android16_wa2.26.40.json: Nothing phone, Android 16, WhatsApp 2.26.40).
"""

import copy
import json
import sys
import threading
import time
import unittest
from pathlib import Path
from xml.sax.saxutils import quoteattr

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import wa_guide  # noqa: E402
from core.wa_guide import WaGuide, classify, extract_key, nodes_from_fixture, parse_layout  # noqa: E402

FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "wa_e2e_setup_android16_wa2.26.40.json").read_text(encoding="utf-8"))
KEY = "0123456789abcdef" * 4  # made up; the fixture never contained the real one


def with_key(items, key=KEY):
    """Fills the recorded key positions with a made-up key, block by block in reading order."""
    items = copy.deepcopy(items)
    blocks = [i for i in items if i.get("key_block")]
    blocks.sort(key=lambda i: (wa_guide._bounds(i["bounds"])[1], wa_guide._bounds(i["bounds"])[0]))
    for n, item in enumerate(blocks):
        item["text"] = key[n * 4:(n + 1) * 4]
    return items


def screen(step):
    s = next(s for s in FIXTURE["screens"] if s["step"] == step)
    return with_key(s["nodes"]) if any(i.get("key_block") for i in s["nodes"]) else copy.deepcopy(s["nodes"])


def to_xml(items):
    def node(i):
        attrs = {"text": i.get("text", ""), "resource-id": i.get("id", ""), "class": "android.widget." + i.get("class", "View"),
                 "package": i.get("package", ""), "content-desc": i.get("desc", ""),
                 "clickable": "true" if i.get("clickable") else "false", "bounds": i.get("bounds", "[0,0][0,0]")}
        return "<node " + " ".join(f"{k}={quoteattr(v)}" for k, v in attrs.items()) + " />"
    return '<?xml version="1.0" encoding="UTF-8"?><hierarchy rotation="0">' + "".join(map(node, items)) + "</hierarchy>"


HOME = [
    {"id": "com.whatsapp:id/toolbar", "class": "ViewGroup", "bounds": "[0,126][1080,273]", "package": "com.whatsapp"},
    {"id": "com.whatsapp:id/menuitem_overflow", "class": "ImageView", "clickable": True, "bounds": "[980,140][1070,260]",
     "package": "com.whatsapp", "desc": "More options"},
    {"id": "com.whatsapp:id/conversations_row", "class": "View", "clickable": True, "bounds": "[0,400][1080,600]",
     "package": "com.whatsapp", "text": "Mom"},
]
MENU = [
    {"class": "FrameLayout", "bounds": "[560,140][1070,700]", "package": "com.whatsapp"},
    {"class": "LinearLayout", "clickable": True, "bounds": "[560,560][1070,690]", "package": "com.whatsapp"},
    {"id": "android:id/title", "class": "TextView", "bounds": "[600,590][1000,660]", "package": "com.whatsapp", "text": "Settings"},
]


class ClassifyRecordedScreens(unittest.TestCase):
    def test_01_every_recorded_screen_is_recognised(self):
        for s in FIXTURE["screens"]:
            nodes = nodes_from_fixture(screen(s["step"]))
            with self.subTest(step=s["step"], expected=s["expected"]):
                self.assertEqual(classify(nodes, s["recorded_activity"]).name, s["expected"])

    def test_02_screen_names_alone_are_not_trusted(self):
        # Step 5 was reported as SettingsChat while the Chat backup screen was already showing
        s = next(s for s in FIXTURE["screens"] if s["step"] == 5)
        self.assertTrue(s["recorded_activity"].endswith("SettingsChat"))
        self.assertEqual(classify(nodes_from_fixture(s["nodes"]), s["recorded_activity"]).name, "backup_settings")

    def test_03_key_is_read_in_reading_order(self):
        self.assertEqual(extract_key(nodes_from_fixture(screen(16))), KEY)
        shuffled = list(reversed(screen(16)))
        self.assertEqual(extract_key(nodes_from_fixture(shuffled)), KEY)
        self.assertIsNone(extract_key(nodes_from_fixture(screen(15))))
        one_line = [{"id": "x", "class": "TextView", "bounds": "[0,0][9,9]", "package": "com.whatsapp", "text": " ".join(KEY[i:i + 4] for i in range(0, 64, 4))}]
        self.assertEqual(extract_key(nodes_from_fixture(one_line)), KEY)

    def test_04_targets_are_the_right_buttons(self):
        expect = {2: "settings_chat", 4: "chat_backup_preference", 6: "settings_gdrive_e2e_encryption",
                  13: "enable_info_more_options_button", 14: "enc_backup_more_options_encryption_key",
                  15: "encryption_key_info_bottom_button", 16: "encryption_key_info_bottom_button",
                  19: "encryption_key_confirm_button_confirm", 20: "enable_done_create_button",
                  8: "enc_backup_encryption_key_input_forgot", 10: "confirm_disable_disable_button"}
        for step, rid in expect.items():
            with self.subTest(step=step):
                self.assertEqual(classify(nodes_from_fixture(screen(step))).target.rid, rid)

    def test_05_passkey_is_never_the_target(self):
        off = classify(nodes_from_fixture(screen(13)))
        self.assertEqual(off.target.rid, "enable_info_more_options_button")
        self.assertEqual(off.info["passkey_button"].rid, "enable_info_turn_on_button")

    def test_06_home_menu_and_other_apps(self):
        home = classify(parse_layout(to_xml(HOME)), "com.whatsapp/.home.ui.HomeActivity")
        self.assertEqual((home.name, home.target.rid), ("home", "menuitem_overflow"))
        menu = classify(parse_layout(to_xml(MENU)), "com.whatsapp/.home.ui.HomeActivity")
        self.assertEqual(menu.name, "menu")
        self.assertEqual(menu.target.cls, "LinearLayout")  # the row, not the text inside it
        launcher = [{"id": "com.android.launcher:id/x", "class": "View", "bounds": "[0,0][9,9]", "package": "com.android.launcher"}]
        self.assertEqual(classify(nodes_from_fixture(launcher), "com.android.launcher/.Home").name, "other_app")
        self.assertEqual(classify([], "").name, "unreadable")
        self.assertEqual(parse_layout("garbage"), [])

    def test_07_business_app_ids(self):
        items = screen(2)
        for i in items:
            i["id"] = i.get("id", "").replace("com.whatsapp:", "com.whatsapp.w4b:")
            i["package"] = "com.whatsapp.w4b" if i.get("package") == "com.whatsapp" else i.get("package", "")
        self.assertEqual(classify(nodes_from_fixture(items)).name, "settings")


class FakePhone:
    """Plays the recorded setup: each tap on a recognised button shows the next recorded screen."""

    def __init__(self, e2e_on=True, taps_allowed=True, free_gb=20.0, fail_backup=False):
        self.current = "launcher"
        self.e2e_on = e2e_on
        self.taps_allowed = taps_allowed
        self.free = int(free_gb * 1024 ** 3)
        self.fail_backup = fail_backup
        self.taps, self.swipes, self.backs = [], 0, 0
        self.lock_reads = 0
        self.shown = []
        self.scrolled_chats = False
        self.lock = threading.Lock()

    def layout(self):
        c = self.current
        if c == "launcher":
            return [{"id": "com.android.launcher:id/workspace", "class": "View", "bounds": "[0,0][1080,2412]", "package": "com.android.launcher"}]
        if c == "home":
            return HOME
        if c == "menu":
            return MENU
        if c == "chats":
            items = screen(4)
            if self.scrolled_chats:
                for i in items:
                    if i.get("id", "").endswith("chat_backup_preference"):
                        i["bounds"] = "[0,1900][1080,2100]"
            return items
        if c == "backup":
            return screen(6 if self.e2e_on else 12)
        return screen(c)

    def foreground(self):
        return {"launcher": "com.android.launcher/.Home", "home": "com.whatsapp/.home.ui.HomeActivity",
                "menu": "com.whatsapp/.home.ui.HomeActivity"}.get(self.current, "com.whatsapp/.Whatever")

    def dump(self):
        with self.lock:
            if not self.shown or self.shown[-1] != self.current:
                self.shown.append(self.current)
            if self.current == 9:  # the user confirms the screen lock after a moment
                self.lock_reads += 1
                if self.lock_reads >= 2:
                    self.current = 10
            return to_xml(self.layout())

    def launch(self, package):
        with self.lock:
            if self.current == "launcher":
                self.current = "home"
        return True

    def free_bytes(self):
        return self.free

    def back(self):
        self.backs += 1
        if self.current == 17:
            self.current = 18
        return True, ""

    def swipe(self, *a):
        self.swipes += 1
        if self.current == "chats":
            self.scrolled_chats = True
        return True, ""

    def tap(self, x, y):
        if not self.taps_allowed:
            return False, "java.lang.SecurityException: Injecting to another application requires INJECT_EVENTS permission"
        items = self.layout()
        hit = [i for i in items if i.get("clickable") and self._inside(i, x, y)]
        hit.sort(key=lambda i: self._area(i))
        rid = hit[0].get("id", "").split("/")[-1] if hit else ""
        self.taps.append((self.current, rid))
        nxt = {
            ("home", "menuitem_overflow"): "menu", ("menu", ""): 2,
            (2, "settings_chat"): "chats", ("chats", "chat_backup_preference"): "backup",
            ("backup", "settings_gdrive_e2e_encryption"): 7 if self.e2e_on else 13,
            (7, "enc_backup_enabled_landing_disable_button"): 8,
            (8, "enc_backup_encryption_key_input_forgot"): 9,
            (10, "confirm_disable_disable_button"): 11,
            (13, "enable_info_more_options_button"): 14,
            (14, "enc_backup_more_options_encryption_key"): 15,
            (15, "encryption_key_info_bottom_button"): 16,
            (16, "encryption_key_info_bottom_button"): 19,
            (19, "encryption_key_confirm_button_confirm"): 20,
            (20, "enable_done_create_button"): 22 if self.fail_backup else "backup_on",
            (22, "button1"): "backup_on",
        }
        if self.current == 11 and rid == "disable_done_done_button":
            self.e2e_on = False
            self.current = "backup"
            return True, ""
        key = (self.current, rid)
        if key in nxt:
            self.current = nxt[key]
            if self.current == "backup_on":
                self.e2e_on = True
                self.current = "backup"
        return True, ""

    @staticmethod
    def _xywh(i):
        return wa_guide._bounds(i["bounds"])

    def _inside(self, i, x, y):
        l, t, r, b = self._xywh(i)
        return l <= x <= r and t <= y <= b

    def _area(self, i):
        l, t, r, b = self._xywh(i)
        return (r - l) * (b - t)


def run_guide(phone, mode="auto", choice=None, until=("done",), timeout=10, allow_low_storage=False):
    saved = []
    guide = WaGuide(lambda: phone, lambda k: saved.append(k) or True, sleep=lambda s: time.sleep(0.002))
    guide.start(mode)
    deadline = time.time() + timeout
    seen = []
    while time.time() < deadline:
        st = guide.status()
        if st["screen"] and (not seen or seen[-1] != st["screen"]):
            seen.append(st["screen"])
        if st["phase"] == "needs_choice" and choice:
            guide.choose(choice)
        if st["phase"] == "low_storage" and allow_low_storage:
            guide.allow_low_storage()
        if st["phase"] in until and st["screen"]:
            break
        time.sleep(0.005)
    final = guide.status()
    guide.stop()
    return final, saved, seen


class AutoSessionTests(unittest.TestCase):
    def test_10_new_key_all_the_way_without_touching_the_phone(self):
        phone = FakePhone(e2e_on=False)
        st, saved, seen = run_guide(phone)
        self.assertEqual(st["phase"], "done", st)
        self.assertEqual(saved, [KEY])
        self.assertTrue(st["key_captured"] and st["created"])
        self.assertIn("making the encrypted backup", st["message"])
        self.assertEqual(st["masked_key"], KEY[:4] + "…" + KEY[-4:])
        self.assertNotIn(KEY, json.dumps(st))  # the full key never reaches the browser
        self.assertTrue(phone.swipes >= 1, "Chat backup was half off-screen and had to be scrolled into view")
        tapped = [rid for _, rid in phone.taps]
        self.assertNotIn("enable_info_turn_on_button", tapped, "never Use passkey")
        self.assertLess(tapped.index("encryption_key_info_bottom_button", tapped.index("enc_backup_more_options_encryption_key") + 2),
                        tapped.index("encryption_key_confirm_button_confirm"))
        self.assertTrue(all(s["state"] == "done" for s in st["steps"]))
        self.assertNotIn("turn_off", [s["key"] for s in st["steps"]])

    def test_11_existing_backup_waits_for_the_users_choice(self):
        phone = FakePhone(e2e_on=True)
        st, saved, _ = run_guide(phone, until=("needs_choice",))
        self.assertEqual((st["phase"], st["screen"]), ("needs_choice", "e2e_on"))
        self.assertNotIn("enc_backup_enabled_landing_disable_button", [rid for _, rid in phone.taps])
        self.assertIn("turn_off", [s["key"] for s in st["steps"]])

    def test_12_reset_turns_the_old_backup_off_and_waits_for_the_screen_lock(self):
        phone = FakePhone(e2e_on=True)
        st, saved, seen = run_guide(phone, choice="reset")
        self.assertEqual(st["phase"], "done", st)
        self.assertEqual(saved, [KEY])
        self.assertIn(9, phone.shown, "went through the screen lock")
        self.assertIn("screen_lock", [classify(nodes_from_fixture(screen(9))).name])
        tapped = [rid for _, rid in phone.taps]
        for rid in ("enc_backup_enabled_landing_disable_button", "enc_backup_encryption_key_input_forgot",
                    "confirm_disable_disable_button", "disable_done_done_button"):
            self.assertIn(rid, tapped)
        self.assertNotIn(9, [screen for screen, _ in phone.taps], "the screen lock is never tapped by the app")

    def test_13_have_key_leaves_the_phone_alone(self):
        phone = FakePhone(e2e_on=True)
        st, saved, _ = run_guide(phone, choice="have_key", until=("have_key",))
        self.assertEqual(st["phase"], "have_key")
        self.assertNotIn("enc_backup_enabled_landing_disable_button", [rid for _, rid in phone.taps])
        self.assertEqual(saved, [])

    def test_14_guide_mode_never_taps(self):
        phone = FakePhone(e2e_on=False)
        st, _, _ = run_guide(phone, mode="guide", until=("running",), timeout=1)
        self.assertEqual(phone.taps, [])
        self.assertEqual(st["mode"], "guide")
        self.assertTrue(st["instruction"])

    def test_15_phone_that_blocks_taps_switches_to_guide_mode(self):
        phone = FakePhone(e2e_on=False, taps_allowed=False)
        saved = []
        guide = WaGuide(lambda: phone, lambda k: saved.append(k) or True, sleep=lambda s: time.sleep(0.002))
        guide.start("auto")
        for _ in range(400):
            st = guide.status()
            if not st["input_allowed"]:
                break
            time.sleep(0.005)
        guide.stop()
        self.assertFalse(st["input_allowed"])
        self.assertEqual(st["mode"], "guide")
        self.assertIn("Security settings", st["notice"])

    def test_16_low_storage_asks_before_create(self):
        phone = FakePhone(e2e_on=False, free_gb=0.3)
        st, _, _ = run_guide(phone, until=("low_storage",))
        self.assertEqual((st["phase"], st["screen"]), ("low_storage", "create"))
        self.assertIn("0.3 GB", st["warning"])
        self.assertNotIn("enable_done_create_button", [rid for _, rid in phone.taps])
        phone2 = FakePhone(e2e_on=False, free_gb=0.3)
        st2, _, _ = run_guide(phone2, allow_low_storage=True)
        self.assertEqual(st2["phase"], "done")

    def test_17_failed_backup_is_reported_honestly(self):
        phone = FakePhone(e2e_on=False, fail_backup=True)
        guide = WaGuide(lambda: phone, lambda k: True, sleep=lambda s: time.sleep(0.002))
        guide.start("auto")
        # The dialog's text is WhatsApp's; the fixture keeps none, so give it one
        for _ in range(2000):
            if phone.current == 22:
                break
            time.sleep(0.002)
        self.assertEqual(phone.current, 22)
        msg = {"id": "android:id/message", "class": "TextView", "bounds": "[91,1067][989,1255]", "package": "com.whatsapp",
               "text": "Not enough storage to back up."}
        original = phone.layout
        phone.layout = lambda: (original() + [msg]) if phone.current == 22 else original()
        for _ in range(400):
            st = guide.status()
            if st["screen"] == "dialog":
                break
            time.sleep(0.005)
        self.assertIn("Not enough storage", st["instruction"])
        # The user taps OK on the phone
        phone.current = "backup"
        phone.e2e_on = True
        for _ in range(400):
            st = guide.status()
            if st["phase"] == "done":
                break
            time.sleep(0.005)
        guide.stop()
        self.assertIn("could not make the backup", st["message"])

    def test_18_unknown_screens_fall_back_to_the_manual_steps(self):
        clock = {"t": 1000.0}
        phone = FakePhone(e2e_on=False)
        phone.current = 17  # a lone popup is fine, but make it something the guide does not know:
        phone.layout = lambda: [{"id": "com.whatsapp:id/mystery", "class": "View", "bounds": "[0,0][1080,2412]", "package": "com.whatsapp"}]

        def sleep(s):
            clock["t"] += 5
            time.sleep(0.002)
        guide = WaGuide(lambda: phone, lambda k: True, clock=lambda: clock["t"], sleep=sleep)
        guide.start("auto")
        for _ in range(400):
            st = guide.status()
            if st["fallback"]:
                break
            time.sleep(0.005)
        guide.stop()
        self.assertTrue(st["fallback"])
        self.assertTrue(st["fallback_reason"])

    def test_19_repeated_taps_without_effect_stop_auto_mode(self):
        phone = FakePhone(e2e_on=False)
        phone.current = 13
        original_tap = phone.tap
        phone.tap = lambda x, y: (phone.taps.append((13, "nothing happens")) or (True, ""))
        st, _, _ = run_guide(phone, until=("never",), timeout=1.5)
        self.assertEqual(st["mode"], "guide")
        self.assertIn("could not move forward", st["notice"])
        self.assertLessEqual(len(phone.taps), wa_guide.SAME_ACTION_LIMIT + 1)


if __name__ == "__main__":
    unittest.main()


class ApiTests(unittest.TestCase):
    """The /api/wa-guide endpoints, with the recorded phone behind them."""

    @classmethod
    def setUpClass(cls):
        import os
        import shutil
        import tempfile
        import urllib.request
        from http.server import ThreadingHTTPServer
        from unittest import mock
        import core.server as srv
        cls.srv, cls.shutil, cls.os, cls.urllib = srv, shutil, os, urllib.request
        cls.tmp = Path(tempfile.mkdtemp(prefix="wa_guide_api_"))
        cls.cwd = os.getcwd()
        os.chdir(cls.tmp)  # config.json lives in the working directory
        cls.output = cls.tmp / "output"
        cls.output.mkdir()
        cls.phone = FakePhone(e2e_on=True)
        guide = WaGuide(lambda: cls.phone, srv._wa_guide_save_key, sleep=lambda s: time.sleep(0.002))
        cls.patch = mock.patch.object(srv, "_wa_guide", guide)
        cls.patch.start()

        class Handler(srv.GalleryHTTPRequestHandler):
            def __init__(self, *a, **kw):
                super().__init__(*a, directory=str(cls.output), **kw)

        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv._wa_guide.stop()
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.patch.stop()
        cls.os.chdir(cls.cwd)
        cls.shutil.rmtree(cls.tmp, ignore_errors=True)

    def call(self, method, path, body=None):
        import urllib.error
        data = json.dumps(body).encode() if body is not None else None
        req = self.urllib.Request(self.base + path, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with self.urllib.urlopen(req, timeout=15) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def wait_for(self, phase, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, st = self.call("GET", "/api/wa-guide/status")
            if st["phase"] == phase and st["screen"]:
                return st
            time.sleep(0.02)
        self.fail(f"never reached {phase}: {st}")

    def test_30_reset_flow_over_http_saves_the_key(self):
        from core.config import load_config
        code, st = self.call("POST", "/api/wa-guide/start", {"mode": "auto"})
        self.assertEqual(code, 200)
        self.wait_for("needs_choice")
        self.assertEqual(self.call("POST", "/api/wa-guide/choose", {"choice": "nonsense"})[0], 400)
        self.call("POST", "/api/wa-guide/choose", {"choice": "reset"})
        st = self.wait_for("done")
        self.assertTrue(st["key_captured"])
        self.assertEqual(load_config().get("hex_key"), KEY)
        self.assertTrue((self.output / "encrypted_backup.key").is_file())
        _, key_status = self.call("GET", "/api/key-status")
        self.assertTrue(key_status["hex_key_set"])
        self.assertIsNone(key_status["received_key"], "the screen-read key is not handed to the browser")

    def test_31_have_key_then_key_provided(self):
        from core.config import save_config
        self.phone.current, self.phone.e2e_on = "launcher", True
        self.call("POST", "/api/wa-guide/start", {"mode": "auto"})
        self.wait_for("needs_choice")
        self.call("POST", "/api/wa-guide/choose", {"choice": "have_key"})
        self.wait_for("have_key")
        save_config({"hex_key": KEY})
        code, st = self.call("POST", "/api/wa-guide/key-provided")
        self.assertEqual((code, st["phase"]), (200, "done"))
        self.assertNotIn(KEY, json.dumps(st))
        self.assertEqual(self.call("POST", "/api/wa-guide/nope")[0], 404)


class AdbPhoneCommandTests(unittest.TestCase):
    """The exact adb calls (no phone needed): the layout stays off the phone's storage."""

    def test_40_commands(self):
        from unittest import mock
        calls = []

        def fake_run(cmd, capture_output, timeout):
            calls.append(cmd)
            out = b""
            if cmd[-1] == "/dev/tty":
                out = b"ERROR: could not get idle state."  # phones that cannot stream the layout
            elif "uiautomator dump /data/local/tmp" in cmd[-1]:
                out = b'<?xml version="1.0"?><hierarchy><node resource-id="com.whatsapp:id/settings_chat" bounds="[0,0][9,9]" package="com.whatsapp" /></hierarchy>'
            elif cmd[3:5] == ["input", "tap"]:
                out = b""
            return mock.Mock(returncode=0, stdout=out, stderr=b"")

        phone = wa_guide.AdbPhone("adb", "SER")
        with mock.patch.object(wa_guide.subprocess, "run", side_effect=fake_run):
            xml = phone.dump()
            ok, _ = phone.tap(10, 20)
        self.assertIn("settings_chat", xml)
        self.assertEqual(calls[0], ["adb", "-s", "SER", "exec-out", "uiautomator", "dump", "/dev/tty"])
        fallback = calls[1]
        self.assertEqual(fallback[:4], ["adb", "-s", "SER", "exec-out"])
        self.assertEqual(len(fallback), 5, "one shell command string, since adb joins arguments")
        self.assertIn("rm -f /data/local/tmp/wa_guide_layout.xml", fallback[4])
        self.assertTrue(ok)
        self.assertEqual(calls[2], ["adb", "-s", "SER", "shell", "input", "tap", "10", "20"])
