"""
Unit tests for core.device_inventory.DeviceInventory:
- status calls never block on the slow WhatsApp account scan
- only one scan runs at a time, however many pollers ask
- a refresh keeps serving the previous accounts (stale) instead of an empty list
- ?wait semantics, forced refresh, TTL expiry, phone swap and unplug handling
"""

import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.adb import DeviceStatus
from core.device_inventory import SCAN_IDLE, SCAN_READY, SCAN_SCANNING, DeviceInventory


class FakePhone:
    def __init__(self):
        self.status = DeviceStatus(True, True, "", "SERIAL1", "Pixel", usb_debugging=True)
        self.scan_calls = 0
        self.release = threading.Event()
        self.release.set()
        self.accounts = [{"path": "/sdcard/WhatsApp", "latest_db_mtime": 123}]

    def check(self):
        return self.status

    def discover(self, device_serial=None):
        self.scan_calls += 1
        self.release.wait(5)
        return [dict(a, serial=device_serial) for a in self.accounts]


class TestDeviceInventory(unittest.TestCase):
    def setUp(self):
        self.phone = FakePhone()
        self.inv = DeviceInventory(check_fn=self.phone.check, discover_fn=self.phone.discover,
                                   accounts_ttl=60, connection_ttl=0)

    def test_01_status_does_not_block_on_scan(self):
        self.phone.release.clear()
        start = time.time()
        snap = self.inv.snapshot()
        self.assertLess(time.time() - start, 0.5)
        self.assertTrue(snap["connected"])
        self.assertEqual(snap["accounts_scan"]["state"], SCAN_SCANNING)
        self.assertEqual(snap["accounts"], [])
        self.phone.release.set()

    def test_02_single_flight_across_concurrent_pollers(self):
        self.phone.release.clear()
        threads = [threading.Thread(target=self.inv.snapshot) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.phone.release.set()
        snap = self.inv.snapshot(wait_timeout=2)
        self.assertEqual(self.phone.scan_calls, 1)
        self.assertEqual(snap["accounts_scan"]["state"], SCAN_READY)
        self.assertEqual(len(snap["accounts"]), 1)

    def test_03_cached_until_ttl_and_refresh_keeps_stale_accounts(self):
        self.inv.snapshot(wait_timeout=2)
        self.inv.snapshot()
        self.assertEqual(self.phone.scan_calls, 1, "fresh result must be reused")

        self.phone.release.clear()
        snap = self.inv.snapshot(refresh=True)
        self.assertEqual(snap["accounts_scan"]["state"], SCAN_SCANNING)
        self.assertTrue(snap["accounts_scan"]["stale"])
        self.assertEqual(len(snap["accounts"]), 1, "previous accounts must stay visible while rescanning")
        self.phone.release.set()
        snap = self.inv.snapshot(wait_timeout=2)
        self.assertEqual(snap["accounts_scan"]["state"], SCAN_READY)
        self.assertEqual(self.phone.scan_calls, 2)

    def test_04_ttl_expiry_triggers_background_rescan(self):
        inv = DeviceInventory(check_fn=self.phone.check, discover_fn=self.phone.discover,
                              accounts_ttl=0.05, connection_ttl=0)
        inv.snapshot(wait_timeout=2)
        time.sleep(0.1)
        inv.snapshot(wait_timeout=2)
        self.assertEqual(self.phone.scan_calls, 2)

    def test_05_new_phone_drops_previous_accounts(self):
        self.inv.snapshot(wait_timeout=2)
        self.phone.status = DeviceStatus(True, True, "", "SERIAL2", "Galaxy", usb_debugging=True)
        self.phone.release.clear()
        snap = self.inv.snapshot()
        self.assertEqual(snap["accounts"], [], "accounts of a different phone must not leak")
        self.phone.release.set()
        snap = self.inv.snapshot(wait_timeout=2)
        self.assertEqual(snap["accounts"][0]["serial"], "SERIAL2")

    def test_06_unplugged_phone_reports_idle_without_scanning(self):
        self.phone.status = DeviceStatus(False, False, "No device", "", "", usb_debugging=True)
        snap = self.inv.snapshot(wait_timeout=1)
        self.assertEqual(snap["accounts_scan"]["state"], SCAN_IDLE)
        self.assertEqual(snap["accounts"], [])
        self.assertEqual(self.phone.scan_calls, 0)


if __name__ == "__main__":
    unittest.main()
