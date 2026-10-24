"""
Whole syncs against a simulated phone (tests/fake_phone.py): real crypt15 backups, real shell
commands, the same pipeline the app runs.

The phone has WhatsApp's account folders as on the beta tester's Samsung: the storage root
(Android/media/com.whatsapp/WhatsApp) holds the account's older media and an old backup, the
account now lives in accounts/1002, and accounts/1003 is a second WhatsApp account.
"""

import base64
import csv
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import core.pipeline as pipeline  # noqa: E402
from core.config import load_config, save_config  # noqa: E402
from core.decrypt import BackupIncompleteError, KeyMismatchError  # noqa: E402
from core import libraries  # noqa: E402
from core.config import set_active_profile  # noqa: E402
from core.decrypt import create_key_file  # noqa: E402
from core.sync_session import SyncSessionManager  # noqa: E402
from fake_phone import FakePhone, supported  # noqa: E402

HEX_KEY = "0f1e2d3c" * 8
OTHER_KEY = "9a8b7c6d" * 8  # accounts/1003 is another account, with its own key
MAIN = "/storage/emulated/0/Android/media/com.whatsapp/WhatsApp"
ACC = f"{MAIN}/accounts/1002"
OTHER = f"{MAIN}/accounts/1003"
T2023, T2025 = 1683000000, 1750000000


def _content(name):
    return (name * 40).encode() + os.urandom(64)


def _sha_b64(data):
    return base64.b64encode(hashlib.sha256(data).digest()).decode()


def _sha(data):
    return hashlib.sha256(data).hexdigest()


class SimulatedPhoneSync(unittest.TestCase):
    def setUp(self):
        if not supported():
            self.skipTest("needs Linux with GNU tar")
        self.tmp = Path(tempfile.mkdtemp(prefix="wa_phone_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cwd = os.getcwd()
        self.app = self.tmp / "app"
        self.app.mkdir()
        os.chdir(self.app)
        self.addCleanup(os.chdir, self.cwd)
        self.phone = FakePhone(self.tmp)
        for target in ("core.adb.find_adb_binary", "core.pipeline.find_adb_binary"):
            p = mock.patch(target, return_value=self.phone.adb_path)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch("time.sleep", return_value=None)  # the pipeline's waits for a backup
        p.start()
        self.addCleanup(p.stop)
        save_config({"hex_key": HEX_KEY, "selected_account_path": ACC})
        self.files = {}  # phone path -> bytes
        self.rows = []

    # --- the phone ---------------------------------------------------------------------------

    def media(self, folder, sub, name, in_db=True, chat="Family", ts="2024-05-01", data=None):
        data = data if data is not None else _content(name)
        path = f"{folder}/Media/{sub}/{name}"
        self.phone.add(path, data)
        self.files[path] = data
        if in_db:
            self.rows.append((chat, f"Media/{sub}/{name}", len(data), _sha_b64(data), ts))
        return path

    def backup(self, folder, rows, mtime, hex_key=HEX_KEY):
        """A real crypt15 chat backup with these media messages in folder/Databases."""
        db = self.tmp / f"msgstore_{uuid.uuid4().hex[:6]}.db"
        con = sqlite3.connect(db)
        con.executescript("""
            CREATE TABLE jid (_id INTEGER PRIMARY KEY, raw_string TEXT);
            CREATE TABLE chat (_id INTEGER PRIMARY KEY, jid_row_id INTEGER, subject TEXT);
            CREATE TABLE message (_id INTEGER PRIMARY KEY, chat_row_id INTEGER, timestamp INTEGER,
                                  starred INTEGER, from_me INTEGER, message_type INTEGER);
            CREATE TABLE message_media (message_row_id INTEGER, file_path TEXT, file_size INTEGER,
                                        mime_type TEXT, media_name TEXT, file_hash TEXT,
                                        enc_file_hash TEXT, original_file_hash TEXT,
                                        media_duration INTEGER);
            CREATE TABLE props (key TEXT, value TEXT);
        """)
        chats = {}
        for i, (chat, file_path, size, digest, day) in enumerate(rows, start=1):
            if chat not in chats:
                cid = len(chats) + 1
                chats[chat] = cid
                con.execute("INSERT INTO jid VALUES (?, ?)", (cid, f"12036300{cid}@g.us"))
                con.execute("INSERT INTO chat VALUES (?, ?, ?)", (cid, cid, chat))
            ts = int(time.mktime(time.strptime(day, "%Y-%m-%d"))) * 1000
            con.execute("INSERT INTO message VALUES (?, ?, ?, 0, 0, 1)", (i, chats[chat], ts))
            con.execute("INSERT INTO message_media VALUES (?, ?, ?, 'image/jpeg', NULL, ?, NULL, NULL, 0)",
                        (i, file_path, size, digest))
        con.commit()
        con.close()
        key = self.tmp / "key"
        create_key_file(hex_key, str(key))
        out = self.tmp / "backup.crypt15"
        subprocess.run([sys.executable, "-m", "wa_crypt_tools.waencrypt", str(key), str(db), str(out)],
                       check=True, capture_output=True)
        self.phone.add(f"{folder}/Databases/msgstore.db.crypt15", out.read_bytes(), mtime=mtime)

    def build_phone(self):
        # The storage root: this account's media from before it moved to accounts/1002
        self.old_photo = self.media(MAIN, "WhatsApp Images", "IMG-20230504-WA0003.jpg", ts="2023-05-04")
        self.old_doc = self.media(MAIN, "WhatsApp Documents", "Report.pdf", chat="Work", ts="2023-04-01")
        self.odd_name = self.media(MAIN, "WhatsApp Documents", "Mom's \"plan\" (1) \U0001F382.pdf",
                                   chat="Work", ts="2023-04-02")
        self.main_unknown = self.media(MAIN, "WhatsApp Images", "IMG-20230505-WA0007.jpg", in_db=False)
        self.phone.add(f"{MAIN}/Media/WhatsApp Images/.nomedia", b"")
        self.backup(MAIN, list(self.rows), T2023)
        # accounts/1002: the account now, its backup knows every message
        self.new_photo = self.media(ACC, "WhatsApp Images", "IMG-20250601-WA0001.jpg", ts="2025-06-01")
        self.sent_photo = self.media(ACC, "WhatsApp Images/Sent", "IMG-20250602-WA0002.jpg", ts="2025-06-02")
        self.video = self.media(ACC, "WhatsApp Video", "VID-20250603-WA0001.mp4", chat="Work", ts="2025-06-03")
        self.unknown = self.media(ACC, "WhatsApp Images", "IMG-20250604-WA0009.jpg", in_db=False)
        self.phone.add(f"{ACC}/Media/.Links/preview.jpg", b"link")
        self.rows.append(("Family", "Media/WhatsApp Images/IMG-20250605-WA0004.jpg", 10, "never-downloaded", "2025-06-05"))
        self.backup(ACC, self.rows, T2025)
        # accounts/1003: another account. Its counters give the same names as this one's
        self.other_same_name = self.media(OTHER, "WhatsApp Images", "IMG-20250601-WA0001.jpg", in_db=False,
                                          data=_content("IMG-20250601-WA0001.jpg"))
        self.other_photo = self.media(OTHER, "WhatsApp Images", "IMG-20250101-WA0005.jpg", in_db=False)
        # ...and a photo forwarded from this account: the same file under another name
        self.forwarded = self.media(OTHER, "WhatsApp Images", "IMG-20250610-WA0099.jpg", in_db=False,
                                    data=self.files[self.sent_photo])
        self.backup(OTHER, [("Strangers", "Media/WhatsApp Images/IMG-20250101-WA0005.jpg",
                             len(self.files[self.other_photo]), _sha_b64(self.files[self.other_photo]),
                             "2025-01-01")], T2025 - 3600, hex_key=OTHER_KEY)

    # --- the PC ------------------------------------------------------------------------------

    def sync(self, with_session=True, session_id=None, stop_after=None):
        """One sync as the app runs it. stop_after: pause once that many files have arrived."""
        pipeline.sync_status["warnings"] = []
        cfg = load_config()  # this library's folders (another account's library has its own)
        out = cfg.get("output_dir") or "./output"
        manager = None
        if with_session:
            manager = SyncSessionManager(str(Path(out) / ".sync_state.sqlite3"))
            if not session_id:
                session_id = str(uuid.uuid4())
                manager.create_session(session_id, "FAKE0001", "Fake_Phone")
        token = threading.Event()
        arrived = []

        def progress(name, size):
            if not name.startswith("Databases/"):
                arrived.append(name)
            if stop_after and len(arrived) >= stop_after:
                token.set()

        result = pipeline.run_streaming_pipeline(
            hex_key=cfg.get("hex_key"), key_file=cfg.get("key_file") or "encrypted_backup.key",
            db_dir=cfg.get("db_dir") or "./Databases", media_dir=out, output_dir=out,
            session_manager=manager, session_id=session_id,
            skip_contacts_pull=True, cancellation_token=token, progress_callback=progress,
        )
        if stop_after:
            self.assertFalse(result)
            return session_id, arrived
        self.assertTrue(result, "the sync failed")
        return json.loads((Path(out) / ".sync_report.json").read_text())

    def pc_files(self):
        """sha256 -> output-relative paths of every media file under output."""
        out = self.app / "output"
        found = {}
        for p in out.rglob("*"):
            rel = p.relative_to(out)
            if p.is_file() and not any(part.startswith(".") for part in rel.parts) \
                    and rel.parts[0] != "gallery_assets" and p.suffix not in (".html", ".js", ".csv", ".bat"):
                found.setdefault(_sha(p.read_bytes()), []).append(rel.as_posix())
        return found

    def csv_rows(self, out="output"):
        with open(self.app / out / "media_index.csv", encoding="utf-8") as f:
            return {r["rel_path"]: r for r in csv.DictReader(f)}

    def where(self, phone_path):
        """Output-relative path of the PC copy of a phone file, by the phone path the app recorded."""
        for rel, row in self.csv_rows().items():
            if row["phone_path"] == phone_path and (self.app / "output" / rel).is_file():
                return rel
        return None

    # --- the tests ---------------------------------------------------------------------------

    def test_media_of_every_account_folder_reaches_the_pc(self):
        self.build_phone()
        report = self.sync()

        on_pc = self.pc_files()
        for path, data in self.files.items():
            self.assertIn(_sha(data), on_pc, f"{path} is not on the PC")
        names = {Path(p).name for paths in on_pc.values() for p in paths}
        self.assertNotIn("preview.jpg", names)

        # This account's media from both folders is in its chats (the root's by its contents)
        self.assertTrue(self.where(self.old_photo).startswith("Family/2023-05/"))
        self.assertTrue(self.where(self.old_doc).startswith("Work/2023-04/"))
        self.assertTrue(self.where(self.odd_name).startswith("Work/2023-04/"))
        self.assertTrue(self.where(self.new_photo).startswith("Family/2025-06/"))
        self.assertTrue(self.where(self.sent_photo).startswith("Family/2025-06/"))
        self.assertTrue(self.where(self.video).startswith("Work/2025-06/"))
        self.assertEqual(self.where(self.unknown), "_unmatched/WhatsApp Images/IMG-20250604-WA0009.jpg")
        self.assertEqual(self.where(self.main_unknown),
                         "_unmatched/From main folder/WhatsApp Images/IMG-20230505-WA0007.jpg")

        # The other account's photos stay apart, even the one named like a photo of this account
        self.assertEqual(self.where(self.other_same_name),
                         "_unmatched/From account 1003/WhatsApp Images/IMG-20250601-WA0001.jpg")
        self.assertEqual(self.where(self.other_photo),
                         "_unmatched/From account 1003/WhatsApp Images/IMG-20250101-WA0005.jpg")
        # A photo forwarded from this account is recognised by its contents
        self.assertTrue(self.where(self.forwarded).startswith("Family/2025-06/"))

        self.assertEqual(report["missing_count"], 0)
        self.assertEqual(report["phone_media_files"], len(self.files))
        self.assertEqual(report["on_pc"], len(self.files))
        self.assertEqual(report["chat_attachments_not_on_phone"], 1)
        self.assertEqual({k: v["files"] for k, v in report["phone_folders"].items()},
                         {"Media": 4, "accounts/1002/Media": 4, "accounts/1003/Media": 3})
        self.assertTrue(report["phone_folders"]["accounts/1002/Media"]["synced_account"])
        # Too few files to tell whose the other folders are: nothing is claimed
        self.assertEqual(pipeline.sync_status["warnings"], [])

    def test_next_sync_only_fetches_new_media(self):
        self.build_phone()
        self.sync()
        self.rows = []
        later = self.media(ACC, "WhatsApp Images", "IMG-20250701-WA0001.jpg", in_db=False)
        older = self.media(MAIN, "WhatsApp Images", "IMG-20230601-WA0001.jpg", in_db=False)
        # Named and sized like a photo already on the PC, but another photo
        clash = self.media(OTHER, "WhatsApp Images", "IMG-20250602-WA0002.jpg", in_db=False)
        lists_before = len(self.phone.transfer_lists())
        report = self.sync()

        media_lists = [lst for lst in self.phone.transfer_lists()[lists_before:]
                       if not any("Databases/" in p for p in lst)]
        self.assertEqual(len(media_lists), 1)
        self.assertEqual(sorted(media_lists[0]), sorted(p[len(MAIN) + 1:] for p in (later, older, clash)))
        on_pc = self.pc_files()
        for path in (later, older, clash):
            self.assertIn(_sha(self.files[path]), on_pc)
        self.assertEqual(report["missing_count"], 0)
        self.assertEqual(report["phone_media_files"], len(self.files))
        # Nothing moved back and forth: the files of the first sync are where they were
        self.assertTrue(self.where(self.old_photo).startswith("Family/2023-05/"))
        self.assertTrue(self.where(self.forwarded).startswith("Family/2025-06/"))

    def test_a_paused_sync_resumes_where_it_stopped(self):
        self.build_phone()
        session_id, first = self.sync(stop_after=3)
        self.assertGreaterEqual(len(first), 3)
        self.assertLess(len(first), len(self.files))
        lists_before = len(self.phone.transfer_lists())
        report = self.sync(session_id=session_id)
        resumed = [p for lst in self.phone.transfer_lists()[lists_before:] for p in lst if "Databases/" not in p]
        self.assertEqual(len(resumed), len(self.files) - len(first), "files already on the PC were sent again")
        self.assertEqual(report["missing_count"], 0)
        on_pc = self.pc_files()
        for data in self.files.values():
            self.assertIn(_sha(data), on_pc)

    def test_sync_without_a_session(self):
        self.build_phone()
        report = self.sync(with_session=False)
        self.assertEqual(report["missing_count"], 0)
        self.assertEqual(report["on_pc"], len(self.files))

    def test_a_file_that_did_not_arrive_is_reported(self):
        self.build_phone()
        self.phone.fail_transfer_of("VID-20250603-WA0001.mp4")
        report = self.sync()
        self.assertEqual(report["missing_count"], 1)
        self.assertEqual(report["missing"][0]["phone_path"], self.video)
        self.assertTrue(any("did not reach the PC" in w for w in pipeline.sync_status["warnings"]))

        self.phone.skip_file.unlink()
        report = self.sync()
        self.assertEqual(report["missing_count"], 0)

    def test_a_newer_backup_in_another_account_folder_is_pointed_out(self):
        self.build_phone()
        save_config({"selected_account_path": MAIN})  # chosen before WhatsApp moved the account
        report = self.sync()
        self.assertTrue(any("1002 has a newer chat backup" in w for w in pipeline.sync_status["warnings"]))
        self.assertEqual(report["missing_count"], 0)  # still, every file is copied
        self.sync()  # said once
        self.assertFalse(any("newer chat backup" in w for w in pipeline.sync_status["warnings"]))

    def test_cut_off_backup_keeps_the_previous_chats(self):
        self.build_phone()
        self.sync()
        backup = self.phone.host(f"{ACC}/Databases/msgstore.db.crypt15")
        data = backup.read_bytes()
        backup.write_bytes(data[: len(data) * 2 // 3])  # WhatsApp still writing it
        os.utime(backup, (T2025 + 60, T2025 + 60))
        self.media(ACC, "WhatsApp Images", "IMG-20250901-WA0001.jpg", in_db=False)
        report = self.sync()
        self.assertTrue(any("incomplete" in w for w in pipeline.sync_status["warnings"]))
        self.assertEqual(report["missing_count"], 0)
        con = sqlite3.connect(self.app / "Databases" / "msgstore.db")
        self.assertEqual(con.execute("SELECT count(*) FROM message").fetchone()[0], len(self.rows))
        con.close()

    # --- whose folder is it, and whose key -----------------------------------------------------

    def big_phone(self):
        """Enough media to tell: 40 older photos of this account in the main folder, 40 of another."""
        self.build_phone()
        for i in range(40):
            self.media(MAIN, "WhatsApp Images", f"IMG-20220101-WA{i:04d}.jpg", ts="2022-01-01")
            self.media(OTHER, "WhatsApp Images", f"IMG-20240101-WA{i:04d}.jpg", in_db=False)
        self.backup(ACC, self.rows, T2025 + 10)

    def test_whose_folder_each_account_folder_is(self):
        self.big_phone()
        report = self.sync()
        folders = report["phone_folders"]
        self.assertEqual(folders["Media"]["verdict"], "this_account")
        self.assertEqual(folders["accounts/1003/Media"]["verdict"], "other_account")
        self.assertGreaterEqual(folders["Media"]["share_in_chats"], 0.9)
        self.assertLessEqual(folders["accounts/1003/Media"]["share_in_chats"], 0.05)  # the forwarded photo
        warnings = pipeline.sync_status["warnings"]
        self.assertTrue(any(w.startswith("The main WhatsApp folder holds this account's older media") for w in warnings))
        self.assertTrue(any("account folder 1003 belongs to another WhatsApp account" in w for w in warnings))
        # Said once
        self.sync()
        self.assertEqual(pipeline.sync_status["warnings"], [])

    def open_other_library(self):
        """What Accounts › Open in a new tab does for accounts/1003, in this process."""
        lib = libraries.ensure_library({"path": OTHER, "account_id": "1003", "app_type": "whatsapp"})
        set_active_profile(OTHER)
        self.addCleanup(set_active_profile, None)
        return lib

    def test_each_account_has_its_own_library(self):
        self.build_phone()
        self.sync()  # the first library: accounts/1002
        lib = self.open_other_library()
        self.assertEqual(lib["output_dir"], "output - WhatsApp (account 1003)")
        cfg = load_config()
        self.assertEqual(cfg["selected_account_path"], OTHER)
        self.assertEqual(cfg["hex_key"], "")  # its key is not known yet
        self.assertEqual(cfg["db_dir"], "Databases - WhatsApp (account 1003)")

        # 1002's key does not open 1003's backup
        save_config({"hex_key": HEX_KEY})
        with self.assertRaises(KeyMismatchError):
            self.sync()
        save_config({"hex_key": OTHER_KEY})
        self.sync()

        # 1003's chats are in its own folder, 1002's stay in theirs
        other_rows = self.csv_rows(lib["output_dir"])
        first_rows = self.csv_rows()
        self.assertTrue(any(r.startswith("Strangers/") for r in other_rows))
        self.assertFalse(any(r.startswith("Strangers/") for r in first_rows))
        self.assertFalse(any(r.startswith(("Family/", "Work/")) for r in other_rows))
        self.assertEqual(pipeline.database_account(str(self.app / "Databases" / "msgstore.db")), ACC)
        self.assertEqual(pipeline.database_account(str(self.app / cfg["db_dir"] / "msgstore.db")), OTHER)

        # Each library keeps its key; both are remembered
        self.assertEqual(load_config()["hex_key"], OTHER_KEY)
        set_active_profile(None)
        self.assertEqual(load_config()["hex_key"], HEX_KEY)
        self.assertEqual(load_config()["account_keys"], {ACC: HEX_KEY, OTHER: OTHER_KEY})
        self.sync()  # the first library is untouched by the other's sync
        self.assertFalse(any(r.startswith("Strangers/") for r in self.csv_rows()))

        # Deleting the key in 1003's tab deletes 1003's key only
        set_active_profile(OTHER)
        save_config({"hex_key": ""})
        self.assertEqual(load_config()["account_keys"], {ACC: HEX_KEY})
        set_active_profile(None)
        self.assertEqual(load_config()["hex_key"], HEX_KEY)

    def test_a_library_never_takes_another_accounts_media(self):
        self.build_phone()
        self.sync()
        # The phone connected now has no accounts/1002 (another phone, WhatsApp reinstalled)
        shutil.rmtree(self.phone.host(ACC))
        with self.assertRaises(RuntimeError) as e:
            self.sync()
        self.assertIn("not on the connected phone", str(e.exception))

    def test_a_cut_off_backup_never_falls_back_to_another_accounts_chats(self):
        self.build_phone()
        self.sync()  # 1002's chats are on the PC
        self.open_other_library()
        save_config({"hex_key": OTHER_KEY})
        backup = self.phone.host(f"{OTHER}/Databases/msgstore.db.crypt15")
        backup.write_bytes(backup.read_bytes()[:-40])
        with self.assertRaises(BackupIncompleteError):
            self.sync()

    # --- coming from an older version ------------------------------------------------------------

    def make_like_older_version(self, out="output"):
        """What v1.2.3 left behind: relative phone paths, no database owner, no per-account settings."""
        csv_path = self.app / out / "media_index.csv"
        with open(csv_path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        for r in rows:
            if r["phone_path"].startswith(MAIN + "/"):
                r["phone_path"] = r["phone_path"][len(MAIN) + 1:]
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        for marker in (self.app / "Databases").glob("*.account"):
            marker.unlink()
        cfg = json.loads((self.app / "config.json").read_text())
        for k in ("profiles", "libraries", "account_keys", "hex_key_account", "account_folder_verdicts", "primary_output_dir"):
            cfg.pop(k, None)
        (self.app / "config.json").write_text(json.dumps(cfg))

    def test_an_older_versions_library_keeps_syncing_without_copying_again(self):
        self.build_phone()
        self.sync()
        self.make_like_older_version()
        self.rows = []
        newer = self.media(ACC, "WhatsApp Images", "IMG-20251001-WA0001.jpg", in_db=False)
        lists_before = len(self.phone.transfer_lists())
        report = self.sync()
        sent = [p for lst in self.phone.transfer_lists()[lists_before:] for p in lst if "Databases/" not in p]
        self.assertEqual(sent, [newer[len(MAIN) + 1:]], "files synced by the older version were copied again")
        self.assertEqual(report["missing_count"], 0)
        self.assertEqual(load_config()["account_keys"], {ACC: HEX_KEY})  # remembered from now on

    def test_import_older_media_then_sync(self):
        # An older installation's output folder, then a fresh app that imports it
        self.build_phone()
        self.sync()
        self.make_like_older_version()
        older = self.tmp / "older install output"
        shutil.copytree(self.app / "output", older)
        shutil.rmtree(self.app / "output")
        shutil.rmtree(self.app / "Databases")
        (self.app / "config.json").write_text(json.dumps({"selected_account_path": ACC}))
        (older / "config.json").write_text(json.dumps({"hex_key": HEX_KEY}))  # older versions kept it there too

        from core.migrator import execute_import_folder
        (self.app / "output").mkdir()
        result = execute_import_folder(str(older), str(self.app / "output"))
        self.assertNotEqual(result.get("status"), "error", result)
        self.assertEqual(load_config()["hex_key"], HEX_KEY)  # the key came with it
        on_pc = self.pc_files()
        for data in self.files.values():
            self.assertIn(_sha(data), on_pc)

        lists_before = len(self.phone.transfer_lists())
        report = self.sync()
        sent = [p for lst in self.phone.transfer_lists()[lists_before:] for p in lst if "Databases/" not in p]
        self.assertEqual(sent, [], "imported media was copied from the phone again")
        self.assertEqual(report["missing_count"], 0)

    def test_import_into_another_accounts_tab(self):
        self.build_phone()
        self.sync()
        lib = self.open_other_library()
        older = self.tmp / "older 1003 output"
        older.mkdir()
        (older / "config.json").write_text(json.dumps({"hex_key": OTHER_KEY}))
        (older / "Strangers").mkdir()
        (older / "Strangers" / "IMG-20240101-WA0001.jpg").write_bytes(b"old photo")
        from core.migrator import execute_import_folder, validate_paths
        from core.gallery import update_gallery_data_live
        update_gallery_data_live([{"chat_jid": "s@g.us", "chat_name": "Strangers", "filename": "IMG-20240101-WA0001.jpg",
                                   "rel_path": "Strangers/IMG-20240101-WA0001.jpg", "size_bytes": 9,
                                   "mime_type": "image/jpeg", "received_at": "2024-01-01 10:00:00"}], str(older))
        result = execute_import_folder(str(older), lib["output_dir"])
        self.assertNotEqual(result.get("status"), "error", result)
        cfg = load_config()
        self.assertEqual(cfg["hex_key"], OTHER_KEY)  # 1003's tab: its own key
        self.assertTrue(Path(cfg["key_file"]).is_file())
        self.assertTrue((Path(lib["output_dir"]) / "Strangers" / "IMG-20240101-WA0001.jpg").is_file())
        set_active_profile(None)
        self.assertEqual(load_config()["hex_key"], HEX_KEY)  # the first library's key is untouched
        # The first account's library cannot be imported into 1003's (their chats would mix)
        set_active_profile(OTHER)
        ok, message, _, _ = validate_paths(str(self.app / "output"), lib["output_dir"])
        self.assertFalse(ok)
        self.assertIn("another WhatsApp account", message)

    # --- features meeting each other -------------------------------------------------------------

    def transferred(self, since):
        return [p for lst in self.phone.transfer_lists()[since:] for p in lst if "Databases/" not in p]

    def test_a_folder_with_its_own_library_is_not_copied_into_another(self):
        self.build_phone()
        self.open_other_library()
        set_active_profile(None)
        before = len(self.phone.transfer_lists())
        report = self.sync()  # the first library: 1003 has its own, so its folder is left to it
        self.assertFalse(any(p.startswith("accounts/1003/") for p in self.transferred(before)))
        self.assertNotIn("accounts/1003/Media", report["phone_folders"])
        self.assertEqual(report["missing_count"], 0)
        self.assertFalse(any("1003" in w and "newer" in w for w in pipeline.sync_status["warnings"]))

        set_active_profile(OTHER)
        save_config({"hex_key": OTHER_KEY})
        before = len(self.phone.transfer_lists())
        report = self.sync()  # and 1003's library leaves 1002's folder to the first one
        sent = self.transferred(before)
        self.assertFalse(any(p.startswith("accounts/1002/") for p in sent))
        self.assertTrue(any(p.startswith("accounts/1003/") for p in sent))
        self.assertTrue(any(r.startswith("Strangers/") for r in self.csv_rows(load_config()["output_dir"])))

    def test_phone_cleanup_leaves_other_accounts_media_alone(self):
        self.build_phone()
        self.sync()  # 1003 has no library: its photos wait in _unmatched/From account 1003
        from core.clean_planner import CleanProfile, generate_clean_plan
        plan = generate_clean_plan(str(self.app / "output"), profile=CleanProfile.CUSTOM,
                                   custom_config={"min_age_days": 0, "keep_starred": False,
                                                  "media_types": ["images", "videos", "documents", "audio", "stickers", "other"]})
        rels = [c.get("rel_path") or "" for c in plan.get("candidates", [])]
        self.assertTrue(rels, "nothing at all was offered: the check below would prove nothing")
        self.assertFalse([r for r in rels if r.startswith(("_unmatched/From account", "_unmatched/From main folder"))])

    def test_a_paused_sync_belongs_to_its_own_library(self):
        import core.server as srv
        self.build_phone()
        session_id, _ = self.sync(stop_after=3)  # the first library has a paused sync
        lib = self.open_other_library()
        srv.sync_status.update({"status": "idle", "phase": "idle", "can_resume": False, "session_id": None})
        srv._restore_paused_session(lib["output_dir"])  # 1003's tab starting
        self.assertFalse(srv.sync_status.get("can_resume"))
        set_active_profile(None)
        srv._restore_paused_session(str(self.app / "output"))  # the first tab starting
        self.assertTrue(srv.sync_status.get("can_resume"))
        self.assertEqual(srv.sync_status.get("session_id"), session_id)

if __name__ == "__main__":
    unittest.main()
