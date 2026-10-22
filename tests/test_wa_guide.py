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

# The fake phone draws every screen at once: no need to wait between repeated taps (one test checks the gap)
wa_guide.REPEAT_GAP_SECS = 0.01

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
                 "clickable": "true" if i.get("clickable") else "false", "bounds": i.get("bounds", "[0,0][0,0]"),
                 "selected": "true" if i.get("selected") else "false"}
        return "<node " + " ".join(f"{k}={quoteattr(v)}" for k, v in attrs.items()) + " />"
    return '<?xml version="1.0" encoding="UTF-8"?><hierarchy rotation="0">' + "".join(map(node, items)) + "</hierarchy>"


HOME = [
    {"id": "com.whatsapp:id/toolbar", "class": "ViewGroup", "bounds": "[0,126][1080,273]", "package": "com.whatsapp"},
    {"id": "com.whatsapp:id/menuitem_overflow", "class": "ImageView", "clickable": True, "bounds": "[980,140][1070,260]",
     "package": "com.whatsapp", "desc": "More options"},
    {"id": "com.whatsapp:id/conversations_row", "class": "View", "clickable": True, "bounds": "[0,400][1080,600]",
     "package": "com.whatsapp", "text": "Mom"},
]
def overflow_menu(labels=("New group", "New community", "Broadcast lists", "Linked devices", "Starred",
                          "Payments", "Read all", "Settings"), title_id="com.whatsapp:id/title"):
    """WhatsApp's ⋮ menu as uiautomator shows it: a row per item, each holding an android:id/title."""
    items = [{"class": "FrameLayout", "bounds": f"[560,140][1070,{160 + 100 * len(labels)}]", "package": "com.whatsapp"},
             {"class": "ListView", "bounds": f"[560,150][1070,{150 + 100 * len(labels)}]", "package": "com.whatsapp"}]
    for n, label in enumerate(labels):
        top = 150 + 100 * n
        items.append({"class": "LinearLayout", "clickable": True, "bounds": f"[560,{top}][1070,{top + 100}]", "package": "com.whatsapp"})
        items.append({"class": "RelativeLayout", "bounds": f"[600,{top + 20}][1040,{top + 80}]", "package": "com.whatsapp"})
        items.append({"id": title_id, "class": "TextView", "bounds": f"[600,{top + 20}][1000,{top + 80}]",
                      "package": "com.whatsapp", "text": label})
    return items


MENU = overflow_menu()
# The self-chat ("Message yourself") is listed as "You": it must never be taken for a "You" tab
SELF_CHAT = [
    {"id": "com.whatsapp:id/contact_row_container", "class": "LinearLayout", "clickable": True, "bounds": "[0,300][1080,480]", "package": "com.whatsapp"},
    {"id": "com.whatsapp:id/contact_photo", "class": "ImageView", "clickable": True, "bounds": "[30,320][170,460]", "package": "com.whatsapp", "desc": "You"},
    {"id": "com.whatsapp:id/conversations_row_contact_name", "class": "TextView", "bounds": "[200,330][700,390]", "package": "com.whatsapp", "text": "You"},
]


def you_page(scrolled=False, chats_label="Chats", chats_id=""):
    """Newer WhatsApp's "You" tab: the Settings page itself (Lists, Chats, Broadcasts...), Chats below the fold."""
    items = [i for i in tabs_home(labels=("Chats", "Updates", "Communities", "Calls", "You"))
             if "conversations" not in i.get("id", "") and "search" not in i.get("id", "")]  # no chat list here
    rows = ["Lists", chats_label, "Broadcasts", "Notifications"] if scrolled else ["Avatar", "Lists"]
    top = 300
    for label in rows:
        rid = chats_id if label == chats_label else ""
        items.append({"id": rid, "class": "LinearLayout", "clickable": True, "bounds": f"[0,{top}][1080,{top + 160}]", "package": "com.whatsapp"})
        items.append({"id": "com.whatsapp:id/row_text", "class": "TextView", "bounds": f"[150,{top + 30}][700,{top + 90}]", "package": "com.whatsapp", "text": label})
        top += 170
    return items


def account_page(label="Settings", row_id=""):
    """Newer WhatsApp's last tab: an account page with a Settings row on it."""
    return tabs_home(labels=("", "", "", "", "")) + [
        {"id": row_id, "class": "LinearLayout", "clickable": True, "bounds": "[0,900][1080,1050]", "package": "com.whatsapp"},
        {"id": "com.whatsapp:id/row_text", "class": "TextView", "bounds": "[200,940][700,1000]", "package": "com.whatsapp", "text": label},
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
        home = classify(parse_layout(to_xml(HOME + SELF_CHAT)), "com.whatsapp/.home.ui.HomeActivity")
        self.assertEqual((home.name, home.info["overflow"].rid), ("home", "menuitem_overflow"))
        self.assertIsNone(home.info["you_tab"], "the self-chat called You is not the You tab")
        menu = classify(parse_layout(to_xml(MENU)), "com.whatsapp/.home.ui.HomeActivity")
        self.assertEqual(menu.name, "menu")
        self.assertEqual((menu.target.cls, menu.target.bounds[1]), ("LinearLayout", 850))  # the Settings row
        spanish = classify(parse_layout(to_xml(overflow_menu(("Nuevo grupo", "Ajustes", "Destacados", "Leer todo")))))
        self.assertEqual((spanish.name, spanish.target.bounds[1]), ("menu", 250), "Settings found by name, wherever it is")
        no_settings = classify(parse_layout(to_xml(overflow_menu(("New group", "New community", "Starred", "Read all")))))
        self.assertEqual(no_settings.name, "menu")
        self.assertIsNone(no_settings.target, "never guess: the last item could be Read all")
        unknown_language = classify(parse_layout(to_xml(overflow_menu(("Grupo novo", "Comunidade nova", "Xyzzy")))))
        self.assertIsNone(unknown_language.target)
        copy_bubble = [{"class": "LinearLayout", "clickable": True, "bounds": "[565,951][1080,1077]", "package": "com.whatsapp"},
                       {"id": "android:id/title", "class": "TextView", "bounds": "[607,983][1038,1044]", "package": "com.whatsapp", "text": "Copy"}]
        self.assertEqual(classify(nodes_from_fixture(copy_bubble)).name, "popup")
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


def tabs_home(labels=("", "", "", "", ""), overflow=False):
    """Newer WhatsApp: a bottom tab bar (labels may be in any language, or missing)."""
    items = [{"id": "com.whatsapp:id/toolbar", "class": "ViewGroup", "bounds": "[0,126][1080,273]", "package": "com.whatsapp"},
             {"id": "com.whatsapp:id/search", "class": "EditText", "bounds": "[30,290][1050,380]", "package": "com.whatsapp"},
             {"id": "com.whatsapp:id/conversations_row", "class": "View", "clickable": True, "bounds": "[0,400][1080,600]",
              "package": "com.whatsapp", "text": "Mom"}]
    if overflow:
        items.append({"id": "com.whatsapp:id/menuitem_overflow", "class": "ImageView", "clickable": True,
                      "bounds": "[980,140][1070,260]", "package": "com.whatsapp", "desc": "More options"})
    width = 1080 // len(labels)
    for n, label in enumerate(labels):
        left = n * width
        items.append({"id": "com.whatsapp:id/navigation_bar_item", "class": "FrameLayout", "clickable": True,
                      "bounds": f"[{left},2200][{left + width},2349]", "package": "com.whatsapp", "desc": label})
        items.append({"id": "com.whatsapp:id/navigation_bar_item_icon", "class": "ImageView",
                      "bounds": f"[{left + 40},2220][{left + 100},2280]", "package": "com.whatsapp"})
    return items


CHAT = [
    {"id": "com.whatsapp:id/conversation_contact_name", "class": "TextView", "bounds": "[150,150][700,220]", "package": "com.whatsapp", "text": "Mom"},
    {"id": "com.whatsapp:id/emoji_picker_btn", "class": "ImageButton", "clickable": True, "bounds": "[20,2240][120,2340]", "package": "com.whatsapp", "desc": "Emoji"},
    {"id": "com.whatsapp:id/entry", "class": "EditText", "clickable": True, "bounds": "[120,2240][700,2340]", "package": "com.whatsapp"},
    {"id": "com.whatsapp:id/input_attach_button", "class": "ImageButton", "clickable": True, "bounds": "[700,2240][800,2340]", "package": "com.whatsapp", "desc": "Attach"},
    {"id": "com.whatsapp:id/camera_btn", "class": "ImageButton", "clickable": True, "bounds": "[800,2240][900,2340]", "package": "com.whatsapp", "desc": "Camera"},
    {"id": "com.whatsapp:id/voice_note_btn", "class": "ImageButton", "clickable": True, "bounds": "[930,2240][1060,2340]", "package": "com.whatsapp", "desc": "Voice message"},
]
DIALOG_TEXT = ("Can't back up your chat history because there isn't enough space left on your internal storage. "
               "Remove files from your internal storage and try again.")


class FakePhone:
    """
    Plays the recorded setup: each tap on a recognised button shows the next recorded screen.
    Also: a lock screen, WhatsApp left on a chat, old (⋮ menu) or new (bottom tab) home screens,
    the phone's clock, and WhatsApp's backup file appearing (or a "not enough space" message).
    """

    def __init__(self, e2e_on=True, taps_allowed=True, free_gb=20.0, fail_backup=False,
                 locked=False, unlock_after=3, start="launcher", home="menu", previous_backup_mb=None):
        self.current = start
        self.e2e_on = e2e_on
        self.taps_allowed = taps_allowed
        self.free = int(free_gb * 1024 ** 3)
        self.fail_backup = fail_backup
        self.locked = locked
        self.unlock_after = unlock_after
        self.home_style = home
        self.taps, self.swipes, self.backs = [], 0, 0
        self.events = []
        self.lock_reads = 0
        self.lock_checks = 0
        self.shown = []
        self.scrolled_chats = False
        self.you_scrolled = False
        self.clock = 1_700_000_000
        self.backup = (self.clock - 86400, previous_backup_mb * 1024 ** 2) if previous_backup_mb else None
        self.after_backup = None  # ("ok" | "fail", dumps left)
        self.lock_at = None       # the phone locks itself when this screen is reached
        self.lock = threading.Lock()

    # ----- what is on screen

    def layout(self):
        c = self.current
        if c == "launcher":
            return [{"id": "com.android.launcher:id/workspace", "class": "View", "bounds": "[0,0][1080,2412]", "package": "com.android.launcher"}]
        if c == "keyguard":
            return [{"id": "com.android.systemui:id/keyguard_pin_view", "class": "View", "bounds": "[0,0][1080,2412]", "package": "com.android.systemui"},
                    {"id": "com.android.systemui:id/pinEntry", "class": "EditText", "bounds": "[100,900][980,1000]", "package": "com.android.systemui"}]
        if c == "chat":
            return CHAT
        if c == "home":
            if self.home_style == "menu":
                return HOME + SELF_CHAT
            if self.home_style in ("account", "account_ids"):
                return tabs_home()
            if self.home_style.startswith("you"):
                return tabs_home(labels=("Chats", "Updates", "Communities", "Calls", "You"))
            if self.home_style == "tabs":
                return tabs_home()
            return tabs_home(labels=("", "", "", ""), overflow=True)  # last tab is Calls, Settings in ⋮
        if c == "calls":
            return tabs_home(labels=("", "", "", ""), overflow=True)
        if c == "you":
            if self.home_style == "you_ids":
                return you_page(scrolled=self.you_scrolled, chats_id="com.whatsapp:id/settings_chat")
            if self.home_style == "you_other_language":
                return you_page(scrolled=self.you_scrolled, chats_label="Conversas")
            return you_page(scrolled=self.you_scrolled)
        if c == "account":
            return account_page(*(("Ajustes", "com.whatsapp:id/you_settings_row") if self.home_style == "account_ids" else ()))
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
        if c == 22:
            return screen(22) + [{"id": "android:id/message", "class": "TextView", "bounds": "[91,1067][989,1255]",
                                  "package": "com.whatsapp", "text": DIALOG_TEXT}]
        return screen(c)

    def foreground(self):
        if self.locked:
            return "com.android.systemui/.keyguard"
        return {"launcher": "com.android.launcher/.Home", "home": "com.whatsapp/.home.ui.HomeActivity",
                "calls": "com.whatsapp/.home.ui.HomeActivity", "menu": "com.whatsapp/.home.ui.HomeActivity",
                "account": "com.whatsapp/.home.ui.HomeActivity", "you": "com.whatsapp/.home.ui.HomeActivity",
                "chat": "com.whatsapp/.Conversation"}.get(self.current, "com.whatsapp/.Whatever")

    def dump(self):
        with self.lock:
            if self.locked:
                return to_xml(self.layout_locked())
            if self.lock_at is not None and self.current == self.lock_at:
                self.lock_at = None
                self.locked, self.lock_checks = True, 0
                return to_xml(self.layout_locked())
            if not self.shown or self.shown[-1] != self.current:
                self.shown.append(self.current)
            if self.current == 9:  # the user confirms the screen lock after a moment
                self.lock_reads += 1
                if self.lock_reads >= 2:
                    self.current = 10
            if self.after_backup and self.current == "backup":
                outcome, left = self.after_backup
                if left <= 0:
                    self.after_backup = None
                    if outcome == "fail":
                        self.current = 22
                    else:
                        self.backup = (self.clock, 48 * 1024 ** 2)
                else:
                    self.after_backup = (outcome, left - 1)
            return to_xml(self.layout())

    def layout_locked(self):
        saved, self.current = self.current, "keyguard"
        try:
            return self.layout()
        finally:
            self.current = saved

    # ----- phone calls

    def lock_state(self):
        self.lock_checks += 1
        if self.locked and self.lock_checks > self.unlock_after:
            self.locked = False  # the user unlocked it
            self.events.append("unlocked")
        return "locked" if self.locked else "unlocked"

    def wake(self):
        self.events.append("wake")

    def go_home(self):
        self.events.append("home")
        self.current = "launcher"

    def open_fresh(self, package):
        self.events.append("open")
        self.current = "home"
        return True

    def launch(self, package):
        return self.open_fresh(package)

    def now(self):
        self.clock += 1
        return self.clock

    def latest_backup(self, package):
        return self.backup

    def free_bytes(self):
        return self.free

    def back(self):
        self.backs += 1
        if self.current == 17:
            self.current = 18
        elif self.current == "menu":
            self.current = "home"  # Back closes the ⋮ menu
        return True, ""

    def swipe(self, *a):
        self.swipes += 1
        if self.current == "chats":
            self.scrolled_chats = True
        if self.current == "you":
            self.you_scrolled = True
        return True, ""

    def tap(self, x, y):
        if not self.taps_allowed:
            return False, "java.lang.SecurityException: Injecting to another application requires INJECT_EVENTS permission"
        items = self.layout()
        hit = [i for i in items if i.get("clickable") and self._inside(i, x, y)]
        hit.sort(key=lambda i: self._area(i))
        rid = hit[0].get("id", "").split("/")[-1] if hit else ""
        self.taps.append((self.current, rid))
        if self.current == "menu":
            row = hit[0] if hit else None
            title = next((i for i in items if i.get("text") and row and self._contains(row, i)
                          and i.get("class") == "TextView"), None)
            self.current = 2 if title and title["text"] in ("Settings", "Ajustes") else "home"
            return True, ""
        if self.current == "you":
            label = next((i["text"] for i in items if i.get("id") == "com.whatsapp:id/row_text" and hit
                          and self._contains(hit[0], i)), "")
            if label in ("Chats", "Conversas"):
                self.current = "chats"
            return True, ""
        if self.current == "account":
            self.current = 2 if hit and wa_guide._bounds(hit[0]["bounds"])[1] == 900 else "account"
            return True, ""
        if self.current in ("home", "calls") and rid == "navigation_bar_item":
            last = x > 1080 * 0.75
            if self.home_style in ("account", "account_ids") and last:
                self.current = "account"  # an account page holding Settings
            elif self.home_style.startswith("you") and last:
                self.current = "you"      # the You tab is the Settings page itself
            elif self.home_style.startswith("you") and x < 216:
                self.current = "home"     # the Chats tab: back to the chat list
            elif self.home_style == "tabs" and last:
                self.current = 2       # newer WhatsApp: the last tab is Settings
            elif last:
                self.current = "calls"  # an older tab bar: the last tab is Calls
            return True, ""
        nxt = {
            ("home", "menuitem_overflow"): "menu", ("calls", "menuitem_overflow"): "menu",
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
            (22, "button1"): "backup",
        }
        if self.current == 11 and rid == "disable_done_done_button":
            self.e2e_on = False
            self.current = "backup"
            return True, ""
        if (self.current == 20 and rid == "enable_done_create_button") or (self.current == "backup" and rid == "google_drive_backup_now_btn"):
            self.e2e_on = True
            self.current = "backup"
            self.after_backup = ("fail" if self.fail_backup else "ok", 2)  # WhatsApp answers a moment later
            return True, ""
        key = (self.current, rid)
        if key in nxt:
            self.current = nxt[key]
        return True, ""

    @staticmethod
    def _xywh(i):
        return wa_guide._bounds(i["bounds"])

    def _inside(self, i, x, y):
        l, t, r, b = self._xywh(i)
        return l <= x <= r and t <= y <= b

    def _contains(self, outer, inner):
        l, t, r, b = self._xywh(outer)
        il, it, ir, ib = self._xywh(inner)
        return l <= il and t <= it and r >= ir and b >= ib

    def _area(self, i):
        l, t, r, b = self._xywh(i)
        return (r - l) * (b - t)


def make_guide(phone, saved=None, **kw):
    saved = [] if saved is None else saved
    return WaGuide(lambda: phone, lambda k: saved.append(k) or True, sleep=lambda s: time.sleep(0.002), **kw)


def run_guide(phone, mode="auto", choice=None, until=("done",), timeout=10, allow_low_storage=False, guide=None):
    saved = []
    guide = guide or make_guide(phone, saved)
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


def wait(guide, predicate, timeout=10):
    deadline = time.time() + timeout
    st = guide.status()
    while time.time() < deadline:
        st = guide.status()
        if predicate(st):
            return st
        time.sleep(0.005)
    raise AssertionError(f"condition not reached: {st}")


class AutoSessionTests(unittest.TestCase):
    def test_10_new_key_all_the_way_without_touching_the_phone(self):
        phone = FakePhone(e2e_on=False)
        st, saved, seen = run_guide(phone)
        self.assertEqual(st["phase"], "done", st)
        self.assertEqual(saved, [KEY])
        self.assertTrue(st["key_captured"] and st["created"])
        self.assertIn("made the encrypted backup (48 MB)", st["message"])
        self.assertEqual(st["masked_key"], KEY[:4] + "…" + KEY[-4:])
        self.assertNotIn(KEY, json.dumps(st))  # the full key never reaches the browser
        self.assertTrue(phone.swipes >= 1, "Chat backup was half off-screen and had to be scrolled into view")
        tapped = [rid for _, rid in phone.taps]
        self.assertNotIn("enable_info_turn_on_button", tapped, "never Use passkey")
        self.assertLess(tapped.index("encryption_key_info_bottom_button", tapped.index("enc_backup_more_options_encryption_key") + 2),
                        tapped.index("encryption_key_confirm_button_confirm"))
        self.assertTrue(all(s["state"] == "done" for s in st["steps"]))
        self.assertNotIn("turn_off", [s["key"] for s in st["steps"]])
        self.assertEqual(phone.events[:2], ["home", "open"], "home screen first, then WhatsApp opened fresh")

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
        tapped = [rid for _, rid in phone.taps]
        for rid in ("enc_backup_enabled_landing_disable_button", "enc_backup_encryption_key_input_forgot",
                    "confirm_disable_disable_button", "disable_done_done_button"):
            self.assertIn(rid, tapped)
        self.assertNotIn(9, [s for s, _ in phone.taps], "the screen lock is never tapped by the app")

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
        guide = make_guide(phone)
        guide.start("auto")
        st = wait(guide, lambda s: not s["input_allowed"])
        guide.stop()
        self.assertEqual(st["mode"], "guide")
        self.assertIn("Security settings", st["notice"])

    def test_16_low_storage_asks_before_create(self):
        phone = FakePhone(e2e_on=False, free_gb=0.3)
        st, _, _ = run_guide(phone, until=("low_storage",))
        self.assertEqual((st["phase"], st["screen"]), ("low_storage", "create"))
        self.assertEqual(st["slide"], 10, "the tutorial screenshot of the Create screen")
        self.assertIn("0.3 GB free", st["warning"])
        self.assertIn("0.3 GB free", st["storage_warning"], "also shown from the start")
        self.assertNotIn("enable_done_create_button", [rid for _, rid in phone.taps])
        phone2 = FakePhone(e2e_on=False, free_gb=0.3)
        st2, _, _ = run_guide(phone2, allow_low_storage=True)
        self.assertEqual(st2["phase"], "done")

    def test_17_not_enough_space_after_create_is_shown_and_can_be_retried(self):
        # Your test phone: WhatsApp returns to Chat backup, then a moment later says there is no space
        phone = FakePhone(e2e_on=False, fail_backup=True)
        guide = make_guide(phone)
        guide.start("auto")
        st = wait(guide, lambda s: s["phase"] == "backup_failed")
        self.assertIn("isn't enough space", st["backup_error"])
        self.assertIn("isn't enough space", st["instruction"])
        self.assertTrue(st["key_captured"], "the key is saved even though the backup failed")
        self.assertNotIn("making the encrypted backup", st["message"])
        self.assertEqual([s["state"] for s in st["steps"] if s["key"] == "making"], ["active"])
        # The user frees space and presses Try again: the app closes the message and taps Back up
        phone.fail_backup = False
        guide.retry_backup()
        st = wait(guide, lambda s: s["phase"] == "done")
        guide.stop()
        self.assertIn("made the encrypted backup", st["message"])
        tapped = [rid for _, rid in phone.taps]
        self.assertIn("button1", tapped)
        self.assertIn("google_drive_backup_now_btn", tapped)

    def test_18_unknown_screens_fall_back_to_the_manual_steps(self):
        clock = {"t": 1000.0}
        phone = FakePhone(e2e_on=False)
        phone.open_fresh = lambda package: phone.events.append("open") or True  # reopening does not help here
        phone.layout = lambda: [{"id": "com.whatsapp:id/mystery", "class": "View", "bounds": "[0,0][1080,2412]", "package": "com.whatsapp"}]

        def sleep(s):
            clock["t"] += 5
            time.sleep(0.002)
        guide = WaGuide(lambda: phone, lambda k: True, clock=lambda: clock["t"], sleep=sleep)
        guide.start("auto")
        st = wait(guide, lambda s: s["fallback"])
        guide.stop()
        self.assertTrue(st["fallback_reason"])
        self.assertGreaterEqual(phone.events.count("open"), 2, "tried reopening WhatsApp first")

    def test_19_repeated_taps_without_effect_stop_auto_mode(self):
        phone = FakePhone(e2e_on=False, start=13)
        phone.go_home = phone.open_fresh = lambda *a: True  # stays on screen 13
        phone.tap = lambda x, y: (phone.taps.append((13, "nothing happens")) or (True, ""))
        st, _, _ = run_guide(phone, until=("never",), timeout=1.5)
        self.assertEqual(st["mode"], "guide")
        self.assertIn("could not move forward", st["notice"])
        self.assertLessEqual(len(phone.taps), wa_guide.SAME_ACTION_LIMIT + 1)

    def test_20_locked_phone_is_woken_and_unlocked_first(self):
        phone = FakePhone(e2e_on=False, locked=True, unlock_after=4)
        guide = make_guide(phone)
        guide.start("auto")
        st = wait(guide, lambda s: s["phase"] == "locked")
        self.assertIn("Unlock your phone", st["instruction"])
        self.assertIn("never enters", st["instruction"])
        st = wait(guide, lambda s: s["phase"] == "done")
        guide.stop()
        e = phone.events
        self.assertLess(e.index("wake"), e.index("unlocked"))
        self.assertLess(e.index("unlocked"), e.index("home"))
        self.assertLess(e.index("home"), e.index("open"))
        self.assertNotIn("keyguard", phone.shown, "nothing is read or tapped on the lock screen")

    def test_21_locked_half_way_waits_and_carries_on(self):
        phone = FakePhone(e2e_on=False, unlock_after=3)
        phone.lock_at = "chats"
        guide = make_guide(phone)
        guide.start("auto")
        wait(guide, lambda s: s["phase"] == "locked")
        st = wait(guide, lambda s: s["phase"] == "done")
        guide.stop()
        self.assertTrue(st["key_captured"])

    def test_22_whatsapp_left_on_a_chat_is_reopened_on_its_main_screen(self):
        phone = FakePhone(e2e_on=False, start="chat")
        phone.open_fresh_count = 0
        original = phone.open_fresh
        first = {"done": False}

        def open_fresh(package):  # the first open still lands on the chat (WhatsApp restored it)
            if not first["done"]:
                first["done"] = True
                phone.events.append("open")
                phone.current = "chat"
                return True
            return original(package)
        phone.open_fresh = open_fresh
        st, _, _ = run_guide(phone)
        self.assertEqual(st["phase"], "done", st)
        self.assertNotIn("chat", [s for s, _ in phone.taps], "never taps inside a chat")
        self.assertGreaterEqual(phone.events.count("open"), 2)

    def test_24_older_tab_bar_without_you_uses_the_menu(self):
        phone = FakePhone(e2e_on=False, home="tabs_calls")
        st, _, _ = run_guide(phone)
        self.assertEqual(st["phase"], "done", st)
        self.assertEqual(phone.taps[0], ("home", "menuitem_overflow"), "no You tab: straight to ⋮")
        self.assertNotIn("navigation_bar_item", [rid for _, rid in phone.taps], "no other tab is tried")

    def test_25_guide_mode_watches_the_backup_after_the_user_taps_create(self):
        phone = FakePhone(e2e_on=False, start=20)
        phone.go_home = phone.open_fresh = lambda *a: True  # keep the phone on the Create screen
        guide = make_guide(phone)
        guide.start("guide")
        wait(guide, lambda s: s["screen"] == "create")
        self.assertEqual(phone.taps, [])
        phone.tap(540, 2100)  # the user taps Create
        st = wait(guide, lambda s: s["phase"] == "done")
        guide.stop()
        self.assertIn("made the encrypted backup", st["message"])

    def test_26_storage_need_comes_from_the_previous_backup(self):
        self.assertEqual(wa_guide.storage_needed(None), wa_guide.LOW_STORAGE_BYTES)
        self.assertEqual(wa_guide.storage_needed(100 * 1024 ** 2), wa_guide.LOW_STORAGE_BYTES)
        self.assertEqual(wa_guide.storage_needed(2 * 1024 ** 3), 3 * 1024 ** 3 + 300 * 1024 ** 2)
        phone = FakePhone(e2e_on=False, free_gb=2.5, previous_backup_mb=2048)
        st, _, _ = run_guide(phone, until=("low_storage",))
        self.assertEqual(st["phase"], "low_storage")
        self.assertIn("about 3.3 GB", st["storage_warning"])


class SettingsRouteTests(unittest.TestCase):
    def test_50_menu_route_never_taps_the_you_chat(self):
        phone = FakePhone(e2e_on=False, home="menu")
        st, _, _ = run_guide(phone)
        self.assertEqual(st["phase"], "done", st)
        self.assertEqual(phone.taps[:2], [("home", "menuitem_overflow"), ("menu", "")])
        self.assertNotIn(("home", "contact_photo"), phone.taps)
        self.assertNotIn(("home", "contact_row_container"), phone.taps)

    def test_53_you_tab_is_the_settings_page_with_chats_below(self):
        phone = FakePhone(e2e_on=False, home="you")
        st, _, _ = run_guide(phone)
        self.assertEqual(st["phase"], "done", st)
        self.assertEqual(phone.taps[0][0], "home")
        self.assertIn(("you", ""), phone.taps, "tapped the Chats row on the You page")
        self.assertGreaterEqual(phone.swipes, 1, "scrolled the You page to find Chats")
        self.assertNotIn(("you", "navigation_bar_item"), phone.taps, "never the Chats tab at the bottom")

    def test_54_you_page_with_whatsapp_settings_ids(self):
        phone = FakePhone(e2e_on=False, home="you_ids")
        st, _, _ = run_guide(phone)
        self.assertEqual(st["phase"], "done", st)

    def test_55_you_page_in_an_unknown_language_hands_over(self):
        phone = FakePhone(e2e_on=False, home="you_other_language")
        st, _, _ = run_guide(phone, until=("never",), timeout=2)
        self.assertEqual(st["mode"], "guide")
        self.assertIn("could not find Chats", st["notice"])
        self.assertLessEqual(phone.swipes, 3)
        self.assertNotIn("menuitem_overflow", [rid for _, rid in phone.taps], "never ⋮ in the You version")
        self.assertEqual(st["slide"], "you_page")

    def test_56_chats_tab_is_not_a_settings_row(self):
        home = classify(parse_layout(to_xml(tabs_home(labels=("Chats", "Updates", "Communities", "Calls", "You")))),
                        "com.whatsapp/.home.ui.HomeActivity")
        self.assertEqual(home.name, "home")
        page = classify(parse_layout(to_xml(you_page(scrolled=True))), "com.whatsapp/.home.ui.HomeActivity")
        self.assertEqual((page.name, page.target.bounds[1]), ("settings", 470))

    def test_52_no_way_to_settings_hands_over_to_the_user(self):
        phone = FakePhone(e2e_on=False, home="menu")
        phone.layout_home = phone.layout
        phone.layout = lambda: [n for n in phone.layout_home() if "overflow" not in n.get("id", "")]
        st, _, _ = run_guide(phone, until=("never",), timeout=1.5)
        self.assertEqual(st["mode"], "guide")
        self.assertIn("open it yourself", st["notice"])
        self.assertEqual(phone.taps, [])


class YouVersionTests(unittest.TestCase):
    def test_60_you_menu_without_settings_closes_and_hands_over(self):
        # A phone whose ⋮ has no Settings and no recognisable You tab (e.g. WhatsApp changed again)
        phone = FakePhone(e2e_on=False, home="menu")
        original = phone.layout
        phone.layout = lambda: (overflow_menu(("New group", "New community", "Starred", "Read all"))
                                if phone.current == "menu" else original())
        st, _, _ = run_guide(phone, until=("never",), timeout=2)
        tapped = phone.taps
        self.assertEqual(tapped, [("home", "menuitem_overflow")], "opened ⋮ once, tapped nothing in it")
        self.assertGreaterEqual(phone.backs, 1, "closed the menu")
        self.assertEqual(st["mode"], "guide")
        self.assertIn("open it yourself", st["notice"])

    def test_61_you_version_slides_and_instructions(self):
        phone = FakePhone(e2e_on=False, home="you")
        guide = make_guide(phone)
        guide.start("guide")  # the user taps: the guide shows where
        st = wait(guide, lambda s: s["screen"] == "home")
        self.assertEqual(st["slide"], "you_home")
        self.assertIn("Tap You (bottom right)", st["instruction"])
        phone.tap(950, 2270)   # the user taps You
        st = wait(guide, lambda s: s["slide"] == "you_page" or s["screen"] == "settings")
        guide.stop()
        self.assertEqual(phone.taps[0], ("home", "navigation_bar_item"))

    def test_62_chat_called_you_is_never_the_you_tab(self):
        phone = FakePhone(e2e_on=False, home="menu")  # HOME + a self-chat "You", older layout
        st, _, _ = run_guide(phone)
        self.assertEqual(st["phase"], "done", st)
        self.assertNotIn("contact_photo", [rid for _, rid in phone.taps])
        self.assertNotIn("contact_row_container", [rid for _, rid in phone.taps])

    def test_63_you_tab_reports_selected_state(self):
        items = you_page(scrolled=False)
        for i in items:
            if i.get("desc") == "You":
                i["selected"] = True
        page = classify(parse_layout(to_xml(items)), "com.whatsapp/.home.ui.HomeActivity")
        self.assertTrue(page.info["on_you_page"])
        home = classify(parse_layout(to_xml(tabs_home(labels=("Chats", "Updates", "Communities", "Calls", "You")))),
                        "com.whatsapp/.home.ui.HomeActivity")
        self.assertIsNone(home.info["on_you_page"], "no selected state reported: unknown")


class MenuIdTests(unittest.TestCase):
    """Your phone: WhatsApp's ⋮ menu labels its items com.whatsapp:id/title (not android:id/title)."""

    def test_70_whatsapp_and_system_menu_ids(self):
        for title_id in ("com.whatsapp:id/title", "android:id/title"):
            menu = classify(parse_layout(to_xml(overflow_menu(title_id=title_id))), "com.whatsapp/.home.ui.HomeActivity")
            self.assertEqual((menu.name, menu.target.bounds[1]), ("menu", 850), title_id)

    def test_71_menu_with_unfamiliar_ids_still_reaches_settings(self):
        phone = FakePhone(e2e_on=False, home="menu")
        original = phone.layout
        phone.layout = lambda: (overflow_menu(title_id="com.whatsapp:id/menu_item_label") if phone.current == "menu" else original())
        st, _, _ = run_guide(phone)
        self.assertEqual(st["phase"], "done", st)
        self.assertEqual(phone.taps[:2], [("home", "menuitem_overflow"), ("menu", "")])

    def test_72_a_chat_named_settings_is_never_tapped(self):
        chat = [{"id": "com.whatsapp:id/contact_row_container", "class": "LinearLayout", "clickable": True,
                 "bounds": "[0,300][1080,480]", "package": "com.whatsapp"},
                {"id": "com.whatsapp:id/conversations_row_contact_name", "class": "TextView", "bounds": "[200,330][700,390]",
                 "package": "com.whatsapp", "text": "Settings"}]
        home = classify(parse_layout(to_xml(HOME + chat)), "com.whatsapp/.home.ui.HomeActivity")
        self.assertIsNone(home.info["settings_item"])


class MidwayTests(unittest.TestCase):
    """The user got part-way before starting the guide, or switches to "Do it for me" later."""

    def test_80_starting_on_a_setup_screen_continues_from_it(self):
        phone = FakePhone(e2e_on=False, start="backup")
        st, saved, _ = run_guide(phone)
        self.assertEqual(st["phase"], "done", st)
        self.assertNotIn("home", phone.events, "did not go to the home screen")
        self.assertNotIn("open", phone.events, "did not reopen WhatsApp")
        self.assertEqual(phone.taps[0], ("backup", "settings_gdrive_e2e_encryption"))

    def test_81_starting_while_the_key_is_shown_reads_it_at_once(self):
        phone = FakePhone(e2e_on=False, start=16)
        st, saved, _ = run_guide(phone)
        self.assertEqual(saved, [KEY])
        self.assertEqual(st["phase"], "done", st)
        self.assertNotIn("open", phone.events)

    def test_82_starting_in_a_chat_still_goes_home_first(self):
        phone = FakePhone(e2e_on=False, start="chat")
        st, _, _ = run_guide(phone)
        self.assertEqual(st["phase"], "done", st)
        self.assertEqual(phone.events[:2], ["home", "open"])

    def test_83_guide_mode_then_do_it_for_me_from_the_users_screen(self):
        phone = FakePhone(e2e_on=False)
        guide = make_guide(phone)
        guide.start("guide")
        wait(guide, lambda s: s["screen"] == "home")
        # The user taps through to Chats themselves, then clicks "Do it for me"
        phone.current = "chats"
        wait(guide, lambda s: s["screen"] == "chat_settings")
        self.assertEqual(phone.taps, [])
        guide.set_mode("auto")
        st = wait(guide, lambda s: s["phase"] == "done")
        guide.stop()
        self.assertEqual(phone.taps[0][0], "chats", "carried on from the user's screen")

    def test_84_do_it_for_me_again_after_a_hand_over_tries_again(self):
        phone = FakePhone(e2e_on=False, home="menu")
        full = phone.layout
        hide = {"on": True}
        phone.layout = lambda: [n for n in full() if not (hide["on"] and "overflow" in n.get("id", ""))]
        guide = make_guide(phone)
        guide.start("auto")
        st = wait(guide, lambda s: s["mode"] == "guide" and "open it yourself" in s["notice"])
        hide["on"] = False  # e.g. the user closed a dialog that was hiding ⋮
        guide.set_mode("auto")
        st = wait(guide, lambda s: s["phase"] == "done")
        guide.stop()
        self.assertIn(("home", "menuitem_overflow"), phone.taps)


class MenuVariantTests(unittest.TestCase):
    """Settings in the ⋮ menu however WhatsApp labels it; the menu is only closed when it truly has none."""

    def menu_with(self, mutate):
        items = overflow_menu()
        for i in items:
            if i.get("text") == "Settings":
                mutate(i, items)
        return items

    def test_90_settings_with_a_new_badge_or_in_the_description(self):
        variants = {
            "badge dot": lambda i, items: i.update(text="Settings \u2022"),
            "badge word": lambda i, items: i.update(text="Settings, New"),
            "description only": lambda i, items: i.update(text="", desc="Settings"),
        }
        for name, mutate in variants.items():
            with self.subTest(name):
                menu = classify(parse_layout(to_xml(self.menu_with(mutate))), "com.whatsapp/.home.ui.HomeActivity")
                self.assertEqual((menu.name, menu.target.bounds[1]), ("menu", 850))

    def test_91_label_on_the_row_itself(self):
        items = overflow_menu()
        for i in items:
            if i.get("text") == "Settings":
                i["text"] = "Xyz"
        rows = [i for i in items if i.get("clickable")]
        rows[-1]["desc"] = "Settings"
        menu = classify(parse_layout(to_xml(items)), "com.whatsapp/.home.ui.HomeActivity")
        self.assertEqual((menu.name, menu.target.bounds[1]), ("menu", 850))

    def test_92_menu_still_opening_is_read_again_before_closing(self):
        phone = FakePhone(e2e_on=False, home="menu")
        reads = {"n": 0}
        original = phone.layout

        def layout():
            if phone.current == "menu":
                reads["n"] += 1
                if reads["n"] <= 2:  # half-drawn: Settings not there yet
                    return overflow_menu(labels=("New group", "New community", "Broadcast lists"))
            return original()
        phone.layout = layout
        st, _, _ = run_guide(phone)
        self.assertEqual(st["phase"], "done", st)
        self.assertEqual(phone.backs, 0, "the menu was not closed")

    def test_93_hand_over_says_what_the_menu_showed(self):
        phone = FakePhone(e2e_on=False, home="menu")
        original = phone.layout
        phone.layout = lambda: (overflow_menu(("New group", "Starred", "Read all")) if phone.current == "menu" else original())
        st, _, _ = run_guide(phone, until=("never",), timeout=2)
        self.assertIn("New group, Starred, Read all", st["notice"])
        self.assertEqual(st["mode"], "guide")

    def test_94_label_matching(self):
        yes = ["Settings", "settings", "Settings \u2022", "Settings 1", "Settings, tab 5 of 5", "Ajustes", "Einstellungen",
               "\u8bbe\u7f6e", "Settings new"]
        no = ["Read all", "New group", "Starred", "", "Setting up", "Chat settings help"]
        for v in yes:
            self.assertTrue(wa_guide.is_settings_label(v), v)
        for v in no:
            self.assertFalse(wa_guide.is_settings_label(v), v)


class ParsingTests(unittest.TestCase):
    def test_27_lock_state(self):
        p = wa_guide.parse_lock_state
        self.assertEqual(p("", "  mWakefulness=Asleep"), "asleep")
        self.assertEqual(p("  mDreamingLockscreen=true mDreamingSleepToken=null", "mWakefulness=Awake"), "locked")
        self.assertEqual(p("KeyguardController:\n  mKeyguardShowing=true", "mWakefulness=Awake"), "locked")
        self.assertEqual(p("    isKeyguardShowing=false\n  mDreamingLockscreen=false", "mWakefulness=Awake"), "unlocked")
        self.assertEqual(p("", "mWakefulness=Awake"), "unknown")

    def test_28_backup_stats(self):
        self.assertEqual(wa_guide.parse_backup_stats("1700000000 1000\n1700000500 2000\njunk\n"), (1700000500, 2000))
        self.assertIsNone(wa_guide.parse_backup_stats(""))

    def test_29_a_chat_is_never_the_home_screen(self):
        chat = classify(parse_layout(to_xml(CHAT)), "com.whatsapp/.home.ui.HomeActivity")  # even with a lagging name
        self.assertEqual(chat.name, "unknown")
        self.assertEqual(wa_guide.bottom_tabs(parse_layout(to_xml(tabs_home())))[-1].bounds[0], 864)
        home = classify(parse_layout(to_xml(tabs_home())), "com.whatsapp/.home.ui.HomeActivity")
        self.assertEqual(home.name, "home")
        self.assertIsNone(home.info["you_tab"], "unlabelled tabs: not taken for the You tab")
        you = classify(parse_layout(to_xml(tabs_home(labels=("Chats", "Updates", "Communities", "Calls", "You")))),
                       "com.whatsapp/.home.ui.HomeActivity")
        self.assertEqual(you.info["you_tab"].bounds[0], 864, "the bottom-right tab")
        calls_last = classify(parse_layout(to_xml(tabs_home(labels=("Chats", "Updates", "Communities", "Calls")))),
                              "com.whatsapp/.home.ui.HomeActivity")
        self.assertIsNone(calls_last.info["you_tab"])
        you_middle = classify(parse_layout(to_xml(tabs_home(labels=("Chats", "You", "Communities", "Calls")))),
                              "com.whatsapp/.home.ui.HomeActivity")
        self.assertIsNone(you_middle.info["you_tab"], "only the bottom-right tab counts")
        hindi = classify(parse_layout(to_xml(tabs_home(labels=("चैट", "अपडेट", "कम्युनिटी", "कॉल", "आप")))),
                         "com.whatsapp/.home.ui.HomeActivity")
        self.assertIsNotNone(hindi.info["you_tab"])


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
        self.assertEqual(self.call("POST", "/api/wa-guide/continue")[0], 400, "Continue needs a running guide")


class BusyPhone(FakePhone):
    """
    A phone that gets interrupted while the guide taps: notification banners, the notification
    shade, the user's own touches, another app, phone calls. `when[screen]` runs once, the first
    time that screen is shown. Records any tap or swipe that landed where it should not.
    """

    OTHER = [{"id": "com.google.android.youtube:id/player", "class": "View", "bounds": "[0,0][1080,2412]",
              "package": "com.google.android.youtube"}]
    SHADE = [{"id": "com.android.systemui:id/notification_panel", "class": "View", "bounds": "[0,0][1080,2412]",
              "package": "com.android.systemui"},
             {"id": "com.android.systemui:id/quick_settings_panel", "class": "View", "bounds": "[0,0][1080,800]",
              "package": "com.android.systemui"}]

    def __init__(self, when=None, **kw):
        super().__init__(**kw)
        self.when = dict(when or {})
        self.activity = 5000
        self.touching = 0            # the user's finger is on the phone for this many more reads
        self.banner = 0              # a notification banner over the top of the screen for this many checks
        self.calling = False
        self.left_on = None          # the WhatsApp screen behind another app / the shade
        self.wa_call = False
        self.menu_moves = 0          # the ⋮ menu is still sliding in for this many reads
        self.menu_shift = 0
        self.bad = []                # inputs under a banner / during a call / while touched / at stale places
        self.collapsed = 0
        self.launches = 0
        self.lost = False            # the USB cable is out
        self.hidden_shade = False    # the shade is open, but the layout read still shows WhatsApp

    def connection_lost(self):
        return self.lost

    def focus(self):
        return "NotificationShade" if self.hidden_shade else "com.whatsapp/com.whatsapp.Whatever"

    def snapshot(self):
        """Like AdbPhone.snapshot: everything the guide checks each round, in one call."""
        if self.lost:
            return None
        return {"lock": self.lock_state(), "activity": self.user_activity(), "in_call": self.calling,
                "foreground": self.foreground(), "focus": self.focus()}

    def _fire(self):
        hook = self.when.pop(self.current, None)
        if hook:
            hook(self)

    def leave_for(self, where):
        self.left_on, self.current = self.current, where

    def layout(self):
        if self.current == "other":
            return self.OTHER
        if self.current == "shade":
            return self.SHADE
        items = super().layout()
        if self.current == "menu" and self.menu_shift:
            items = copy.deepcopy(items)
            for i in items:
                l, t, r, b = wa_guide._bounds(i["bounds"])
                i["bounds"] = f"[{l},{t + self.menu_shift}][{r},{b + self.menu_shift}]"
        return items

    def foreground(self):
        if self.wa_call:
            return "com.whatsapp/com.whatsapp.calling.callscreen.VoipActivityV2"
        if self.current == "other":
            return "com.google.android.youtube/.HomeActivity"
        if self.current == "shade":
            saved, self.current = self.current, self.left_on
            try:
                return super().foreground()  # the shade does not change the app underneath
            finally:
                self.current = saved
        return super().foreground()

    def dump(self):
        self._fire()
        if self.current == "menu" and self.menu_moves > 0:
            self.menu_moves -= 1
            self.menu_shift += 40
        return super().dump()

    # what the guide checks before touching
    def user_activity(self):
        if self.touching > 0:
            self.touching -= 1
            self.activity += 1
        return self.activity

    def in_call(self):
        return self.calling

    def covered_at(self, x, y):
        if self.banner > 0 and y < 400:
            self.banner -= 1
            return "NotificationShade"
        return ""

    def collapse_panels(self):
        self.collapsed += 1
        self.hidden_shade = False
        if self.current == "shade":
            self.current = self.left_on

    def launch(self, package):
        self.launches += 1
        self.activity += 1
        if self.left_on is not None and self.current in ("other", "shade"):
            self.current, self.left_on = self.left_on, None
            return True
        return self.open_fresh(package)

    def _check(self, kind, y):
        if self.lost:
            self.bad.append((kind, "while disconnected", self.current))
        if self.hidden_shade:
            self.bad.append((kind, "into the shade", self.current))
        if self.calling or self.wa_call or self.current in ("other", "shade"):
            self.bad.append((kind, "not in WhatsApp", self.current))
        if self.banner > 0 and y < 400:
            self.bad.append((kind, "under the banner", self.current))
        if self.touching > 0:
            self.bad.append((kind, "while the user touches", self.current))

    def tap(self, x, y):
        self._check("tap", y)
        self.activity += 1
        if self.current == "menu":
            items = self.layout()
            title = next((i for i in items if i.get("text") and self._inside(i, x, y)
                          or (i.get("clickable") and self._inside(i, x, y) and any(
                              t.get("text") == "Settings" and self._contains(i, t) for t in items))), None)
            if not title:
                self.bad.append(("tap", "stale place in the menu", (x, y)))
        return super().tap(x, y)

    def swipe(self, *a):
        self._check("swipe", a[1])
        self.activity += 1
        return super().swipe(*a)

    def back(self):
        self.activity += 1
        return super().back()

    def open_fresh(self, package):
        self.activity += 1
        return super().open_fresh(package)


class InterruptionTests(unittest.TestCase):
    """Notifications, the user's own hands, calls and other apps never make the guide tap the wrong thing."""

    def setUp(self):
        from unittest import mock
        patches = [mock.patch.object(wa_guide, "COVER_WAIT_SECS", 0.4), mock.patch.object(wa_guide, "SHADE_WAIT_SECS", 0.05),
                   mock.patch.object(wa_guide, "USER_QUIET_SECS", 0.05), mock.patch.object(wa_guide, "USER_QUIET_RELAUNCH_SECS", 0.1)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def finish(self, phone, **kw):
        st, saved, seen = run_guide(phone, **kw)
        self.assertEqual(st["phase"], "done", st)
        self.assertEqual(saved, [KEY])
        self.assertEqual(phone.bad, [])
        return st, seen

    def test_50_waits_for_a_notification_banner_over_settings(self):
        # ⋮ sits at the top, right where a banner drops in
        phone = BusyPhone(e2e_on=False, when={"home": lambda p: setattr(p, "banner", 4)})
        self.finish(phone)
        self.assertEqual(phone.banner, 0, "the guide checked the spot until the banner went")

    def test_51_a_banner_that_stays_hands_over_instead_of_tapping_it(self):
        phone = BusyPhone(e2e_on=False, when={"home": lambda p: setattr(p, "banner", 10 ** 6)})
        st, _, _ = run_guide(phone, until=("never",), timeout=1.5)
        self.assertEqual(phone.bad, [])
        self.assertEqual(st["mode"], "guide")
        self.assertIn("covers WhatsApp", st["notice"])
        self.assertNotIn("menu", phone.shown, "⋮ was not tapped through the banner")

    def test_52_closes_the_notification_shade_and_carries_on(self):
        phone = BusyPhone(e2e_on=False, when={"chats": lambda p: p.leave_for("shade")})
        self.finish(phone)
        self.assertEqual(phone.collapsed, 1)
        self.assertEqual(phone.events.count("open"), 1, "WhatsApp was not reopened from the start")

    def test_53_waits_while_the_user_touches_the_phone(self):
        phone = BusyPhone(e2e_on=False, when={2: lambda p: setattr(p, "touching", 25),
                                             "backup": lambda p: setattr(p, "touching", 25)})
        self.finish(phone)
        self.assertEqual(phone.touching, 0)

    def test_54_another_app_pauses_until_whatsapp_is_back(self):
        phone = BusyPhone(e2e_on=False, when={"chats": lambda p: p.leave_for("other")})
        guide = make_guide(phone)
        guide.start("auto")
        st = wait(guide, lambda s: s["phase"] == "paused")
        self.assertEqual(st["pause_reason"], "away")
        self.assertIn("another app", st["instruction"])
        self.assertEqual(st["screen"], "settings", "progress kept: still at the Chats step")
        time.sleep(0.3)
        self.assertEqual(phone.current, "other", "the user is never pulled out of the other app")
        self.assertEqual(phone.events.count("open"), 1)
        phone.current, phone.left_on = phone.left_on, None  # the user goes back to WhatsApp
        st = wait(guide, lambda s: s["phase"] == "done")
        guide.stop()
        self.assertEqual(phone.bad, [])
        self.assertEqual(phone.launches, 0)

    def test_55_continue_brings_whatsapp_back_where_it_was(self):
        phone = BusyPhone(e2e_on=False, when={"backup": lambda p: p.leave_for("other")})
        guide = make_guide(phone)
        guide.start("auto")
        wait(guide, lambda s: s["phase"] == "paused")
        guide.resume()
        st = wait(guide, lambda s: s["phase"] == "done")
        guide.stop()
        self.assertEqual((phone.launches, phone.events.count("open")), (1, 1), "resumed in place, not reopened")
        self.assertEqual(phone.bad, [])
        self.assertEqual(st["masked_key"], KEY[:4] + "…" + KEY[-4:])

    def test_56_phone_call_pauses_and_the_guide_returns_after_it(self):
        def ring(p):
            p.calling = True
            p.leave_for("other")  # the call screen

        phone = BusyPhone(e2e_on=False, when={"chats": ring})
        guide = make_guide(phone)
        guide.start("auto")
        st = wait(guide, lambda s: s["phase"] == "paused")
        self.assertEqual(st["pause_reason"], "call")
        self.assertIn("phone call", st["instruction"])
        time.sleep(0.2)
        phone.calling = False  # hung up: the phone stays on the call app
        st = wait(guide, lambda s: s["phase"] == "done")
        guide.stop()
        self.assertEqual(phone.bad, [])
        self.assertEqual(phone.launches, 1)

    def test_57_whatsapp_call_is_never_touched(self):
        phone = BusyPhone(e2e_on=False, when={"chats": lambda p: setattr(p, "wa_call", True)})
        guide = make_guide(phone)
        guide.start("auto")
        st = wait(guide, lambda s: s["phase"] == "paused")
        self.assertIn("WhatsApp call", st["instruction"])
        taps = len(phone.taps)
        time.sleep(0.3)
        self.assertEqual(len(phone.taps), taps)
        phone.wa_call = False
        wait(guide, lambda s: s["phase"] == "done")
        guide.stop()
        self.assertEqual(phone.bad, [])

    def test_58_a_menu_still_sliding_in_is_tapped_where_it_ends_up(self):
        phone = BusyPhone(e2e_on=False, when={"menu": lambda p: setattr(p, "menu_moves", 2)})
        self.finish(phone)  # finish() fails on any tap at a place the menu has left

    def test_58b_a_screen_that_changed_by_itself_is_read_once_more_before_tapping(self):
        guide = make_guide(BusyPhone())
        node = parse_layout(to_xml(MENU))[-1]
        guide._prev_round = ("home", False)  # the menu opened, but not by the guide (the user did)
        self.assertIn("again", guide._before_touch(BusyPhone(), "menu", ("tap", node), node.center, parse_layout(to_xml(MENU))))
        guide._prev_round = ("menu", False)  # the second look shows the same menu: go ahead
        self.assertEqual(guide._before_touch(BusyPhone(), "menu", ("tap", node), node.center, parse_layout(to_xml(MENU))), "")
        guide._prev_round = ("home", True)   # the guide's own ⋮ tap opened it
        self.assertEqual(guide._before_touch(BusyPhone(), "menu", ("tap", node), node.center, parse_layout(to_xml(MENU))), "")

    def test_59_guide_mode_never_closes_or_reopens_anything(self):
        # (the shade comes down after the guide has read the Chats screen once)
        phone = BusyPhone(e2e_on=False, start="chats",
                          when={"chats": lambda p: p.when.__setitem__("chats", lambda q: q.leave_for("shade"))})
        guide = make_guide(phone)
        guide.start("guide")
        st = wait(guide, lambda s: "notification panel" in s["instruction"])
        time.sleep(0.2)
        guide.stop()
        self.assertEqual((phone.collapsed, phone.taps), (0, []))

    def test_61_unplugged_cable_pauses_and_carries_on_when_back(self):
        phone = BusyPhone(e2e_on=False, when={"chats": lambda p: setattr(p, "lost", True)})
        guide = make_guide(phone)
        guide.start("auto")
        st = wait(guide, lambda s: s["phase"] == "paused")
        self.assertEqual(st["pause_reason"], "disconnected")
        self.assertIn("USB cable", st["instruction"])
        self.assertEqual(st["screen"], "chat_settings", "progress kept (the Chats screen was read before the cable came out)")
        time.sleep(0.2)
        phone.lost = False
        wait(guide, lambda s: s["phase"] == "done")
        guide.stop()
        self.assertEqual((phone.bad, phone.events.count("open")), ([], 1))

    def test_62_a_lock_while_whatsapp_makes_the_backup_does_not_ask_to_unlock(self):
        class LocksDuringBackup(BusyPhone):
            def dump(self):
                if self.locked and self.after_backup:  # WhatsApp finishes the backup with the screen off
                    self.after_backup, self.backup = None, (self.clock, 48 * 1024 ** 2)
                return super().dump()

        phone = LocksDuringBackup(e2e_on=False, unlock_after=10 ** 6, when={20: lambda p: setattr(p, "lock_at", "backup")})
        guide = make_guide(phone)
        guide.start("auto")
        phases = set()
        deadline = time.time() + 10
        while time.time() < deadline:
            st = guide.status()
            phases.add(st["phase"])
            if st["phase"] == "done":
                break
            time.sleep(0.005)
        guide.stop()
        self.assertEqual(st["phase"], "done", st)
        self.assertTrue(phone.locked, "the phone stayed locked")
        self.assertNotIn("locked", phases)
        self.assertNotIn("wake", phone.events)
        self.assertIn("made the encrypted backup", st["message"])

    def test_63_a_call_state_that_never_clears_can_be_overridden(self):
        phone = BusyPhone(e2e_on=False, when={"chats": lambda p: setattr(p, "calling", True)})
        guide = make_guide(phone)
        guide.start("auto")
        wait(guide, lambda s: s["pause_reason"] == "call")
        guide.resume()  # "Not on a call? Continue anyway"
        st = wait(guide, lambda s: s["phase"] == "done")
        guide.stop()
        self.assertEqual(st["phase"], "done")
        phone.bad = [b for b in phone.bad if b[1] != "not in WhatsApp"]  # the fake still "calls"
        self.assertEqual(phone.bad, [])

    def test_64_a_shade_the_layout_read_misses_is_still_closed_first(self):
        phone = BusyPhone(e2e_on=False, when={"chats": lambda p: setattr(p, "hidden_shade", True)})
        self.finish(phone)
        self.assertEqual(phone.collapsed, 1)

    def test_65_call_history_is_not_a_call(self):
        nodes = parse_layout(to_xml(HOME))
        self.assertEqual(classify(nodes, "com.whatsapp/com.whatsapp.voipcalling.VoipActivityV2").name, "wa_call")
        self.assertEqual(classify(nodes, "com.whatsapp/com.whatsapp.calling.callscreen.CallScreenActivity").name, "wa_call")
        for page in ("com.whatsapp/com.whatsapp.calling.callhistory.CallLogActivity",
                     "com.whatsapp/com.whatsapp.calling.calllink.CallLinkActivity",
                     "com.whatsapp/com.whatsapp.calling.CallInfoActivity"):
            self.assertNotEqual(classify(nodes, page).name, "wa_call", page)
        self.assertTrue(wa_guide.focus_blocks("NotificationShade"))
        self.assertTrue(wa_guide.focus_blocks("com.android.systemui/com.android.systemui.usb.UsbPermissionActivity"))
        self.assertFalse(wa_guide.focus_blocks("com.whatsapp/com.whatsapp.HomeActivity"))
        self.assertFalse(wa_guide.focus_blocks("PopupWindow:9c1f"), "WhatsApp's own ⋮ menu")
        self.assertFalse(wa_guide.focus_blocks(""))
        self.assertEqual(wa_guide.parse_focus("  mCurrentFocus=Window{8a u0 NotificationShade}"), "NotificationShade")
        self.assertEqual(wa_guide.parse_focus("  mCurrentFocus=null"), "")

    def test_60_parsing(self):
        windows = """
  Window #12 Window{a1 u0 NotificationShade}:
    mOwnerUid=10050 showForAllUsers=true package=com.android.systemui appop=NONE
      fl=NOT_FOCUSABLE LAYOUT_IN_SCREEN
    mViewVisibility=0x0 mHaveFrame=true mObscured=false
      Frames: parent=[0,0][1080,2400] display=[0,0][1080,2400] frame=[0,0][1080,2400]
    isOnScreen=true
    isVisible=true
  Window #11 Window{b2 u0 ScreenDecorOverlay}:
    package=com.android.systemui appop=NONE
      fl=NOT_FOCUSABLE NOT_TOUCHABLE
    mViewVisibility=0x0
      Frames: frame=[0,0][1080,2400]
  Window #10 Window{c3 u0 com.whatsapp/com.whatsapp.HomeActivity}:
    package=com.whatsapp appop=NONE
    mViewVisibility=0x0
      Frames: frame=[0,0][1080,2400]
  Window #9 Window{d4 u0 com.facebook.orca}:
    package=com.facebook.orca appop=SYSTEM_ALERT_WINDOW
    mViewVisibility=0x0
    mFrame=[0,0][1080,2400] last=[0,0][1080,2400]
"""
        cw = wa_guide.covering_window
        self.assertEqual(cw(windows, 500, 300), "NotificationShade")
        hidden = windows.replace("mViewVisibility=0x0 mHaveFrame", "mViewVisibility=0x4 mHaveFrame")
        self.assertEqual(cw(hidden, 500, 300), "", "an invisible shade covers nothing; screen filters let taps through")
        self.assertEqual(cw(windows.replace("frame=[0,0][1080,2400]\n    isOnScreen", "frame=[0,0][1080,300]\n    isOnScreen"), 500, 900), "")
        bubble = hidden.replace("Window #9 Window{d4 u0 com.facebook.orca}", "Window #13 Window{e5 u0 com.facebook.orca}")
        bubble = bubble.replace("  Window #12", "  Window #13 Window{e5 u0 ChatHead}:\n    package=com.facebook.orca\n"
                                               "    mViewVisibility=0x0\n    mFrame=[900,1000][1080,1180]\n  Window #12")
        self.assertEqual(cw(bubble, 950, 1100), "ChatHead", "another app's bubble over the target")
        self.assertEqual(cw(bubble, 500, 1100), "")
        self.assertEqual(cw("", 1, 1), "")
        self.assertEqual(wa_guide.parse_user_activity("  mLastUserActivityTime=81234567 (12s ago)"), 81234567)
        self.assertIsNone(wa_guide.parse_user_activity("nothing"))
        self.assertTrue(wa_guide.parse_in_call("  mCallState=0\n  mCallState=2"))
        self.assertFalse(wa_guide.parse_in_call("  mCallState=0\n  mCallState=0"))
        self.assertEqual(classify(parse_layout(to_xml(BusyPhone.SHADE)), "com.whatsapp/.Conversation").name, "shade")
        self.assertEqual(classify(parse_layout(to_xml(BusyPhone.SHADE)), "com.android.launcher/.Home").name, "other_app")
        self.assertEqual(classify(parse_layout(to_xml(HOME)), "com.whatsapp/com.whatsapp.voipcalling.VoipActivityV2").name, "wa_call")


class SectionPhone(FakePhone):
    """WhatsApp left on another section (Calls, Updates...) of the bottom tab bar."""

    YOU_LABELS = ("Chats", "Updates", "Communities", "Calls", "You")
    MENU_LABELS = ("Chats", "Updates", "Communities", "Calls")

    def __init__(self, section="Calls", reports_selected=True, no_chats=False, **kw):
        super().__init__(e2e_on=False, **kw)
        self.section = section
        self.reports_selected = reports_selected
        self.no_chats = no_chats
        self.tab_taps = []

    @property
    def labels(self):
        return self.YOU_LABELS if self.home_style.startswith("you") else self.MENU_LABELS

    def layout(self):
        items = super().layout()
        if self.current not in ("home", "you"):
            return items
        if self.current == "home":
            items = tabs_home(labels=self.labels, overflow=not self.home_style.startswith("you"))
            if self.section != "Chats" or self.no_chats:
                items = [i for i in items if "conversations" not in i.get("id", "")]  # Calls has no chat list
        items = copy.deepcopy(items)
        if self.reports_selected:
            open_tab = "You" if self.current == "you" else self.section
            for i in items:
                if i.get("id", "").endswith("navigation_bar_item"):
                    i["selected"] = i.get("desc") == open_tab
        return items

    def tap(self, x, y):
        if self.current == "home" and y > 2200:
            label = self.labels[x * len(self.labels) // 1080]
            self.tab_taps.append(label)
            if label == "You":
                self.current = "you"
            else:
                self.section = label
            self.taps.append(("home", "navigation_bar_item"))
            return True, ""
        return super().tap(x, y)


class ChatsTabTests(unittest.TestCase):
    """Calls, Updates or Communities open: the guide goes to Chats (bottom left) first."""

    def run_it(self, phone):
        st, saved, _ = run_guide(phone)
        self.assertEqual((st["phase"], saved), ("done", [KEY]), st)
        return phone.tab_taps

    def test_70_menu_version_from_calls(self):
        phone = SectionPhone(home="calls_tabs")
        self.assertEqual(self.run_it(phone), ["Chats"])
        self.assertIn(("home", "menuitem_overflow"), phone.taps)
        self.assertLess(phone.taps.index(("home", "navigation_bar_item")), phone.taps.index(("home", "menuitem_overflow")))

    def test_71_you_version_from_calls(self):
        self.assertEqual(self.run_it(SectionPhone(home="you", section="Calls")), ["Chats", "You"])

    def test_72_you_version_from_updates_without_selection_info(self):
        self.assertEqual(self.run_it(SectionPhone(home="you", section="Updates", reports_selected=False)), ["Chats", "You"])

    def test_73_already_on_chats_goes_straight_on(self):
        self.assertEqual(self.run_it(SectionPhone(home="you", section="Chats")), ["You"])
        self.assertEqual(self.run_it(SectionPhone(home="calls_tabs", section="Chats")), [])

    def test_74_an_empty_chat_list_does_not_loop_on_chats(self):
        taps = self.run_it(SectionPhone(home="you", section="Chats", reports_selected=False, no_chats=True))
        self.assertEqual(taps, ["Chats", "You"], "one look at Chats, then on to You")

    def test_75_never_taps_chats_on_the_you_page(self):
        phone = SectionPhone(home="you", section="Calls")
        phone.current = "you"  # the user opened You (Chats row still below the fold)
        screen = classify(parse_layout(to_xml(phone.layout())), "com.whatsapp/.home.ui.HomeActivity")
        self.assertEqual((screen.name, screen.info["on_you_page"], screen.info["chats_tab_selected"]), ("home", True, False))
        action, _, _ = make_guide(phone)._plan_home(screen, "")
        self.assertEqual(action, ("scroll", "you_page"), "scrolls to Chats, no tab tap")


class SlowScreenTests(unittest.TestCase):
    def test_76_a_slow_screen_is_never_tapped_twice(self):
        """The guide reads the screen soon after a tap; a phone slow to show the result gets no second tap."""
        from unittest import mock

        class SlowPhone(FakePhone):
            pending = None

            def tap(self, x, y):
                if self.current == 2:
                    self.taps.append((2, "settings_chat"))
                    self.pending = time.time() + 0.6  # Chats opens 0.6 s later
                    return True, ""
                return super().tap(x, y)

            def dump(self):
                if self.pending and time.time() >= self.pending:
                    self.pending, self.current = None, "chats"
                return super().dump()

        phone = SlowPhone(e2e_on=False)
        with mock.patch.object(wa_guide, "REPEAT_GAP_SECS", 2.0):
            st, saved, _ = run_guide(phone, timeout=15)
        self.assertEqual(st["phase"], "done", st)
        self.assertEqual(phone.taps.count((2, "settings_chat")), 1)


class AdbPhoneCommandTests(unittest.TestCase):
    def test_42_slow_or_unplugged_phone_never_crashes_the_guide(self):
        from unittest import mock
        phone = wa_guide.AdbPhone("adb", "SER")
        with mock.patch.object(wa_guide.subprocess, "run", side_effect=wa_guide.subprocess.TimeoutExpired("adb", 20)):
            self.assertEqual(phone.dump(), "")
            self.assertIsNone(phone.snapshot())
        self.assertFalse(phone.connection_lost(), "slow is not unplugged")
        gone = mock.Mock(returncode=1, stdout=b"", stderr=b"adb: device 'SER' not found")
        with mock.patch.object(wa_guide.subprocess, "run", return_value=gone):
            self.assertIsNone(phone.snapshot())
        self.assertTrue(phone.connection_lost())
        back = mock.Mock(returncode=0, stdout=b"@@end\n", stderr=b"")
        with mock.patch.object(wa_guide.subprocess, "run", return_value=back):
            phone.snapshot()
        self.assertFalse(phone.connection_lost())

    def test_41_one_adb_call_per_round_and_per_tap(self):
        from unittest import mock
        calls = []
        snapshot_out = ("@@lock\n  mDreamingLockscreen=false\n    isKeyguardShowing=false\n"
                        "  mCurrentFocus=Window{9f u0 com.whatsapp/com.whatsapp.home.ui.HomeActivity}\n"
                        "@@power\n  mWakefulness=Awake\n  mLastUserActivityTime=4242 (1s ago)\n"
                        "@@call\n  mCallState=0\n  mCallState=0\n"
                        "@@top\n  topResumedActivity=ActivityRecord{1 u0 com.whatsapp/.home.ui.HomeActivity t3}\n@@end\n")
        windows = ("  Window #3 Window{a u0 NotificationShade}:\n    package=com.android.systemui\n    mViewVisibility=0x0\n"
                   "      Frames: frame=[0,0][1080,2400]\n  Window #2 Window{b u0 com.whatsapp/.home.ui.HomeActivity}:\n"
                   "    package=com.whatsapp\n")

        def fake_run(cmd, capture_output, timeout):
            calls.append(cmd)
            out = snapshot_out
            if "@@win" in cmd[-1]:
                out = ("@@power\n  mLastUserActivityTime=4243\n@@top\n  topResumedActivity=ActivityRecord{1 u0 com.whatsapp/.home.ui.HomeActivity t3}\n"
                       "@@win\n" + windows + "@@end\n")
            elif "@@top" in cmd[-1] and "@@lock" not in cmd[-1]:
                out = "@@power\n  mLastUserActivityTime=4243\n@@top\n@@end\n"
            return mock.Mock(returncode=0, stdout=out.encode(), stderr=b"")

        phone = wa_guide.AdbPhone("adb", "SER")
        with mock.patch.object(wa_guide.subprocess, "run", side_effect=fake_run):
            snap = phone.snapshot()
            near_top = phone.pre_touch(1020, 200, True)
            lower = phone.pre_touch(540, 1500, False)
        self.assertEqual(snap, {"lock": "unlocked", "activity": 4242, "in_call": False,
                                "foreground": "com.whatsapp/.home.ui.HomeActivity",
                                "focus": "com.whatsapp/com.whatsapp.home.ui.HomeActivity"})
        self.assertEqual((near_top["activity"], near_top["cover"]), (4243, "NotificationShade"))
        self.assertEqual(lower["cover"], "", "no window list for spots below the banner area")
        self.assertEqual(len(calls), 3, "one adb call each")
        self.assertNotIn("dumpsys window windows", calls[2][-1])
        self.assertIsNone(wa_guide.parse_snapshot("@@lock\n"), "a cut-short answer is not trusted")
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


if __name__ == "__main__":
    unittest.main()
