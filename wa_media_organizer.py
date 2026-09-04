#!/usr/bin/env python3
"""
WhatsApp Media Organizer - Main Entry Point and CLI Adapter.
Provides full backward compatibility for command-line arguments while delegating
to the modular core package.
"""

import argparse
import os
import sys
import threading
import time
from pathlib import Path

# Add project root to sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# Reconfigure terminal stdout/stderr to use UTF-8 to prevent Cp1252 UnicodeEncodeErrors
# If running under pythonw.exe, redirect None streams to os.devnull to prevent NoneType write crashes
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8", errors="replace")
elif sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8", errors="replace")
elif sys.platform == "win32":
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Backward-compatible symbol exports from core
from core.adb import (
    adb_pull,
    adb_pull_tar,
    check_adb_device,
    cleanup_nested_databases_folder,
    disable_developer_options,
    discover_android_base_path,
    find_adb_binary,
    wait_for_adb_device,
)
from core.config import (
    DEFAULT_CONFIG_FILE,
    DEFAULT_CONTACTS_CACHE,
    DEFAULT_DB_DIR,
    DEFAULT_IDLE_TIMEOUT,
    DEFAULT_KEY_FILE,
    DEFAULT_MEDIA_DIR,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PORT,
    load_config,
    mask_key,
    save_config,
    to_long_path,
)
from core.contacts import (
    load_contacts_mapping,
    load_db_mappings,
    resolve_jid_name,
    sanitize_phone_to_jid,
)
from core.database import build_media_index, get_table_columns
from core.decrypt import (
    create_key_file,
    decrypt_db,
    find_wadecrypt_binary,
    validate_hex_key,
)
from core.duplicates import (
    HashCache,
    analyze_duplicates,
    compute_fast_hash,
    compute_file_md5,
    compute_image_phash,
    detect_quality_duplicates,
)
from core.gallery import (
    gallery_data_lock,
    generate_gallery,
    update_gallery_data_js,
    update_gallery_data_live,
    update_media_index_csv,
)
from core.organizer import (
    index_media_files,
    normalize_filename,
    organize_media,
    salvage_unmatched_media,
    sanitize_filename,
    sanitize_folder_name,
    zip_chat,
    zip_file_list,
)
from core.pipeline import (
    cleanup_cache,
    delete_media_folder,
    file_stability_check,
    run_pipeline,
)
from core.server import (
    GalleryHTTPRequestHandler,
    find_open_port,
    start_gallery_server,
    sync_status,
)

# Legacy global aliases
_gallery_data_lock = gallery_data_lock
_sync_status = sync_status
_update_gallery_data_live = update_gallery_data_live


def background_organizer_loop(args, media_rows, contacts, lid_to_phone, chat_names):
    """
    Runs in a daemon background thread during --live mode.
    Periodically checks for newly arrived media from phone, organizes them,
    and merges them into gallery_data.js.
    """
    poll_interval = 30
    prev_index_keys = set()
    consecutive_idle = 0

    print("[Live] Background organizer started. Polling every 30 seconds.")

    while True:
        time.sleep(poll_interval)
        try:
            file_index, actual_sizes = index_media_files(
                args.media_dir, secondary_roots=[args.output]
            )
            current_keys = set(file_index.keys())
            raw_new_keys = current_keys - prev_index_keys

            if not raw_new_keys:
                consecutive_idle += 1
                if _sync_status.get("media_pull_done") and consecutive_idle >= 2:
                    print("[Live] No new files detected. Background organizer stopping.")
                    break
                continue

            stable_new_keys = set()
            for k in raw_new_keys:
                path = file_index.get(k)
                if path and file_stability_check(path, wait_ms=500):
                    stable_new_keys.add(k)

            if not stable_new_keys:
                continue

            consecutive_idle = 0
            prev_index_keys = current_keys

            cache_file = os.path.join(args.output, ".hashes_cache.sqlite3")
            md5_map, phash_map, file_hashes = analyze_duplicates(
                file_index, skip_imagehash=True, cache_path=cache_file
            )

            _, new_organized = organize_media(
                media_rows,
                file_index,
                file_hashes,
                md5_map,
                phash_map,
                args.output,
                contacts=contacts,
                mode=args.mode,
                actual_sizes=actual_sizes,
            )

            if not new_organized:
                continue

            update_gallery_data_live(
                new_organized, args.output, contacts, lid_to_phone, chat_names
            )

            _sync_status["version"] = _sync_status.get("version", 0) + 1
            _sync_status["organized_count"] = (
                _sync_status.get("organized_count", 0) + len(new_organized)
            )
            print(
                f"[Live] +{len(new_organized)} files organized. "
                f"Gallery v{_sync_status['version']} ({_sync_status['organized_count']} total)."
            )

        except Exception as e:
            sys.stderr.write(f"[Live] Warning: Background organizer error: {e}\n")

    _sync_status["active"] = False
    _sync_status["phase"] = "done"
    print("[Live] Background organizer finished. Gallery is fully synced.")


def main():
    """Main CLI entry point with backward-compatible argument parsing."""
    ap = argparse.ArgumentParser(description="WhatsApp Media Organizer (ADB pipeline)")
    ap.add_argument("--hex-key", help="64-char hex E2E backup key")
    ap.add_argument("--key-file", default=DEFAULT_KEY_FILE, help="Pre-made key file path")
    ap.add_argument("--db-dir", default=DEFAULT_DB_DIR, help="Folder containing .crypt15 files")
    ap.add_argument("--media-dir", default=DEFAULT_MEDIA_DIR, help="Pulled WhatsApp Media folder")
    ap.add_argument("--output", default=DEFAULT_OUTPUT_DIR, help="Destination for organized media")
    ap.add_argument("--mode", choices=["copy", "symlink"], default="copy")
    ap.add_argument("--skip-pull", action="store_true", help="Skip ADB pull (use existing dirs)")
    ap.add_argument("--skip-db-pull", action="store_true", help="Skip pulling Databases from phone (use existing local Databases/ folder)")
    ap.add_argument("--skip-decrypt", action="store_true", help="Skip decryption (use existing .db)")
    ap.add_argument("--backup-chat", help="Case-insensitive chat name to back up as a zip archive")
    ap.add_argument("--no-verify", action="store_true", help="Skip integrity verification for zip backups")
    ap.add_argument("--skip-imagehash", action="store_true", help="Skip perceptual image hashing (phash) for faster runs")
    ap.add_argument("--backup-list", help="Path to a text file containing file paths to back up as a zip archive")
    ap.add_argument("--skip-contacts-pull", action="store_true", help="Skip querying phone contacts via ADB")
    ap.add_argument("--force-contacts-pull", action="store_true", help="Force querying phone contacts via ADB even if cache exists")
    ap.add_argument("--serve", action="store_true", help="Start local Python web server to view gallery and transcode on-the-fly")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to run the local server on (default: 8000)")
    ap.add_argument("--idle-timeout", type=int, default=DEFAULT_IDLE_TIMEOUT, help="Auto-shutdown server after N minutes of inactivity (0 to disable)")
    ap.add_argument("--auto-open", action="store_true", help="Automatically open gallery in browser when server starts")
    ap.add_argument("--allow-lan", action="store_true", help="Bind to all network interfaces (0.0.0.0) instead of 127.0.0.1")
    ap.add_argument("--cleanup-media", action="store_true", help="After organizing, salvage unmatched files then interactively delete ./Media to free space")
    ap.add_argument(
        "--live",
        action="store_true",
        help="Live pipeline: pull Databases first, open gallery immediately, then pull Media in background",
    )

    args = ap.parse_args()

    # Zero-terminal default: if no arguments given and output folder exists, start server
    if len(sys.argv) == 1 and Path(args.output).is_dir():
        start_gallery_server(
            args.output,
            port=args.port,
            idle_timeout=args.idle_timeout,
            auto_open=True,
            allow_lan=args.allow_lan,
        )
        return

    if args.serve:
        start_gallery_server(
            args.output,
            port=args.port,
            idle_timeout=args.idle_timeout,
            auto_open=args.auto_open,
            allow_lan=args.allow_lan,
        )
        return

    if args.backup_list:
        if not os.path.isfile(args.backup_list):
            print(f"[ERROR] Selected files list not found: {args.backup_list}")
            sys.exit(1)
        with open(args.backup_list, "r", encoding="utf-8") as f:
            rel_paths = [line.strip() for line in f if line.strip()]
        success, zip_path, count = zip_file_list(rel_paths, args.output, verify=not args.no_verify)
        if success:
            print(f"[Backup] Successfully created archive: {zip_path} ({count} files)")
        else:
            print(f"[Backup] Error: {zip_path}")
            sys.exit(1)
        return

    # Two-phase live pipeline
    if args.live:
        msgstore_live = os.path.join(args.db_dir, "msgstore.db")

        if not args.skip_pull:
            print("=" * 60)
            print("STEP 1a: ADB Pull: Databases only (fast)")
            print("=" * 60)
            adb_pull(dest_db=args.db_dir, folders_filter=["Databases"])

        cleanup_nested_databases_folder(args.db_dir)
        if not args.skip_decrypt:
            print("\n" + "=" * 60)
            print("STEP 2: Decrypt msgstore.db")
            print("=" * 60)
            if args.hex_key:
                create_key_file(args.hex_key, args.key_file)

            crypt_file = None
            for ext in [".crypt15", ".crypt14", ".crypt12"]:
                candidate = os.path.join(args.db_dir, f"msgstore.db{ext}")
                if os.path.isfile(candidate):
                    crypt_file = candidate
                    break

            if crypt_file and os.path.isfile(crypt_file):
                print(f"[DB] Decrypting: {crypt_file} -> {msgstore_live}")
                decrypt_db(args.key_file, crypt_file, msgstore_live)

        contacts_live = load_contacts_mapping(
            skip_pull=args.skip_contacts_pull or args.skip_pull,
            force_pull=args.force_contacts_pull,
            device_checker=check_adb_device,
        )
        chat_names_live, lid_to_phone_live = load_db_mappings(msgstore_live)

        wa_db_live = "wa.db" if os.path.isfile("wa.db") else None
        media_rows_live = build_media_index(
            msgstore_live, wa_db_live, contacts_live, lid_to_phone_live, chat_names_live
        )

        file_index_live, actual_sizes_live = index_media_files(
            args.media_dir, secondary_roots=[args.output]
        )

        cache_file_live = os.path.join(args.output, ".hashes_cache.sqlite3")
        md5_map_live, phash_map_live, file_hashes_live = analyze_duplicates(
            file_index_live, skip_imagehash=True, cache_path=cache_file_live
        )

        summary_live, organized_live = organize_media(
            media_rows_live,
            file_index_live,
            file_hashes_live,
            md5_map_live,
            phash_map_live,
            args.output,
            contacts=contacts_live,
            mode=args.mode,
            actual_sizes=actual_sizes_live,
        )

        generate_gallery(
            organized_live,
            args.output,
            contacts=contacts_live,
            lid_to_phone=lid_to_phone_live,
            chat_names=chat_names_live,
        )

        # Start live background worker
        _sync_status["active"] = True
        _sync_status["phase"] = "syncing"
        _sync_status["organized_count"] = len(organized_live)

        organizer_thread = threading.Thread(
            target=background_organizer_loop,
            args=(args, media_rows_live, contacts_live, lid_to_phone_live, chat_names_live),
            daemon=True,
        )
        organizer_thread.start()

        # Start server in main thread
        start_gallery_server(
            args.output,
            port=args.port,
            idle_timeout=0,  # Never auto-kill during live sync
            auto_open=True,
            allow_lan=args.allow_lan,
        )
        return

    # Standard pipeline execution
    run_pipeline(
        hex_key=args.hex_key,
        key_file=args.key_file,
        db_dir=args.db_dir,
        media_dir=args.media_dir,
        output_dir=args.output,
        mode=args.mode,
        skip_pull=args.skip_pull,
        skip_db_pull=args.skip_db_pull,
        skip_decrypt=args.skip_decrypt,
        skip_imagehash=args.skip_imagehash,
        skip_contacts_pull=args.skip_contacts_pull,
        force_contacts_pull=args.force_contacts_pull,
        cleanup_media=args.cleanup_media,
        backup_chat=args.backup_chat,
        no_verify=args.no_verify,
    )

    if args.auto_open:
        start_gallery_server(
            args.output,
            port=args.port,
            idle_timeout=args.idle_timeout,
            auto_open=True,
            allow_lan=args.allow_lan,
        )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[INFO] Execution interrupted by user (Ctrl+C). Terminating gracefully.")
        sys.exit(130)
