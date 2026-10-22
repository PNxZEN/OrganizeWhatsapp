"""
Records how WhatsApp's end-to-end encrypted backup setup looks on a real phone, so the setup
guide can follow the user's screen and open WhatsApp for them (instead of 12 static slides).

Run it once while you go through the setup on your phone, then send the report file:

    python scripts/record_e2e_flow.py                  (from the repository folder)
    python scripts/record_e2e_flow.py --adb PATH       (if adb is not found by itself)
    python scripts/record_e2e_flow.py --no-text        (keep no on-screen text at all)
    python scripts/record_e2e_flow.py --include-home   (also the home screen, tabs and account page)

What it records, every time the phone shows a different screen:
- the Android screen (activity) name, e.g. com.whatsapp/.settings.SettingsChat
- the layout: element ids, types, which ones are tappable, and their position
- on WhatsApp settings / backup screens only: button and menu labels that contain a known
  setup word ("Chats", "Chat backup", "Continue", "64-digit"...), with every digit masked.
  Any other text (your profile name, Google account, sizes) becomes <text>.
- whether the 64-digit key can be read from the screen (yes/no only; the key is never stored)

What it never records: chat lists, conversations, contact names, messages, media, your key.
Screens outside the backup settings are reduced to ids and layout, with no text at all.
Nothing is written on the phone except a temporary layout file that is deleted at once (and only
on phones that cannot send it over the cable directly).

The report is saved next to where you run this. Open it and check it before you send it.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POLL_SECS = 0.7
SETTINGS_SCREEN_RE = re.compile(r"(setting|backup|encrypt|e2e|passkey|password|key)", re.I)
# Screens that show contacts or personal details even though they sit near the settings
PRIVATE_CLASS_RE = re.compile(r"(Profile|Contact|Conversation|Status|Call|Community|Camera|Gallery|Media)", re.I)
HEX4_RE = re.compile(r"\b[0-9a-fA-F]{4}\b")
KEY64_RE = re.compile(r"[0-9a-fA-F]{64}")
MAX_LABEL_CHARS = 48
# Words of the setup screens' buttons and menus (English). Labels without one of them are not kept.
KNOWN_LABEL_WORDS = (
    "setting", "chat", "backup", "back up", "encrypt", "end-to-end", "64-digit", "digit", "key", "passkey",
    "password", "more options", "option", "generate", "continue", "create", "turn on", "turn off", "next",
    "done", "cancel", "ok", "copy", "saved", "account", "privacy", "storage", "notification", "help",
    "google", "frequency", "daily", "weekly", "monthly", "never", "include video", "cellular", "wi-fi",
)


# ---------------------------------------------------------------- adb

def find_adb(explicit=None):
    candidates = [explicit] if explicit else []
    exe = "adb.exe" if sys.platform == "win32" else "adb"
    candidates += [str(ROOT / "bin" / "platform-tools" / exe), shutil.which("adb")]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(os.path.join(local, "Android", "Sdk", "platform-tools", "adb.exe"))
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


class Phone:
    def __init__(self, adb, serial=None):
        self.base = [adb] + (["-s", serial] if serial else [])

    def run(self, *args, timeout=15, binary=False):
        res = subprocess.run(self.base + list(args), capture_output=True, timeout=timeout)
        out = res.stdout if binary else res.stdout.decode("utf-8", errors="replace")
        return res.returncode, out

    def shell(self, command, timeout=15):
        return self.run("shell", command, timeout=timeout)[1]


def ready_devices(adb):
    out = subprocess.run([adb, "devices"], capture_output=True, text=True, timeout=10).stdout
    lines = [l.split() for l in out.splitlines()[1:] if l.strip()]
    return [l[0] for l in lines if len(l) >= 2 and l[1] == "device"], lines


# ---------------------------------------------------------------- parsing (pure, unit tested)

def parse_foreground(text):
    """The resumed activity "pkg/.Activity" from dumpsys activity / window output, or ""."""
    for pattern in (r"topResumedActivity[=:].*?\s([\w.]+/[\w.$]+)",
                    r"mResumedActivity[=:].*?\s([\w.]+/[\w.$]+)",
                    r"ResumedActivity[=:].*?\s([\w.]+/[\w.$]+)",
                    r"mCurrentFocus=.*?\s([\w.]+/[\w.$]+)",
                    r"mFocusedApp=.*?\s([\w.]+/[\w.$]+)"):
        m = re.search(pattern, text or "")
        if m:
            return m.group(1)
    return ""


def is_settings_screen(activity):
    """True for WhatsApp settings / backup screens (labels may be kept), never for chats or contacts."""
    activity = activity or ""
    cls = activity.split("/")[-1].split(".")[-1]
    if PRIVATE_CLASS_RE.search(cls.replace("Settings", "")):
        return False
    return bool(SETTINGS_SCREEN_RE.search(activity))


def mask_label(text):
    """A button / menu label with anything personal masked."""
    t = (text or "").strip()
    if not t:
        return ""
    if "@" in t:
        return "<email>"
    if KEY64_RE.search(t.replace(" ", "")):
        return "<key>"
    t = HEX4_RE.sub("<HEX4>", t) if len(HEX4_RE.findall(t)) >= 2 or re.fullmatch(r"[0-9a-fA-F]{4}", t) else t
    t = re.sub(r"\d+", "#", t)
    if len(t) > MAX_LABEL_CHARS:
        return f"<long text, {len(t)} chars>"
    if not any(w in t.lower() for w in KNOWN_LABEL_WORDS):
        return "<text>"
    return t


# Home / tab / account pages (--include-home): only these exact button words are kept, so a chat
# or contact name can never end up in the report, whatever it is called
HOME_WORDS = {
    "settings", "chats", "updates", "communities", "calls", "you", "account", "profile", "status",
    "more options", "new group", "new community", "broadcast lists", "linked devices", "starred",
    "starred messages", "payments", "read all", "search", "camera", "new chat", "archived", "lists",
    "favourites", "favorites", "unread", "groups", "all", "help", "privacy", "avatar", "notifications",
    "storage and data", "app language", "invite a friend", "app updates", "meta ai",
}


def mask_strict(text):
    t = (text or "").strip()
    if not t:
        return ""
    head = t.split(",")[0].strip().lower()  # tabs read like "Settings, tab 5 of 5"
    return t if head in HOME_WORDS and not re.search(r"\d{3,}|@", t) else "<text>"


def key_visibility(nodes_text):
    """How much of a 64-digit key the screen shows: (hex blocks of 4, a full 64-hex string seen)."""
    blocks = 0
    full = False
    for t in nodes_text:
        compact = (t or "").replace(" ", "").replace("\n", "")
        if KEY64_RE.search(compact):
            full = True
        if re.fullmatch(r"[0-9a-fA-F]{4}", (t or "").strip()):
            blocks += 1
        elif len(HEX4_RE.findall(t or "")) >= 16:
            full = True
    return blocks, full or blocks >= 16


def summarize_layout(xml_text, keep_text, strict=False):
    """Layout without personal data: ids, classes, tappable, bounds, masked labels if allowed."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    nodes, texts = [], []
    for n in root.iter("node"):
        a = n.attrib
        text = a.get("text", "")
        desc = a.get("content-desc", "")
        texts.extend([text, desc])
        item = {
            "id": a.get("resource-id", ""),
            "class": a.get("class", "").split(".")[-1],
            "clickable": a.get("clickable") == "true",
            "bounds": a.get("bounds", ""),
        }
        if a.get("package"):
            item["package"] = a.get("package")
        if keep_text:
            mask = mask_strict if strict else mask_label
            if text:
                item["text"] = mask(text)
            if desc:
                item["desc"] = mask(desc)
        else:
            item["has_text"] = bool(text or desc)
        nodes.append(item)
    blocks, readable = key_visibility(texts)
    ids = sorted({n["id"] for n in nodes if n["id"]})
    return {"nodes": nodes, "ids": ids, "key_hex_blocks_visible": blocks, "key_readable_from_screen": readable}


def resolver_candidates(dumpsys_text, package):
    """
    Activities of `package` that other apps (and adb) may open, with their actions, from the
    "Activity Resolver Table" of `dumpsys package`. Receivers and services are ignored.
    """
    found = {}
    in_activities = False
    current = None
    for line in (dumpsys_text or "").splitlines():
        if line.strip().endswith("Resolver Table:"):
            in_activities = line.strip() == "Activity Resolver Table:"
            current = None
            continue
        if line and not line[0].isspace():  # next top-level section
            in_activities = False
            current = None
            continue
        if not in_activities:
            continue
        m = re.search(r"\s([\w.]+/[\w.$]+)\s+filter", line)
        if m:
            current = m.group(1) if m.group(1).startswith(package + "/") else None
            if current:
                found.setdefault(current, set())
            continue
        a = re.search(r'Action: "([^"]+)"', line)
        if a and current:
            found[current].add(a.group(1))
    return {k: sorted(v) for k, v in found.items()}


# ---------------------------------------------------------------- capture

def dump_layout(phone):
    """The current screen's layout XML, streamed over the cable when possible."""
    code, out = phone.run("exec-out", "uiautomator", "dump", "/dev/tty", timeout=20)
    if "<hierarchy" in out:
        return out[out.index("<hierarchy"):out.rindex("</hierarchy>") + len("</hierarchy>")], "tty"
    tmp = "/data/local/tmp/wa_layout_probe.xml"
    phone.shell(f"uiautomator dump {tmp}", timeout=20)
    _, out = phone.run("exec-out", "cat", tmp, timeout=20)
    phone.shell(f"rm -f {tmp}")
    if "<hierarchy" in out:
        return out[out.index("<hierarchy"):out.rindex("</hierarchy>") + len("</hierarchy>")], "file"
    return "", "failed"


def foreground(phone):
    for cmd in ("dumpsys activity activities | grep -E 'topResumedActivity|mResumedActivity|ResumedActivity'",
                "dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'"):
        act = parse_foreground(phone.shell(cmd))
        if act:
            return act, cmd.split("|")[0].strip()
    return "", ""


def device_info(phone, package):
    prop = lambda k: phone.shell(f"getprop {k}").strip()
    pkg_dump = phone.shell(f"dumpsys package {package}", timeout=30)
    version = re.search(r"versionName=(\S+)", pkg_dump)
    return {
        "manufacturer": prop("ro.product.manufacturer"),
        "brand": prop("ro.product.brand"),
        "model": prop("ro.product.model"),
        "android": prop("ro.build.version.release"),
        "sdk": prop("ro.build.version.sdk"),
        "rom": prop("ro.build.display.id")[:60],
        "language": prop("persist.sys.locale") or prop("ro.product.locale"),
        "package": package,
        "whatsapp_version": version.group(1) if version else "",
    }, pkg_dump


def try_open(phone, component):
    _, out = phone.run("shell", "am", "start", "-W", "-n", component, timeout=20)
    if "Permission Denial" in out or "not exported" in out:
        return "denied"
    if "Error" in out or "Exception" in out:
        return "error: " + out.strip().splitlines()[-1][:120]
    return "opened"


def ask(question):
    try:
        return input(question).strip().lower() in ("y", "yes")
    except EOFError:
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--adb", help="path to adb")
    ap.add_argument("--serial", help="phone serial, when several are connected")
    ap.add_argument("--package", default="com.whatsapp", help="com.whatsapp (default) or com.whatsapp.w4b")
    ap.add_argument("--no-text", action="store_true", help="keep no on-screen text at all")
    ap.add_argument("--include-home", action="store_true",
                    help="also record the layout of WhatsApp's home screen, tabs and account page (button words only)")
    ap.add_argument("--out", help="report file (default: e2e_recording_<model>_<time>.json)")
    args = ap.parse_args(argv)

    adb = find_adb(args.adb)
    if not adb:
        print("adb not found. Pass it with --adb, e.g. --adb \"C:\\path\\to\\platform-tools\\adb.exe\"")
        return 2
    serials, lines = ready_devices(adb)
    if args.serial:
        serials = [s for s in serials if s == args.serial]
    if len(serials) != 1:
        print("Connect exactly one phone with USB debugging allowed (adb devices shows):")
        for l in lines:
            print("   ", " ".join(l))
        return 2
    phone = Phone(adb, serials[0])

    info, pkg_dump = device_info(phone, args.package)
    if not info["whatsapp_version"]:
        print(f"{args.package} is not installed on this phone.")
        return 2
    print(f"Phone: {info['manufacturer']} {info['model']}, Android {info['android']}, "
          f"WhatsApp {info['whatsapp_version']}, language {info['language'] or '?'}")

    report = {"recorded_at": datetime.now().isoformat(timespec="seconds"), "device": info,
              "keep_text": not args.no_text, "screens": [], "open_tests": {}, "notes": []}

    candidates = resolver_candidates(pkg_dump, args.package)
    interesting = {k: v for k, v in candidates.items() if SETTINGS_SCREEN_RE.search(k.split("/")[-1])}
    report["openable_settings_activities"] = interesting
    report["openable_activity_count"] = len(candidates)
    print(f"Found {len(interesting)} WhatsApp settings/backup screen(s) that other apps may open.")

    if ask("Test whether the app can open WhatsApp (and its backup screens) for the user? "
           "Your phone will switch screens a few times. [y/N] "):
        _, out = phone.run("shell", "monkey", "-p", args.package, "-c", "android.intent.category.LAUNCHER", "1")
        report["open_tests"]["launch_whatsapp"] = "opened" if "Events injected: 1" in out else out.strip()[-120:]
        time.sleep(2)
        for comp in sorted(interesting):
            report["open_tests"][comp] = try_open(phone, comp)
            print(f"   {comp}: {report['open_tests'][comp]}")
            time.sleep(2)
            phone.shell("input keyevent KEYCODE_BACK")
            time.sleep(1)
        home = phone.shell("input keyevent KEYCODE_HOME")
        # Xiaomi blocks simulated taps unless "USB debugging (Security settings)" is on
        report["input_injection_allowed"] = "SecurityException" not in home and "INJECT_EVENTS" not in home

    print()
    print("Now go through the backup setup on your phone, exactly as the setup guide shows:")
    print("  WhatsApp > Settings > Chats > Chat backup > End-to-end encrypted backup > ...")
    print("  ... > Use 64-digit encryption key > Generate > (Continue, confirm, Create).")
    print("Take your time. Each new screen is recorded automatically.")
    print("If a screen changes but nothing is printed, press Enter to record it anyway.")
    print("Type q and press Enter when you are done.\n")

    stop = threading.Event()
    force = threading.Event()

    def read_keys():
        while not stop.is_set():
            try:
                line = input()
            except EOFError:
                stop.set()
                return
            if line.strip().lower() == "q":
                stop.set()
            else:
                force.set()

    threading.Thread(target=read_keys, daemon=True).start()
    last_signature = None
    started = time.time()
    try:
        while not stop.is_set():
            act, method = foreground(phone)
            report.setdefault("foreground_method", method)
            own_app = act.startswith(args.package + "/")
            settings = own_app and is_settings_screen(act)
            home = own_app and args.include_home and bool(re.search(r"(HomeActivity|\.Main)$", act))
            if own_app and not settings and not home and not force.is_set():
                # Chat list, conversations, etc.: record only that the screen was visited
                signature = ("private", act)
                if signature != last_signature:
                    last_signature = signature
                    report["screens"].append({"t": round(time.time() - started, 1), "activity": act,
                                              "recorded": "name only (private screen)"})
                    print(f"  [{len(report['screens']):>2}] {act}  (name only)")
                time.sleep(POLL_SECS)
                continue
            if not own_app and not force.is_set():
                time.sleep(POLL_SECS)
                continue
            t0 = time.time()
            xml_text, dump_method = dump_layout(phone)
            report.setdefault("layout_method", dump_method)
            layout = summarize_layout(xml_text, keep_text=(settings or home) and not args.no_text,
                                      strict=home and not settings) if xml_text else None
            signature = (act, tuple(layout["ids"]) if layout else (), len(layout["nodes"]) if layout else 0)
            if signature != last_signature or force.is_set():
                forced = force.is_set()
                force.clear()
                last_signature = signature
                entry = {"t": round(time.time() - started, 1), "activity": act, "forced": forced,
                         "dump_ms": int((time.time() - t0) * 1000), "layout": layout}
                if layout is None:
                    entry["note"] = "layout could not be read on this screen"
                report["screens"].append(entry)
                key = "  KEY READABLE" if layout and layout["key_readable_from_screen"] else ""
                print(f"  [{len(report['screens']):>2}] {act}  ({len(layout['nodes']) if layout else 0} elements){key}")
            time.sleep(POLL_SECS)
    except KeyboardInterrupt:
        pass
    stop.set()

    report["key_readable_on_any_screen"] = any(
        s.get("layout") and s["layout"]["key_readable_from_screen"] for s in report["screens"])
    model = re.sub(r"[^\w-]+", "_", info["model"] or "phone")
    out = Path(args.out or f"e2e_recording_{model}_{datetime.now():%Y%m%d_%H%M%S}.json")
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved {len(report['screens'])} screens to {out.resolve()}")
    print("Please open it and check it before sending. It contains no messages, contacts or key.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
