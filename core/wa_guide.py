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
        )
        for n in root.iter("node")
        for a in [n.attrib]
    ]


def nodes_from_fixture(items: List[dict]) -> List[Node]:
    """Nodes from the recorded-fixture format (tests)."""
    return [Node(rid=_short_id(i.get("id", "")), cls=i.get("class", ""), clickable=bool(i.get("clickable")),
                 bounds=_bounds(i.get("bounds")), package=i.get("package", ""),
                 text=i.get("text", ""), desc=i.get("desc", "")) for i in items]


def screen_size(nodes: List[Node]):
    w = max((n.bounds[2] for n in nodes), default=1080)
    h = max((n.bounds[3] for n in nodes), default=2400)
    return w, h


def find(nodes, rid) -> Optional[Node]:
    return next((n for n in nodes if n.rid == rid), None)


def find_label(nodes, *labels) -> Optional[Node]:
    """The tappable element showing one of `labels` (its own text / description, or a parent row)."""
    wanted = {l.lower() for l in labels}
    for n in nodes:
        if (n.text or "").strip().lower() in wanted or (n.desc or "").strip().lower() in wanted:
            if n.clickable:
                return n
            parents = [p for p in nodes if p.clickable and p.contains(n)]
            if parents:
                return min(parents, key=lambda p: (p.bounds[2] - p.bounds[0]) * (p.bounds[3] - p.bounds[1]))
    return None


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
    if "android:id/button1" in has and len(nodes) < 30:
        message = next((n for n in nodes if n.rid == "android:id/message" and n.text), None)
        return Screen("dialog", find(nodes, "android:id/button1"), "OK", {"message": (message.text if message else "")[:300]})
    if len(nodes) <= 12 and find(nodes, "android:id/title"):
        settings_item = find_label(nodes, "Settings")
        if settings_item:
            return Screen("menu", settings_item, "Settings")
        return Screen("popup")
    if re.search(r"(HomeActivity|\.Main)$", foreground or ""):
        target = find_label(nodes, "Settings", "You")
        if target:
            return Screen("home", target, "Settings")
        overflow = find(nodes, "menuitem_overflow") or find_label(nodes, "More options")
        return Screen("home", overflow, "⋮ (More options)" if overflow else "", {"via_menu": bool(overflow)})
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
INSTRUCTIONS = {
    "other_app": "Open WhatsApp on your phone.",
    "home": "Open Settings: tap ⋮ (top right) and then Settings, or the Settings / You tab.",
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
    "unknown": "Go back to WhatsApp Settings › Chats › Chat backup.",
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

    def free_bytes(self) -> Optional[int]:
        try:
            from core.adb import get_device_storage_info
            info = get_device_storage_info(serial=self.serial or None)
            return info.get("free_bytes") if info.get("success") else None
        except Exception:
            return None


# ---------------------------------------------------------------- guide session

class WaGuide:
    """
    One guided setup at a time. `start()` runs a background loop that reads the phone's screen,
    updates `status()` for the setup guide and, in auto mode, taps the next step.
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
            "choice": None, "e2e_was_on": False, "low_storage_ok": False, "free_bytes": None,
            "created": False, "backup_error": "", "fallback": False, "fallback_reason": "", "started_at": now,
        }
        self._last_poll = now
        self._unknown_since = None
        self._last_action = None
        self._same_action = 0
        self._scrolls = {}

    def status(self) -> dict:
        with self._lock:
            self._last_poll = self._clock()
            st = dict(self._state)
        st["steps"] = self._steps(st)
        return st

    def _steps(self, st):
        current = SCREEN_STEP.get(st["screen"], "")
        keys = [k for k, _ in STEPS if k != "turn_off" or st["e2e_was_on"]]
        idx = keys.index(current) if current in keys else -1
        done_all = st["created"] or st["phase"] == "done"
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
            self._loop(phone)
        except Exception as e:  # the guide must never take the server down
            self._set(phase="error", message=f"The guide stopped: {e}")
        finally:
            with self._lock:
                self._state["active"] = False

    def _loop(self, phone):
        # Both modes start by opening WhatsApp: one step less for the user
        phone.launch(self.package)
        launched_at = self._clock()
        self._sleep(SETTLE_SECS)
        while not self._stop.is_set():
            now = self._clock()
            if now - self._last_poll > IDLE_STOP_SECS or now - self._state["started_at"] > MAX_SESSION_SECS:
                self._set(phase="stopped", message="The guide stopped because it was not being watched.")
                return
            foreground = phone.foreground()
            nodes = parse_layout(phone.dump())
            screen = classify(nodes, foreground)
            acted = self._handle(phone, screen, nodes, now, launched_at)
            if screen.name == "other_app" and acted == "launch":
                launched_at = now
            if self._state["phase"] == "done":
                return
            self._sleep(SETTLE_SECS if acted else 0.4)

    def _handle(self, phone, screen: Screen, nodes, now, launched_at):
        st = self._state
        name = screen.name
        warning = ""
        instruction = INSTRUCTIONS.get(name, INSTRUCTIONS["unknown"])
        phase = "running"
        action = None  # ("tap", node) | ("scroll",) | ("back",) | ("launch",)

        # Unrecognised for too long -> manual slides (keeps watching for the key meanwhile)
        if name in ("unknown", "unreadable", "other_app"):
            self._unknown_since = self._unknown_since or now
            if now - self._unknown_since > UNKNOWN_FALLBACK_SECS and not st["fallback"]:
                self._set(fallback=True, fallback_reason="This phone shows a WhatsApp screen the guide does not know yet.")
        else:
            self._unknown_since = None

        if name == "key_shown" and not st["key_captured"]:
            key = screen.info["key"]
            if self._save_key(key):
                self._set(key_captured=True, masked_key=key[:4] + "…" + key[-4:])
        if name == "e2e_on":
            self._set(e2e_was_on=True)

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
        elif name in ("more_options", "key_intro", "turned_off", "menu", "settings"):
            action = ("tap", screen.target) if screen.target else ("scroll",)
        elif name in ("chat_settings", "backup_settings"):
            if name == "backup_settings" and st["created"]:
                if st["backup_error"]:
                    message = (f"Your key is saved, but WhatsApp could not make the backup: “{st['backup_error']}” "
                               "Fix that on the phone (usually: free up storage), then tap Back up in WhatsApp's Chat backup screen.")
                else:
                    message = ("WhatsApp is now making the encrypted backup. Keep the phone connected; "
                               "the sync picks it up when it is ready.")
                self._set(phase="done", screen=name, step="", instruction="", message=message)
                return None
            action = ("tap", screen.target) if screen.target else ("scroll",)
        elif name == "home":
            action = ("tap", screen.target) if screen.target else None
        elif name == "key_shown":
            if self._state["key_captured"]:
                action = ("tap", screen.target)
                instruction = "Key received on this computer. Tap Continue."
            else:
                instruction = "The key could not be read. Long-press it, tap Copy, and use \"Paste key\" below."
        elif name == "popup":
            action = ("back",)
        elif name == "key_confirm":
            if self._state["key_captured"]:
                action = ("tap", screen.target)
            else:
                instruction = "Make sure you have the key (copy it), then tap \"I saved my 64-digit key\"."
        elif name == "create":
            free = st["free_bytes"]
            if free is None:
                free = phone.free_bytes()
                self._set(free_bytes=free)
            if free is not None and free < LOW_STORAGE_BYTES and not st["low_storage_ok"]:
                phase = "low_storage"
                warning = (f"Your phone has only {free / 1024 ** 3:.1f} GB free. WhatsApp may not be able to "
                           "make the backup. Free up some space first, or continue anyway.")
            else:
                action = ("tap", screen.target)
        elif name == "dialog":
            if screen.info.get("message"):
                instruction = f"WhatsApp says: “{screen.info['message']}” Tap OK on the phone."
                if st["created"]:
                    self._set(backup_error=screen.info["message"])
        elif name == "other_app":
            if now - launched_at > 8:
                action = ("launch",)

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
                instruction = "Key received on this computer. Continuing\u2026"
            elif kind == "tap":
                instruction = f"Tapping \u201c{screen.label}\u201d\u2026"
            elif kind == "scroll":
                instruction = f"Scrolling to \u201c{screen.label}\u201d\u2026" if screen.label else "Scrolling\u2026"
            elif kind == "back":
                instruction = "Closing the menu\u2026"
            else:
                instruction = "Opening WhatsApp\u2026"
        self._set(screen=name, step=SCREEN_STEP.get(name, ""), instruction=instruction, warning=warning,
                  phase=phase if st["phase"] not in ("done",) else st["phase"],
                  target=screen.label, message="" if phase == "running" else st["message"])

        if st["mode"] != "auto" or action is None or phase not in ("running",):
            return None
        return self._act(phone, name, action, nodes)

    def _act(self, phone, name, action, nodes):
        kind = action[0]
        signature = (name, kind, action[1].bounds if kind == "tap" and action[1] else None)
        if signature == self._last_action:
            self._same_action += 1
        else:
            self._last_action, self._same_action = signature, 1
        if self._same_action > SAME_ACTION_LIMIT:
            self._set(mode="guide", notice="The app could not move forward on this screen. Please tap it yourself.")
            return None
        if kind == "scroll":
            count = self._scrolls.get(name, 0)
            if count >= 4:
                return None
            self._scrolls[name] = count + 1
            w, h = screen_size(nodes)
            ok, out = phone.swipe(w // 2, int(h * 0.72), w // 2, int(h * 0.38))
        elif kind == "tap":
            if name == "create":
                self._set(created=True)
            ok, out = phone.tap(*action[1].center)
        elif kind == "back":
            ok, out = phone.back()
        else:
            ok, out = phone.launch(self.package), ""
            return "launch"
        if not ok and ("INJECT_EVENTS" in out or "SecurityException" in out):
            if name == "create":
                self._set(created=False)
            self._set(input_allowed=False, mode="guide",
                      notice="This phone does not let apps tap for you. Follow the steps yourself"
                              " (on Xiaomi you can allow it: Developer options › USB debugging (Security settings)).")
            return None
        return kind
