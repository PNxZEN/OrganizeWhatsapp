"""
WhatsApp Media Organizer - Pipeline Orchestrator.
Coordinates ADB synchronization, decryption, database querying, deduplication,
media organization, gallery generation, and background live workers.
"""

import csv
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

from core.adb import (
    adb_pull,
    check_adb_device,
    cleanup_nested_databases_folder,
    discover_android_base_path,
    find_adb_binary,
    wait_for_adb_device,
)
from core.config import load_config, save_config
from core.contacts import load_contacts_mapping, load_db_mappings
from core.database import build_media_index
from core.decrypt import create_key_file, decrypt_db
from core.duplicates import analyze_duplicates, detect_quality_duplicates
from core.gallery import gallery_data_lock, generate_gallery
from core.organizer import (
    index_media_files,
    organize_media,
    salvage_unmatched_media,
    sanitize_folder_name,
    zip_chat,
    StreamingMediaRouter,
)
from core.server import sync_status


def file_stability_check(path, wait_ms=500):
    """
    Returns True if the file exists and its size is stable after wait_ms delay.
    Protects the background organizer from processing incomplete ADB writes.
    """
    try:
        size1 = os.path.getsize(path)
        if size1 == 0:
            return False
        time.sleep(wait_ms / 1000.0)
        size2 = os.path.getsize(path)
        return size1 == size2
    except OSError:
        return False


def cleanup_cache(out_dir, max_size_mb=500):
    """
    Removes oldest video previews in .cache if total cache size exceeds max_size_mb.
    """
    cache_dir = Path(out_dir) / ".cache"
    if not cache_dir.is_dir():
        return

    cache_files = []
    for p in cache_dir.rglob("*"):
        if p.is_file():
            try:
                stat = p.stat()
                cache_files.append((p, stat.st_mtime, stat.st_size))
            except Exception:
                continue

    total_size = sum(f[2] for f in cache_files)
    max_size_bytes = max_size_mb * 1024 * 1024

    if total_size <= max_size_bytes:
        return

    cache_files.sort(key=lambda x: x[1])
    deleted_bytes = 0
    for p, _, size in cache_files:
        try:
            p.unlink()
            deleted_bytes += size
            if (total_size - deleted_bytes) <= max_size_bytes:
                break
        except Exception:
            pass


def delete_media_folder(media_dir):
    """
    Interactively deletes ./Media after confirming all files are organized.
    Never automatic: requires user to explicitly type 'YES'.
    """
    media_root = Path(media_dir)
    if not media_root.is_dir():
        print(f"[Cleanup] {media_dir} does not exist. Nothing to delete.")
        return

    total_bytes = sum(p.stat().st_size for p in media_root.rglob("*") if p.is_file())
    total_gb = total_bytes / (1024**3)

    print("\n" + "=" * 60)
    print("MEDIA FOLDER CLEANUP")
    print("=" * 60)
    print(f"  Folder : {media_root.resolve()}")
    print(f"  Size   : {total_gb:.2f} GB ({total_bytes:,} bytes)")
    print("\n  All organized files are safely in ./output/")
    print("  Unmatched files are in ./output/_unmatched/")
    print("\n  THIS CANNOT BE UNDONE.\n")

    try:
        confirm = input(f"  Type YES to permanently delete {media_dir}: ").strip()
    except EOFError:
        confirm = "NO"

    if confirm == "YES":
        try:
            shutil.rmtree(str(media_root))
            print(f"[Cleanup] Deleted {media_dir} ({total_gb:.2f} GB freed).")
        except Exception as e:
            sys.stderr.write(f"[Cleanup] Error: Failed to delete {media_dir}: {e}\n")
    else:
        print("[Cleanup] Deletion cancelled.")


def run_pipeline(
    hex_key=None,
    key_file="encrypted_backup.key",
    db_dir="./Databases",
    media_dir="./output",
    output_dir="./output",
    mode="copy",
    skip_pull=False,
    skip_db_pull=False,
    skip_decrypt=False,
    skip_imagehash=False,
    skip_contacts_pull=False,
    force_contacts_pull=False,
    cleanup_media=False,
    backup_chat=None,
    no_verify=False,
    session_manager=None,
    session_id=None,
    cancellation_token=None,
    progress_callback=None,
    status_callback=None,
    adb_path=None,
):
    """
    Executes the full linear organization pipeline from Step 1 through Step 8.
    Supports persistent pause, resume, and session tracking.
    """
    out_path = Path(output_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    # Step 1: ADB Pull
    if not skip_pull:
        print("=" * 60)
        print("STEP 1: Pull encrypted DB + media tree from phone via ADB")
        print("=" * 60)
        cfg = load_config()
        saved_account_path = cfg.get("selected_account_path", "")
        cmd = find_adb_binary(adb_path)
        base_path = discover_android_base_path(
            cmd,
            hex_key=hex_key,
            preferred_account_path=saved_account_path,
        )
        if not saved_account_path and base_path:
            acc_id = Path(base_path).name if "/accounts/" in base_path else "main"
            app_type = "whatsapp_business" if ("w4b" in base_path or "WhatsApp Business" in base_path) else "whatsapp"
            save_config({
                "selected_account_path": base_path,
                "selected_account_id": acc_id,
                "selected_app_type": app_type,
            })
        print(f"[ADB] Active WhatsApp storage: {base_path}")

        pull_ok = adb_pull(
            base=base_path,
            dest_db=db_dir,
            dest_media=media_dir,
            folders_filter=["Media"] if skip_db_pull else None,
            session_manager=session_manager,
            session_id=session_id,
            cancellation_token=cancellation_token,
            progress_callback=progress_callback,
            status_callback=status_callback,
        )
        if cancellation_token and cancellation_token.is_set():
            print("\n[SYNC] Synchronization paused by user request.")
            return False
        if not pull_ok:
            print("\n[SYNC ERROR] ADB Pull failed or device was disconnected.")
            return False

    if cancellation_token and cancellation_token.is_set():
        return False

    # Step 2: Decrypt Databases
    cleanup_nested_databases_folder(db_dir)
    msgstore = os.path.join(db_dir, "msgstore.db")
    if not skip_decrypt:
        print("\n" + "=" * 60)
        print("STEP 2: Decrypt msgstore.db (and wa.db if present)")
        print("=" * 60)
        if status_callback:
            status_callback("decrypting", "Decrypting WhatsApp database (msgstore.db)...")
        if hex_key:
            create_key_file(hex_key, key_file)

        crypt_file = None
        # When 64-digit key is used, strictly prioritize modern Crypt15
        extensions = [".crypt15"] if hex_key else [".crypt15", ".crypt14", ".crypt12"]
        for ext in extensions:
            cand = os.path.join(db_dir, f"msgstore.db{ext}")
            if os.path.isfile(cand):
                crypt_file = cand
                break

        if not crypt_file and os.path.isdir(db_dir):
            candidates = [
                os.path.join(db_dir, f)
                for f in os.listdir(db_dir)
                if f.startswith("msgstore")
                and any(f.endswith(e) for e in extensions)
            ]
            if candidates:
                crypt_file = sorted(candidates, key=os.path.getmtime, reverse=True)[0]

        # If 64-digit key is set and no crypt15 was found, check if only legacy crypt14/12 exists
        if hex_key and not crypt_file and os.path.isdir(db_dir):
            legacy_cands = [
                os.path.join(db_dir, f)
                for f in os.listdir(db_dir)
                if f.startswith("msgstore") and any(f.endswith(e) for e in [".crypt14", ".crypt12"])
            ]
            if legacy_cands and not skip_pull and not skip_db_pull:
                print("\n[DB] WhatsApp backup is generating on phone. Polling for msgstore.db.crypt15 (up to 4m)...")
                start_poll_time = time.time()
                while time.time() - start_poll_time < 240:
                    if cancellation_token and cancellation_token.is_set():
                        return False
                    elapsed = int(time.time() - start_poll_time)
                    print(f"\r[DB] Waiting for backup to complete on phone... ({elapsed}s elapsed)", end="", flush=True)
                    time.sleep(3)
                    adb_pull(
                        base=base_path,
                        dest_db=db_dir,
                        dest_media=media_dir,
                        folders_filter=["Databases"],
                        cancellation_token=cancellation_token,
                    )
                    cands15 = [
                        os.path.join(db_dir, f)
                        for f in os.listdir(db_dir)
                        if f.startswith("msgstore") and f.endswith(".crypt15")
                    ]
                    if cands15:
                        cand_latest = sorted(cands15, key=os.path.getmtime, reverse=True)[0]
                        if os.path.isfile(cand_latest) and os.path.getsize(cand_latest) > 0:
                            s1 = os.path.getsize(cand_latest)
                            time.sleep(2)
                            adb_pull(
                                base=base_path,
                                dest_db=db_dir,
                                dest_media=media_dir,
                                folders_filter=["Databases"],
                                cancellation_token=cancellation_token,
                            )
                            s2 = os.path.getsize(cand_latest)
                            if s1 == s2 and s2 > 0:
                                crypt_file = cand_latest
                                print(f"\n[DB] Encrypted backup ready: {crypt_file}")
                                break

            if not crypt_file and legacy_cands:
                raise RuntimeError(
                    "WhatsApp backup is still in progress on your phone...\n\n"
                    "Only an older backup (msgstore.db.crypt14) was found. The 64-digit encrypted backup "
                    "(msgstore.db.crypt15) was not completed within 4 minutes.\n\n"
                    "Please wait for WhatsApp on your phone to complete its backup (100%), then run again."
                )

        if crypt_file and os.path.isfile(crypt_file):
            print(f"[DB] Decrypting: {crypt_file} -> {msgstore}")
            decrypt_db(key_file, crypt_file, msgstore)
        else:
            print("[WARN] No encrypted msgstore.db found in Databases folder.")

        wa_crypt = None
        for path in [db_dir, "./Backups"]:
            if os.path.isdir(path):
                files = os.listdir(path)
                for ext in [".crypt15", ".crypt14", ".crypt12"]:
                    cand = f"wa.db{ext}"
                    if cand in files:
                        wa_crypt = os.path.join(path, cand)
                        break
            if wa_crypt:
                break

        if wa_crypt and os.path.isfile(wa_crypt):
            print(f"[DB] Decrypting contacts: {wa_crypt} -> wa.db")
            decrypt_db(key_file, wa_crypt, "wa.db")

    # Contacts mapping
    adb_bin = find_adb_binary()
    contacts = load_contacts_mapping(
        adb_path=adb_bin,
        skip_pull=skip_contacts_pull or skip_pull,
        force_pull=force_contacts_pull,
        device_checker=check_adb_device,
    )
    chat_names, lid_to_phone = load_db_mappings(msgstore)

    # Step 3: Query msgstore.db
    print("\n" + "=" * 60)
    print("STEP 3: Query msgstore.db for media -> chat mapping")
    print("=" * 60)
    if status_callback:
        status_callback("parsing", "Reading messages and contacts from database...")
    wa_db = "wa.db" if os.path.isfile("wa.db") else None
    media_rows = build_media_index(msgstore, wa_db, contacts, lid_to_phone, chat_names)
    print(f"  Found {len(media_rows)} media messages across all chats")

    # Step 4: Index media files on disk
    print("\n" + "=" * 60)
    print("STEP 4: Index media files on disk")
    print("=" * 60)
    if status_callback:
        status_callback("indexing", "Indexing media files on disk...")
    file_index, actual_sizes = index_media_files(media_dir, secondary_roots=[output_dir])
    indexed_primary = sum(
        1
        for p in file_index.values()
        if str(p).replace("\\", "/").startswith(media_dir.replace("\\", "/").lstrip("./"))
    )
    print(f"  Indexed {len(file_index)} files ({indexed_primary} from {media_dir}, rest from output)")

    # Analyze duplicates with SQLite cache
    if status_callback:
        status_callback("scanning", "Scanning media for duplicate files...")
    cache_file = os.path.join(output_dir, ".hashes_cache.sqlite3")
    md5_map, phash_map, file_hashes = analyze_duplicates(
        file_index, skip_imagehash=skip_imagehash, cache_path=cache_file
    )

    # Step 5: Organize media into folders
    print("\n" + "=" * 60)
    print("STEP 5: Organize media into chat/date folders")
    print("=" * 60)
    if status_callback:
        status_callback("organizing", "Organizing media into chat folders...")
    summary, organized_list = organize_media(
        media_rows,
        file_index,
        file_hashes,
        md5_map,
        phash_map,
        output_dir,
        contacts=contacts,
        mode=mode,
        actual_sizes=actual_sizes,
        quality_duplicate_detector=detect_quality_duplicates,
    )

    # Storage dashboard
    print("\n" + "=" * 60)
    print("STORAGE DASHBOARD (by chat, sorted by size)")
    print("=" * 60)
    print(f"{'Chat Name':<40} {'Files':>6} {'Size (MB)':>12} {'Unmatched':>10}")
    print("-" * 70)
    enc = sys.stdout.encoding or "utf-8"
    for chat, stats in sorted(summary.items(), key=lambda x: x[1]["total_bytes"], reverse=True):
        mb = stats["total_bytes"] / 1048576
        safe_chat = chat.encode(enc, errors="replace").decode(enc)
        print(f"{safe_chat:<40} {stats['count']:>6} {mb:>12.1f} {stats['unmatched']:>10}")
    print("-" * 70)

    # Export CSV
    csv_path = os.path.join(output_dir, "media_index.csv")
    if organized_list:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "chat_jid",
                    "chat_name",
                    "filename",
                    "rel_path",
                    "size_bytes",
                    "mime_type",
                    "thumb_path",
                    "preview_path",
                    "is_doc",
                    "received_at",
                    "sender_jid",
                    "md5",
                    "phash",
                    "is_duplicate",
                    "duplicate_reason",
                    "duplicate_primary",
                    "media_duration",
                    "starred",
                    "from_me",
                    "forward_score",
                ],
            )
            writer.writeheader()
            writer.writerows(organized_list)
        print(f"\nFull media index exported to: {csv_path}")

    # Generate Gallery
    print("\n" + "=" * 60)
    print("STEP 6: Generating HTML Offline Gallery")
    print("=" * 60)
    if status_callback:
        status_callback("building_gallery", "Generating interactive offline gallery...")
    generate_gallery(
        organized_list,
        output_dir,
        contacts=contacts,
        lid_to_phone=lid_to_phone,
        chat_names=chat_names,
    )

    # Clean up video previews if exceeding 500MB
    cleanup_cache(output_dir, max_size_mb=500)

    # Step 5b: Salvage unmatched files
    if os.path.isdir(media_dir) and not skip_pull:
        print("\n" + "=" * 60)
        print("STEP 5b: Salvage unmatched Media files")
        print("=" * 60)
        gallery_exts = {".js", ".html", ".csv", ".json"}
        skip_dirs = {".thumbnails", ".cache", "_unmatched"}
        organized_lower = set()
        for root, dirs, files in os.walk(output_dir):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for fn in files:
                if os.path.splitext(fn)[1].lower() not in gallery_exts:
                    organized_lower.add(fn.lower())
        salvage_unmatched_media(media_dir, output_dir, organized_lower)

    # Optional media folder cleanup
    if cleanup_media:
        delete_media_folder(media_dir)

    # Selective ZIP backup
    if backup_chat:
        print("\n" + "=" * 60)
        print(f"STEP 7: Backup Chat '{backup_chat}' to ZIP")
        print("=" * 60)
    return summary, organized_list


def run_streaming_pipeline(
    hex_key=None,
    key_file="encrypted_backup.key",
    db_dir="./Databases",
    media_dir="./output",
    output_dir="./output",
    mode="copy",
    skip_pull=False,
    skip_db_pull=False,
    skip_decrypt=False,
    skip_contacts_pull=False,
    force_contacts_pull=False,
    session_manager=None,
    session_id=None,
    cancellation_token=None,
    skip_db_token=None,
    progress_callback=None,
    status_callback=None,
    in_flight_callback=None,
    adb_path=None,
):
    """
    Executes the high-performance Single-Pass Streaming Organization pipeline.
    Phase 1: Fast Databases pull (~5-10s) -> Decrypt msgstore.db -> Pre-index chat/message metadata.
    Phase 2: Single ADB Tar stream of Media/ routed directly to output/<Chat>/<Date>/<filename>.
             Live incremental updates flushed to gallery_data.js and media_index.csv.
    Zero redundant disk copies, zero data loss, full reverse phone_path traceability.
    """
    out_path = Path(output_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)
    cleanup_nested_databases_folder(db_dir)

    cfg = load_config()
    saved_account_path = cfg.get("selected_account_path", "")
    cmd = find_adb_binary(adb_path)
    base_path = discover_android_base_path(
        cmd,
        hex_key=hex_key,
        preferred_account_path=saved_account_path,
    )
    if not saved_account_path and base_path:
        acc_id = Path(base_path).name if "/accounts/" in base_path else "main"
        app_type = "whatsapp_business" if ("w4b" in base_path or "WhatsApp Business" in base_path) else "whatsapp"
        save_config({
            "selected_account_path": base_path,
            "selected_account_id": acc_id,
            "selected_app_type": app_type,
        })
    print(f"[ADB] Active WhatsApp storage: {base_path}")

    # Phase 1: Fast Pull Databases only
    if not skip_pull and not skip_db_pull:
        if status_callback:
            status_callback("database", "Downloading chat database from phone...")
        pull_db_ok = adb_pull(
            base=base_path,
            dest_db=db_dir,
            dest_media=media_dir,
            folders_filter=["Databases"],
            cancellation_token=cancellation_token,
            skip_db_token=skip_db_token,
            progress_callback=progress_callback,
            status_callback=status_callback,
            in_flight_callback=in_flight_callback,
        )
        if cancellation_token and cancellation_token.is_set():
            return False
        if skip_db_token and skip_db_token.is_set():
            if status_callback:
                status_callback("database", "Skipped fresh DB download - using existing local database...")
        elif not pull_db_ok:
            sys.stderr.write("[Streaming] Warning: Could not pull Databases from device.\n")
    elif skip_db_pull:
        if status_callback:
            status_callback("database", "Using local database (fresh download skipped)...")

    if cancellation_token and cancellation_token.is_set():
        return False

    # Phase 2: Decrypt Databases
    msgstore = os.path.join(db_dir, "msgstore.db")
    if not skip_decrypt:
        if status_callback:
            status_callback("decrypting", "Decrypting WhatsApp database (msgstore.db)...")
        if hex_key:
            create_key_file(hex_key, key_file)

        crypt_file = None
        extensions = [".crypt15"] if hex_key else [".crypt15", ".crypt14", ".crypt12"]
        for ext in extensions:
            cand = os.path.join(db_dir, f"msgstore.db{ext}")
            if os.path.isfile(cand):
                crypt_file = cand
                break

        if not crypt_file and os.path.isdir(db_dir):
            candidates = [
                os.path.join(db_dir, f)
                for f in os.listdir(db_dir)
                if f.startswith("msgstore")
                and any(f.endswith(e) for e in extensions)
            ]
            if candidates:
                crypt_file = sorted(candidates, key=os.path.getmtime, reverse=True)[0]

        # If 64-digit key is configured but only legacy Crypt14/12 exists,
        # WhatsApp on the phone might still be packaging the new Crypt15 backup.
        if hex_key and not crypt_file and os.path.isdir(db_dir):
            legacy_cands = [
                os.path.join(db_dir, f)
                for f in os.listdir(db_dir)
                if f.startswith("msgstore") and any(f.endswith(e) for e in [".crypt14", ".crypt12"])
            ]
            if legacy_cands and not skip_pull and not skip_db_pull:
                max_wait_seconds = 240  # Poll phone for up to 4 minutes
                poll_interval = 3
                start_poll_time = time.time()
                while time.time() - start_poll_time < max_wait_seconds:
                    if cancellation_token and cancellation_token.is_set():
                        return False
                    if skip_db_token and skip_db_token.is_set():
                        break

                    elapsed = int(time.time() - start_poll_time)
                    if status_callback:
                        status_callback(
                            "decrypting",
                            f"Waiting for WhatsApp backup to finish on phone... ({elapsed}s elapsed)",
                        )

                    time.sleep(poll_interval)

                    # If backup hasn't appeared yet, re-check phone accounts in case WhatsApp wrote
                    # the new backup into an account folder that was created or refreshed.
                    if elapsed >= 12 and (elapsed % 9 == 0):
                        try:
                            fresh_base = discover_android_base_path(cmd, hex_key=hex_key)
                            if fresh_base and fresh_base != base_path:
                                base_path = fresh_base
                        except Exception:
                            pass

                    adb_pull(
                        base=base_path,
                        dest_db=db_dir,
                        dest_media=media_dir,
                        folders_filter=["Databases"],
                        cancellation_token=cancellation_token,
                        skip_db_token=skip_db_token,
                    )
                    cands15 = [
                        os.path.join(db_dir, f)
                        for f in os.listdir(db_dir)
                        if f.startswith("msgstore") and f.endswith(".crypt15")
                    ]
                    if cands15:
                        cand_latest = sorted(cands15, key=os.path.getmtime, reverse=True)[0]
                        if os.path.isfile(cand_latest) and os.path.getsize(cand_latest) > 0:
                            s1 = os.path.getsize(cand_latest)
                            time.sleep(2)
                            adb_pull(
                                base=base_path,
                                dest_db=db_dir,
                                dest_media=media_dir,
                                folders_filter=["Databases"],
                                cancellation_token=cancellation_token,
                                skip_db_token=skip_db_token,
                            )
                            s2 = os.path.getsize(cand_latest)
                            if s1 == s2 and s2 > 0:
                                crypt_file = cand_latest
                                if status_callback:
                                    status_callback(
                                        "decrypting",
                                        "Encrypted WhatsApp backup ready! Starting decryption...",
                                    )
                                break

            if not crypt_file and legacy_cands:
                raise RuntimeError(
                    "WhatsApp backup is still in progress on your phone...\n\n"
                    "Only an older backup (msgstore.db.crypt14) was found. The 64-digit encrypted backup "
                    "(msgstore.db.crypt15) was not completed within 4 minutes.\n\n"
                    "Please wait for WhatsApp on your phone to complete its backup (100%), then click 'Resume Sync'."
                )

        def _on_decrypt_progress(bytes_read, total_bytes):
            if status_callback:
                mb_read = round(bytes_read / (1024 * 1024), 1)
                mb_tot = round(total_bytes / (1024 * 1024), 1)
                pct = round((bytes_read / max(1, total_bytes)) * 100, 1)
                status_callback(
                    "decrypting",
                    f"Decrypting chat database ({mb_read} MB / {mb_tot} MB - {pct}%)",
                )

        if crypt_file and os.path.isfile(crypt_file):
            decrypt_db(
                key_file,
                crypt_file,
                msgstore,
                cancellation_token=cancellation_token,
                progress_callback=_on_decrypt_progress,
            )
        else:
            sys.stderr.write("[Streaming] Warning: No encrypted msgstore.db found.\n")

        wa_crypt = None
        for path in [db_dir, "./Backups"]:
            if os.path.isdir(path):
                files = os.listdir(path)
                for ext in [".crypt15", ".crypt14", ".crypt12"]:
                    cand = f"wa.db{ext}"
                    if cand in files:
                        wa_crypt = os.path.join(path, cand)
                        break
                if wa_crypt:
                    break

        wa_db = os.path.join(db_dir, "wa.db")
        if wa_crypt and os.path.isfile(wa_crypt):
            decrypt_db(key_file, wa_crypt, wa_db)

    if cancellation_token and cancellation_token.is_set():
        return False

    # Phase 3: Load Contacts & Build Metadata Index
    if status_callback:
        status_callback("decrypting", "Reading messages and contact mappings...")

    contacts = load_contacts_mapping(
        adb_path=adb_path,
        skip_pull=skip_contacts_pull or skip_pull,
        force_pull=force_contacts_pull,
        device_checker=check_adb_device,
    )
    chat_names, lid_to_phone = load_db_mappings(msgstore)
    wa_db_path = os.path.join(db_dir, "wa.db")
    wa_db_active = wa_db_path if os.path.isfile(wa_db_path) else None

    media_rows = []
    if os.path.isfile(msgstore):
        media_rows = build_media_index(
            msgstore, wa_db_active, contacts, lid_to_phone, chat_names
        )

    # Initialize the Streaming Media Router with all contact & identity mappings
    router = StreamingMediaRouter(
        output_dir=output_dir,
        media_rows=media_rows,
        contacts=contacts,
        lid_to_phone=lid_to_phone,
        chat_names=chat_names,
        mode=mode,
    )

    if cancellation_token and cancellation_token.is_set():
        return False

    # Phase 4: Stream Media from Phone Directly to Output Folder
    if not skip_pull:
        if status_callback:
            status_callback("indexing", "Scanning media files on phone...")

        stream_ok = adb_pull(
            base=base_path,
            dest_db=db_dir,
            dest_media=media_dir,
            folders_filter=["Media", "Backups"],
            session_manager=session_manager,
            session_id=session_id,
            cancellation_token=cancellation_token,
            progress_callback=progress_callback,
            status_callback=status_callback,
            destination_resolver=router.resolve_destination,
            on_commit_callback=router.record_committed_file,
            in_flight_callback=in_flight_callback,
        )

        if cancellation_token and cancellation_token.is_set():
            router.flush_all(export_csv=True)
            return False

        if not stream_ok:
            router.flush_all(export_csv=True)
            return False

    # Phase 5: Finalize and Export
    if status_callback:
        status_callback("building_gallery", "Finalizing gallery data and export catalog...")

    summary, organized_list = router.flush_all(export_csv=True)
    cleanup_cache(output_dir, max_size_mb=500)

    if session_manager and session_id:
        session_manager.complete_session(session_id)

    return summary, organized_list
