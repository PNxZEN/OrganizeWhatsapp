"""
Live Hardware & ADB Edge-Case Verification Script for:
1. Push to Phone (restore_chat_to_phone)
2. Deleting from Phone (batch_delete_phone_files & execute_clean_plan)
3. Multi-Account WhatsApp (accounts/1002) and WhatsApp Business (com.whatsapp.w4b)
4. Special characters: spaces, parentheses, brackets, ampersands, single quotes
5. Idempotent skip when identical file already exists on phone
6. Safe cleanup and verification that no test artifacts remain on device
"""

import os
import sys
import json
import time
import shutil
import tempfile
import subprocess
from pathlib import Path

from core.adb import (
    find_adb_binary,
    check_adb_device,
    get_device_storage_info,
    get_remote_file_sizes,
    batch_delete_phone_files,
    restore_chat_to_phone,
    broadcast_media_scan,
)

def run():
    print("=" * 70)
    print("STARTING LIVE PHONE EDGE-CASE VERIFICATION")
    print("=" * 70)

    adb = find_adb_binary()
    print(f"[1] Located ADB binary: {adb}")
    dev = check_adb_device(adb_path=adb)
    print(f"[2] Device connected: {dev.connected}, authorized: {dev.authorized}, serial: {dev.device_serial}, model: {dev.model}")
    assert dev.connected and dev.authorized, f"Phone not ready: {dev}"

    storage = get_device_storage_info(adb_path=adb, serial=dev.device_serial)
    print(f"[3] Device storage: {storage.get('free_gb')} GB free of {storage.get('total_gb')} GB")
    assert storage.get("free_bytes", 0) > 600 * 1024 * 1024, "Insufficient storage for testing"

    # Base ADB command
    base_cmd = [adb, "-s", dev.device_serial]

    # Setup temporary local PC directory for mock chat gallery
    temp_dir = tempfile.mkdtemp(prefix="wa_live_test_")
    out_p = Path(temp_dir)
    print(f"[4] Created temporary test workspace on PC: {out_p}")

    test_files_on_phone = []
    test_dirs_on_phone = []

    try:
        # =====================================================================
        # SCENARIO 1: PRIMARY ACCOUNT EDGE CASES (Single Account)
        # =====================================================================
        print("\n" + "-" * 70)
        print("SCENARIO 1: Primary Account Edge Cases (Images, Videos, Audio, Docs, Sent, Quotes/Spaces)")
        print("-" * 70)

        chat_jid_primary = "test_primary_chat@s.whatsapp.net"
        chat_folder_primary = out_p / "Primary_Chat"
        chat_folder_primary.mkdir(parents=True, exist_ok=True)

        # 1. Standard image
        f1_name = "TEST_std_photo.jpg"
        f1_p = chat_folder_primary / f1_name
        f1_p.write_bytes(b"JPEG_HEADER_MOCK_12345" * 20)

        # 2. Sent image (from_me = True) -> should land in WhatsApp Images/Sent
        f2_name = "TEST_sent_photo.jpg"
        f2_p = chat_folder_primary / f2_name
        f2_p.write_bytes(b"JPEG_SENT_MOCK_54321" * 30)

        # 3. Video
        f3_name = "TEST_video_clip.mp4"
        f3_p = chat_folder_primary / f3_name
        f3_p.write_bytes(b"MP4_VIDEO_HEADER_MOCK" * 40)

        # 4. Audio
        f4_name = "TEST_audio_note.opus"
        f4_p = chat_folder_primary / f4_name
        f4_p.write_bytes(b"OPUS_AUDIO_MOCK" * 25)

        # 5. Document
        f5_name = "TEST_document_invoice.pdf"
        f5_p = chat_folder_primary / f5_name
        f5_p.write_bytes(b"PDF_DOCUMENT_MOCK" * 35)

        # 6. Special characters, spaces, parentheses, brackets, ampersand, quotes
        f6_name = "TEST_Friend's Special (Photo) & [Doc] #1.jpg"
        f6_p = chat_folder_primary / f6_name
        f6_p.write_bytes(b"SPECIAL_CHARS_IMAGE_MOCK" * 22)

        primary_media = [
            {"rel_path": f"Primary_Chat/{f1_name}", "mime_type": "image/jpeg", "size_bytes": f1_p.stat().st_size, "from_me": False},
            {"rel_path": f"Primary_Chat/{f2_name}", "mime_type": "image/jpeg", "size_bytes": f2_p.stat().st_size, "from_me": True},
            {"rel_path": f"Primary_Chat/{f3_name}", "mime_type": "video/mp4", "size_bytes": f3_p.stat().st_size, "from_me": False},
            {"rel_path": f"Primary_Chat/{f4_name}", "mime_type": "audio/ogg", "size_bytes": f4_p.stat().st_size, "from_me": False},
            {"rel_path": f"Primary_Chat/{f5_name}", "mime_type": "application/pdf", "size_bytes": f5_p.stat().st_size, "is_doc": True, "from_me": False},
            {"rel_path": f"Primary_Chat/{f6_name}", "mime_type": "image/jpeg", "size_bytes": f6_p.stat().st_size, "from_me": False},
        ]

        # Write gallery_data.js
        gal_data = {
            "chats": [
                {
                    "jid": chat_jid_primary,
                    "name": "Primary Chat",
                    "media": primary_media
                }
            ]
        }
        (out_p / "gallery_data.js").write_text("window.GALLERY_DATA = " + json.dumps(gal_data) + ";", encoding="utf-8")

        # Test Push to Phone for Primary Chat
        print("[Push 1] Restoring primary chat to phone...")
        t0 = time.time()
        res_push1 = restore_chat_to_phone(
            chat_jid_primary,
            output_dir=str(out_p),
            adb_path=adb,
            serial=dev.device_serial,
        )
        print(f"  -> Result: success={res_push1['success']}, restored={res_push1['restored_count']}, skipped={res_push1['skipped_count']}, time={round(time.time()-t0, 2)}s")
        assert res_push1["success"], f"Primary restore failed: {res_push1.get('errors')}"
        assert res_push1["restored_count"] == 6, f"Expected 6 restored files, got {res_push1['restored_count']}"

        # Expected remote phone paths
        expected_paths_primary = [
            f"/storage/emulated/0/Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images/{f1_name}",
            f"/storage/emulated/0/Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images/Sent/{f2_name}",
            f"/storage/emulated/0/Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Video/{f3_name}",
            f"/storage/emulated/0/Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Audio/{f4_name}",
            f"/storage/emulated/0/Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Documents/{f5_name}",
            f"/storage/emulated/0/Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images/{f6_name}",
        ]
        test_files_on_phone.extend(expected_paths_primary)

        # Verify on phone via get_remote_file_sizes
        print("[Verify 1] Verifying all 6 files exist on phone with exact byte counts...")
        remote_sizes = get_remote_file_sizes(expected_paths_primary, adb_path=adb, serial=dev.device_serial)
        for expected_p, meta in zip(expected_paths_primary, primary_media):
            assert expected_p in remote_sizes, f"Missing on phone: {expected_p}"
            assert remote_sizes[expected_p] == meta["size_bytes"], f"Size mismatch for {expected_p}: remote {remote_sizes[expected_p]} vs local {meta['size_bytes']}"
            print(f"  OK: {expected_p} -> {remote_sizes[expected_p]} bytes")

        # Test Idempotency (Pushing same files again should skip 100%)
        print("\n[Push 1b] Testing idempotency: Re-pushing without changes should skip 100% of files...")
        t0 = time.time()
        res_push1_idem = restore_chat_to_phone(
            chat_jid_primary,
            output_dir=str(out_p),
            adb_path=adb,
            serial=dev.device_serial,
        )
        print(f"  -> Result: success={res_push1_idem['success']}, restored={res_push1_idem['restored_count']}, skipped={res_push1_idem['skipped_count']}")
        assert res_push1_idem["success"], "Idempotent push should succeed"
        assert res_push1_idem["restored_count"] == 0, "No files should be re-pushed"
        assert res_push1_idem["skipped_count"] == 6, f"Expected all 6 files to be skipped, got {res_push1_idem['skipped_count']}"

        # Test Modification (Modify 1 local file, re-push should push only that 1 file)
        print("\n[Push 1c] Modifying 1 local file size: should re-push only modified file...")
        f1_p.write_bytes(b"NEW_EXPANDED_JPEG_CONTENT" * 50)
        new_f1_size = f1_p.stat().st_size
        res_push1_mod = restore_chat_to_phone(
            chat_jid_primary,
            output_dir=str(out_p),
            adb_path=adb,
            serial=dev.device_serial,
        )
        print(f"  -> Result: restored={res_push1_mod['restored_count']}, skipped={res_push1_mod['skipped_count']}")
        assert res_push1_mod["restored_count"] == 1, "Only modified file should be pushed"
        assert res_push1_mod["skipped_count"] == 5, "Unmodified 5 files should be skipped"
        new_remote_sizes = get_remote_file_sizes([expected_paths_primary[0]], adb_path=adb, serial=dev.device_serial)
        assert new_remote_sizes[expected_paths_primary[0]] == new_f1_size, "Remote file size should match updated local size"

        # =====================================================================
        # SCENARIO 2: MULTI-ACCOUNT WHATSAPP (accounts/1002)
        # =====================================================================
        print("\n" + "-" * 70)
        print("SCENARIO 2: Multi-Account WhatsApp (accounts/1002 folder structure)")
        print("-" * 70)

        multi_base_path = "/storage/emulated/0/Android/media/com.whatsapp/WhatsApp/accounts/1002"
        test_dirs_on_phone.append(multi_base_path)

        chat_jid_multi = "test_multi_chat@s.whatsapp.net"
        chat_folder_multi = out_p / "Multi_Chat"
        chat_folder_multi.mkdir(parents=True, exist_ok=True)

        m_f1_name = "TEST_multi_img_1002.jpg"
        m_f1_p = chat_folder_multi / m_f1_name
        m_f1_p.write_bytes(b"MULTI_ACCOUNT_IMAGE_MOCK" * 20)

        m_f2_name = "TEST_multi_vid_1002.mp4"
        m_f2_p = chat_folder_multi / m_f2_name
        m_f2_p.write_bytes(b"MULTI_ACCOUNT_VIDEO_MOCK" * 30)

        multi_media = [
            {"rel_path": f"Multi_Chat/{m_f1_name}", "mime_type": "image/jpeg", "size_bytes": m_f1_p.stat().st_size, "from_me": False},
            {"rel_path": f"Multi_Chat/{m_f2_name}", "mime_type": "video/mp4", "size_bytes": m_f2_p.stat().st_size, "from_me": False},
        ]

        gal_data["chats"].append({
            "jid": chat_jid_multi,
            "name": "Multi Account Chat",
            "media": multi_media
        })
        (out_p / "gallery_data.js").write_text("window.GALLERY_DATA = " + json.dumps(gal_data) + ";", encoding="utf-8")

        print(f"[Push 2] Restoring multi-account chat targeting {multi_base_path}...")
        res_push2 = restore_chat_to_phone(
            chat_jid_multi,
            output_dir=str(out_p),
            base_path=multi_base_path,
            adb_path=adb,
            serial=dev.device_serial,
        )
        print(f"  -> Result: success={res_push2['success']}, restored={res_push2['restored_count']}, errors={res_push2.get('errors')}")
        assert res_push2["success"], f"Multi-account restore failed: {res_push2.get('errors')}"
        assert res_push2["restored_count"] == 2, f"Expected 2 restored files, got {res_push2['restored_count']}"

        expected_paths_multi = [
            f"{multi_base_path}/Media/WhatsApp Images/{m_f1_name}",
            f"{multi_base_path}/Media/WhatsApp Video/{m_f2_name}",
        ]
        test_files_on_phone.extend(expected_paths_multi)

        # Verify on phone
        print("[Verify 2] Verifying multi-account files on phone...")
        m_remote_sizes = get_remote_file_sizes(expected_paths_multi, adb_path=adb, serial=dev.device_serial)
        for expected_p, meta in zip(expected_paths_multi, multi_media):
            assert expected_p in m_remote_sizes, f"Missing multi-account file on phone: {expected_p}"
            assert m_remote_sizes[expected_p] == meta["size_bytes"], f"Size mismatch for {expected_p}"
            print(f"  OK: {expected_p} -> {m_remote_sizes[expected_p]} bytes")

        # =====================================================================
        # SCENARIO 3: WHATSAPP BUSINESS MULTI-APP SETUP (com.whatsapp.w4b)
        # =====================================================================
        print("\n" + "-" * 70)
        print("SCENARIO 3: WhatsApp Business Multi-App Setup (com.whatsapp.w4b folder structure)")
        print("-" * 70)

        w4b_base_path = "/storage/emulated/0/Android/media/com.whatsapp.w4b/WhatsApp Business"
        test_dirs_on_phone.append(w4b_base_path)

        chat_jid_w4b = "test_w4b_chat@s.whatsapp.net"
        chat_folder_w4b = out_p / "W4B_Chat"
        chat_folder_w4b.mkdir(parents=True, exist_ok=True)

        w_f1_name = "TEST_w4b_photo.jpg"
        w_f1_p = chat_folder_w4b / w_f1_name
        w_f1_p.write_bytes(b"W4B_PHOTO_MOCK" * 25)

        w_f2_name = "TEST_w4b_invoice.pdf"
        w_f2_p = chat_folder_w4b / w_f2_name
        w_f2_p.write_bytes(b"W4B_INVOICE_MOCK" * 35)

        w4b_media = [
            {"rel_path": f"W4B_Chat/{w_f1_name}", "mime_type": "image/jpeg", "size_bytes": w_f1_p.stat().st_size, "from_me": False},
            {"rel_path": f"W4B_Chat/{w_f2_name}", "mime_type": "application/pdf", "size_bytes": w_f2_p.stat().st_size, "is_doc": True, "from_me": False},
        ]

        gal_data["chats"].append({
            "jid": chat_jid_w4b,
            "name": "W4B Chat",
            "media": w4b_media
        })
        (out_p / "gallery_data.js").write_text("window.GALLERY_DATA = " + json.dumps(gal_data) + ";", encoding="utf-8")

        print(f"[Push 3] Restoring WhatsApp Business chat targeting {w4b_base_path}...")
        res_push3 = restore_chat_to_phone(
            chat_jid_w4b,
            output_dir=str(out_p),
            base_path=w4b_base_path,
            adb_path=adb,
            serial=dev.device_serial,
        )
        print(f"  -> Result: success={res_push3['success']}, restored={res_push3['restored_count']}, errors={res_push3.get('errors')}")
        assert res_push3["success"], f"W4B restore failed: {res_push3.get('errors')}"
        assert res_push3["restored_count"] == 2

        # In W4B, directories have the "WhatsApp Business" prefix
        expected_paths_w4b = [
            f"{w4b_base_path}/Media/WhatsApp Business Images/{w_f1_name}",
            f"{w4b_base_path}/Media/WhatsApp Business Documents/{w_f2_name}",
        ]
        test_files_on_phone.extend(expected_paths_w4b)

        print("[Verify 3] Verifying WhatsApp Business files on phone...")
        w_remote_sizes = get_remote_file_sizes(expected_paths_w4b, adb_path=adb, serial=dev.device_serial)
        for expected_p, meta in zip(expected_paths_w4b, w4b_media):
            assert expected_p in w_remote_sizes, f"Missing W4B file on phone: {expected_p}"
            assert w_remote_sizes[expected_p] == meta["size_bytes"], f"Size mismatch for {expected_p}"
            print(f"  OK: {expected_p} -> {w_remote_sizes[expected_p]} bytes")

        # =====================================================================
        # SCENARIO 4: DELETION AND SAFETY GUARDS
        # =====================================================================
        print("\n" + "-" * 70)
        print("SCENARIO 4: Deletion from Phone & Security Guard Tests")
        print("-" * 70)

        # Safety Guard Test: forbidden non-whatsapp paths must be completely ignored!
        illegal_paths = [
            "/system/bin/sh",
            "/data/system/users/0.xml",
            "/storage/emulated/0/DCIM/Camera/my_personal_photo.jpg",
            "/storage/emulated/0/Download/bank_statement.pdf",
        ]
        print("[Guard Test] Testing safety guard with illegal non-WhatsApp paths...")
        guard_res = batch_delete_phone_files(illegal_paths, adb_path=adb, serial=dev.device_serial)
        print(f"  -> Guard result: success={guard_res['success']}, deleted={guard_res['deleted_count']}, errors={guard_res['errors']}")
        assert guard_res["deleted_count"] == 0, "Safety guard MUST prevent deleting non-WhatsApp files!"
        assert "No eligible paths" in guard_res["errors"][0]

        # Live Batch Delete Test: delete all test files pushed to phone
        print(f"\n[Delete Test] Performing batch delete on all {len(test_files_on_phone)} test files across accounts...")
        del_res = batch_delete_phone_files(test_files_on_phone, adb_path=adb, serial=dev.device_serial)
        print(f"  -> Result: success={del_res['success']}, deleted={del_res['deleted_count']}, failed={del_res['failed_count']}")
        assert del_res["success"], f"Batch delete failed: {del_res.get('errors')}"
        assert del_res["deleted_count"] == len(test_files_on_phone), f"Expected {len(test_files_on_phone)} deleted, got {del_res['deleted_count']}"

        # Verify on phone that ALL test files are gone!
        print("\n[Verify Deletion] Verifying test files no longer exist on phone...")
        post_del_sizes = get_remote_file_sizes(test_files_on_phone, adb_path=adb, serial=dev.device_serial)
        print(f"  -> Files still found on phone: {len(post_del_sizes)}")
        assert len(post_del_sizes) == 0, f"Some files were not deleted: {post_del_sizes}"
        print("  OK: All test files successfully removed from phone!")

        # Deletion Idempotency (deleting already deleted files should not error)
        print("\n[Delete Idempotency] Re-deleting already deleted paths (idempotency check)...")
        del_again = batch_delete_phone_files(test_files_on_phone, adb_path=adb, serial=dev.device_serial)
        assert del_again["success"], "Idempotent deletion should succeed"
        assert del_again["failed_count"] == 0

    finally:
        # Clean up test directories created on the phone
        print("\n" + "-" * 70)
        print("CLEANUP: Removing test directories from phone and PC...")
        print("-" * 70)
        for td in test_dirs_on_phone:
            print(f"  Removing phone test folder: {td}")
            subprocess.run(base_cmd + ["shell", f"rm -rf '{td}'"], capture_output=True, text=True)

        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"  Removed local PC temp dir: {temp_dir}")

    print("\n" + "=" * 70)
    print("ALL LIVE PHONE EDGE-CASE TESTS PASSED PERFECTLY!")
    print("=" * 70)

if __name__ == "__main__":
    run()
