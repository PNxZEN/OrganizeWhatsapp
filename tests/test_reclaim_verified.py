"""
Reclaim Space on a simulated phone (tests/fake_phone.py): the estimate is what is really on the
phone, only verified files are deleted, every run is recorded, and an older cleanup can be
checked afterwards. Reproduces the gap seen with v1.2.4 (an estimate of 23.7 GB, 7-8 GB freed).
"""

import csv
import json
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

from core import clean_planner, reclaim_history  # noqa: E402
from core.adb import phone_md5, phone_media_inventory  # noqa: E402
from fake_phone import FakePhone, supported  # noqa: E402

STORE = "/storage/emulated/0/Android/media/com.whatsapp/WhatsApp"
VIDEO = f"{STORE}/Media/WhatsApp Video"
ACC_VIDEO = f"{STORE}/accounts/1002/Media/WhatsApp Video"
OLD = "2023-01-05 10:00:00"
RULES = {"min_age_days": 0, "keep_starred": False, "media_types": ["videos"]}


class ReclaimOnASimulatedPhone(unittest.TestCase):
    def setUp(self):
        if not supported():
            self.skipTest("needs Linux with GNU tar")
        self.tmp = Path(tempfile.mkdtemp(prefix="wa_reclaim_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.out = self.tmp / "output"
        self.out.mkdir()
        self.phone = FakePhone(self.tmp)
        p = mock.patch("core.adb.find_adb_binary", return_value=self.phone.adb_path)
        p.start()
        self.addCleanup(p.stop)
        self.rows = []

    def video(self, name, phone_path=None, recorded=True, on_phone=True, chat="Family", size=1000, pc_data=None):
        data = (name.encode() * 400)[:size]
        rel = f"{chat}/2023-01/{name}"
        (self.out / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.out / rel).write_bytes(pc_data if pc_data is not None else data)
        phone_path = phone_path or f"{VIDEO}/{name}"
        if on_phone:
            self.phone.add(phone_path, data)
        self.rows.append({"chat_jid": f"{chat}@g.us", "chat_name": chat, "filename": name, "rel_path": rel,
                          "size_bytes": len(pc_data if pc_data is not None else data), "mime_type": "video/mp4",
                          "received_at": OLD, "phone_path": phone_path if recorded else "", "is_doc": "False",
                          "starred": "0", "from_me": "0"})
        return phone_path

    def write_index(self):
        with open(self.out / "media_index.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(self.rows[0].keys()))
            w.writeheader()
            w.writerows(self.rows)

    def hooks(self):
        return {"storage_root": STORE, "phone_inventory": phone_media_inventory, "md5_on_phone": phone_md5,
                "phone_free_bytes": lambda: 10 ** 9}

    def build_gap_library(self):
        self.present = [self.video(f"VID-2023010{i % 9}-WA00{i:02d}.mp4") for i in range(10)]
        # No phone path recorded (older versions, imports): the guessed path is wrong, the file is in accounts/1002
        self.elsewhere = [self.video(f"VID-20230201-WA00{i:02d}.mp4", phone_path=f"{ACC_VIDEO}/VID-20230201-WA00{i:02d}.mp4",
                                     recorded=False) for i in range(5)]
        # Already gone from the phone (deleted earlier, or never there)
        self.gone = [self.video(f"VID-20230301-WA00{i:02d}.mp4", on_phone=False) for i in range(5)]
        # The same phone file listed twice
        self.rows.append(dict(self.rows[0], rel_path=self.rows[0]["rel_path"]))
        # A guessed path holding a different file of the same size (another chat's)
        self.video("VID-20230401-WA0001.mp4", recorded=False, pc_data=b"y" * 1000)
        self.write_index()

    def plan(self, verify=True):
        plan = clean_planner.generate_clean_plan(str(self.out), profile=clean_planner.CleanProfile.CUSTOM,
                                                 custom_config=RULES)
        if verify:
            h = self.hooks()
            clean_planner.verify_plan_on_phone(plan, str(self.out), h["phone_inventory"](), h["storage_root"],
                                               h["md5_on_phone"])
        return plan

    # --- the estimate --------------------------------------------------------------------------

    def test_the_estimate_is_what_is_on_the_phone(self):
        self.build_gap_library()
        unchecked = self.plan(verify=False)
        self.assertEqual(unchecked["reclaimable_files_count"], 22)  # what v1.2.4 promised
        plan = self.plan()
        check = plan["phone_check"]
        self.assertEqual(check["on_phone"]["count"], 15)
        self.assertEqual(check["found_elsewhere"]["count"], 5)
        self.assertEqual(check["not_on_phone"]["count"], 5)
        self.assertEqual(check["duplicates"]["count"], 1)
        self.assertEqual(check["differs"]["count"], 1)
        self.assertEqual(plan["reclaimable_files_count"], 15)
        self.assertEqual(plan["reclaimable_bytes"], 15 * 1000)
        self.assertEqual(check["estimate_before_check"], 22 * 1000)
        paths = {c["phone_path"] for c in plan["candidates"]}
        self.assertTrue(set(self.elsewhere) <= paths, "found where they really are")
        self.assertEqual(sum(c["count"] for c in plan["breakdown"]["by_chat"]), 15)

    def test_another_accounts_folder_is_never_searched(self):
        # The library's account is the main folder: accounts/1002 is another account's, even
        # when it holds a file with the same name, size and contents
        self.build_gap_library()
        plan = clean_planner.generate_clean_plan(str(self.out), profile=clean_planner.CleanProfile.CUSTOM,
                                                 custom_config=RULES)
        h = self.hooks()
        clean_planner.verify_plan_on_phone(plan, str(self.out), h["phone_inventory"](), STORE, h["md5_on_phone"],
                                           search_folders=[f"{STORE}/Media"])
        paths = {c["phone_path"] for c in plan["candidates"]}
        self.assertFalse(paths & set(self.elsewhere))
        self.assertEqual(plan["phone_check"]["not_on_phone"]["count"], 5 + 5)
        clean_planner.execute_clean_plan(plan, str(self.out), **h)
        for p in self.elsewhere:
            self.assertTrue(self.phone.host(p).exists(), "another account's file stays")

    # --- the deletion --------------------------------------------------------------------------

    def test_only_verified_files_are_deleted_and_the_run_is_recorded(self):
        self.build_gap_library()
        plan = self.plan()
        res = clean_planner.execute_clean_plan(plan, str(self.out), **self.hooks())
        self.assertTrue(res["success"], res)
        self.assertEqual(res["deleted_count"], 15)
        self.assertEqual(res["freed_bytes"], 15 * 1000)
        for p in self.present + self.elsewhere:
            self.assertFalse(self.phone.host(p).exists(), p)
        self.assertTrue(self.phone.host(f"{VIDEO}/VID-20230401-WA0001.mp4").exists(), "another file: never deleted")
        # Every PC copy is still there
        for r in self.rows:
            self.assertTrue((self.out / r["rel_path"]).is_file())

        runs = reclaim_history.list_runs(self.out)
        self.assertEqual(len(runs), 1)
        run = runs[0]
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["counts"]["deleted"], 15)
        self.assertEqual(run["bytes"]["deleted"], 15 * 1000)
        self.assertEqual(run["estimate_before_check"], 22 * 1000)
        self.assertEqual(run["counts"]["not_on_phone"], 5, "the record explains the whole estimate")
        detail = reclaim_history.read_run(self.out, run["run_id"], status="deleted")
        self.assertEqual(detail["matched"], 15)
        csv_text = reclaim_history.run_csv(self.out, run["run_id"])
        self.assertIn("not_on_phone", csv_text)
        self.assertIsNone(clean_planner.get_active_plan(plan["plan_id"]), "a plan runs once")

    def test_a_changed_pc_copy_keeps_the_phone_file(self):
        self.build_gap_library()
        plan = self.plan()
        changed = self.out / self.rows[2]["rel_path"]
        changed.write_bytes(b"edited on the PC")  # after the plan, before the deletion
        res = clean_planner.execute_clean_plan(plan, str(self.out), **self.hooks())
        # this one, and from the plan check the different file; the row listed twice is its own kind
        self.assertEqual(res["skipped_count"], 1 + 1)
        self.assertEqual(res["duplicate_count"], 1)
        self.assertTrue(self.phone.host(self.present[2]).exists())
        detail = reclaim_history.read_run(self.out, res["run_id"], status="skipped")
        self.assertTrue(any("differs from its PC copy" in (f["reason"] or "") for f in detail["files"]))

    def test_an_unplugged_phone_leaves_an_exact_record(self):
        self.build_gap_library()
        plan = self.plan()
        self.phone.unplug_after(1)  # the first batch's check goes through, then the cable is pulled
        res = clean_planner.execute_clean_plan(plan, str(self.out), **self.hooks())
        self.assertFalse(res["success"])
        run = reclaim_history.list_runs(self.out)[0]
        self.assertEqual(run["status"], "interrupted")
        c = run["counts"]
        self.assertEqual(c["deleted"] + c["unknown"] + c["not_done"], 15)
        detail = reclaim_history.read_run(self.out, run["run_id"])
        statuses = {f["status"] for f in detail["files"]}
        self.assertTrue(statuses & {"unknown", "not_done"})
        for r in self.rows:
            self.assertTrue((self.out / r["rel_path"]).is_file(), "the PC copies are untouched")
        # Plugged back in: a new plan finds exactly what is still there
        self.phone.unplug_file.unlink()
        again = self.plan()
        still = sum(self.phone.host(p).exists() for p in self.present + self.elsewhere)
        self.assertEqual(again["reclaimable_files_count"], still)

    def test_cancel_records_what_was_not_reached(self):
        self.build_gap_library()
        plan = self.plan()
        cancel = threading.Event()
        cancel.set()
        res = clean_planner.execute_clean_plan(plan, str(self.out), cancel_event=cancel, **self.hooks())
        run = reclaim_history.list_runs(self.out)[0]
        self.assertEqual(run["status"], "cancelled")
        self.assertEqual(run["counts"]["not_done"], 15)
        self.assertEqual(res["deleted_count"], 0)

    def test_a_plan_made_without_the_phone_is_checked_before_deleting(self):
        self.build_gap_library()
        plan = self.plan(verify=False)  # the phone was not connected while analysing
        res = clean_planner.execute_clean_plan(plan, str(self.out), **self.hooks())
        self.assertEqual(res["deleted_count"], 15)
        self.assertTrue(self.phone.host(f"{VIDEO}/VID-20230401-WA0001.mp4").exists())

    def test_a_run_cut_off_by_a_crash_reads_as_interrupted(self):
        run = reclaim_history.CleanupRun(self.out, {"planned_files": 3})
        run.record([{"status": "deleted", "name": "a.mp4", "size": 5}])
        reclaim_history._running.pop(run.run_id)  # the app stopped without finishing it
        with open(self.out / reclaim_history.HISTORY_DIR / f"{run.run_id}.jsonl", "a") as f:
            f.write('{"status": "dele')  # a line cut off mid-write
        listed = reclaim_history.list_runs(self.out)[0]
        self.assertEqual(listed["status"], "interrupted")
        self.assertEqual(reclaim_history.read_run(self.out, run.run_id)["matched"], 1)
        self.assertIsNone(reclaim_history.read_run(self.out, "../../etc"))

    # --- after a cleanup by an older version -----------------------------------------------------

    def test_checking_the_phone_after_an_older_cleanup(self):
        self.build_gap_library()
        # v1.2.4 deleted the files at their recorded paths and "deleted" the guessed ones (rm -f
        # of paths that do not exist): those are still on the phone
        for p in self.present:
            self.phone.host(p).unlink()
        report = clean_planner.audit_phone_vs_library(str(self.out), phone_media_inventory(), STORE)
        s = report["summary"]
        self.assertEqual(s["gone_from_phone"]["count"], 10 + 5)
        self.assertEqual(s["on_phone_elsewhere"]["count"], 5)
        self.assertEqual(s["on_phone_elsewhere"]["bytes"], 5 * 1000)
        found = {x["found"] for x in report["samples"]["on_phone_elsewhere"]}
        self.assertEqual(found, set(self.elsewhere))



class OneThingOnThePhoneAtATime(unittest.TestCase):
    def test_no_sync_starts_during_a_cleanup(self):
        import core.server as srv
        tmp = Path(tempfile.mkdtemp(prefix="wa_lock_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        self.assertTrue(srv._clean_run_lock.acquire(blocking=False))
        try:
            self.assertFalse(srv._start_background_sync(str(tmp)))
            self.assertIn("cleanup", srv._sync_busy_payload()["message"])
            self.assertFalse(srv._clean_run_lock.acquire(blocking=False), "a second cleanup waits")
        finally:
            srv._clean_run_lock.release()

if __name__ == "__main__":
    unittest.main()
