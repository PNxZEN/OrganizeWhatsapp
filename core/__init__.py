"""
WhatsApp Media Organizer - Core Package.
Exposes modular engines for configuration, ADB, crypto, database, duplicates,
organizing, gallery generation, and HTTP server.
"""

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

from core.decrypt import (
    create_key_file,
    decrypt_db,
    find_wadecrypt_binary,
    validate_hex_key,
)

from core.contacts import (
    load_contacts_mapping,
    load_db_mappings,
    resolve_jid_name,
    sanitize_phone_to_jid,
)

from core.database import (
    build_media_index,
    get_table_columns,
)

from core.duplicates import (
    HashCache,
    analyze_duplicates,
    compute_fast_hash,
    compute_file_md5,
    compute_image_phash,
    detect_quality_duplicates,
)

from core.organizer import (
    StreamingMediaRouter,
    index_media_files,
    normalize_filename,
    organize_media,
    reorganize_unmatched_media,
    salvage_unmatched_media,
    sanitize_filename,
    sanitize_folder_name,
    zip_chat,
    zip_file_list,
)

from core.gallery import (
    gallery_data_lock,
    generate_gallery,
    get_chat_media,
    get_chats_summary,
    load_gallery_data,
    update_gallery_data_js,
    update_media_index_csv,
)

from core.server import (
    GalleryHTTPRequestHandler,
    find_open_port,
    start_gallery_server,
    sync_status,
)

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
