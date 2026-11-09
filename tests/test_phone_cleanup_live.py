"""
Phone cleanup on a simulated phone (tests/fake_phone.py): the files really go, over one shell
session, with live progress per batch, and nothing is claimed that the phone did not confirm.
"""

import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from core import adb  # noqa: E402
from fake_phone import FakePhone, supported  # noqa: E402

BASE = "/storage/emulated/0/Android/media/com.whatsapp/WhatsApp"
IMAGES = f"{BASE}/Media/WhatsApp Images"


class PhoneCleanup(unittest.TestCase):
    def setUp(self):
        if not supported():
            self.skipTest("needs Linux with GNU tar")
        self.tmp = Path(tempfile.mkdtemp(prefix="wa_clean_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.phone = FakePhone(self.tmp)
        p = mock.patch("core.adb.find_adb_binary", return_value=self.phone.adb_path)
        p.start()
        self.addCleanup(p.stop)

    def files(self, n, name="IMG {i} it's \"q\" (1).jpg"):
        paths = []
        for i in range(n):
            path = f"{IMAGES}/{name.format(i=i)}"
            self.phone.add(path, b"x" * (100 + i))
            paths.append(path)
        return paths

    def on_phone(self, path):
        return self.phone.host(path).exists()

    def test_files_are_deleted_with_live_progress(self):
        paths = self.files(60)
        events, progress = [], []
        res = adb.batch_delete_phone_files(paths, base_path=BASE, on_batch=events.append,
                                           progress_callback=lambda d, t: progress.append((d, t)))
        self.assertTrue(res["success"], res)
        self.assertEqual(res["deleted_count"], 60)
        self.assertEqual(sorted(res["deleted_paths"]), sorted(paths))
        self.assertFalse(any(self.on_phone(p) for p in paths))
        # one session, batches of 25: start/done pairs, in order, adding up
        self.assertEqual([e["event"] for e in events], ["start", "done"] * 3)
        self.assertEqual([len(e["paths"]) for e in events if e["event"] == "start"], [25, 25, 10])
        self.assertEqual([e["deleted_count"] for e in events if e["event"] == "done"], [25, 50, 60])
        self.assertEqual(progress, [(25, 60), (50, 60), (60, 60)])
        shells = [c for c in self.phone.calls() if c.endswith("shell sh")]
        self.assertEqual(len(shells), 1, "one adb shell session for the whole cleanup")

    def test_relative_paths_and_the_safety_guard(self):
        kept = "/storage/emulated/0/DCIM/Camera/IMG_2026.jpg"
        self.phone.add(kept, b"camera")
        self.phone.add(f"{IMAGES}/rel.jpg", b"r")
        res = adb.batch_delete_phone_files(["Media/WhatsApp Images/rel.jpg", kept, "/system/bin/sh"], base_path=BASE)
        self.assertEqual(res["deleted_paths"], ["Media/WhatsApp Images/rel.jpg"])
        self.assertFalse(self.on_phone(f"{IMAGES}/rel.jpg"))
        self.assertTrue(self.on_phone(kept))

    def test_a_file_that_cannot_be_deleted_is_named(self):
        paths = self.files(5)
        stuck = f"{IMAGES}/stuck.jpg"
        self.phone.host(stuck).mkdir(parents=True)  # rm -f cannot remove a folder
        res = adb.batch_delete_phone_files(paths + [stuck], base_path=BASE)
        self.assertFalse(res["success"])
        self.assertEqual(res["failed_paths"], [stuck])
        self.assertEqual(res["deleted_count"], 5)

    def test_unplugged_phone_claims_nothing_unconfirmed(self):
        paths = self.files(60)
        self.phone.unplug_after(1)  # the first batch's line goes through, then the cable is pulled
        res = adb.batch_delete_phone_files(paths, base_path=BASE, batch_timeout=10)
        self.assertFalse(res["success"])
        self.assertTrue(any("disconnected" in e.lower() for e in res["errors"]))
        # Whatever the phone did not confirm is not counted as deleted
        for p in res["deleted_paths"]:
            self.assertFalse(self.on_phone(p))
        self.assertLess(res["deleted_count"], 60)
        self.assertTrue(set(res["deleted_paths"]).isdisjoint(res["failed_paths"]))

    def test_cancel_between_batches(self):
        paths = self.files(60)
        cancel = threading.Event()

        def on_batch(event):
            if event["event"] == "done":
                cancel.set()  # the user presses Cancel during the first batch

        res = adb.batch_delete_phone_files(paths, base_path=BASE, on_batch=on_batch, cancel_event=cancel)
        self.assertEqual(res["deleted_count"], 25)
        self.assertIn("cancelled", " ".join(res["errors"]))
        self.assertEqual(sum(self.on_phone(p) for p in paths), 35)


class ProgressForThePage(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wa_progress_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_the_progress_record_follows_the_batches(self):
        import core.server as srv
        prog = srv.CleanProgress()
        f = lambda n: {"name": f"IMG-{n}.jpg", "chat": "Family", "size": 10}
        prog.update({"event": "begin", "total": 3, "total_bytes": 30})
        prog.update({"event": "start", "files": [f(1), f(2)]})
        snap = prog.snapshot()
        self.assertTrue(snap["active"])
        self.assertEqual([x["name"] for x in snap["current"]], ["IMG-1.jpg", "IMG-2.jpg"])
        self.assertIsNone(snap["seconds_per_file"])
        prog.update({"event": "done", "files": [f(1), f(2)], "failed": [], "deleted_count": 2,
                     "failed_count": 0, "freed_bytes": 20})
        snap = prog.snapshot()
        self.assertEqual((snap["deleted"], snap["freed_bytes"], snap["current"]), (2, 20, []))
        self.assertIsNotNone(snap["seconds_per_file"])
        self.assertEqual([x["name"] for x in snap["recent"]], ["IMG-1.jpg", "IMG-2.jpg"])
        prog.finish({"success": True, "deleted_count": 2, "failed_count": 0, "freed_bytes": 20, "errors": []})
        self.assertFalse(prog.snapshot()["active"])

    def test_freed_space_counts_only_confirmed_files(self):
        from core import clean_planner
        plan = {"candidates": [
            {"phone_path": f"{IMAGES}/a.jpg", "size_bytes": 100, "filename": "a.jpg", "chat_name": "A"},
            {"phone_path": f"{IMAGES}/b.jpg", "size_bytes": 200, "filename": "b.jpg", "chat_name": "B"},
            {"phone_path": f"{IMAGES}/c.jpg", "size_bytes": 400, "filename": "c.jpg", "chat_name": "C"},
        ]}
        events = []

        def fake_delete(paths, on_batch=None, **kw):
            # The middle file fails: the first two in plan order are not what was freed
            on_batch({"event": "start", "paths": paths})
            sizes = {paths[0]: 100, paths[2]: 400}
            on_batch({"event": "done", "deleted": [paths[0], paths[2]], "deleted_sizes": sizes,
                      "failed": [paths[1]], "failed_reasons": {paths[1]: "Permission denied"},
                      "not_found": [], "skipped": {}, "deleted_count": 2, "failed_count": 1,
                      "not_found_count": 0, "skipped_count": 0, "total": 3, "freed_bytes": 500})
            return {"success": False, "deleted_count": 2, "failed_count": 1, "errors": ["1 file(s) could not be deleted"],
                    "deleted_paths": [paths[0], paths[2]], "deleted_sizes": sizes, "failed_paths": [paths[1]],
                    "not_done_paths": [], "unknown_paths": []}

        with mock.patch("core.adb.batch_delete_phone_files", side_effect=fake_delete):
            res = clean_planner.execute_clean_plan(plan, str(self.tmp), on_progress=events.append)
        self.assertEqual(res["freed_bytes"], 500)
        self.assertEqual([e["event"] for e in events], ["begin", "start", "done"])
        self.assertEqual(events[1]["files"][1], {"name": "b.jpg", "chat": "B", "size": 200})
        self.assertEqual(events[2]["freed_bytes"], 500)
        self.assertEqual([x["name"] for x in events[2]["failed"]], ["b.jpg"])


if __name__ == "__main__":
    unittest.main()
