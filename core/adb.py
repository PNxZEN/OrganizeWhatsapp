"""
WhatsApp Media Organizer - Android Debug Bridge (ADB) Engine.
Handles device detection, authorization status checking, base path discovery,
incremental streaming tar pull, and folder synchronization.
"""

import functools
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
from datetime import datetime
from pathlib import Path

from core.config import load_config, to_long_path
from core.organizer import normalize_filename


def find_adb_binary(custom_path=None):
    """
    Locates the adb executable on the system.
    Checks custom path, bundled local platform-tools, system PATH, and local Android SDK.
    """
    if custom_path and os.path.isfile(custom_path):
        return custom_path

    # Check bundled local directories relative to application root
    app_root = Path(__file__).resolve().parent.parent
    exe_name = "adb.exe" if sys.platform == "win32" else "adb"
    bundled_candidates = [
        app_root / "bin" / "platform-tools" / exe_name,
        app_root / "platform-tools" / exe_name,
        app_root / "bin" / exe_name,
    ]
    for candidate in bundled_candidates:
        if candidate.is_file():
            return str(candidate)

    found = shutil.which("adb")
    if found:
        return found

    # Windows fallback to AppData Android SDK
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if local_appdata:
        candidate = os.path.join(
            local_appdata, "Android", "Sdk", "platform-tools", "adb.exe"
        )
        if os.path.isfile(candidate):
            return candidate

    return "adb"


def _terminate_adb_proc(proc, timeout=15):
    """Best-effort terminate of an ADB exec-out process so workers cannot hang on a stuck pipe."""
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=timeout)
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass


class DeviceStatus(tuple):
    """
    Subclass of 5-element tuple (connected, authorized, error_message, device_serial, model)
    for 100% backward compatibility, with an extra attribute usb_debugging (bool).
    """

    def __new__(cls, connected, authorized, error_message, device_serial, model, usb_debugging=True,
                stage=None, vendor=""):
        obj = super().__new__(cls, (connected, authorized, error_message, device_serial, model))
        obj.connected = connected
        obj.authorized = authorized
        obj.error_message = error_message
        obj.device_serial = device_serial
        obj.model = model
        obj.usb_debugging = usb_debugging
        obj.stage = stage or _default_stage(connected, authorized, usb_debugging)
        obj.vendor = vendor
        return obj


# Where the user is in getting the phone connected (drives the setup guide's checklist)
STAGE_UNPLUGGED = "unplugged"          # no phone seen at all
STAGE_USB_ONLY = "usb_only"            # phone on USB, but ADB cannot see it: USB debugging is off
STAGE_NO_ADB = "no_adb"                # phone on USB, but the ADB program itself is missing
STAGE_NO_PERMISSION = "no_permission"  # Linux: ADB sees the phone but may not open it (udev rules)
STAGE_UNAUTHORIZED = "unauthorized"    # waiting for "Allow USB debugging?" on the phone
STAGE_OFFLINE = "offline"              # ADB sees the phone but it does not answer
STAGE_READY = "ready"


def _default_stage(connected, authorized, usb_debugging):
    if connected and authorized:
        return STAGE_READY
    if connected:
        return STAGE_UNAUTHORIZED if usb_debugging else STAGE_USB_ONLY
    return STAGE_UNPLUGGED


ANDROID_USB_VIDS = {
    "18d1": "Google",
    "04e8": "Samsung",
    "22d9": "Oppo",
    "2a70": "OnePlus",
    "1eb7": "OnePlus",
    "2717": "Xiaomi",
    "2b4c": "Vivo",
    "12d1": "Huawei",
    "0bb4": "HTC",
    "17ef": "Lenovo",
    "22b8": "Motorola",
    "0fce": "Sony",
    "0b05": "Asus",
    "1949": "Amazon",
    "29a9": "Realme",
    "3318": "Nothing",
    "35bf": "Nothing",
    "2ae5": "Infinix",
    "1bbb": "TCL",
    "20a0": "Fairphone",
    "1004": "LG",
}

NON_PHONE_PERIPHERAL_KEYWORDS = [
    "bluetooth",
    "adapter",
    "wireless",
    "wi-fi",
    "wifi",
    "ethernet",
    "network",
    "audio",
    "sound",
    "speaker",
    "headset",
    "headphones",
    "earphone",
    "earbuds",
    "buds",
    "keyboard",
    "mouse",
    "camera",
    "webcam",
    "hub",
    "controller",
    "touchpad",
    "trackpad",
    "hid",
    "receiver",
    "dongle",
    "composite device",
    "mass storage",
    "flash drive",
]


def _android_usb_entry(vid: str, name: str, serial: str = "", instance_id: str = ""):
    """The detection entry for one USB device, or None when it is not an Android phone."""
    vid = (vid or "").lower()
    name_lower = (name or "").lower()
    # Exclude known PC peripherals, Bluetooth adapters, sound cards, etc.
    if any(kw in name_lower for kw in NON_PHONE_PERIPHERAL_KEYWORDS):
        return None
    vendor = ANDROID_USB_VIDS.get(vid, "")
    is_phone_name = any(
        k in name_lower
        for k in ["android", "pixel", "phone", "mobile", "mtp", "galaxy", "oneplus", "xiaomi", "redmi", "poco"]
    )
    if not (vendor or is_phone_name):
        return None
    return {
        "name": name or (f"{vendor} Device" if vendor else "Android Device"),
        "vendor": vendor,
        "serial": serial,
        "instance_id": instance_id,
    }


def parse_linux_usb_devices(sys_root: str = "/sys/bus/usb/devices") -> list[dict]:
    """Android phones among the USB devices Linux lists in sysfs (no permissions needed)."""
    def read(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return ""

    matches = []
    root = Path(sys_root)
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return []
    for dev in entries:
        vid = read(dev / "idVendor")
        if not vid or ":" in dev.name:  # interfaces ("1-2:1.0") have no idVendor of their own
            continue
        if read(dev / "bDeviceClass") == "09":  # USB hub
            continue
        name = " ".join(x for x in (read(dev / "manufacturer"), read(dev / "product")) if x)
        entry = _android_usb_entry(vid, name, read(dev / "serial"), dev.name)
        if entry:
            matches.append(entry)
    return matches


def parse_macos_ioreg(text: str) -> list[dict]:
    """Android phones in the output of `ioreg -p IOUSB -l -w0`."""
    matches = []
    blocks = re.split(r"\n(?=[ |]*\+-o )", "\n" + (text or ""))
    for block in blocks:
        m = re.search(r'"idVendor" = (\d+)', block)
        if not m:
            continue
        if re.search(r'"bDeviceClass" = 9\b', block):  # USB hub
            continue
        vid = format(int(m.group(1)), "04x")

        def prop(key):
            pm = re.search(r'"' + re.escape(key) + r'" = "([^"]*)"', block)
            return pm.group(1) if pm else ""

        # Older macOS: "USB Vendor Name"; newer: "kUSBVendorString" (same for product / serial)
        vendor_name = prop("USB Vendor Name") or prop("kUSBVendorString")
        product_name = prop("USB Product Name") or prop("kUSBProductString")
        name = " ".join(x for x in (vendor_name, product_name) if x)
        entry = _android_usb_entry(vid, name, prop("USB Serial Number") or prop("kUSBSerialNumberString"))
        if entry:
            matches.append(entry)
    return matches


def detect_usb_android_hardware() -> list[dict]:
    """
    Detects an Android phone physically connected over USB, even while USB debugging / ADB is
    turned off: Windows PnP (cfgmgr32), Linux sysfs or macOS ioreg. No extra tools needed.
    Excludes internal PC components (Bluetooth, Wi-Fi, audio) and USB peripherals.
    """
    if sys.platform.startswith("linux"):
        return parse_linux_usb_devices()
    if sys.platform == "darwin":
        try:
            res = subprocess.run(["ioreg", "-p", "IOUSB", "-l", "-w0"], capture_output=True,
                                 text=True, timeout=3, check=False)
            return parse_macos_ioreg(res.stdout) if res.returncode == 0 else []
        except Exception:
            return []
    if sys.platform != "win32":
        return []

    try:
        import ctypes
        import re
        from ctypes import wintypes

        cfgmgr32 = ctypes.windll.cfgmgr32
        CR_SUCCESS = 0
        CM_GETIDLIST_FILTER_PRESENT = 0x100

        buf_len = wintypes.ULONG()
        ret = cfgmgr32.CM_Get_Device_ID_List_SizeW(ctypes.byref(buf_len), "USB", CM_GETIDLIST_FILTER_PRESENT)
        if ret != CR_SUCCESS:
            return []

        buf = ctypes.create_unicode_buffer(buf_len.value)
        ret = cfgmgr32.CM_Get_Device_ID_ListW("USB", buf, buf_len.value, CM_GETIDLIST_FILTER_PRESENT)
        if ret != CR_SUCCESS:
            return []

        dev_ids = [s for s in buf[:].split("\x00") if s]
        matches = []
        for dev_id in dev_ids:
            dev_id_lower = dev_id.lower()
            # Skip composite sub-interfaces (&MI_00, etc.)
            if "&mi_" in dev_id_lower:
                continue

            m = re.search(r"vid_([0-9a-f]{4})&pid_([0-9a-f]{4})", dev_id_lower)
            if not m:
                continue
            vid = m.group(1)

            dev_inst = wintypes.DWORD()
            name = ""
            if cfgmgr32.CM_Locate_DevNodeW(ctypes.byref(dev_inst), dev_id, 0) == CR_SUCCESS:
                prop_buf = ctypes.create_unicode_buffer(512)
                prop_len = wintypes.ULONG(ctypes.sizeof(prop_buf))
                # CM_DRP_FRIENDLYNAME = 13
                if (
                    cfgmgr32.CM_Get_DevNode_Registry_PropertyW(
                        dev_inst, 13, None, prop_buf, ctypes.byref(prop_len), 0
                    )
                    == CR_SUCCESS
                ):
                    name = prop_buf.value
                else:
                    # CM_DRP_DEVICEDESC = 1
                    prop_len = wintypes.ULONG(ctypes.sizeof(prop_buf))
                    if (
                        cfgmgr32.CM_Get_DevNode_Registry_PropertyW(
                            dev_inst, 1, None, prop_buf, ctypes.byref(prop_len), 0
                        )
                        == CR_SUCCESS
                    ):
                        name = prop_buf.value

            parts = dev_id.split("\\")
            serial = parts[2] if len(parts) > 2 and "&" not in parts[2] else ""
            entry = _android_usb_entry(vid, name, serial, dev_id)
            if entry:
                matches.append(entry)
        return matches
    except Exception:
        return []


def check_adb_device(adb_path=None):
    """
    Checks if an Android device is connected and authorized.
    First checks ADB daemon. If ADB returns no devices, checks the physical USB devices.
    Returns: DeviceStatus(connected, authorized, error_message, device_serial, model, usb_debugging),
    with .stage (STAGE_*) saying which setup step the user is on.
    """
    cmd = find_adb_binary(adb_path)
    device_lines = []
    adb_err = ""
    try:
        res = subprocess.run([cmd, "devices", "-l"], capture_output=True, text=True, timeout=5, check=False)
        if res.returncode == 0:
            lines = [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]
            device_lines = [l for l in lines[1:] if not l.startswith("*")]
        else:
            adb_err = f"ADB execution failed: {res.stderr.strip()}"
    except subprocess.TimeoutExpired:
        adb_err = "ADB communication timed out."
    except Exception as e:
        adb_err = f"Failed to execute ADB: {e}"

    # 1. If ADB detected devices, return ADB status
    if device_lines:
        for dev in device_lines:
            parts = dev.split()
            if len(parts) >= 2:
                serial = parts[0]
                status = parts[1]

                # Extract model if available
                model = ""
                for p in parts[2:]:
                    if p.startswith("model:"):
                        model = p.split("model:", 1)[1]
                        break

                if status == "device":
                    return DeviceStatus(True, True, "", serial, model, usb_debugging=True)
                elif status in ("unauthorized", "authorizing"):
                    return DeviceStatus(
                        True,
                        False,
                        "Device detected but UNAUTHORIZED. Check your phone screen and tap 'Allow USB debugging'.",
                        serial,
                        model,
                        usb_debugging=True,
                    )
                elif status == "offline":
                    return DeviceStatus(True, False, "Device is offline or sleeping.", serial, model,
                                        usb_debugging=True, stage=STAGE_OFFLINE)
                elif status == "no" and "permission" in dev:
                    return DeviceStatus(True, False, "ADB is not allowed to open the phone (USB permissions).",
                                        serial, model, usb_debugging=True, stage=STAGE_NO_PERMISSION)

    # 2. ADB found no active devices. Check if phone is physically plugged in via Windows USB PnP!
    usb_hw = detect_usb_android_hardware()
    if usb_hw:
        first_dev = usb_hw[0]
        dev_name = first_dev.get("name") or first_dev.get("vendor") or "Android Device"
        serial = first_dev.get("serial") or ""
        vendor = first_dev.get("vendor") or ""
        if adb_err.startswith("Failed to execute ADB"):
            msg = f"Phone connected via USB ({dev_name}), but the ADB program is missing."
            return DeviceStatus(True, False, msg, serial, dev_name, usb_debugging=False,
                                stage=STAGE_NO_ADB, vendor=vendor)
        msg = f"Phone connected via USB ({dev_name}), but USB Debugging is turned OFF. Please enable Developer Options > USB Debugging."
        return DeviceStatus(True, False, msg, serial, dev_name, usb_debugging=False, vendor=vendor)

    err = adb_err or "No Android device detected. Please connect phone via USB."
    return DeviceStatus(False, False, err, "", "", usb_debugging=True)


def wait_for_adb_device(
    adb_path=None,
    timeout=60,
    poll_interval=2,
    status_callback=None,
):
    """
    Polls ADB device state until device is connected and authorized, or timeout occurs.
    Displays clear guidance if unauthorized. Resolves TODO Item 1.
    Returns: (ready: bool, message: str, serial: str, model: str)
    """
    cmd = find_adb_binary(adb_path)
    start_time = time.time()
    last_status = None
    notified_unauthorized = False

    while time.time() - start_time < timeout:
        connected, authorized, err_msg, serial, model = check_adb_device(cmd)
        elapsed = int(time.time() - start_time)
        remaining = max(0, timeout - elapsed)

        if connected and authorized:
            if status_callback:
                status_callback(
                    {
                        "status": "device",
                        "serial": serial,
                        "model": model,
                        "message": f"Device ready: {model or serial}",
                    }
                )
            return True, f"Device ready: {model or serial}", serial, model

        current_status = "unauthorized" if connected else "disconnected"

        if connected and not authorized:
            prompt_msg = (
                "Device detected but UNAUTHORIZED. "
                "Please unlock your phone and tap 'Allow USB debugging' on the screen."
            )
            if not notified_unauthorized:
                sys.stderr.write(f"\n[ADB] Action Required: {prompt_msg}\n")
                sys.stderr.write(f"[ADB] Waiting up to {remaining} seconds for authorization...\n")
                notified_unauthorized = True

            if status_callback:
                status_callback(
                    {
                        "status": "unauthorized",
                        "serial": serial,
                        "model": model,
                        "remaining_seconds": remaining,
                        "message": prompt_msg,
                    }
                )
        else:
            # If offline, attempt adb reconnect
            if "offline" in err_msg.lower():
                try:
                    subprocess.run([cmd, "reconnect"], capture_output=True, timeout=5, check=False)
                except Exception:
                    pass

            if status_callback:
                status_callback(
                    {
                        "status": "disconnected",
                        "serial": "",
                        "model": "",
                        "remaining_seconds": remaining,
                        "message": err_msg or "Connecting to Android device...",
                    }
                )

        last_status = current_status
        time.sleep(poll_interval)

    timeout_msg = f"Timed out after {timeout} seconds waiting for authorized ADB device."
    if status_callback:
        status_callback(
            {
                "status": "timeout",
                "serial": "",
                "model": "",
                "remaining_seconds": 0,
                "message": timeout_msg,
            }
        )
    return False, timeout_msg, "", ""


def cleanup_nested_databases_folder(dest_db="./Databases"):
    """
    Detects and fixes redundant nested dest_db/Databases folders created by legacy adb pull (BUG-02 fix).
    Moves any valid database files up into dest_db and removes the redundant directory.
    Returns the number of files moved.
    """
    base = Path(dest_db).resolve()
    nested = base / "Databases"
    if not nested.is_dir():
        return 0

    moved_count = 0
    try:
        for p in nested.iterdir():
            target = base / p.name
            if not target.exists():
                shutil.move(str(p), str(target))
                moved_count += 1
            elif target.stat().st_size < p.stat().st_size:
                # Target is smaller or partial: overwrite with larger one
                target.unlink()
                shutil.move(str(p), str(target))
                moved_count += 1
            else:
                if p.is_file():
                    p.unlink()

        # Remove now-empty nested directory
        try:
            nested.rmdir()
        except OSError:
            shutil.rmtree(str(nested), ignore_errors=True)
    except Exception as e:
        sys.stderr.write(f"[ADB] Warning: Failed to clean up nested Databases folder: {e}\n")

    return moved_count



def parse_parcel_phone_number(output_text: str) -> str:
    """
    Parses a valid phone number string from Android 'service call iphonesubinfo' Parcel output.
    Handles UTF-16 character streams separated by null bytes in Android dumps.
    """
    if not output_text or "Parcel" not in output_text:
        return ""

    chars = []
    for match in re.finditer(r"'([^']*)'", output_text):
        chunk = match.group(1)
        for ch in chunk:
            if ch.isdigit() or ch == "+":
                chars.append(ch)
    cand = "".join(chars).strip()
    m = re.search(r"(\+?\d{10,15})", cand)
    if m:
        num = m.group(1)
        # Avoid ICCID / SIM serial numbers (16-20 digits starting with 89)
        if len(num) > 15 or (len(num) >= 15 and num.startswith("89")):
            return ""
        if not num.startswith("+") and len(num) >= 10:
            num = f"+{num}"
        return num
    return ""


def get_device_sim_phone_numbers(adb_path=None, device_serial=None) -> list:
    """
    Extracts active SIM phone numbers from Android telephony service, siminfo, or iphonesubinfo.
    Returns a list of clean phone number strings (e.g. ['+919876543210']).
    """
    cmd = find_adb_binary(adb_path)
    adb_base = [cmd, "-s", device_serial] if device_serial else [cmd]
    sim_numbers = []

    # 1. Probe content://telephony/siminfo
    try:
        res = subprocess.run(
            adb_base + ["shell", "content query --uri content://telephony/siminfo --projection number"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
        if res.returncode == 0 and res.stdout:
            for line in res.stdout.splitlines():
                m = re.search(r"number=([+0-9]{10,16})", line)
                if m:
                    num = m.group(1).strip()
                    if not num.startswith("+") and len(num) >= 10:
                        num = f"+{num}"
                    if num not in sim_numbers:
                        sim_numbers.append(num)
    except Exception:
        pass

    # 2. Probe dumpsys telephony.registry
    if not sim_numbers:
        try:
            res = subprocess.run(
                adb_base + ["shell", "dumpsys telephony.registry"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
                encoding="utf-8",
                errors="replace",
            )
            if res.returncode == 0 and res.stdout:
                for line in res.stdout.splitlines():
                    if "mLine1Number" in line:
                        m = re.search(r"mLine1Number=([+0-9]{10,16})", line)
                        if m:
                            num = m.group(1).strip()
                            if not num.startswith("+") and len(num) >= 10:
                                num = f"+{num}"
                            if num not in sim_numbers:
                                sim_numbers.append(num)
        except Exception:
            pass

    # 3. Probe service call iphonesubinfo (IPC to telephony manager for line1 number)
    if not sim_numbers:
        for code in (16, 15, 17, 18):
            for sub_arg in ("", " i32 1", " i32 2", " i32 0"):
                try:
                    res = subprocess.run(
                        adb_base + ["shell", f"service call iphonesubinfo {code}{sub_arg}"],
                        capture_output=True,
                        text=True,
                        timeout=3,
                        check=False,
                        encoding="utf-8",
                        errors="replace",
                    )
                    if res.returncode == 0 and res.stdout:
                        num = parse_parcel_phone_number(res.stdout)
                        if num and num not in sim_numbers:
                            sim_numbers.append(num)
                            break
                except Exception:
                    pass
            if sim_numbers:
                break

    return sim_numbers


def get_registered_whatsapp_accounts(adb_path=None, device_serial=None) -> list:
    """
    Queries Android AccountManager via 'dumpsys account' to extract registered phone numbers
    and user profile IDs for com.whatsapp and com.whatsapp.w4b.
    Execution time: <50 ms.
    """
    cmd = find_adb_binary(adb_path)
    adb_base = [cmd, "-s", device_serial] if device_serial else [cmd]
    try:
        res = subprocess.run(
            adb_base + ["shell", "dumpsys", "account"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
        if res.returncode != 0 or not res.stdout:
            return []

        accounts = []
        current_user_id = "0"
        for line in res.stdout.splitlines():
            line = line.strip()
            user_match = re.search(r"UserInfo\{(\d+):", line)
            if user_match:
                current_user_id = user_match.group(1)
                continue

            acc_match = re.search(
                r"Account\s*\{\s*name\s*[=:]\s*[\"']?([^,\"'}\r\n]+?)[\"']?\s*,\s*type\s*[=:]\s*[\"']?(com\.whatsapp(?:\.w4b)?)[\"']?\s*\}",
                line,
            )
            if acc_match:
                raw_name = acc_match.group(1).strip("\"'")
                pkg = acc_match.group(2)
                phone_display = ""
                # Only treat raw_name as phone number if it contains valid digits
                clean_digits = re.sub(r"\D", "", raw_name)
                if (
                    len(clean_digits) >= 10
                    and raw_name.lower() not in ("whatsapp", "whatsapp business", "whatsapp messenger", "unknown")
                ):
                    phone_display = f"+{clean_digits}" if not raw_name.startswith("+") else raw_name

                accounts.append(
                    {
                        "phone_number": phone_display,
                        "raw_name": raw_name,
                        "package": pkg,
                        "user_id": current_user_id,
                        "app_type": "whatsapp_business" if "w4b" in pkg else "whatsapp",
                    }
                )
        return accounts
    except Exception:
        return []


def _safe_status_emit(callback, phase, label, total_files=None, detail=None):
    if not callback:
        return
    try:
        callback(phase, label, total_files=total_files, detail=detail)
    except TypeError:
        try:
            callback(phase, label, total=total_files, detail=detail)
        except TypeError:
            try:
                callback(phase, label, total_files)
            except TypeError:
                try:
                    callback(phase, label)
                except Exception:
                    pass


# SIM numbers per device serial: reading them costs up to ~18 ADB shell calls, and the device
# inventory rescans every 90 s, so they are remembered for a while.
_SIM_NUMBERS_CACHE = {}
_SIM_NUMBERS_TTL_SECS = 600

# Storage roots probed for WhatsApp / WhatsApp Business data (each may also contain accounts/*)
WHATSAPP_PROBE_ROOTS = (
    "/storage/emulated/*/Android/media/com.whatsapp/WhatsApp",
    "/storage/emulated/*/Android/media/com.whatsapp.w4b/WhatsApp\\ Business",
    "/storage/emulated/*/WhatsApp",
    "/storage/emulated/*/WhatsApp\\ Business",
    "/storage/emulated/0/DualApp/WhatsApp",
    "/storage/emulated/0/DUAL_APP/WhatsApp",
    "/storage/emulated/0/Parallel/WhatsApp",
    "/storage/emulated/0/Clone/WhatsApp",
    "/sdcard/WhatsApp",
    "/storage/*-*/Android/media/com.whatsapp/WhatsApp",
    "/storage/*-*/WhatsApp",
)


def build_account_probe_script(roots=WHATSAPP_PROBE_ROOTS) -> str:
    """
    Builds the single `sh` script that inventories every WhatsApp folder in one ADB round trip.
    Emits one line per folder: ACC|<path>|<has_media>|<has_db>|<db_file>|<db_mtime>|<db_size>.
    The reported database is the NEWEST msgstore backup (crypt15 preferred, then crypt14, then any):
    WhatsApp keeps dated daily copies (msgstore-YYYY-MM-DD.1.db.crypt15) that sort before
    msgstore.db.crypt15, so taking the first glob match reported the oldest backup's age.
    """
    return (
        "file_stat() { "
        "st=$(stat -c \"%Y:%s\" \"$1\" 2>/dev/null); "
        "if [ -n \"$st\" ]; then echo \"$st\"; "
        "else echo \"$(date -r \"$1\" +%s 2>/dev/null || echo 0):$(wc -c < \"$1\" 2>/dev/null || echo 0)\"; fi; "
        "}; "
        "probe_dir() { "
        "p=\"$1\"; "
        "[ -d \"$p\" ] || return; "
        "has_media=0; [ -d \"$p/Media\" ] && has_media=1; "
        "has_db=0; db_file=\"\"; db_mtime=0; db_size=0; "
        "if [ -d \"$p/Databases\" ]; then "
        "has_db=1; "
        "for pat in 'msgstore*.crypt15' 'msgstore*.crypt14' 'msgstore*'; do "
        "best_f=\"\"; best_m=-1; best_s=0; "
        "for f in \"$p/Databases\"/$pat; do "
        "[ -f \"$f\" ] || continue; "
        "st=$(file_stat \"$f\"); m=\"${st%%:*}\"; sz=\"${st##*:}\"; "
        "case \"$m\" in ''|*[!0-9]*) m=0;; esac; "
        "if [ \"$m\" -gt \"$best_m\" ]; then best_f=\"$f\"; best_m=\"$m\"; best_s=\"$sz\"; fi; "
        "done; "
        "if [ -n \"$best_f\" ]; then db_file=\"${best_f##*/}\"; db_mtime=\"$best_m\"; db_size=\"$best_s\"; break; fi; "
        "done; "
        "fi; "
        "echo \"ACC|$p|$has_media|$has_db|$db_file|$db_mtime|$db_size\"; "
        "}; "
        "for r in " + " ".join(roots) + " ; do "
        "[ -d \"$r\" ] || continue; "
        "probe_dir \"$r\"; "
        "if [ -d \"$r/accounts\" ]; then "
        "for acc in \"$r/accounts\"/*; do "
        "[ -d \"$acc\" ] && probe_dir \"$acc\"; "
        "done; "
        "fi; "
        "done"
    )


def discover_whatsapp_accounts(
    adb_path=None,
    hex_key=None,
    device_serial=None,
    status_callback=None,
) -> list:
    """
    Probes connected Android device storage across all user spaces (user 0, user 95, user 999),
    native WhatsApp multi-account folders (accounts/*), WhatsApp Business (com.whatsapp.w4b),
    OEM Dual Messenger / Parallel mounts, and legacy storage.

    Returns a ranked list of candidate account dicts sorted by freshness and target encryption match.
    """
    cmd = find_adb_binary(adb_path)
    adb_base = [cmd, "-s", device_serial] if device_serial else [cmd]

    status_callback = functools.partial(_safe_status_emit, status_callback) if status_callback else None
    if status_callback:
        status_callback(
            "database",
            "Scanning phone for WhatsApp accounts...",
            detail="Checking storage directories and multi-account folders via ADB",
        )

    probe_script = build_account_probe_script()

    try:
        res = subprocess.run(
            adb_base + ["shell", "sh"],
            input=probe_script,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except Exception as e:
        sys.stderr.write(f"[ADB] Warning: Probe command failed: {e}\n")
        res = None

    lines = [
        line.strip()
        for line in (res.stdout.splitlines() if res and res.stdout else [])
        if line.startswith("ACC|")
    ]
    if not lines:
        return []

    # Query registered accounts from Android AccountManager
    if status_callback:
        status_callback(
            "database",
            "Scanning registered phone accounts...",
            detail="Querying Android AccountManager via dumpsys account",
        )
    registered = get_registered_whatsapp_accounts(cmd, device_serial=device_serial)

    cfg = load_config()
    has_hex = bool(hex_key) or bool(cfg.get("hex_key"))
    known_accounts = cfg.get("known_accounts", {})

    # Expensive lookups run at most once per scan (previously once per candidate folder):
    # SIM numbers need up to ~18 ADB shell calls, self info opens the local msgstore.db.
    sim_numbers = None
    self_info = None

    def _get_sim_numbers():
        nonlocal sim_numbers
        if sim_numbers is None:
            cached = _SIM_NUMBERS_CACHE.get(device_serial) if device_serial else None
            if cached and time.time() - cached[0] < _SIM_NUMBERS_TTL_SECS:
                sim_numbers = cached[1]
            else:
                sim_numbers = get_device_sim_phone_numbers(cmd, device_serial=device_serial) or []
                if device_serial:
                    _SIM_NUMBERS_CACHE[device_serial] = (time.time(), sim_numbers)
        return sim_numbers

    def _get_self_info():
        nonlocal self_info
        if self_info is None:
            self_info = {}
            try:
                from core.contacts import extract_self_account_info
                self_info = extract_self_account_info("Databases/msgstore.db") or {}
                if not self_info.get("phone_number") and not self_info.get("push_name"):
                    out_db = Path(cfg.get("output_dir", "./output")) / "Databases" / "msgstore.db"
                    if out_db.is_file():
                        self_info = extract_self_account_info(str(out_db)) or {}
            except Exception:
                self_info = {}
        return self_info

    first_resolved_phone = ""
    candidates_by_path = {}
    for line in lines:
        parts = line.split("|")
        if len(parts) < 7:
            continue
        p = parts[1].strip()
        if not p or p in candidates_by_path:
            continue

        has_media = (parts[2].strip() == "1")
        has_db = (parts[3].strip() == "1")
        db_file = parts[4].strip()
        try:
            db_mtime = int(parts[5].strip())
        except ValueError:
            db_mtime = 0
        try:
            db_size = int(parts[6].strip())
        except ValueError:
            db_size = 0

        # Crypt version
        crypt_ver = 0
        m = re.search(r"\.crypt(\d+)", db_file)
        if m:
            crypt_ver = int(m.group(1))

        # App type & package
        is_business = ("com.whatsapp.w4b" in p or "WhatsApp Business" in p)
        pkg = "com.whatsapp.w4b" if is_business else "com.whatsapp"
        app_type = "whatsapp_business" if is_business else "whatsapp"
        app_label = "WhatsApp Business" if is_business else "WhatsApp"

        # User profile ID & Account ID
        u_match = re.search(r"/storage/emulated/(\d+)/", p)
        user_id = u_match.group(1) if u_match else "0"

        if "/accounts/" in p:
            account_id = Path(p).name
            parent_path = p.rsplit("/accounts/", 1)[0]
        elif user_id != "0":
            account_id = f"dual_{user_id}"
            parent_path = p
        else:
            account_id = "main"
            parent_path = p

        # Correlate phone number from known_accounts, registered accounts, SIMs, or local DB
        phone_number = known_accounts.get(p, "")
        if not phone_number:
            matched_reg = [r for r in registered if r["user_id"] == user_id and r["app_type"] == app_type]
            if matched_reg and matched_reg[0]["phone_number"]:
                phone_number = matched_reg[0]["phone_number"]
        if not phone_number:
            sims = _get_sim_numbers()
            if sims:
                phone_number = sims[0]

        info = _get_self_info()
        if not phone_number and info.get("phone_number"):
            phone_number = info["phone_number"]
        push_name = info.get("push_name") or ""

        if phone_number and not first_resolved_phone:
            first_resolved_phone = phone_number

        # Human-readable formatted date and size
        if db_mtime > 0:
            try:
                last_backup_str = datetime.fromtimestamp(db_mtime).strftime("%d %b %Y, %I:%M %p")
            except Exception:
                last_backup_str = str(db_mtime)
        else:
            last_backup_str = "No backup found"

        size_str = f"{db_size / (1024 * 1024):.1f} MB" if db_size > 0 else "0 MB"

        if phone_number:
            if push_name:
                label = f"{app_label} ({phone_number} - {push_name})"
            else:
                label = f"{app_label} ({phone_number})"
        elif account_id != "main":
            label = f"{app_label} (Account {account_id})"
        elif app_type == "whatsapp_business":
            label = "WhatsApp Business (Business Account)"
        else:
            label = f"{app_label} (Primary Account)"

        # Calculate ranking score
        score = 0.0
        if has_hex:
            if crypt_ver == 15:
                score += 10_000_000_000.0
            elif crypt_ver > 0:
                score += 1_000_000_000.0
        else:
            if crypt_ver > 0:
                score += 5_000_000_000.0

        if has_db and db_size > 0:
            score += 1_000_000_000.0

        score += float(db_mtime)

        if has_media:
            score += 500_000.0

        if "/accounts/" in p:
            score += 100_000.0

        cand_record = {
            "path": p,
            "account_id": account_id,
            "parent_path": parent_path,
            "package": pkg,
            "app_type": app_type,
            "app_label": app_label,
            "label": label,
            "phone_number": phone_number,
            "push_name": push_name,
            "has_db": has_db,
            "has_media": has_media,
            "latest_db_file": db_file,
            "latest_db_mtime": db_mtime,
            "latest_db_size": db_size,
            "latest_backup_str": last_backup_str,
            "size_str": size_str,
            "crypt_version": crypt_ver,
            "score": score,
            "is_active_recommendation": False,
        }
        candidates_by_path[p] = cand_record

    if first_resolved_phone and not cfg.get("selected_account_phone"):
        try:
            save_config({"selected_account_phone": first_resolved_phone})
        except Exception:
            pass

    account_list = list(candidates_by_path.values())
    account_list.sort(key=lambda c: c["score"], reverse=True)
    if account_list:
        account_list[0]["is_active_recommendation"] = True

    return account_list


def discover_android_base_path(
    adb_path=None,
    hex_key=None,
    device_serial=None,
    preferred_account_path=None,
    status_callback=None,
) -> str:
    """
    Auto-discovers the active WhatsApp or WhatsApp Business storage path on the Android device.
    Supports native multi-account paths (accounts/*), Samsung Dual Messenger (user 95),
    Xiaomi Dual Apps (user 999), Work Profiles, and WhatsApp Business.

    If preferred_account_path (or config selected_account_path) is provided and exists on the device,
    strictly sticks to it to prevent cross-account overwriting.
    """
    cmd = find_adb_binary(adb_path)
    adb_base = [cmd, "-s", device_serial] if device_serial else [cmd]
    status_callback = functools.partial(_safe_status_emit, status_callback) if status_callback else None

    # 1. Check if an account path was explicitly requested or saved in config.json
    target_path = preferred_account_path
    if not target_path:
        cfg = load_config()
        target_path = cfg.get("selected_account_path")

    if target_path:
        if status_callback:
            status_callback(
                "database",
                "Verifying selected account storage...",
                detail=f"Checking {target_path} on phone",
            )
        test_cmd = adb_base + ["shell", f"[ -d '{target_path}' ] && echo 'FOUND'"]
        try:
            res = subprocess.run(test_cmd, capture_output=True, text=True, timeout=5, check=False)
            if res.returncode == 0 and "FOUND" in res.stdout:
                return target_path
        except Exception:
            pass

    # 2. Probe device dynamically for all accounts and pick top-ranked
    accounts = discover_whatsapp_accounts(
        cmd,
        hex_key=hex_key,
        device_serial=device_serial,
        status_callback=status_callback,
    )
    if accounts:
        return accounts[0]["path"]

    # 3. Fallback to default Android 11+ path
    return "/storage/emulated/0/Android/media/com.whatsapp/WhatsApp"


def already_pulled_roots(dest_media=None):
    """
    Folders whose files count as "already on the PC" for a sync, each walked once.
    The parent of dest_media only matters for the legacy output/Media layout; for the default
    dest_media ("./output") the parent is the application folder itself, which used to make every
    sync walk the whole app (runtime, venv, Databases) plus the output folder a second time.
    """
    candidates = [Path("./output")]
    if dest_media:
        media_path = Path(dest_media)
        candidates.append(media_path)
        if media_path.name.lower() == "media":
            candidates.append(media_path.parent)
    roots = []
    for cand in candidates:
        try:
            resolved = cand.resolve()
        except OSError:
            continue
        if resolved.is_dir() and resolved not in roots:
            roots.append(resolved)
    # A root inside another root is already covered by walking the outer one
    return [
        str(r) for r in roots
        if not any(other != r and r.is_relative_to(other) for other in roots)
    ]


def build_already_pulled_index(output_dir):
    """
    Builds a set of (normalized_filename, size) tuples already present in output_dir.
    Allows skipping files already organized, even if ./Media was cleaned up.
    Includes both raw/sanitized filenames, duplicate-stripped stems, and cross-references
    media_index.csv / .sync_state.sqlite3 to map renamed documents back to their phone names.
    """
    seen = set()
    out = Path(output_dir)
    if not out.is_dir():
        return seen

    # 1. Walk output directory files
    for p in out.rglob("*"):
        try:
            if p.is_file():
                parts = p.parts
                if any(part in (".cache", ".thumbnails", ".Links", ".git", "gallery_assets") for part in parts) or p.name == ".nomedia":
                    continue
                if p.name in (
                    "media_index.csv",
                    "gallery.html",
                    "gallery_data.js",
                    "start_gallery.bat",
                    "sync_and_start_gallery.bat",
                    ".sync_state.sqlite3",
                ):
                    continue
                size = p.stat().st_size
                fn = p.name
                seen.add((normalize_filename(fn, strip_dup_suffix=False), size))
                seen.add((normalize_filename(fn, strip_dup_suffix=True), size))
        except Exception:
            continue

    # 2. Cross-reference media_index.csv for renamed documents and phone_path mapping
    csv_file = out / "media_index.csv"
    if csv_file.is_file():
        try:
            import csv
            with open(csv_file, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    phone_path = row.get("phone_path")
                    rel_p = row.get("rel_path")
                    sz_str = row.get("size_bytes")
                    if phone_path and rel_p and sz_str:
                        try:
                            sz = int(sz_str)
                            dest_f = out / rel_p
                            if dest_f.is_file() and dest_f.stat().st_size == sz:
                                phone_fn = os.path.basename(phone_path)
                                seen.add((normalize_filename(phone_fn, strip_dup_suffix=False), sz))
                                seen.add((normalize_filename(phone_fn, strip_dup_suffix=True), sz))
                        except Exception:
                            continue
        except Exception:
            pass

    # 3. Cross-reference completed rows in .sync_state.sqlite3
    db_file = out / ".sync_state.sqlite3"
    if db_file.is_file():
        try:
            import sqlite3
            with sqlite3.connect(str(db_file)) as conn:
                cur = conn.execute(
                    "SELECT rel_path, target_path, file_size FROM sync_manifest WHERE status = 'completed'"
                )
                for rel_p, target_p, sz in cur.fetchall():
                    try:
                        if target_p and os.path.isfile(target_p) and os.path.getsize(target_p) == sz:
                            base_fn = os.path.basename(rel_p)
                            seen.add((normalize_filename(base_fn, strip_dup_suffix=False), sz))
                            seen.add((normalize_filename(base_fn, strip_dup_suffix=True), sz))
                    except Exception:
                        continue
        except Exception:
            pass

    return seen


def adb_pull_tar_full(
    adb_path,
    base,
    dest_db,
    dest_media,
    folders_str,
    device_serial=None,
    cancellation_token=None,
    progress_callback=None,
):
    """Full streaming tar pull fallback when remote stat indexing is unavailable."""
    adb_base = [adb_path, "-s", device_serial] if device_serial else [adb_path]
    tar_cmd = adb_base + ["exec-out", f"tar -C '{base}/' -cf - {folders_str} 2>/dev/null"]
    proc = None
    try:
        proc = subprocess.Popen(tar_cmd, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL)
        with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
            for member in tar:
                if cancellation_token and cancellation_token.is_set():
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except Exception:
                        proc.kill()
                    return False

                clean_name = member.name.lstrip("/").replace("\\", "/")
                if clean_name.startswith("Databases/"):
                    dest_p = Path(dest_db) / clean_name[len("Databases/") :]
                elif clean_name.startswith("Media/"):
                    dest_p = Path(dest_media) / clean_name[len("Media/") :]
                elif clean_name.startswith("Backups/"):
                    dest_p = Path("./Backups") / clean_name[len("Backups/") :]
                else:
                    continue

                if member.isdir():
                    dest_p.mkdir(parents=True, exist_ok=True)
                elif member.isreg():
                    dest_p.parent.mkdir(parents=True, exist_ok=True)
                    with open(to_long_path(dest_p), "wb") as f_out:
                        f_in = tar.extractfile(member)
                        if f_in:
                            shutil.copyfileobj(f_in, f_out)
                    if progress_callback:
                        progress_callback(clean_name, member.size)

                if cancellation_token and cancellation_token.is_set():
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except Exception:
                        proc.kill()
                    return False
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            _terminate_adb_proc(proc)
            return False
        return proc.returncode == 0
    except Exception as e:
        sys.stderr.write(f"[ADB] Full tar pull failed: {e}\n")
        return False
    finally:
        _terminate_adb_proc(proc)


def safe_atomic_replace(src_path, dst_path, timeout=30.0):
    """
    Atomically renames src_path to dst_path with exponential backoff retry loop
    to handle transient file locks from Windows Defender, indexing, or explorer handles.
    """
    src_long = to_long_path(src_path)
    dst_long = to_long_path(dst_path)
    deadline = time.time() + timeout
    attempt = 0
    while time.time() < deadline:
        try:
            os.replace(str(src_long), str(dst_long))
            return
        except (PermissionError, OSError) as e:
            attempt += 1
            time.sleep(min(0.5, 0.1 * (1.5 ** attempt)))
    os.replace(str(src_long), str(dst_long))


def safe_atomic_unlink(path, timeout=10.0):
    """
    Safely unlinks a file with retry loop for transient Windows file locks.
    """
    p = Path(path)
    deadline = time.time() + timeout
    attempt = 0
    while time.time() < deadline:
        try:
            p.unlink(missing_ok=True)
            return
        except (PermissionError, OSError):
            attempt += 1
            time.sleep(min(0.5, 0.1 * (1.5 ** attempt)))
def is_skippable_system_path(rel_p: str) -> bool:
    """
    Identifies system marker files and web preview caches that should never be pulled
    or stored in the user media library.
    """
    if not rel_p:
        return False
    norm = rel_p.replace("\\", "/").lstrip("/")
    return (
        norm == ".nomedia"
        or norm.endswith("/.nomedia")
        or "/.Links/" in norm
        or norm.startswith("Media/.Links/")
        or norm.startswith(".Links/")
    )


_session_inventory_cache = {}


_DATED_MSGSTORE_RE = re.compile(r"^msgstore-(\d{4}-\d{2}-\d{2})\.(\d+)\.db\.crypt\d+$", re.IGNORECASE)
_CURRENT_MSGSTORE_RE = re.compile(r"^msgstore\.db(\.crypt\d+)?$", re.IGNORECASE)


def select_database_files(phone_files):
    """
    Picks which files under Databases/ are worth transferring.
    WhatsApp keeps the current backup as msgstore.db.cryptNN plus up to ~7 dated daily copies
    (msgstore-YYYY-MM-DD.N.db.cryptNN). Only the current one is ever decrypted, so the dated
    copies (each as large as the whole chat history) are skipped. If the current file is
    missing, the newest dated copy is kept instead. Every other file (wa.db, settings) is kept.
    """
    current_present = any(_CURRENT_MSGSTORE_RE.match(os.path.basename(p)) for p, _ in phone_files)
    newest_dated = None
    selected = []
    for rel_path, size in phone_files:
        m = _DATED_MSGSTORE_RE.match(os.path.basename(rel_path))
        if not m:
            selected.append((rel_path, size))
            continue
        key = (m.group(1), int(m.group(2)))
        if newest_dated is None or key > newest_dated[0]:
            newest_dated = (key, (rel_path, size))
    if not current_present and newest_dated is not None:
        selected.append(newest_dated[1])
    return selected


def adb_pull_tar(
    adb_path,
    base,
    dest_db,
    dest_media,
    folders_filter=None,
    device_serial=None,
    session_manager=None,
    session_id=None,
    cancellation_token=None,
    skip_db_token=None,
    progress_callback=None,
    status_callback=None,
    destination_resolver=None,
    on_commit_callback=None,
    in_flight_callback=None,
):
    """
    Fast incremental tar pull from Android to PC using a single tar stream.
    Features:
    - High-speed in-process file inventory using find -printf
    - Media Union: Automatically unions account-specific and parent/historical media folders
    - Atomic staging files (.part_{session_id}) with size validation to prevent corrupted files
    - Persistent session progress tracking in SQLite
    - Safe cooperative pause via cancellation_token
    """
    global _session_inventory_cache
    cmd = find_adb_binary(adb_path)
    adb_base = [cmd, "-s", device_serial] if device_serial else [cmd]
    status_callback = functools.partial(_safe_status_emit, status_callback) if status_callback else None

    if cancellation_token and cancellation_token.is_set():
        return False

    # Clean up any leftover partial files from interrupted previous transfers
    if session_manager:
        session_manager.cleanup_orphaned_part_files([dest_db, dest_media, "./Backups"])

    # Determine tar_root and target folders
    # Media Union Architecture:
    # If base is an account subfolder (e.g. /storage/emulated/0/Android/media/com.whatsapp/WhatsApp/accounts/1002):
    # - For Databases: pull strictly from base/Databases
    # - For Media: probe BOTH base/Media AND parent_path/Media to capture both post-migration and pre-migration media!
    is_db_only = (folders_filter == ["Databases"])
    tar_root = base
    account_sub = ""
    parent_path = ""

    if "/accounts/" in base:
        parent_path = base.rsplit("/accounts/", 1)[0]
        account_sub = "accounts/" + base.rsplit("/accounts/", 1)[1].strip("/")

    folders_to_pull = []
    if is_db_only:
        check_cmd = adb_base + ["shell", f"ls -d '{base}/Databases' 2>/dev/null"]
        check_res = subprocess.run(check_cmd, capture_output=True, text=True, check=False)
        if check_res.returncode == 0 and check_res.stdout.strip():
            folders_to_pull.append("Databases")
    else:
        # Media / Backups pull
        if parent_path and account_sub:
            # Multi-account folder: Set tar_root to parent_path so find and tar can address both
            tar_root = parent_path
            # 1. Probe companion account folders
            for fld in [f"{account_sub}/Media", f"{account_sub}/Backups"]:
                if folders_filter is not None and "Media" not in folders_filter and "Media" in fld:
                    continue
                check_cmd = adb_base + ["shell", f"ls -d '{parent_path}/{fld}' 2>/dev/null"]
                check_res = subprocess.run(check_cmd, capture_output=True, text=True, check=False)
                if check_res.returncode == 0 and check_res.stdout.strip():
                    folders_to_pull.append(fld)

            # 2. Probe shared/historical parent folders (pre-migration media)
            for fld in ["Media", "Backups"]:
                if folders_filter is not None and fld not in folders_filter:
                    continue
                check_cmd = adb_base + ["shell", f"ls -d '{parent_path}/{fld}' 2>/dev/null"]
                check_res = subprocess.run(check_cmd, capture_output=True, text=True, check=False)
                if check_res.returncode == 0 and check_res.stdout.strip():
                    folders_to_pull.append(fld)
        else:
            # Single account or root base
            for fld in ["Media", "Backups"]:
                if folders_filter is not None and fld not in folders_filter:
                    continue
                check_cmd = adb_base + ["shell", f"ls -d '{base}/{fld}' 2>/dev/null"]
                check_res = subprocess.run(check_cmd, capture_output=True, text=True, check=False)
                if check_res.returncode == 0 and check_res.stdout.strip():
                    folders_to_pull.append(fld)
            if not is_db_only and (folders_filter is None or "Media" in folders_filter):
                check_acc = adb_base + ["shell", f"ls -d '{base}/accounts'/*/Media 2>/dev/null"]
                acc_res = subprocess.run(check_acc, capture_output=True, text=True, check=False)
                if acc_res.returncode == 0 and acc_res.stdout.strip():
                    for line in acc_res.stdout.splitlines():
                        acc_dir = line.strip()
                        if acc_dir:
                            rel_acc = os.path.relpath(acc_dir, base).replace("\\", "/")
                            if rel_acc and rel_acc not in folders_to_pull:
                                folders_to_pull.append(rel_acc)

    if not folders_to_pull:
        return False

    folders_str = " ".join(folders_to_pull)

    if cancellation_token and cancellation_token.is_set():
        return False

    if status_callback:
        if is_db_only:
            status_callback(
                "database",
                "Retrieving chat database from phone...",
                detail="Checking Databases/ directory on phone over ADB",
                total_files=0,
            )
        else:
            status_callback(
                "indexing",
                "Scanning WhatsApp media on phone...",
                detail=f"Checking storage folders ({folders_str})",
                total_files=0,
            )

    phone_files = None
    cache_key = f"{session_id}:{tar_root}:{folders_str}" if session_id else None

    if cache_key and not is_db_only and cache_key in _session_inventory_cache:
        phone_files = _session_inventory_cache[cache_key]
        if status_callback:
            status_callback(
                "indexing",
                f"Reusing media inventory ({len(phone_files):,} files)...",
                detail="Instant in-session inventory cache active",
                total_files=len(phone_files),
            )

    if phone_files is None:
        # Use -printf '%s:%p\n' as primary high-speed inventory (avoids ARG_MAX crash on 50k+ files)
        find_cmd = adb_base + [
            "shell",
            f"cd '{tar_root}' && find {folders_str} -type f -printf '%s:%p\\n' 2>/dev/null",
        ]

        try:
            res = subprocess.run(
                find_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
            )
            if not res.stdout.strip():
                # Fallback for minimal toybox builds that lack -printf
                fallback_cmd = adb_base + [
                    "shell",
                    f"cd '{tar_root}' && find {folders_str} -type f -exec stat -c '%s:%n' {{}} + 2>/dev/null",
                ]
                res = subprocess.run(
                    fallback_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
                )
        except Exception as e:
            sys.stderr.write(f"[ADB] Warning: Failed to inventory phone files: {e}\n")
            if session_manager:
                return False
            return adb_pull_tar_full(
                cmd,
                base,
                dest_db,
                dest_media,
                folders_str,
                device_serial=device_serial,
                cancellation_token=cancellation_token,
                progress_callback=progress_callback,
            )

        phone_files = []
        for line in res.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(":", 1)
            if len(parts) == 2:
                try:
                    sz = int(parts[0])
                    rel_p = parts[1].strip()
                    if rel_p.startswith("./"):
                        rel_p = rel_p[2:]
                    phone_files.append((rel_p, sz))
                except ValueError:
                    continue

        # Filter out Android system marker files (.nomedia) and link preview cache (.Links)
        phone_files = [(p, sz) for p, sz in phone_files if not is_skippable_system_path(p)]

        if is_db_only:
            # Only the current backup is decrypted: skip WhatsApp's dated daily rotations
            phone_files = select_database_files(phone_files)

        if cache_key and not is_db_only and phone_files:
            _session_inventory_cache[cache_key] = phone_files

    if not phone_files:
        if session_manager:
            sys.stderr.write("[ADB] Warning: No WhatsApp files found on phone during inventory scan.\n")
            return False
        return adb_pull_tar_full(
            cmd,
            base,
            dest_db,
            dest_media,
            folders_str,
            device_serial=device_serial,
            cancellation_token=cancellation_token,
            progress_callback=progress_callback,
        )

    if cancellation_token and cancellation_token.is_set():
        return False

    def get_local_path(rel_path):
        clean = rel_path.lstrip("/").replace("\\", "/")
        if "/Media/" in clean:
            sub = clean.split("/Media/", 1)[1].split("/")
            sanitized_sub = [re.sub(r'[<>:"/\\|?*]', "_", p).rstrip(". ") or "unknown" for p in sub]
            return os.path.join(dest_media, *sanitized_sub)
        elif clean.startswith("Media/"):
            sub = clean[len("Media/") :].split("/")
            sanitized_sub = [re.sub(r'[<>:"/\\|?*]', "_", p).rstrip(". ") or "unknown" for p in sub]
            return os.path.join(dest_media, *sanitized_sub)
        elif "/Databases/" in clean or clean.startswith("Databases/"):
            sub = clean.split("Databases/", 1)[1].split("/")
            sanitized_sub = [re.sub(r'[<>:"/\\|?*]', "_", p).rstrip(". ") or "unknown" for p in sub]
            return os.path.join(dest_db, *sanitized_sub)
        elif "/Backups/" in clean or clean.startswith("Backups/"):
            sub = clean.split("Backups/", 1)[1].split("/")
            sanitized_sub = [re.sub(r'[<>:"/\\|?*]', "_", p).rstrip(". ") or "unknown" for p in sub]
            return os.path.join("./Backups", *sanitized_sub)
        parts = clean.split("/")
        sanitized_parts = [re.sub(r'[<>:"/\\|?*]', "_", p).rstrip(". ") or "unknown" for p in parts]
        return os.path.join(".", *sanitized_parts)

    files_to_pull = []
    is_db_only = (folders_filter == ["Databases"])
    phase_key = "database" if is_db_only else "syncing"
    type_label = "database" if is_db_only else "media"

    if session_manager and session_id:
        # Reconcile existing session manifest with current remote phone inventory
        session_manager.reconcile_manifest(
            session_id, phone_files, dest_db=dest_db, dest_media=dest_media
        )
        # Purge any leftover skippable system paths (.nomedia, .Links) from manifest
        try:
            with session_manager._lock, session_manager._get_connection() as conn:
                conn.execute(
                    """
                    DELETE FROM sync_manifest
                    WHERE session_id = ? AND (
                        rel_path LIKE '%.nomedia' OR rel_path = '.nomedia'
                        OR rel_path LIKE 'Media/.Links/%' OR rel_path LIKE '.Links/%'
                    )
                    """,
                    (session_id,),
                )
                now = time.time()
                conn.execute(
                    """
                    UPDATE sync_sessions
                    SET total_files = (SELECT COUNT(*) FROM sync_manifest WHERE session_id = ?),
                        total_bytes = (SELECT COALESCE(SUM(file_size), 0) FROM sync_manifest WHERE session_id = ?),
                        synced_files = (SELECT COUNT(*) FROM sync_manifest WHERE session_id = ? AND status = 'completed'),
                        synced_bytes = (SELECT COALESCE(SUM(synced_bytes), 0) FROM sync_manifest WHERE session_id = ? AND status = 'completed'),
                        updated_at = ?
                    WHERE session_id = ?
                    """,
                    (session_id, session_id, session_id, session_id, now, session_id),
                )
                conn.commit()
        except Exception:
            pass
        if not is_db_only:
            # Reconcile already organized files in output so even fresh/cancelled sessions skip existing files
            already_pulled = set()
            for cand_out in already_pulled_roots(dest_media):
                already_pulled.update(build_already_pulled_index(cand_out))

            pending_rows = session_manager.get_pending_files(session_id)
            existing_batch = []
            for r in pending_rows:
                rel_p = r["rel_path"]
                sz = r["file_size"]
                if rel_p.startswith("Databases/"):
                    continue
                if destination_resolver:
                    try:
                        resolved_p, _ = destination_resolver(rel_p, sz)
                        if resolved_p and resolved_p.is_file() and resolved_p.stat().st_size == sz:
                            existing_batch.append((rel_p, sz))
                            continue
                    except Exception:
                        pass
                fn = os.path.basename(rel_p)
                norm = normalize_filename(fn, strip_dup_suffix=False)
                norm_strip = normalize_filename(fn, strip_dup_suffix=True)
                if (norm, sz) in already_pulled or (norm_strip, sz) in already_pulled:
                    existing_batch.append((rel_p, sz))
            if existing_batch:
                session_manager.mark_files_completed_batch(session_id, existing_batch)

        pending_rows = session_manager.get_pending_files(session_id)
        files_to_pull = [r["rel_path"] for r in pending_rows]
        sess_info = session_manager.get_session(session_id)
        if status_callback and sess_info:
            status_callback(
                phase_key,
                f"Transferring {len(files_to_pull):,} {type_label} files from phone...",
                detail="Direct streaming to organized folders in progress",
                total_files=sess_info.get("total_files", len(phone_files)),
            )
    else:
        already_pulled = set()
        for cand_out in already_pulled_roots(dest_media):
            already_pulled.update(build_already_pulled_index(cand_out))

        for rel_path, size in phone_files:
            if rel_path.startswith("Databases/"):
                files_to_pull.append(rel_path)
                continue

            if destination_resolver:
                try:
                    resolved_p, _ = destination_resolver(rel_path, size)
                    if resolved_p and resolved_p.is_file() and resolved_p.stat().st_size == size:
                        continue
                except Exception:
                    pass

            local_p = get_local_path(rel_path)
            if os.path.isfile(local_p):
                if os.path.getsize(local_p) == size:
                    continue
            else:
                filename_only = os.path.basename(rel_path)
                norm_name = normalize_filename(filename_only, strip_dup_suffix=False)
                norm_strip = normalize_filename(filename_only, strip_dup_suffix=True)
                if (norm_name, size) in already_pulled or (norm_strip, size) in already_pulled:
                    continue
            files_to_pull.append(rel_path)
        if status_callback:
            status_callback(
                phase_key,
                f"Transferring {len(files_to_pull):,} {type_label} files from phone...",
                total_files=len(files_to_pull),
            )

    if not files_to_pull:
        return True

    if cancellation_token and cancellation_token.is_set():
        return False

    # Pre-pull disk space verification
    try:
        if session_manager and session_id:
            pending_rows = session_manager.get_pending_files(session_id)
            required_bytes = sum(r.get("file_size", 0) for r in pending_rows)
        else:
            phone_files_dict = dict(phone_files)
            required_bytes = sum(phone_files_dict.get(p, 0) for p in files_to_pull)

        if required_bytes > 0:
            target_p = Path(dest_media).resolve()
            check_target = target_p if target_p.exists() else target_p.parent
            while not check_target.exists() and check_target != check_target.parent:
                check_target = check_target.parent
            _, _, free_space = shutil.disk_usage(str(check_target))
            safety_margin = 200 * 1024 * 1024  # 200 MB buffer
            if free_space < (required_bytes + safety_margin):
                err_msg = (
                    f"Insufficient disk space on PC drive. "
                    f"Required: {required_bytes / (1024**3):.2f} GB, "
                    f"Available: {free_space / (1024**3):.2f} GB."
                )
                sys.stderr.write(f"[ADB ERROR] {err_msg}\n")
                if session_manager and session_id:
                    session_manager.pause_session(session_id, err_msg)
                return False
    except Exception as e:
        sys.stderr.write(f"[ADB] Warning: Could not verify disk space: {e}\n")

    pull_list_name = "pull_list.txt"
    try:
        with open(pull_list_name, "w", encoding="utf-8", newline="") as f:
            for p in files_to_pull:
                f.write(p + "\n")

        phone_list_path = f"/data/local/tmp/wa_pull_list_{session_id[:8] if session_id else 'sync'}.txt"
        subprocess.run(
            adb_base + ["push", pull_list_name, phone_list_path],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        sys.stderr.write(f"[ADB] Warning: Failed to push pull list: {e}\n")
        if os.path.exists(pull_list_name):
            try:
                os.remove(pull_list_name)
            except OSError:
                pass
        if session_manager:
            return False
        return adb_pull_tar_full(
            cmd,
            base,
            dest_db,
            dest_media,
            folders_str,
            device_serial=device_serial,
            cancellation_token=cancellation_token,
            progress_callback=progress_callback,
        )

    tar_cmd = adb_base + ["exec-out", f"tar -C '{tar_root}/' -cf - -T '{phone_list_path}' 2>/dev/null"]

    proc = None
    try:
        proc = subprocess.Popen(tar_cmd, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL)
        with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
            for member in tar:
                # Check for cancellation/pause or skip_db before writing each member
                if skip_db_token and skip_db_token.is_set():
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except Exception:
                        proc.kill()
                    return True

                if cancellation_token and cancellation_token.is_set():
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except Exception:
                        proc.kill()
                    return False

                clean_name = member.name.lstrip("/").replace("\\", "/")
                if is_skippable_system_path(clean_name):
                    continue

                matched_row = None
                if destination_resolver:
                    dest_p, matched_row = destination_resolver(clean_name, member.size)
                elif "/Databases/" in clean_name or clean_name.startswith("Databases/"):
                    sub_p = clean_name.split("Databases/", 1)[1]
                    dest_p = Path(dest_db) / sub_p
                elif "/Media/" in clean_name or clean_name.startswith("Media/"):
                    sub_p = clean_name.split("Media/", 1)[1]
                    dest_p = Path(dest_media) / sub_p
                elif "/Backups/" in clean_name or clean_name.startswith("Backups/"):
                    sub_p = clean_name.split("Backups/", 1)[1]
                    dest_p = Path("./Backups") / sub_p
                else:
                    continue

                if dest_p is None:
                    continue

                if member.isdir():
                    os.makedirs(to_long_path(dest_p), exist_ok=True)
                elif member.isreg():
                    if dest_p.is_file() and dest_p.stat().st_size == member.size:
                        # File already exists at destination with matching size. Skip extraction to eliminate redundant disk writes.
                        if progress_callback:
                            progress_callback(clean_name, member.size)
                        if on_commit_callback:
                            on_commit_callback(clean_name, dest_p, member.size, matched_row)
                        if session_manager and session_id:
                            session_manager.mark_file_completed(session_id, clean_name, member.size, target_path=str(dest_p))
                        continue
                    os.makedirs(to_long_path(dest_p.parent), exist_ok=True)
                    # Atomic write pattern: extract to .part_{session_id} staging file
                    tag = session_id[:8] if session_id else "sync"
                    temp_dest_p = dest_p.with_name(f"{dest_p.name}.part_{tag}")

                    try:
                        in_flight_written = 0
                        last_in_flight_t = time.time()
                        with open(to_long_path(temp_dest_p), "wb") as f_out:
                            f_in = tar.extractfile(member)
                            if f_in:
                                while True:
                                    if (cancellation_token and cancellation_token.is_set()) or (skip_db_token and skip_db_token.is_set()):
                                        break
                                    chunk = f_in.read(1048576)
                                    if not chunk:
                                        break
                                    f_out.write(chunk)
                                    in_flight_written += len(chunk)
                                    now = time.time()
                                    if member.size > 2 * 1024 * 1024 and (now - last_in_flight_t) >= 0.4:
                                        last_in_flight_t = now
                                        if in_flight_callback:
                                            try:
                                                in_flight_callback(clean_name, member.size, in_flight_written)
                                            except Exception:
                                                pass

                        # If user skipped DB transfer mid-file, remove partial file and return
                        if skip_db_token and skip_db_token.is_set():
                            safe_atomic_unlink(temp_dest_p)
                            proc.terminate()
                            try:
                                proc.wait(timeout=2)
                            except Exception:
                                proc.kill()
                            return True

                        # Validate byte size before atomic rename
                        actual_size = temp_dest_p.stat().st_size
                        if actual_size == member.size:
                            safe_atomic_replace(temp_dest_p, dest_p, timeout=30.0)
                            if session_manager and session_id:
                                session_manager.mark_file_completed(
                                    session_id, clean_name, member.size, target_path=str(dest_p)
                                )
                            if on_commit_callback:
                                try:
                                    on_commit_callback(clean_name, dest_p, member.size, matched_row)
                                except Exception as e_hook:
                                    sys.stderr.write(f"[Live] Warning: on_commit_callback error: {e_hook}\n")
                            if progress_callback:
                                progress_callback(clean_name, member.size)
                        else:
                            # Incomplete/truncated transfer: delete staging file
                            safe_atomic_unlink(temp_dest_p)
                            if session_manager and session_id:
                                session_manager.mark_file_failed(
                                    session_id, clean_name, f"Truncated: {actual_size}/{member.size}"
                                )
                    except Exception as err:
                        safe_atomic_unlink(temp_dest_p)
                        if session_manager and session_id:
                            session_manager.mark_file_failed(session_id, clean_name, str(err))
                        raise err

                # Check for skip_db or cancellation/pause immediately after file is committed
                if skip_db_token and skip_db_token.is_set():
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except Exception:
                        proc.kill()
                    return True

                if cancellation_token and cancellation_token.is_set():
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except Exception:
                        proc.kill()
                    return False

        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            _terminate_adb_proc(proc)
            return False
        return proc.returncode == 0
    except Exception as e:
        sys.stderr.write(f"[ADB] Tar stream pull error: {e}\n")
        return False
    finally:
        _terminate_adb_proc(proc)
        if os.path.exists(pull_list_name):
            try:
                os.remove(pull_list_name)
            except OSError:
                pass
        try:
            subprocess.run(
                adb_base + ["shell", f"rm -f '{phone_list_path}'"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception:
            pass


def adb_pull(
    adb_path="adb",
    base=None,
    dest_db="./Databases",
    dest_media="./Media",
    folders_filter=None,
    wait_auth_timeout=30,
    session_manager=None,
    session_id=None,
    cancellation_token=None,
    skip_db_token=None,
    progress_callback=None,
    status_callback=None,
    destination_resolver=None,
    on_commit_callback=None,
    in_flight_callback=None,
    hex_key=None,
    preferred_account_path=None,
):
    """
    Pulls WhatsApp databases and media from Android.
    Tries atomic incremental tar streaming first; falls back to clean folder pull.
    Supports pause, resume, and persistent session state.
    """
    cleanup_nested_databases_folder(dest_db)

    cmd = find_adb_binary(adb_path)
    connected, authorized, err_msg, device_serial, model = check_adb_device(cmd)
    if connected and not authorized and wait_auth_timeout > 0:
        ready, auth_msg, dev_serial, _ = wait_for_adb_device(cmd, timeout=wait_auth_timeout)
        if ready:
            connected = True
            authorized = True
            if dev_serial:
                device_serial = dev_serial
        else:
            err_msg = auth_msg

    if not base:
        base = discover_android_base_path(
            cmd,
            hex_key=hex_key,
            device_serial=device_serial if (connected and authorized) else None,
            preferred_account_path=preferred_account_path,
        )

    if not connected or not authorized:
        sys.stderr.write(f"[ADB] Warning: Device not ready ({err_msg}). Skipping pull.\n")
        return False

    success = adb_pull_tar(
        cmd,
        base,
        dest_db,
        dest_media,
        folders_filter=folders_filter,
        device_serial=device_serial,
        session_manager=session_manager,
        session_id=session_id,
        cancellation_token=cancellation_token,
        skip_db_token=skip_db_token,
        progress_callback=progress_callback,
        status_callback=status_callback,
        destination_resolver=destination_resolver,
        on_commit_callback=on_commit_callback,
        in_flight_callback=in_flight_callback,
    )
    if success:
        cleanup_nested_databases_folder(dest_db)
        return True

    # If skip_db was requested, return True so pipeline proceeds to Phase 2
    if skip_db_token and skip_db_token.is_set():
        return True

    # If cancellation was requested, exit cleanly without launching fallback
    if cancellation_token and cancellation_token.is_set():
        return False

    # Do not execute untracked raw fallback when session manager is active
    if session_manager:
        return False

    # Fallback to standard adb pull with BUG-02 fix
    for subpath, dest in [
        ("Databases", dest_db),
        ("Media", dest_media),
        ("Backups", "./Backups"),
    ]:
        if folders_filter is not None and subpath not in folders_filter:
            continue

        if cancellation_token and cancellation_token.is_set():
            return False

        src = f"{base}/{subpath}"
        dest_p = Path(dest).resolve()
        dest_p.parent.mkdir(parents=True, exist_ok=True)

        try:
            subprocess.run([cmd, "pull", src, str(dest_p.parent)], check=True)
        except Exception as e:
            sys.stderr.write(f"[ADB] Warning: Fallback pull failed for {src}: {e}\n")
            cleanup_nested_databases_folder(dest_db)
            return False

    cleanup_nested_databases_folder(dest_db)
    return True


def disable_developer_options(adb_path=None):
    """
    Disables Android Developer Options and USB Debugging on the connected device via ADB.
    Executes:
      adb shell settings put global development_settings_enabled 0
      adb shell settings put global adb_enabled 0
    Returns: (success: bool, message: str)
    """
    cmd = find_adb_binary(adb_path)
    try:
        dev = check_adb_device(adb_path)
        if dev.connected and getattr(dev, "usb_debugging", True) is False:
            return True, "USB Debugging and Developer Options are already turned off on your device."

        if not dev.connected:
            return False, "No Android device detected. Connect your phone via USB first."

        if not dev.authorized:
            return False, "Device is unauthorized. Please unlock phone and authorize USB debugging."

        cmd_str = "settings put global development_settings_enabled 0; settings put global adb_enabled 0"
        res = subprocess.run(
            [cmd, "shell", cmd_str],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if res.returncode == 0:
            return True, "Developer Options and USB Debugging have been disabled on your device."
        err_msg = res.stderr.strip() or res.stdout.strip() or f"Exit code {res.returncode}"
        return False, f"Failed to disable Developer Options: {err_msg}"
    except subprocess.TimeoutExpired:
        return False, "ADB command timed out while attempting to disable Developer Options."
    except Exception as e:
        return False, f"Error communicating with device: {e}"


def detect_device_oem(adb_path=None):
    """
    Detects the connected Android device OEM/brand and model.
    Prioritizes active ADB getprop if authorized, otherwise falls back to Windows USB hardware VID.
    Returns:
        dict: {
            "oem_key": "xiaomi" | "samsung" | "oneplus" | "pixel" | "generic",
            "brand": str,
            "model": str,
            "confidence": "high" | "suggested" | "unknown"
        }
    """
    cmd = find_adb_binary(adb_path)
    try:
        dev = check_adb_device(adb_path)
        if dev.connected and dev.authorized:
            res_m = subprocess.run([cmd, "shell", "getprop ro.product.manufacturer"], capture_output=True, text=True, timeout=3, check=False)
            res_model = subprocess.run([cmd, "shell", "getprop ro.product.model"], capture_output=True, text=True, timeout=3, check=False)
            brand = res_m.stdout.strip()
            model = res_model.stdout.strip()
            if brand:
                b_low = brand.lower()
                if any(x in b_low for x in ["xiaomi", "redmi", "poco"]):
                    return {"oem_key": "xiaomi", "brand": brand, "model": model, "confidence": "high"}
                if "samsung" in b_low:
                    return {"oem_key": "samsung", "brand": brand, "model": model, "confidence": "high"}
                if any(x in b_low for x in ["oneplus", "oppo", "realme"]):
                    return {"oem_key": "oneplus", "brand": brand, "model": model, "confidence": "high"}
                if any(x in b_low for x in ["vivo", "iqoo"]):
                    return {"oem_key": "vivo", "brand": brand, "model": model, "confidence": "high"}
                if any(x in b_low for x in ["motorola", "moto", "lenovo"]):
                    return {"oem_key": "motorola", "brand": brand, "model": model, "confidence": "high"}
                if "nothing" in b_low:
                    return {"oem_key": "nothing", "brand": brand, "model": model, "confidence": "high"}
                if any(x in b_low for x in ["google", "pixel"]):
                    return {"oem_key": "pixel", "brand": brand, "model": model, "confidence": "high"}
                return {"oem_key": "generic", "brand": brand, "model": model, "confidence": "high"}
    except Exception:
        pass

    try:
        usb_devices = detect_usb_android_hardware()
        if usb_devices:
            first = usb_devices[0]
            vendor = (first.get("vendor") or "").lower()
            name = (first.get("name") or "").lower()
            combined = f"{vendor} {name}"
            if any(x in combined for x in ["xiaomi", "redmi", "poco"]):
                return {"oem_key": "xiaomi", "brand": first.get("vendor") or "Xiaomi", "model": first.get("name") or "", "confidence": "suggested"}
            if "samsung" in combined:
                return {"oem_key": "samsung", "brand": "Samsung", "model": first.get("name") or "", "confidence": "suggested"}
            if any(x in combined for x in ["oneplus", "oppo", "realme"]):
                return {"oem_key": "oneplus", "brand": first.get("vendor") or "OnePlus", "model": first.get("name") or "", "confidence": "suggested"}
            if any(x in combined for x in ["vivo", "iqoo"]):
                return {"oem_key": "vivo", "brand": first.get("vendor") or "Vivo", "model": first.get("name") or "", "confidence": "suggested"}
            if any(x in combined for x in ["motorola", "moto", "lenovo"]):
                return {"oem_key": "motorola", "brand": first.get("vendor") or "Motorola", "model": first.get("name") or "", "confidence": "suggested"}
            if "nothing" in combined:
                return {"oem_key": "nothing", "brand": first.get("vendor") or "Nothing", "model": first.get("name") or "", "confidence": "suggested"}
            if any(x in combined for x in ["google", "pixel"]):
                return {"oem_key": "pixel", "brand": first.get("vendor") or "Google", "model": first.get("name") or "", "confidence": "suggested"}
            return {"oem_key": "generic", "brand": first.get("vendor") or "Android", "model": first.get("name") or "", "confidence": "suggested"}
    except Exception:
        pass

    return {"oem_key": "generic", "brand": "Android", "model": "", "confidence": "unknown"}


def setup_reverse_port(port=8000, adb_path=None):
    """
    Sets up ADB reverse port forwarding (adb reverse tcp:PORT tcp:PORT)
    so the phone can access http://localhost:PORT over the physical USB wire.
    Returns: (success: bool, message: str)
    """
    cmd = find_adb_binary(adb_path)
    try:
        dev = check_adb_device(adb_path)
        if not dev.connected:
            return False, "No Android phone detected. Connect via USB first."
        if not dev.authorized:
            return False, "Phone is unauthorized. Please tap 'Allow USB debugging' on your phone."

        res = subprocess.run([cmd, "reverse", f"tcp:{port}", f"tcp:{port}"], capture_output=True, text=True, timeout=5, check=False)
        if res.returncode == 0:
            return True, f"Reverse port {port} forwarding enabled over USB."
        return False, res.stderr.strip() or f"Failed to reverse port {port}"
    except Exception as e:
        return False, str(e)


def open_url_on_phone(url="http://localhost:8000/paste-key", adb_path=None):
    """
    Opens a URL in the default browser on the connected Android phone via ADB intent.
    Returns: (success: bool, message: str)
    """
    cmd = find_adb_binary(adb_path)
    try:
        dev = check_adb_device(adb_path)
        if not dev.connected or not dev.authorized:
            return False, "Phone not connected or unauthorized."

        res = subprocess.run(
            [cmd, "shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url],
            capture_output=True,
            text=True,
            timeout=5,
            check=False
        )
        if res.returncode == 0:
            return True, f"Opened {url} on phone."
        return False, res.stderr.strip() or "Failed to open URL on phone."
    except Exception as e:
        return False, str(e)


def get_device_storage_info(adb_path=None, serial=None):
    """
    Queries free and total storage on the connected Android device.
    Returns: dict with total_bytes, used_bytes, free_bytes, free_gb, total_gb, connected, authorized, error.
    """
    cmd = find_adb_binary(adb_path)
    base_cmd = [cmd]
    if serial:
        base_cmd.extend(["-s", serial])

    for target in ("/storage/emulated/0", "/sdcard", "/data"):
        try:
            res = subprocess.run(
                base_cmd + ["shell", "df", "-k", target],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if res.returncode == 0 and res.stdout:
                lines = [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]
                if len(lines) >= 2:
                    parts = lines[-1].split()
                    if len(parts) >= 4:
                        total_kb = int(re.sub(r"\D", "", parts[1]))
                        used_kb = int(re.sub(r"\D", "", parts[2]))
                        free_kb = int(re.sub(r"\D", "", parts[3]))
                        pct = round((used_kb / total_kb) * 100, 1) if total_kb > 0 else 0.0
                        return {
                            "success": True,
                            "connected": True,
                            "authorized": True,
                            "total_bytes": total_kb * 1024,
                            "used_bytes": used_kb * 1024,
                            "free_bytes": free_kb * 1024,
                            "free_gb": round((free_kb * 1024) / (1024**3), 2),
                            "total_gb": round((total_kb * 1024) / (1024**3), 2),
                            "percent_used": pct,
                            "error": None,
                        }
        except Exception:
            continue

    dev = check_adb_device(adb_path=adb_path)
    if not dev.connected:
        err = getattr(dev, "error", None) or getattr(dev, "reason", None) or "No Android device detected over USB"
    elif not dev.authorized:
        err = "Phone is connected but unauthorized. Please allow USB debugging on your device."
    else:
        err = "Failed to determine device storage via df"

    return {
        "success": False,
        "connected": bool(dev.connected),
        "authorized": bool(dev.authorized),
        "total_bytes": 0,
        "used_bytes": 0,
        "free_bytes": 0,
        "free_gb": 0.0,
        "total_gb": 0.0,
        "percent_used": 0.0,
        "error": err,
    }


def get_remote_file_sizes(file_paths, adb_path=None, serial=None):
    """
    Queries exact file sizes (in bytes) on the Android phone for a list of remote file paths.
    Uses batch shell execution for performance.
    Returns: dict mapping remote_path -> size_in_bytes (omitted if file does not exist).
    """
    if not file_paths:
        return {}

    cmd = find_adb_binary(adb_path)
    base_cmd = [cmd]
    if serial:
        base_cmd.extend(["-s", serial])

    results = {}
    batch_size = 40
    for i in range(0, len(file_paths), batch_size):
        chunk = file_paths[i : i + batch_size]
        sh_cmds = []
        for p in chunk:
            clean = p.replace("'", "'\\''")
            sh_cmds.append(f"if [ -f '{clean}' ]; then printf 'SZ %s %s\\n' \"$(stat -c %s '{clean}' 2>/dev/null || echo -1)\" '{clean}'; fi")
        full_script = "; ".join(sh_cmds)
        try:
            res = subprocess.run(
                base_cmd + ["shell", full_script],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if res.returncode == 0 and res.stdout:
                for line in res.stdout.splitlines():
                    line = line.strip()
                    if line.startswith("SZ "):
                        parts = line.split(" ", 2)
                        if len(parts) == 3:
                            try:
                                sz = int(parts[1])
                                target = parts[2].strip()
                                if sz >= 0:
                                    results[target] = sz
                            except ValueError:
                                pass
        except Exception:
            pass

    return results


def broadcast_media_scan(phone_paths, adb_path=None, serial=None):
    """
    Broadcasts Android MEDIA_SCANNER_SCAN_FILE intents for restored media items
    so native Android Gallery and Google Photos immediately index them.
    """
    if not phone_paths:
        return 0

    cmd = find_adb_binary(adb_path)
    base_cmd = [cmd]
    if serial:
        base_cmd.extend(["-s", serial])

    scanned = 0
    batch_size = 20
    for i in range(0, len(phone_paths), batch_size):
        chunk = phone_paths[i : i + batch_size]
        cmds = []
        for p in chunk:
            clean_p = p.replace("'", "'\\''")
            cmds.append(f"am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d 'file://{clean_p}' >/dev/null 2>&1")
        full_sh = " ; ".join(cmds)
        try:
            subprocess.run(
                base_cmd + ["shell", full_sh],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            scanned += len(chunk)
        except Exception:
            pass

    return scanned


def batch_delete_phone_files(
    phone_paths,
    base_path=None,
    adb_path=None,
    serial=None,
    batch_size=100,
    progress_callback=None,
    cancel_event=None,
):
    """
    Deletes files from Android storage in high-performance batches.
    Includes strict path sanitization ensuring only WhatsApp media directories are touched.
    """
    if cancel_event and cancel_event.is_set():
        return {"success": False, "deleted_count": 0, "failed_count": 0, "errors": ["Deletion cancelled by user"]}
    if not phone_paths:
        return {"success": True, "deleted_count": 0, "failed_count": 0, "errors": []}

    cmd = find_adb_binary(adb_path)
    dev = check_adb_device(adb_path=adb_path)
    if not dev.connected:
        return {"success": False, "deleted_count": 0, "failed_count": 0, "errors": [f"Phone not connected: {dev.error or 'No USB device detected'}"]}
    if not dev.authorized:
        return {"success": False, "deleted_count": 0, "failed_count": 0, "errors": ["Phone is connected but unauthorized. Please allow USB debugging on your device."]}

    base_cmd = [cmd]
    if serial:
        base_cmd.extend(["-s", serial])

    if not base_path:
        base_path = discover_android_base_path(adb_path=adb_path, device_serial=serial)

    sanitized_paths = []
    for p in phone_paths:
        if not p:
            continue
        norm = p.replace("\\", "/").strip()
        if not norm.startswith("/"):
            if base_path:
                full = f"{base_path.rstrip('/')}/{norm}"
            else:
                full = f"/storage/emulated/0/{norm}"
        else:
            full = norm

        # Safety Guard: Only delete inside legitimate WhatsApp media directories
        whatsapp_signatures = (
            "com.whatsapp",
            "com.whatsapp.w4b",
            "WhatsApp/Media",
            "WhatsApp Business/Media",
            "WhatsApp/accounts",
            "DualApp/WhatsApp",
            "DUAL_APP/WhatsApp",
            "Parallel/WhatsApp",
            "Clone/WhatsApp",
        )
        if any(full.startswith(bad) for bad in ("/system", "/data/system", "/sbin", "/vendor", "/etc")):
            continue
        if any(sig in full for sig in whatsapp_signatures):
            sanitized_paths.append(full)

    if not sanitized_paths:
        return {"success": True, "deleted_count": 0, "failed_count": 0, "errors": ["No eligible paths to delete"]}

    total = len(sanitized_paths)
    deleted = 0
    failed = 0
    errors = []

    for i in range(0, total, batch_size):
        if cancel_event and cancel_event.is_set():
            errors.append("Deletion cancelled by user")
            break

        chunk = sanitized_paths[i : i + batch_size]
        escaped_chunk = []
        for p in chunk:
            esc = p.replace("'", "'\\''")
            escaped_chunk.append(f"'{esc}'")
        rm_cmd = "rm -f " + " ".join(escaped_chunk)

        try:
            res = subprocess.run(
                base_cmd + ["shell", rm_cmd],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if res.returncode == 0:
                deleted += len(chunk)
            else:
                err_text = (res.stderr or "").strip()
                failed += len(chunk)
                errors.append(err_text or f"rm returned exit code {res.returncode}")
                lower_err = err_text.lower()
                if any(s in lower_err for s in ("device not found", "device offline", "device unauthorized", "error: closed")):
                    errors.append("Phone was disconnected during cleanup")
                    break
        except Exception as e:
            failed += len(chunk)
            errors.append(str(e))

        if progress_callback:
            try:
                progress_callback(deleted, total)
            except Exception:
                pass

    return {
        "success": failed == 0,
        "deleted_count": deleted,
        "failed_count": failed,
        "errors": errors,
    }


def restore_chat_to_phone(
    chat_jid,
    output_dir,
    base_path=None,
    adb_path=None,
    serial=None,
    progress_callback=None,
    cancel_event=None,
):
    """
    Restores media files for a specific chat back to the phone.
    Handles device connection checks, WhatsApp existence check ("no whatsapp at all"),
    pre-flight storage safety buffer check (+20% safety buffer + 500MB),
    folder accessibility/mkdir verification, USB disconnection handling, and user cancellation.
    """
    out_p = Path(output_dir).resolve()
    from core.gallery import load_gallery_data

    gal_data = load_gallery_data(out_p)
    matched_chat = None
    for c in gal_data.get("chats", []):
        if c.get("jid") == chat_jid:
            matched_chat = c
            break

    if not matched_chat:
        return {"success": False, "cancelled": False, "disconnected": False, "error": f"Chat with JID '{chat_jid}' not found in local backup"}

    media_items = matched_chat.get("media", [])
    if not media_items:
        return {"success": False, "cancelled": False, "disconnected": False, "error": "No media items found in this chat to restore"}

    files_to_push = []
    total_bytes = 0
    for m in media_items:
        rel = m.get("rel_path")
        if not rel:
            continue
        local_f = (out_p / rel).resolve()
        if local_f.is_file():
            sz = local_f.stat().st_size
            files_to_push.append((local_f, m))
            total_bytes += sz

    if not files_to_push:
        return {"success": False, "cancelled": False, "disconnected": False, "error": "None of the chat media files exist on local PC storage"}

    # 1. Pre-flight phone connection and authorization check
    dev = check_adb_device(adb_path=adb_path)
    if not dev.connected:
        return {
            "success": False,
            "cancelled": False,
            "disconnected": True,
            "error": f"Phone not connected via USB: {getattr(dev, 'error', None) or getattr(dev, 'reason', None) or 'No device detected'}",
        }
    if not dev.authorized:
        return {
            "success": False,
            "cancelled": False,
            "disconnected": False,
            "error": "Phone is connected but unauthorized. Please allow USB debugging on your device.",
        }

    cmd = find_adb_binary(adb_path)
    base_cmd = [cmd]
    if serial:
        base_cmd.extend(["-s", serial])

    # 2. Check if WhatsApp is installed or WhatsApp storage folder exists ("no whatsapp at all")
    pkg_installed = False
    try:
        pm_res = subprocess.run(
            base_cmd + ["shell", "pm path com.whatsapp || pm path com.whatsapp.w4b"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if pm_res.returncode == 0 and "package:" in (pm_res.stdout or ""):
            pkg_installed = True
    except Exception:
        pass

    if not base_path:
        base_path = discover_android_base_path(adb_path=adb_path, device_serial=serial)

    base_exists = False
    if base_path:
        try:
            chk_res = subprocess.run(
                base_cmd + ["shell", f"[ -d '{base_path}' ] && echo 'EXISTS'"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if chk_res.returncode == 0:
                base_exists = True
        except Exception:
            pass

    if not pkg_installed and not base_exists:
        return {
            "success": False,
            "cancelled": False,
            "disconnected": False,
            "error": "WhatsApp is not installed on this device (com.whatsapp package and storage folders not found).",
        }

    if not base_path:
        base_path = "/storage/emulated/0/Android/media/com.whatsapp/WhatsApp/Media"
    elif not base_path.rstrip("/").endswith(("/Media", "/media")):
        base_path = f"{base_path.rstrip('/')}/Media"

    is_w4b = "com.whatsapp.w4b" in base_path or "WhatsApp Business" in base_path
    prefix = "WhatsApp Business" if is_w4b else "WhatsApp"

    # 3. Pre-flight phone storage safety buffer check
    storage_info = get_device_storage_info(adb_path=adb_path, serial=serial)
    free_bytes = storage_info.get("free_bytes", 0)
    required_bytes = int(total_bytes * 1.20) + (500 * 1024 * 1024)

    if free_bytes > 0 and free_bytes < required_bytes:
        req_mb = round(required_bytes / (1024 * 1024), 1)
        free_mb = round(free_bytes / (1024 * 1024), 1)
        return {
            "success": False,
            "cancelled": False,
            "disconnected": False,
            "error": f"Insufficient phone storage. Required: {req_mb} MB (includes 20% safety buffer), Free: {free_mb} MB",
        }

    # 4. Pre-flight target directory access check
    try:
        base_path_esc = base_path.replace("'", "'\\''")
        mkdir_base = subprocess.run(
            base_cmd + ["shell", f"mkdir -p '{base_path_esc}'"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if mkdir_base.returncode != 0:
            err_msg = mkdir_base.stderr.strip() if mkdir_base.stderr else "Storage inaccessible or read-only"
            return {
                "success": False,
                "cancelled": False,
                "disconnected": False,
                "error": f"Failed to access or create WhatsApp media directory on device ({base_path}): {err_msg}",
            }
    except Exception as e:
        return {
            "success": False,
            "cancelled": False,
            "disconnected": False,
            "error": f"Failed to access or create WhatsApp media directory on device ({base_path}): {e}",
        }

    planned_items = []
    for local_file, meta in files_to_push:
        fn = local_file.name
        mime = (meta.get("mime_type") or "").lower()
        if mime.startswith("video/") or fn.lower().endswith((".mp4", ".3gp")):
            sub_folder = f"{prefix} Video"
        elif mime.startswith("image/") or fn.lower().endswith((".jpg", ".jpeg", ".png")):
            sub_folder = f"{prefix} Images"
        elif mime.startswith("audio/") or fn.lower().endswith((".opus", ".mp3", ".ogg")):
            sub_folder = f"{prefix} Audio"
        elif meta.get("is_doc"):
            sub_folder = f"{prefix} Documents"
        else:
            sub_folder = f"{prefix} Documents"

        is_sent = bool(meta.get("from_me"))
        if not is_sent and meta.get("phone_path") and "/sent/" in meta.get("phone_path").lower():
            is_sent = True

        target_dir = f"{base_path.rstrip('/')}/{sub_folder}/Sent" if is_sent else f"{base_path.rstrip('/')}/{sub_folder}"
        target_path = f"{target_dir}/{fn}"
        planned_items.append((local_file, meta, sub_folder, target_dir, target_path))

    # Pre-query existing file sizes on phone to skip pushing duplicate files with identical size
    target_paths = [item[4] for item in planned_items]
    remote_sizes = get_remote_file_sizes(target_paths, adb_path=adb_path, serial=serial)

    restored_count = 0
    skipped_count = 0
    restored_bytes = 0
    skipped_bytes = 0
    restored_paths = []
    errors = []
    is_cancelled = False
    disconnected = False

    for idx, (local_file, meta, sub_folder, target_dir, target_path) in enumerate(planned_items):
        if cancel_event and cancel_event.is_set():
            is_cancelled = True
            errors.append("Restore cancelled by user")
            break

        fn = local_file.name
        local_size = local_file.stat().st_size
        remote_size = remote_sizes.get(target_path)

        # Check if file already exists on phone with the exact same size
        if remote_size is not None and remote_size == local_size:
            skipped_count += 1
            skipped_bytes += local_size
            restored_paths.append(target_path)
            if progress_callback:
                try:
                    progress_callback(restored_count + skipped_count, len(planned_items))
                except Exception:
                    pass
            continue

        try:
            target_dir_esc = target_dir.replace("'", "'\\''")
            mkdir_res = subprocess.run(
                base_cmd + ["shell", f"mkdir -p '{target_dir_esc}'"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if mkdir_res.returncode != 0:
                errors.append(f"Failed to create target folder {sub_folder}: {mkdir_res.stderr.strip()}")
                continue

            push_res = subprocess.run(
                base_cmd + ["push", str(local_file), target_path],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            err_out = (push_res.stderr or "") + " " + (push_res.stdout or "")
            if push_res.returncode == 0:
                restored_count += 1
                restored_bytes += local_size
                restored_paths.append(target_path)
            else:
                lower_err = err_out.lower()
                if any(s in lower_err for s in ("device not found", "device offline", "device unauthorized", "error: closed", "protocol fault")):
                    disconnected = True
                    errors.append(f"Phone disconnected during transfer: {err_out.strip()}")
                    break
                elif "no space left on device" in lower_err:
                    errors.append(f"Phone storage full: {err_out.strip()}")
                    break
                else:
                    errors.append(f"Failed to push {fn}: {push_res.stderr.strip()}")
        except subprocess.TimeoutExpired:
            errors.append(f"Timeout pushing {fn} to phone (device may be disconnected)")
            chk = check_adb_device(adb_path=adb_path)
            if not chk.connected:
                disconnected = True
                break
        except Exception as e:
            errors.append(f"Error restoring {fn}: {e}")

        if progress_callback:
            try:
                progress_callback(restored_count + skipped_count, len(planned_items))
            except Exception:
                pass

    if restored_paths:
        try:
            broadcast_media_scan(restored_paths, adb_path=adb_path, serial=serial)
        except Exception as e:
            errors.append(f"Media scanner warning: {e}")

    total_effective = restored_count + skipped_count
    return {
        "success": total_effective > 0 and not disconnected and not is_cancelled,
        "cancelled": is_cancelled,
        "disconnected": disconnected,
        "restored_count": restored_count,
        "skipped_count": skipped_count,
        "total_attempted": len(files_to_push),
        "restored_bytes": restored_bytes,
        "skipped_bytes": skipped_bytes,
        "errors": errors,
    }


