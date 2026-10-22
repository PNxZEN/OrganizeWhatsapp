"""Phone detection over USB before USB debugging is on, and the setup stage (core/adb.py)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import adb  # noqa: E402
from core.adb import DeviceStatus  # noqa: E402
from core.device_inventory import DeviceInventory  # noqa: E402

IOREG = """+-o Root  <class IORegistryEntry, id 0x100000100, retain 25>
  +-o AppleT8112USBXHCI@00000000  <class AppleT8112USBXHCI, id 0x100000301>
    +-o USB3.1 Hub@00100000  <class IOUSBHostDevice, id 0x100000a01>
    | {
    |   "idVendor" = 3141
    |   "bDeviceClass" = 9
    |   "USB Product Name" = "USB3.1 Hub"
    | }
    +-o Redmi Note 12@00200000  <class IOUSBHostDevice, id 0x100000b01>
    | {
    |   "idVendor" = 10007
    |   "bDeviceClass" = 0
    |   "kUSBVendorString" = "Xiaomi"
    |   "kUSBProductString" = "Redmi Note 12"
    |   "kUSBSerialNumberString" = "abc123"
    | }
    +-o Magic Keyboard@00300000  <class IOUSBHostDevice, id 0x100000c01>
      {
        "idVendor" = 1452
        "USB Product Name" = "Magic Keyboard"
      }
"""


class UsbDetectionTests(unittest.TestCase):
    def test_01_macos_ioreg(self):
        found = adb.parse_macos_ioreg(IOREG)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["vendor"], "Xiaomi")
        self.assertEqual(found[0]["name"], "Xiaomi Redmi Note 12")
        self.assertEqual(found[0]["serial"], "abc123")
        self.assertEqual(adb.parse_macos_ioreg(""), [])

    def test_02_macos_older_property_names(self):
        text = '+-o Pixel 8@1  <class IOUSBDevice>\n  {\n    "idVendor" = 6353\n    "USB Vendor Name" = "Google"\n    "USB Product Name" = "Pixel 8"\n    "USB Serial Number" = "P8"\n  }\n'
        found = adb.parse_macos_ioreg(text)
        self.assertEqual([(f["vendor"], f["serial"]) for f in found], [("Google", "P8")])

    def test_03_linux_sysfs(self):
        root = Path(tempfile.mkdtemp())
        try:
            def dev(name, **files):
                d = root / name
                d.mkdir()
                for k, v in files.items():
                    (d / k).write_text(v + "\n")
            dev("1-1", idVendor="04e8", bDeviceClass="00", manufacturer="SAMSUNG", product="SAMSUNG_Android", serial="R5CT")
            if sys.platform != "win32":  # ":" cannot be in a Windows folder name (Linux names interfaces so)
                dev("1-1:1.0", idVendor="04e8")                  # interface, not a device
            dev("usb1", idVendor="1d6b", bDeviceClass="09", product="xHCI Host Controller")
            dev("1-2", idVendor="046d", bDeviceClass="00", product="USB Receiver")
            dev("1-3", idVendor="abcd", bDeviceClass="00", product="Android")  # unknown vendor, phone name
            found = adb.parse_linux_usb_devices(str(root))
            self.assertEqual([(f["vendor"], f["serial"]) for f in found], [("Samsung", "R5CT"), ("", "")])
            self.assertEqual(adb.parse_linux_usb_devices(str(root / "missing")), [])
        finally:
            shutil.rmtree(root)

    def test_04_peripherals_are_never_phones(self):
        self.assertIsNone(adb._android_usb_entry("18d1", "Google Wireless Headset"))
        self.assertIsNone(adb._android_usb_entry("1234", "Generic Mouse"))
        self.assertIsNotNone(adb._android_usb_entry("2717", ""))


def fake_adb(stdout="", returncode=0, missing=False):
    def run(cmd, **kw):
        if missing:
            raise FileNotFoundError("adb")
        return mock.Mock(returncode=returncode, stdout=stdout, stderr="")
    return run


class StageTests(unittest.TestCase):
    def check(self, stdout="", usb=(), missing=False):
        with mock.patch.object(adb.subprocess, "run", side_effect=fake_adb(stdout, missing=missing)), \
                mock.patch.object(adb, "detect_usb_android_hardware", return_value=list(usb)), \
                mock.patch.object(adb, "find_adb_binary", return_value="adb"):
            return adb.check_adb_device()

    HEADER = "List of devices attached\n"
    PHONE = {"name": "Galaxy", "vendor": "Samsung", "serial": "R5"}

    def test_10_stages(self):
        self.assertEqual(self.check(self.HEADER).stage, adb.STAGE_UNPLUGGED)
        st = self.check(self.HEADER, usb=[self.PHONE])
        self.assertEqual((st.stage, st.vendor, st.connected, st.usb_debugging), (adb.STAGE_USB_ONLY, "Samsung", True, False))
        self.assertEqual(self.check(self.HEADER + "R5\tunauthorized usb:1-1\n").stage, adb.STAGE_UNAUTHORIZED)
        self.assertEqual(self.check(self.HEADER + "R5\toffline\n").stage, adb.STAGE_OFFLINE)
        st = self.check(self.HEADER + "R5\tdevice usb:1-1 model:SM_S911B\n")
        self.assertEqual((st.stage, st.model, st.authorized), (adb.STAGE_READY, "SM_S911B", True))

    def test_11_linux_udev_permission_problem(self):
        line = "R5\tno permissions (user in plugdev group; are your udev rules wrong?); see [http://developer.android.com/tools/device.html]\n"
        st = self.check(self.HEADER + line)
        self.assertEqual(st.stage, adb.STAGE_NO_PERMISSION)
        self.assertTrue(st.connected and not st.authorized)

    def test_12_missing_adb_is_not_reported_as_debugging_off(self):
        self.assertEqual(self.check(missing=True, usb=[self.PHONE]).stage, adb.STAGE_NO_ADB)
        self.assertEqual(self.check(missing=True).stage, adb.STAGE_UNPLUGGED)

    def test_13_default_stage_for_old_style_statuses(self):
        self.assertEqual(DeviceStatus(True, True, "", "s", "m").stage, "ready")
        self.assertEqual(DeviceStatus(True, False, "", "s", "m").stage, "unauthorized")
        self.assertEqual(DeviceStatus(True, False, "", "s", "m", usb_debugging=False).stage, "usb_only")
        self.assertEqual(DeviceStatus(False, False, "", "", "").stage, "unplugged")


class StageTimerTests(unittest.TestCase):
    def test_20_time_on_a_step_resets_when_the_step_changes(self):
        status = {"v": DeviceStatus(False, False, "", "", "")}
        clock = {"t": 1000.0}
        with mock.patch("core.device_inventory.time.time", side_effect=lambda: clock["t"]):
            inv = DeviceInventory(check_fn=lambda: status["v"], discover_fn=lambda **k: [], connection_ttl=0)
            inv.snapshot()
            clock["t"] += 30
            snap = inv.snapshot()
            self.assertEqual((snap["stage"], snap["stage_seconds"]), ("unplugged", 30.0))
            status["v"] = DeviceStatus(True, False, "", "s", "Galaxy", usb_debugging=False, vendor="Samsung")
            clock["t"] += 5
            snap = inv.snapshot()
            self.assertEqual((snap["stage"], snap["stage_seconds"], snap["vendor"]), ("usb_only", 0.0, "Samsung"))
            clock["t"] += 12
            self.assertEqual(inv.snapshot()["stage_seconds"], 12.0)


if __name__ == "__main__":
    unittest.main()
