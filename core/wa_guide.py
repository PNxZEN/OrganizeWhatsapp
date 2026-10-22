"""
WhatsApp Media Organizer - guided setup of WhatsApp's end-to-end encrypted backup over USB.

The setup guide used to be 12 static slides plus copying the 64-digit key by hand. With the
phone connected over ADB, this module instead:

- reads which WhatsApp screen the phone shows (`uiautomator dump`, streamed over the cable; the
  layout stays in memory and is never stored or logged),
- tells the user exactly what to tap next ("guide" mode), or taps it for them ("auto" mode,
  where the phone allows simulated taps),
- reads the 64-digit key straight off the screen when WhatsApp shows it, and saves it,
- never taps "Use passkey" (a passkey cannot decrypt backups on a PC), never answers the
  phone's screen lock, and only turns off an existing encrypted backup after the user chose so.

Screens are recognised by WhatsApp's element ids, which do not depend on the phone's language
(tests/fixtures holds a recorded setup). Anything not recognised for a while sets `fallback`,
and the guide shows the manual slides instead, while this keeps watching for the key.
"""

import re
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

WA_PACKAGES = ("com.whatsapp", "com.whatsapp.w4b")
SYSTEM_LOCK_PACKAGES = ("com.android.systemui", "com.android.settings")
LOW_STORAGE_BYTES = 1024 ** 3        # warn before "Create" when the phone has less free space
UNKNOWN_FALLBACK_SECS = 20.0         # unrecognised screen this long -> manual slides
IDLE_STOP_SECS = 90.0                # nobody polls the status (guide closed) -> stop
MAX_SESSION_SECS = 30 * 60
SAME_ACTION_LIMIT = 3                # the same tap on the same screen without effect -> stop tapping
SETTLE_SECS = 1.2                    # after a tap, let the phone draw the next screen
BACKUP_WATCH_SECS = 10 * 60          # after "Create": wait this long for the backup file or an error
UNKNOWN_RECOVER_SECS = 2.5           # a WhatsApp screen that is not part of the setup (a chat, Status...)

HEX4 = re.compile(r"^[0-9a-fA-F]{4}$")
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")

# ---------------------------------------------------------------- screen model

@dataclass
class Node:
    rid: str          # short id ("settings_chat"); system ids keep their prefix ("android:id/button1")
    cls: str
    clickable: bool
    bounds: tuple     # (left, top, right, bottom)
    package: str = ""
    text: str = ""
    desc: str = ""
    selected: bool = False

    @property
    def center(self):
        l, t, r, b = self.bounds
        return (l + r) // 2, (t + b) // 2

    @property
    def height(self):
        return self.bounds[3] - self.bounds[1]

    def contains(self, other: "Node") -> bool:
        l, t, r, b = self.bounds
        ol, ot, orr, ob = other.bounds
        return l <= ol and t <= ot and r >= orr and b >= ob


def _bounds(text):
    nums = [int(x) for x in re.findall(r"-?\d+", text or "")]
    return tuple(nums[:4]) if len(nums) >= 4 else (0, 0, 0, 0)


def _short_id(rid: str) -> str:
    for pkg in WA_PACKAGES:
        if rid.startswith(pkg + ":id/"):
            return rid[len(pkg) + 4:]
    return rid


def parse_layout(xml_text: str) -> List[Node]:
    """Nodes of a `uiautomator dump`, or [] when it cannot be read."""
    if not xml_text or "<hierarchy" not in xml_text:
        return []
    xml_text = xml_text[xml_text.index("<hierarchy"):]
    end = xml_text.rfind("</hierarchy>")
    if end != -1:
        xml_text = xml_text[:end + len("</hierarchy>")]
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    return [
        Node(
            rid=_short_id(a.get("resource-id", "")),
            cls=a.get("class", "").split(".")[-1],
            clickable=a.get("clickable") == "true",
            bounds=_bounds(a.get("bounds")),
            package=a.get("package", ""),
            text=a.get("text", ""),
            desc=a.get("content-desc", ""),
            selected=a.get("selected") == "true",
        )
        for n in root.iter("node")
        for a in [n.attrib]
    ]


def nodes_from_fixture(items: List[dict]) -> List[Node]:
    """Nodes from the recorded-fixture format (tests)."""
    return [Node(rid=_short_id(i.get("id", "")), cls=i.get("class", ""), clickable=bool(i.get("clickable")),
                 bounds=_bounds(i.get("bounds")), package=i.get("package", ""),
                 text=i.get("text", ""), desc=i.get("desc", ""), selected=bool(i.get("selected"))) for i in items]


def screen_size(nodes: List[Node]):
    w = max((n.bounds[2] for n in nodes), default=1080)
    h = max((n.bounds[3] for n in nodes), default=2400)
    return w, h


def find(nodes, rid) -> Optional[Node]:
    return next((n for n in nodes if n.rid == rid), None)


def find_label(nodes, *labels, prefix=False) -> Optional[Node]:
    """The tappable element showing one of `labels` (its own text / description, or a parent row)."""
    wanted = {l.lower() for l in labels}

    def matches(value):
        value = (value or "").strip().lower()
        return value in wanted or (prefix and any(value.startswith(w + ",") or value.startswith(w + " ") for w in wanted))

    for n in nodes:
        if matches(n.text) or matches(n.desc):
            if n.clickable:
                return n
            parents = [p for p in nodes if p.clickable and p.contains(n)]
            if parents:
                return min(parents, key=lambda p: (p.bounds[2] - p.bounds[0]) * (p.bounds[3] - p.bounds[1]))
    return None


def clickable_around(nodes: List[Node], node: Node) -> Node:
    """The smallest tappable element containing `node` (or the node itself)."""
    if node.clickable:
        return node
    parents = [p for p in nodes if p.clickable and p.contains(node)]
    return min(parents, key=lambda p: (p.bounds[2] - p.bounds[0]) * (p.bounds[3] - p.bounds[1])) if parents else node


CHAT_ROW_ID = re.compile(r"conversation|contact|chat_row|jid", re.I)
CHAT_LIST_ID = re.compile(r"conversations?_row|contact_row|chat_row", re.I)  # rows of the chat list itself


# "Settings" in WhatsApp's ⋮ menu, in the languages it is most used in. A menu item is only tapped
# when it is one of these: guessing (e.g. "the last item") could hit "Read all" instead.
SETTINGS_WORDS = {
    "settings", "ajustes", "configuración", "configuraciones", "configurações", "definições", "paramètres",
    "réglages", "einstellungen", "impostazioni", "instellingen", "setelan", "pengaturan", "tetapan", "ayarlar",
    "настройки", "налаштування", "ustawienia", "nastavení", "nastavenia", "beállítások", "inställningar",
    "innstillinger", "indstillinger", "asetukset", "setări", "postavke", "ρυθμίσεις", "הגדרות", "الإعدادات",
    "تنظیمات", "ترتیبات", "सेटिंग", "सेटिंग्स", "সেটিংস", "சேவை அமைப்புகள்", "அமைப்புகள்", "సెట్టింగ్‌లు",
    "ಸೆಟ್ಟಿಂಗ್‌ಗಳು", "ക്രമീകരണങ്ങൾ", "सेटिंग्ज", "સેટિંગ્સ", "ਸੈਟਿੰਗਾਂ", "设置", "設定", "설정", "การตั้งค่า",
    "cài đặt", "mipangilio", "mga setting", "tilpasninger",
}
# The bottom-right tab of newer WhatsApp, which opens the Settings page itself
YOU_WORDS = {
    "you", "tú", "tu", "usted", "você", "vous", "du", "sie", "jij", "u", "anda", "kamu", "awak", "siz", "sen",
    "вы", "ты", "ви", "ти", "ty", "wy", "te", "ön", "εσύ", "אתה", "أنت", "شما", "آپ", "आप", "तुम", "আপনি",
    "நீங்கள்", "మీరు", "ನೀವು", "നിങ്ങൾ", "तुम्ही", "તમે", "ਤੁਸੀਂ", "你", "您", "あなた", "나", "คุณ", "bạn",
}
YOU_ID = re.compile(r"profile|avatar|\bme\b|_me_|you|account", re.I)


def _first_label(value: str) -> str:
    # Tabs read like "You, tab 5 of 5" or "Settings, 3 new"
    return (value or "").split(",")[0].strip().lower()


def settings_menu_item(nodes: List[Node], titles: List[Node]) -> Optional[Node]:
    """The ⋮ menu's Settings row, only when it is recognisably Settings."""
    for t in titles:
        if _first_label(t.text) in SETTINGS_WORDS:
            return clickable_around(nodes, t)
    return None


def is_you_tab(nodes: List[Node], tab: Node) -> bool:
    """Whether this (bottom-right) tab is newer WhatsApp's "You" tab: by its label or element id."""
    inside = [n for n in nodes if tab.contains(n)]
    for n in inside:
        if _first_label(n.text) in YOU_WORDS or _first_label(n.desc) in YOU_WORDS:
            return True
        if n.rid and YOU_ID.search(n.rid):
            return True
    return False


def tab_selected(nodes: List[Node], tab: Node) -> Optional[bool]:
    """Whether the tab is the open one, or None when this phone does not report it."""
    tabs_report = any(n.selected for n in nodes)
    if not tabs_report:
        return None
    return any(n.selected for n in nodes if tab.contains(n))


def settings_row(nodes: List[Node], wa_nodes: List[Node], label: str) -> Optional[Node]:
    """A full-width settings row showing `label` (not a bottom tab, chip or chat row), or None."""
    w, h = screen_size(nodes)
    for n in wa_nodes:
        if (n.text or "").strip().lower() != label.lower():
            continue
        row = clickable_around(nodes, n)
        wide = (row.bounds[2] - row.bounds[0]) >= 0.6 * w
        if row.clickable and wide and row.bounds[1] < 0.85 * h and not CHAT_ROW_ID.search(row.rid):
            return row
    return None


def bottom_tabs(nodes: List[Node]) -> List[Node]:
    """The tabs of a bottom navigation bar (3 or more tappable items in a row), left to right."""
    w, h = screen_size(nodes)
    candidates = [n for n in nodes if n.clickable and n.bounds[1] > 0.8 * h and 0 < n.height < 0.15 * h
                  and (n.bounds[2] - n.bounds[0]) < 0.45 * w]
    rows = {}
    for n in candidates:
        rows.setdefault(round(n.bounds[1] / 40), []).append(n)
    best = max(rows.values(), key=len, default=[])
    if len(best) < 3:
        return []
    # Keep the outermost element per tab (a tab and its icon can both be tappable)
    best.sort(key=lambda n: (n.bounds[0], -(n.bounds[2] - n.bounds[0])))
    tabs = []
    for n in best:
        if tabs and n.bounds[0] < tabs[-1].bounds[2]:
            continue
        tabs.append(n)
    return tabs if len(tabs) >= 3 else []


def extract_key(nodes: List[Node]) -> Optional[str]:
    """The 64-digit key shown on screen (16 blocks of 4, read row by row), or None."""
    for n in nodes:
        compact = re.sub(r"\s", "", n.text or "")
        if HEX64.match(compact):
            return compact.lower()
    blocks = [n for n in nodes if HEX4.match((n.text or "").strip())]
    if len(blocks) != 16:
        return None
    blocks.sort(key=lambda n: (n.bounds[1], n.bounds[0]))
    return "".join(n.text.strip() for n in blocks).lower()


@dataclass
class Screen:
    name: str
    target: Optional[Node] = None    # what to tap next
    label: str = ""                  # its name as shown to the user
    info: Dict = field(default_factory=dict)


def classify(nodes: List[Node], foreground: str = "") -> Screen:
    """
    Which step of the backup setup the phone shows. Most specific first: dialogs and the key
    confirmation sit on top of screens that are still in the layout behind them.
    """
    if not nodes:
        return Screen("unreadable")
    has = {n.rid for n in nodes if n.rid}
    wa_nodes = [n for n in nodes if n.package in WA_PACKAGES]

    if any(n.package in SYSTEM_LOCK_PACKAGES and re.search(r"credential|biometric|password_entry|pinEntry|lockPattern|lockPassword", n.rid)
           for n in nodes):
        return Screen("screen_lock")
    if not wa_nodes:
        return Screen("other_app", info={"foreground": foreground})

    if "enable_done_create_button" in has:
        return Screen("create", find(nodes, "enable_done_create_button"), "Create")
    if "encryption_key_confirm_button_confirm" in has:
        return Screen("key_confirm", find(nodes, "encryption_key_confirm_button_confirm"), "I saved my 64-digit key")
    if "confirm_disable_disable_button" in has:
        return Screen("confirm_turn_off", find(nodes, "confirm_disable_disable_button"), "Turn off")
    if "disable_done_done_button" in has:
        return Screen("turned_off", find(nodes, "disable_done_done_button"), "Done")
    if "enc_backup_encryption_key_input_forgot" in has:
        return Screen("enter_old_key", find(nodes, "enc_backup_encryption_key_input_forgot"), "I lost my encryption key")
    if "enc_backup_more_options_encryption_key" in has:
        return Screen("more_options", find(nodes, "enc_backup_more_options_encryption_key"), "64-digit encryption key")
    if "enable_info_more_options_button" in has:
        return Screen("e2e_off", find(nodes, "enable_info_more_options_button"), "More options",
                      {"passkey_button": find(nodes, "enable_info_turn_on_button")})
    if "enc_backup_enabled_landing_disable_button" in has:
        return Screen("e2e_on", find(nodes, "enc_backup_enabled_landing_disable_button"), "Turn off")
    key = extract_key(wa_nodes)
    if key:
        return Screen("key_shown", find(nodes, "encryption_key_info_bottom_button"), "Continue", {"key": key})
    if "encryption_key_info_bottom_button" in has or "encryption_key_info_middle_button" in has:
        return Screen("key_intro", find(nodes, "encryption_key_info_bottom_button") or find(nodes, "encryption_key_info_middle_button"),
                      "Generate your 64-digit key")
    if has & {"settings_gdrive_e2e_encryption", "google_drive_backup_now_btn", "settings_gdrive_change_frequency_view"}:
        return Screen("backup_settings", find(nodes, "settings_gdrive_e2e_encryption"), "End-to-end encrypted backup")
    if has & {"chat_backup_preference", "enter_key_preference", "font_size_preference"}:
        return Screen("chat_settings", find(nodes, "chat_backup_preference"), "Chat backup")
    if has & {"settings_chat", "settings_account_info", "privacy_preference"}:
        return Screen("settings", find(nodes, "settings_chat"), "Chats")
    # Newer WhatsApp's "You" tab is the Settings page itself (Lists, Chats, Broadcasts...): its
    # full-width "Chats" row, never the narrow "Chats" tab at the bottom
    chats_row = settings_row(nodes, wa_nodes, "Chats")
    if chats_row:
        return Screen("settings", chats_row, "Chats")
    if "android:id/button1" in has and len(nodes) < 30:
        message = next((n for n in nodes if n.rid == "android:id/message" and n.text), None)
        return Screen("dialog", find(nodes, "android:id/button1"), "OK", {"message": (message.text if message else "")[:300]})
    # WhatsApp's ⋮ menu (New group, ..., Settings): a popup of 3 or more items
    titles = [n for n in wa_nodes if n.rid == "android:id/title" and (n.text or "").strip()]
    if len(titles) >= 3:
        item = settings_menu_item(nodes, titles)
        return Screen("menu", item, "Settings", {"has_settings": item is not None})
    if len(nodes) <= 12 and titles:
        return Screen("popup")  # e.g. the "Copy" bubble after long-pressing the key
    # Only WhatsApp's own home screen: a chat also has a row of buttons at the bottom (emoji,
    # attach, camera, mic) and a text box, and must never be mistaken for the home tabs.
    message_box = any(n.cls == "EditText" and n.bounds[1] > 0.7 * screen_size(nodes)[1] for n in wa_nodes)
    if re.search(r"(HomeActivity|\.Main)$", foreground or "") and not message_box:
        tabs = bottom_tabs(wa_nodes)
        # Only the bottom-right tab is checked (never a chat that happens to be called "You")
        you_tab = tabs[-1] if tabs and is_you_tab(nodes, tabs[-1]) else None
        overflow = find(nodes, "menuitem_overflow") or find_label(nodes, "More options")
        if overflow and overflow.bounds[1] > 0.3 * screen_size(nodes)[1]:
            overflow = None  # ⋮ is in the top bar
        return Screen("home", None, "Settings", {
            "you_tab": you_tab,
            "on_you_page": tab_selected(nodes, you_tab) if you_tab else False,
            "chat_rows": any(CHAT_LIST_ID.search(n.rid) for n in wa_nodes if n.rid),
            "overflow": overflow,
        })
    return Screen("unknown", info={"foreground": foreground})


# What to show the user, per screen (the guide's progress list uses the step keys)
STEPS = [
    ("settings", "Open WhatsApp Settings"),
    ("chats", "Chats"),
    ("backup", "Chat backup"),
    ("e2e", "End-to-end encrypted backup"),
    ("turn_off", "Turn off the old encrypted backup"),
    ("key_option", "Choose the 64-digit key"),
    ("generate", "Generate the key (read automatically)"),
    ("confirm", "Confirm you saved the key"),
    ("create", "Create the backup"),
    ("making", "WhatsApp makes the backup"),
]
SCREEN_STEP = {
    "other_app": "settings", "home": "settings", "menu": "settings", "settings": "chats",
    "chat_settings": "backup", "backup_settings": "e2e",
    "e2e_on": "turn_off", "enter_old_key": "turn_off", "screen_lock": "turn_off",
    "confirm_turn_off": "turn_off", "turned_off": "turn_off",
    "e2e_off": "key_option", "more_options": "key_option",
    "key_intro": "generate", "key_shown": "generate", "popup": "generate",
    "key_confirm": "confirm", "create": "create",
}
# The setup guide's tutorial screenshot of the same WhatsApp screen (gallery_assets wa_step<N>.webp),
# shown next to the live instructions so the user sees where on the phone things happen
SCREEN_SLIDE = {
    "other_app": 0, "home": 0, "menu": 0, "settings": 1, "chat_settings": 2, "backup_settings": 3, "e2e_on": 3,
    "e2e_off": 4, "more_options": 5, "key_intro": 6, "key_shown": 8, "popup": 8, "key_confirm": 9, "create": 10,
}
INSTRUCTIONS = {
    "locked": "Unlock your phone. (This app never enters or sees your PIN.)",
    "other_app": "Open WhatsApp on your phone.",
    "home": "Open Settings: tap the last tab at the bottom (Settings / You), or ⋮ at the top right and then Settings.",
    "menu": "Tap Settings.",
    "settings": "Tap Chats.",
    "chat_settings": "Scroll down and tap Chat backup.",
    "backup_settings": "Scroll down and tap End-to-end encrypted backup.",
    "e2e_on": "Your backup is already end-to-end encrypted. Choose below how to continue.",
    "enter_old_key": "Tap \"I lost my encryption key\".",
    "screen_lock": "Confirm with your fingerprint, face or screen lock on the phone.",
    "confirm_turn_off": "Tap Turn off.",
    "turned_off": "Tap Done.",
    "e2e_off": "Tap More options. Do not tap \"Use passkey\": a passkey cannot unlock your backup on this computer.",
    "more_options": "Tap \"64-digit encryption key\".",
    "key_intro": "Tap \"Generate your 64-digit key\".",
    "key_shown": "Tap Continue.",
    "popup": "Tap outside the small menu. You do not need to copy the key: this app reads it.",
    "key_confirm": "Tap \"I saved my 64-digit key\".",
    "create": "Tap Create. WhatsApp then makes the backup this app reads.",
    "dialog": "WhatsApp shows a message on your phone. Read it and tap OK.",
    "unknown": "Go back to WhatsApp's Chats list, then open Settings.",
    "unreadable": "Unlock your phone and keep it on.",
}


# ---------------------------------------------------------------- phone access

def parse_foreground(text: str) -> str:
    for pattern in (r"topResumedActivity[=:].*?\s([\w.]+/[\w.$]+)", r"ResumedActivity[=:].*?\s([\w.]+/[\w.$]+)",
                    r"mCurrentFocus=.*?\s([\w.]+/[\w.$]+)"):
        m = re.search(pattern, text or "")
        if m:
            return m.group(1)
    return ""


def parse_lock_state(window_text: str, power_text: str) -> str:
    """'asleep', 'locked', 'unlocked' or 'unknown', from `dumpsys window` / `dumpsys power` lines."""
    if re.search(r"mWakefulness=(Asleep|Dozing)", power_text or "") or re.search(r"Display Power: state=OFF", power_text or ""):
        return "asleep"
    keys = r"(mKeyguardShowing|isKeyguardShowing|KeyguardShowing|keyguardShowing|mShowingLockscreen|mDreamingLockscreen)"
    if re.search(keys + r"\s*[=:]\s*true", window_text or ""):
        return "locked"
    if re.search(keys + r"\s*[=:]\s*false", window_text or ""):
        return "unlocked"
    return "unknown"


def parse_backup_stats(text: str):
    """(newest modification time, its size) from lines of `stat -c '%Y %s'`, or None."""
    best = None
    for line in (text or "").splitlines():
        m = re.match(r"^\s*(\d{9,})\s+(\d+)\s*$", line)
        if m:
            entry = (int(m.group(1)), int(m.group(2)))
            if best is None or entry[0] > best[0]:
                best = entry
    return best


class AdbPhone:
    """The few ADB calls the guide needs. A layout is kept in memory only, never written to disk."""

    def __init__(self, adb: str, serial: str = ""):
        self.base = [adb] + (["-s", serial] if serial else [])
        self.serial = serial

    def _run(self, *args, timeout=20):
        res = subprocess.run(self.base + list(args), capture_output=True, timeout=timeout)
        return res.returncode, res.stdout.decode("utf-8", errors="replace") + res.stderr.decode("utf-8", errors="replace")

    def dump(self) -> str:
        _, out = self._run("exec-out", "uiautomator", "dump", "/dev/tty")
        if "<hierarchy" in out:
            return out
        tmp = "/data/local/tmp/wa_guide_layout.xml"  # phones that cannot stream it: removed at once
        # adb joins its arguments into one shell command line on the phone
        _, out = self._run("exec-out", f"uiautomator dump {tmp} >/dev/null 2>&1; cat {tmp}; rm -f {tmp}")
        return out if "<hierarchy" in out else ""

    def foreground(self) -> str:
        _, out = self._run("shell", "dumpsys activity activities | grep -E 'ResumedActivity'", timeout=10)
        return parse_foreground(out)

    def lock_state(self) -> str:
        _, window = self._run("shell", "dumpsys window | grep -iE 'keyguard|lockscreen'", timeout=10)
        _, power = self._run("shell", "dumpsys power | grep -E 'mWakefulness=|Display Power'", timeout=10)
        return parse_lock_state(window, power)

    def wake(self):
        # Turns the screen on (shows the lock screen); it cannot unlock anything
        self._run("shell", "input keyevent KEYCODE_WAKEUP", timeout=10)

    def go_home(self):
        # An intent, not a key press: works on phones that block simulated input
        self._run("shell", "am start -a android.intent.action.MAIN -c android.intent.category.HOME", timeout=10)

    def open_fresh(self, package: str) -> bool:
        """Opens WhatsApp on its main screen, not on the chat or screen it was last left on."""
        _, out = self._run("shell", f"cmd package resolve-activity --brief -a android.intent.action.MAIN "
                                    f"-c android.intent.category.LAUNCHER {package}", timeout=10)
        component = next((l.strip() for l in reversed(out.splitlines()) if l.strip().startswith(package + "/")), "")
        if component:
            code, out = self._run("shell", f"am start -W --activity-clear-task --activity-new-task "
                                           f"-a android.intent.action.MAIN -c android.intent.category.LAUNCHER -n {component}",
                                  timeout=20)
            if code == 0 and "Error" not in out and "Exception" not in out:
                return True
        return self.launch(package)

    def tap(self, x: int, y: int):
        code, out = self._run("shell", "input", "tap", str(x), str(y), timeout=10)
        return code == 0 and "Exception" not in out, out

    def swipe(self, x1, y1, x2, y2, ms=300):
        code, out = self._run("shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(ms), timeout=10)
        return code == 0 and "Exception" not in out, out

    def back(self):
        code, out = self._run("shell", "input", "keyevent", "4", timeout=10)
        return code == 0 and "Exception" not in out, out

    def launch(self, package: str) -> bool:
        _, out = self._run("shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1", timeout=15)
        return "Events injected: 1" in out

    def now(self) -> Optional[int]:
        """The phone's clock (backup file times are compared with it, not with this computer's)."""
        _, out = self._run("shell", "date +%s", timeout=10)
        m = re.search(r"\d{9,}", out)
        return int(m.group(0)) if m else None

    def latest_backup(self, package: str):
        """(modification time, size) of WhatsApp's newest local backup database, or None."""
        name = "WhatsApp Business" if package.endswith(".w4b") else "WhatsApp"
        bases = [f"/sdcard/Android/media/{package}/{name}", f"/sdcard/{name}"]
        globs = " ".join(f'"{b}"/Databases/msgstore*.crypt1* "{b}"/accounts/*/Databases/msgstore*.crypt1*' for b in bases)
        _, out = self._run("shell", f'for f in {globs}; do [ -f "$f" ] && stat -c "%Y %s" "$f"; done', timeout=15)
        return parse_backup_stats(out)

    def free_bytes(self) -> Optional[int]:
        try:
            from core.adb import get_device_storage_info
            info = get_device_storage_info(serial=self.serial or None)
            return info.get("free_bytes") if info.get("success") else None
        except Exception:
            return None


def storage_needed(previous_backup_size: Optional[int]) -> int:
    """Free space to ask for before WhatsApp writes a new local backup (with room to spare)."""
    if not previous_backup_size:
        return LOW_STORAGE_BYTES
    return max(LOW_STORAGE_BYTES, int(previous_backup_size * 1.5) + 300 * 1024 ** 2)


def _gb(n):
    return f"{n / 1024 ** 3:.1f} GB"


# ---------------------------------------------------------------- guide session

class WaGuide:
    """
    One guided setup at a time. `start()` runs a background loop that reads the phone's screen,
    updates `status()` for the setup guide and, in auto mode, taps the next step.

    Order: wait until the phone is unlocked, go to the home screen, open WhatsApp fresh (not on
    the chat it was left on), walk to the backup settings, read the key, and after "Create" watch
    until WhatsApp's backup file appears or WhatsApp reports an error.
    """

    def __init__(self, phone_factory: Callable[[], object], save_key: Callable[[str], bool],
                 package: str = "com.whatsapp", clock=time.time, sleep=time.sleep):
        self._phone_factory = phone_factory
        self._save_key = save_key
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.package = package
        self._reset_state("guide")
        self._state["phase"] = "idle"

    # ----- state

    def _reset_state(self, mode):
        now = self._clock()
        self._state = {
            "active": False, "mode": mode, "phase": "running", "screen": "", "step": "",
            "instruction": "", "warning": "", "notice": "", "message": "", "target": "",
            "key_captured": False, "masked_key": "", "input_allowed": True,
            "choice": None, "e2e_was_on": False, "low_storage_ok": False,
            "free_bytes": None, "storage_needed": None, "storage_warning": "",
            "created": False, "backup_error": "", "backup_size": None, "slide_hint": None,
            "fallback": False, "fallback_reason": "", "started_at": now,
        }
        self._last_poll = now
        self._unknown_since = None
        self._last_action = None
        self._same_action = 0
        self._scrolls = {}
        self._you_version = False      # newer WhatsApp: Settings is the bottom-right "You" tab
        self._you_tapped = False
        self._you_taps = 0
        self._you_scrolls = 0
        self._menu_taps = 0
        self._menu_failed = False
        self._handed_over = False
        self._recoveries = 0
        self._backs = 0
        self._prev_screen = ""
        self._backup_since = None      # the phone's clock when "Create" / "Back up" was tapped
        self._backup_clock = None      # this computer's clock then (for the watch timeout)
        self._retry = False

    def status(self) -> dict:
        with self._lock:
            self._last_poll = self._clock()
            st = dict(self._state)
        st["steps"] = self._steps(st)
        st["slide"] = (11 if st["phase"] == "backing_up" else None if st["phase"] in ("locked", "backup_failed")
                       else st.get("slide_hint") if st.get("slide_hint") is not None else SCREEN_SLIDE.get(st["screen"]))
        return st

    def _steps(self, st):
        current = SCREEN_STEP.get(st["screen"], "")
        if st["phase"] in ("backing_up", "backup_failed"):
            current = "making"
        keys = [k for k, _ in STEPS if k != "turn_off" or st["e2e_was_on"]]
        idx = keys.index(current) if current in keys else -1
        done_all = st["phase"] == "done"
        out = []
        for i, (k, title) in enumerate((k, t) for k, t in STEPS if k in keys):
            state = "done" if done_all or (idx >= 0 and i < idx) else "active" if i == idx else "todo"
            out.append({"key": k, "title": title, "state": state})
        return out

    def _set(self, **kw):
        with self._lock:
            self._state.update(kw)

    # ----- control (called from the server)

    def start(self, mode="auto", package=None):
        self.stop()
        if package:
            self.package = package
        with self._lock:
            self._reset_state(mode if mode in ("auto", "guide") else "guide")
            self._state["active"] = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self.status()

    def stop(self):
        self._stop.set()
        t = self._thread
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=8)
        with self._lock:
            if self._state.get("active"):
                self._state.update(active=False, phase="stopped")

    def set_mode(self, mode):
        self._set(mode=mode if mode in ("auto", "guide") else "guide", notice="")
        self._same_action = 0

    def choose(self, choice):
        """After "already encrypted": 'reset' (turn it off, make a new key) or 'have_key'."""
        if choice not in ("reset", "have_key"):
            raise ValueError("unknown choice")
        self._set(choice=choice, phase="running")

    def allow_low_storage(self):
        self._set(low_storage_ok=True, phase="running", warning="")

    def retry_backup(self):
        """After WhatsApp could not make the backup (e.g. storage now freed): close its message, tap Back up."""
        if not self._state.get("active"):
            raise ValueError("the guide is not running; start it again")
        self._retry = True
        self._backup_since = None
        self._set(phase="running", backup_error="", warning="")

    def key_provided(self, masked):
        """The user gave the key on the PC (paste or older version): nothing more to do on the phone."""
        self._stop.set()
        self._set(key_captured=True, masked_key=masked, phase="done", active=False,
                  message="Key saved. If your phone's end-to-end encrypted backup was made with this key, "
                          "the sync can read it now.")

    # ----- loop

    def _run(self):
        try:
            phone = self._phone_factory()
        except Exception as e:
            self._set(active=False, phase="error", message=f"Could not reach the phone: {e}")
            return
        try:
            if self._prepare(phone):
                self._loop(phone)
        except Exception as e:  # the guide must never take the server down
            self._set(phase="error", message=f"The guide stopped: {e}")
        finally:
            with self._lock:
                self._state["active"] = False

    def _timed_out(self):
        now = self._clock()
        if now - self._last_poll > IDLE_STOP_SECS or now - self._state["started_at"] > MAX_SESSION_SECS:
            self._set(phase="stopped", message="The guide stopped because it was not being watched.")
            return True
        return False

    def _wait_unlocked(self, phone) -> bool:
        """Asks the user to unlock the phone and waits. False when stopped meanwhile."""
        woke = False
        while not self._stop.is_set():
            if self._timed_out():
                return False
            if phone.lock_state() not in ("asleep", "locked"):
                return True
            if not woke:
                phone.wake()
                woke = True
            self._set(phase="locked", screen="locked", step="", instruction=INSTRUCTIONS["locked"], target="")
            self._sleep(1.0)
        return False

    def _prepare(self, phone) -> bool:
        if not self._wait_unlocked(phone):
            return False
        self._set(phase="running", screen="", instruction="Opening WhatsApp…")
        phone.go_home()
        self._sleep(0.8)
        phone.open_fresh(self.package)
        self._launched_at = self._clock()
        self._check_storage(phone)
        self._sleep(SETTLE_SECS)
        return True

    def _check_storage(self, phone):
        free = phone.free_bytes()
        previous = phone.latest_backup(self.package)
        need = storage_needed(previous[1] if previous else None)
        warning = ""
        if free is not None and free < need:
            warning = (f"Your phone has {_gb(free)} free, and WhatsApp needs about {_gb(need)} to make the backup. "
                       "Free up space on the phone (delete large videos or apps) before the last step.")
        self._set(free_bytes=free, storage_needed=need, storage_warning=warning)

    def _loop(self, phone):
        while not self._stop.is_set():
            if self._timed_out():
                return
            if phone.lock_state() in ("asleep", "locked"):  # locked half-way: wait, then carry on
                if not self._wait_unlocked(phone):
                    return
                self._set(phase="running")
            now = self._clock()
            foreground = phone.foreground()
            nodes = parse_layout(phone.dump())
            screen = classify(nodes, foreground)
            acted = self._handle(phone, screen, nodes, now)
            self._prev_screen = screen.name
            if self._state["phase"] == "done":
                return
            self._sleep(SETTLE_SECS if acted else 0.4)

    # ----- one screen

    def _start_backup_watch(self, phone, instruction="WhatsApp is making the backup on your phone. Keep it on and connected."):
        since = phone.now()
        if since is None:  # no phone clock: only a file newer than the current newest one counts
            previous = phone.latest_backup(self.package)
            since = previous[0] + 3 if previous else 0
        self._backup_since = since
        self._backup_clock = self._clock()
        self._set(created=True, phase="backing_up", backup_error="", warning="", instruction=instruction)

    def _watch_backup(self, phone, screen: Screen, nodes):
        """After Create / Back up: success when the backup file is new, failure on WhatsApp's message."""
        st = self._state
        if screen.name == "dialog":
            message = screen.info.get("message") or "WhatsApp could not make the backup."
            self._set(phase="backup_failed", backup_error=message, screen="dialog",
                      instruction=f"WhatsApp says: “{message}”")
            self._check_storage(phone)
            return None
        latest = phone.latest_backup(self.package)
        if latest and self._backup_since is not None and latest[0] >= self._backup_since - 2 and latest[1] > 0:
            self._set(phase="done", backup_size=latest[1], screen=screen.name, instruction="",
                      message=f"WhatsApp made the encrypted backup ({latest[1] / 1024 ** 2:.0f} MB). "
                              "This app can read it now.")
            return None
        if self._clock() - (self._backup_clock or self._clock()) > BACKUP_WATCH_SECS:
            self._set(phase="done", screen=screen.name, instruction="",
                      message="Your key is saved. WhatsApp is still making the backup; "
                              "keep the phone connected, the sync waits for it.")
            return None
        if st["phase"] != "backup_failed":
            self._set(phase="backing_up", screen=screen.name)
        return None

    def _handle(self, phone, screen: Screen, nodes, now):
        st = self._state
        name = screen.name

        # Unrecognised for too long -> manual slides (keeps watching for the key meanwhile)
        if name in ("unknown", "unreadable", "other_app"):
            self._unknown_since = self._unknown_since or now
            if now - self._unknown_since > UNKNOWN_FALLBACK_SECS and not st["fallback"]:
                self._set(fallback=True, fallback_reason="This phone shows a WhatsApp screen the guide does not know yet.")
        else:
            self._unknown_since = None
            self._recoveries = self._backs = 0

        if name == "key_shown" and not st["key_captured"]:
            key = screen.info["key"]
            if self._save_key(key):
                self._set(key_captured=True, masked_key=key[:4] + "…" + key[-4:])
        if name == "e2e_on":
            self._set(e2e_was_on=True)

        # The user tapped Create themselves (guide mode)
        if self._prev_screen == "create" and name in ("backup_settings", "dialog") and not st["created"]:
            self._start_backup_watch(phone)

        # After Create: watch the backup instead of navigating
        if st["created"] and not self._retry:
            return self._watch_backup(phone, screen, nodes)

        warning = ""
        instruction = INSTRUCTIONS.get(name, INSTRUCTIONS["unknown"])
        phase = "running"
        label = screen.label
        action = None  # ("tap", node) | ("scroll",) | ("back",) | ("relaunch",)

        if self._retry:
            # Close WhatsApp's message, then tap "Back up" on the Chat backup screen
            if name == "dialog":
                action, label = ("tap", screen.target), "OK"
                instruction = "Tap OK on the phone."
            elif name == "backup_settings":
                backup_now = find(nodes, "google_drive_backup_now_btn")
                if backup_now:
                    action, label = ("tap", backup_now), "Back up"
                instruction = "Tap Back up on the phone."
                if st["mode"] != "auto" or not backup_now:
                    # The user taps it: watch for the new backup (or WhatsApp's message) from now on
                    self._retry = False
                    self._start_backup_watch(phone, "Tap Back up on the phone. This app watches for the new backup.")
                    self._set(screen=name)
                    return None

        if action is None and not self._retry or (self._retry and name not in ("dialog", "backup_settings")):
            action, instruction, phase, warning, label = self._plan(phone, screen, nodes, now, instruction)

        if name in ("chat_settings", "backup_settings", "settings") and action and action[0] == "tap":
            # Rows at the very bottom are only partly visible: scroll them into view first
            w, h = screen_size(nodes)
            t = action[1]
            if t.height < 90 or t.bounds[3] > h - 60:
                action = ("scroll",)

        will_act = st["mode"] == "auto" and action is not None and phase == "running"
        if will_act:
            # Say what the app is doing, not what the user should tap
            kind = action[0]
            if kind == "tap" and name == "key_shown":
                instruction = "Key received on this computer. Continuing…"
            elif kind == "tap":
                instruction = f"Tapping “{label}”…"
            elif kind == "scroll":
                instruction = f"Scrolling to “{label}”…" if label else "Scrolling…"
            elif kind == "back":
                instruction = "Going back…" if name == "unknown" else "Closing the menu…"
            else:
                instruction = "Opening WhatsApp on its main screen…"
        # Newer WhatsApp ("You" tab): its own tutorial pictures instead of the ⋮ menu ones
        slide_hint = None
        if self._you_version and name in ("home", "settings", "other_app", "unknown"):
            on_page = name == "settings" or (name == "home" and (screen.info.get("on_you_page") or (
                screen.info.get("on_you_page") is None and (self._you_tapped or not screen.info.get("chat_rows")))))
            slide_hint = "you_page" if on_page else "you_home"
        self._set(slide_hint=slide_hint)
        self._set(screen=name, step=SCREEN_STEP.get(name, ""), instruction=instruction, warning=warning,
                  phase=phase, target=label, message="" if phase == "running" else st["message"])

        if not will_act:
            return None
        return self._act(phone, name, action, nodes)

    def _plan(self, phone, screen, nodes, now, instruction):
        """What to do on a setup screen: (action, instruction, phase, warning, label)."""
        st = self._state
        name = screen.name
        action, phase, warning, label = None, "running", "", screen.label

        if name == "e2e_on":
            if st["choice"] is None:
                phase = "needs_choice"
            elif st["choice"] == "have_key":
                phase = "have_key"
                instruction = "Leave your phone as it is and give this app your key below."
            else:
                action = ("tap", screen.target)
                instruction = "Tap Turn off (the old backup stays on Google Drive)."
        elif name == "enter_old_key":
            if st["choice"] == "reset":
                action = ("tap", screen.target)
            elif st["choice"] == "have_key":
                phase = "have_key"
                instruction = "No need to type the key on the phone. Give it to this app below."
        elif name == "confirm_turn_off":
            if st["choice"] == "reset":
                action = ("tap", screen.target)
            else:
                instruction = "Tap Cancel on the phone, unless you want to make a new key."
        elif name == "screen_lock":
            phase = "needs_user"
        elif name == "e2e_off":
            warning = "Do not tap \"Use passkey\": a passkey cannot unlock your backup on this computer."
            action = ("tap", screen.target)
        elif name in ("more_options", "key_intro", "turned_off", "settings", "chat_settings", "backup_settings"):
            action = ("tap", screen.target) if screen.target else ("scroll",)
        elif name == "home":
            action, instruction, label = self._plan_home(screen, instruction)
        elif name == "menu":
            if screen.target:
                action, label = ("tap", screen.target), "Settings"
                instruction = "Tap Settings."
            else:
                # This menu has no recognisable Settings (newer WhatsApp keeps it in the "You" tab, or
                # another language): never guess an item (it could be "Read all"); close it, hand over
                action, label = ("back",), "the menu"
                instruction = "Close the menu, then open WhatsApp's Settings yourself."
                self._menu_failed = True
        elif name == "key_shown":
            if st["key_captured"]:
                action = ("tap", screen.target)
                instruction = "Key received on this computer. Tap Continue."
            else:
                instruction = "The key could not be read. Long-press it, tap Copy, and use \"Paste key\" below."
        elif name == "popup":
            action = ("back",)
        elif name == "key_confirm":
            if st["key_captured"]:
                action = ("tap", screen.target)
            else:
                instruction = "Make sure you have the key (copy it), then tap \"I saved my 64-digit key\"."
        elif name == "create":
            if st["storage_warning"] and not st["low_storage_ok"]:
                self._check_storage(phone)  # maybe the user freed some space meanwhile
            if self._state["storage_warning"] and not st["low_storage_ok"]:
                phase = "low_storage"
                warning = self._state["storage_warning"]
                instruction = "Paused before \u201cCreate\u201d: your phone may be too full for the backup."
            else:
                action = ("tap", screen.target)
        elif name == "dialog":
            if screen.info.get("message"):
                instruction = f"WhatsApp says: “{screen.info['message']}” Tap OK on the phone."
        elif name == "unknown":
            # A chat, Status, Calls... : reopen WhatsApp on its main screen, then try Back
            if self._unknown_since and now - self._unknown_since >= UNKNOWN_RECOVER_SECS:
                if self._recoveries < 2:
                    action = ("relaunch",)
                elif self._backs < 3:
                    action = ("back",)
        elif name == "other_app":
            if now - getattr(self, "_launched_at", 0) > 6 and self._recoveries < 3:
                action = ("relaunch",)
        return action, instruction, phase, warning, label

    def _hand_over(self, why):
        """Settings could not be reached automatically: the user opens it, the guide continues from there."""
        if self._state["mode"] == "auto" and not self._handed_over:
            self._handed_over = True
            self._set(mode="guide", notice=why + " Please open it yourself on the phone; the app takes over from there.")

    def _plan_home(self, screen, instruction):
        """
        From WhatsApp's main screen to Settings, in this order:
        1. newer WhatsApp: the bottom-right "You" tab is the Settings page (Chats a little further down);
        2. otherwise the ⋮ menu, which then has Settings;
        3. anything else (e.g. a WhatsApp update moved it): the user opens Settings.
        """
        info = screen.info
        you_tab = info.get("you_tab")
        if you_tab:
            self._you_version = True
            on_page = info.get("on_you_page")
            if on_page is None:
                # The phone does not say which tab is open: our own tap, or (the user tapped) no chat list
                on_page = self._you_tapped or not info.get("chat_rows")
            if not on_page:
                if self._you_taps < 2:
                    return ("tap", you_tab, "you_tab"), "Tap You (bottom right).", "You"
                self._hand_over("The app could not open the You tab.")
                return None, "Tap You (bottom right), scroll down a little and tap Chats.", "You"
            if self._you_scrolls < 3:
                return ("scroll", "you_page"), "Scroll down a little and tap Chats.", "Chats"
            self._hand_over("The app could not find Chats on the You page.")
            return None, "On the You page, scroll down and tap Chats.", "Chats"
        if self._you_version:
            # Seen the You tab before but not now: do not try ⋮ (no Settings there in that version)
            self._hand_over("The app lost track of WhatsApp's screens.")
            return None, "Tap You (bottom right), scroll down a little and tap Chats.", "You"
        overflow = info.get("overflow")
        if overflow and not self._menu_failed and self._menu_taps < 2:
            return ("tap", overflow, "overflow"), "Tap \u22ee (top right), then Settings.", "\u22ee (More options)"
        self._hand_over("The app could not find WhatsApp's Settings on this phone.")
        return None, "Open WhatsApp's Settings: tap \u22ee (top right) and then Settings, or You (bottom right).", ""

    def _act(self, phone, name, action, nodes):
        kind = action[0]
        signature = (name, kind, action[1].bounds if kind == "tap" and action[1] else None)
        if signature == self._last_action:
            self._same_action += 1
        else:
            self._last_action, self._same_action = signature, 1
        if self._same_action > SAME_ACTION_LIMIT and kind != "relaunch":
            self._set(mode="guide", notice="The app could not move forward on this screen. Please tap it yourself.")
            return None
        if kind == "relaunch":
            self._recoveries += 1
            phone.open_fresh(self.package)
            self._launched_at = self._clock()
            return "relaunch"
        if kind == "scroll":
            count = self._scrolls.get(name, 0)
            if count >= 4:
                return None
            self._scrolls[name] = count + 1
            w, h = screen_size(nodes)
            ok, out = phone.swipe(w // 2, int(h * 0.72), w // 2, int(h * 0.38))
            if ok and action[1:] == ("you_page",):
                self._you_scrolls += 1
        elif kind == "tap":
            ok, out = phone.tap(*action[1].center)
            if ok and action[2:] == ("you_tab",):
                self._you_tapped = True
                self._you_taps += 1
            if ok and action[2:] == ("overflow",):
                self._menu_taps += 1
            if ok and (name == "create" or (self._retry and name == "backup_settings")):
                self._retry = False
                self._start_backup_watch(phone)
        else:  # back
            if name == "unknown":
                self._backs += 1
            ok, out = phone.back()
        if not ok and ("INJECT_EVENTS" in out or "SecurityException" in out):
            self._set(input_allowed=False, mode="guide",
                      notice="This phone does not let apps tap for you. Follow the steps yourself"
                             " (on Xiaomi you can allow it: Developer options › USB debugging (Security settings)).")
            return None
        return kind
