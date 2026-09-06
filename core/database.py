"""
WhatsApp Media Organizer - Database Query Engine.
Parses SQLite msgstore.db schemas (modern and legacy) to extract media metadata.
"""

import os
import sqlite3
import sys
from pathlib import Path

from core.contacts import resolve_jid_name


def get_table_columns(cur, table_name):
    """Returns a list of column names for a given table."""
    try:
        cur.execute(f"PRAGMA table_info({table_name})")
        return [row[1] for row in cur.fetchall()]
    except Exception:
        return []


def build_media_index(
    msgstore_path,
    wa_db_path=None,
    contacts=None,
    lid_to_phone=None,
    chat_names=None,
):
    """
    Queries msgstore.db to get a list of media messages mapped to chats.
    Supports both modern (message + message_media) and legacy (messages) WhatsApp schemas.
    Returns a list of dictionaries with all 20 required media metadata fields.
    """
    db_p = Path(msgstore_path)
    if not db_p.is_file():
        sys.stderr.write(f"[DB] Error: Database file not found: {msgstore_path}\n")
        return []

    conn = sqlite3.connect(str(db_p))
    try:
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.execute("PRAGMA cache_size = -32000")
    except Exception:
        pass
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    wa_attached = False
    if wa_db_path and Path(wa_db_path).is_file():
        try:
            cur.execute(f"ATTACH DATABASE '{wa_db_path}' AS wa")
            wa_attached = True
        except Exception as e:
            sys.stderr.write(f"[DB] Warning: Failed to attach wa.db: {e}\n")

    # Get list of tables in msgstore.db
    try:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cur.fetchall()]
    except sqlite3.DatabaseError as e_db:
        conn.close()
        raise RuntimeError(
            f"Failed to read database '{msgstore_path}': {e_db}. "
            "The chat database file appears corrupt or was not completely decrypted."
        )

    has_fwd_table = "message_forwarded" in tables
    select_fwd = "COALESCE(m_fwd.forward_score, 0)" if has_fwd_table else "0"
    join_fwd = "LEFT JOIN message_forwarded m_fwd ON m._id = m_fwd.message_row_id" if has_fwd_table else ""

    rows = []

    if "message_media" in tables:
        media_cols = get_table_columns(cur, "message_media")
        has_media_name = "media_name" in media_cols

        file_path_col = "file_path" if "file_path" in media_cols else "NULL"
        file_size_col = (
            "file_size"
            if "file_size" in media_cols
            else ("media_size" if "media_size" in media_cols else "NULL")
        )
        mime_col = (
            "mime_type"
            if "mime_type" in media_cols
            else ("media_mime_type" if "media_mime_type" in media_cols else "NULL")
        )
        duration_col = "media_duration" if "media_duration" in media_cols else "NULL"

        file_hash_col = "file_hash" if "file_hash" in media_cols else "NULL"
        enc_hash_col = "enc_file_hash" if "enc_file_hash" in media_cols else "NULL"
        orig_hash_col = "original_file_hash" if "original_file_hash" in media_cols else "NULL"

        msg_cols = get_table_columns(cur, "message")
        has_sender_jid = "sender_jid_row_id" in msg_cols
        msg_type_col = "m.message_type" if "message_type" in msg_cols else "0"

        select_media_name = "m_media.media_name" if has_media_name else "NULL"
        select_sender = "sender_j.raw_string" if has_sender_jid else "NULL"
        join_sender = (
            "LEFT JOIN jid sender_j ON m.sender_jid_row_id = sender_j._id"
            if has_sender_jid
            else ""
        )

        if wa_attached:
            query = f"""
            SELECT 
                j.raw_string AS chat_jid,
                COALESCE(wa.display_name, wa.wa_name, c.subject, j.raw_string) AS chat_name,
                {select_media_name} AS filename,
                {select_media_name} AS media_name,
                m_media.{file_path_col} AS file_path,
                m_media.{file_size_col} AS size_bytes,
                m_media.{mime_col} AS mime_type,
                m_media.{duration_col} AS media_duration,
                datetime(m.timestamp / 1000, 'unixepoch', 'localtime') AS received_at,
                {select_sender} AS sender_jid,
                m.starred AS starred,
                m.from_me AS from_me,
                {select_fwd} AS forward_score,
                m_media.{file_hash_col} AS file_hash,
                m_media.{enc_hash_col} AS enc_file_hash,
                m_media.{orig_hash_col} AS original_file_hash,
                {msg_type_col} AS message_type
            FROM message m
            JOIN message_media m_media ON m._id = m_media.message_row_id
            JOIN chat c ON m.chat_row_id = c._id
            JOIN jid j ON c.jid_row_id = j._id
            {join_sender}
            LEFT JOIN wa.wa_contacts wa ON wa.jid = j.raw_string
            {join_fwd}
            """
        else:
            query = f"""
            SELECT 
                j.raw_string AS chat_jid,
                COALESCE(c.subject, j.raw_string) AS chat_name,
                {select_media_name} AS filename,
                {select_media_name} AS media_name,
                m_media.{file_path_col} AS file_path,
                m_media.{file_size_col} AS size_bytes,
                m_media.{mime_col} AS mime_type,
                m_media.{duration_col} AS media_duration,
                datetime(m.timestamp / 1000, 'unixepoch', 'localtime') AS received_at,
                {select_sender} AS sender_jid,
                m.starred AS starred,
                m.from_me AS from_me,
                {select_fwd} AS forward_score,
                m_media.{file_hash_col} AS file_hash,
                m_media.{enc_hash_col} AS enc_file_hash,
                m_media.{orig_hash_col} AS original_file_hash,
                {msg_type_col} AS message_type
            FROM message m
            JOIN message_media m_media ON m._id = m_media.message_row_id
            JOIN chat c ON m.chat_row_id = c._id
            JOIN jid j ON c.jid_row_id = j._id
            {join_sender}
            {join_fwd}
            """
        try:
            cur.execute(query)
            rows = [dict(r) for r in cur.fetchall()]
        except Exception as e:
            sys.stderr.write(f"[DB] Error: Modern query failed: {e}\n")
            rows = []

        # Extract clean filename and prioritize real document media_name
        for r in rows:
            fp = r.get("file_path") or ""
            mn = r.get("media_name") or ""
            clean_fp_base = os.path.basename(fp) if fp else ""
            clean_mn = mn if mn and mn != "NULL" and not mn.endswith(".crypt15") else ""

            # When media_name is a real human-readable filename (e.g. cbjescss08.pdf):
            # Prioritize media_name!
            if clean_mn and (clean_fp_base.startswith(".Shared") or not clean_fp_base or ("." in clean_mn and "." not in clean_fp_base)):
                r["filename"] = clean_mn
            elif clean_fp_base:
                r["filename"] = clean_fp_base
            else:
                r["filename"] = clean_mn or ""

            if not r.get("filename") or r["filename"] == "NULL":
                r["filename"] = ""

    elif "messages" in tables or "message" in tables:
        target_table = "messages" if "messages" in tables else "message"
        cols = get_table_columns(cur, target_table)

        jid_col = "key_remote_jid" if "key_remote_jid" in cols else "chat_row_id"
        media_name_col = "media_name" if "media_name" in cols else "NULL"
        media_url_col = (
            "media_url"
            if "media_url" in cols
            else ("file_path" if "file_path" in cols else "NULL")
        )
        media_size_col = (
            "media_size"
            if "media_size" in cols
            else ("file_size" if "file_size" in cols else "NULL")
        )
        mime_col = (
            "media_mime_type"
            if "media_mime_type" in cols
            else ("mime_type" if "mime_type" in cols else "NULL")
        )
        duration_col = "media_duration" if "media_duration" in cols else "NULL"
        sender_col = (
            "remote_resource"
            if "remote_resource" in cols
            else ("sender_jid_row_id" if "sender_jid_row_id" in cols else "NULL")
        )

        if wa_attached and jid_col == "key_remote_jid":
            query = f"""
            SELECT 
                m.{jid_col} AS chat_jid,
                COALESCE(wa.display_name, wa.wa_name, m.{jid_col}) AS chat_name,
                {media_name_col} AS filename,
                {media_url_col} AS file_path,
                {media_size_col} AS size_bytes,
                {mime_col} AS mime_type,
                {duration_col} AS media_duration,
                datetime(m.timestamp / 1000, 'unixepoch', 'localtime') AS received_at,
                {sender_col} AS sender_jid,
                m.starred AS starred,
                m.from_me AS from_me,
                {select_fwd} AS forward_score
            FROM {target_table} m
            LEFT JOIN wa.wa_contacts wa ON wa.jid = m.{jid_col}
            {join_fwd}
            WHERE ({media_url_col} IS NOT NULL AND {media_url_col} != '') OR ({media_name_col} IS NOT NULL AND {media_name_col} != '')
            ORDER BY m.{jid_col}, m.timestamp
            """
        else:
            query = f"""
            SELECT 
                m.{jid_col} AS chat_jid,
                m.{jid_col} AS chat_name,
                {media_name_col} AS filename,
                {media_url_col} AS file_path,
                {media_size_col} AS size_bytes,
                {mime_col} AS mime_type,
                {duration_col} AS media_duration,
                datetime(m.timestamp / 1000, 'unixepoch', 'localtime') AS received_at,
                {sender_col} AS sender_jid,
                m.starred AS starred,
                m.from_me AS from_me,
                {select_fwd} AS forward_score
            FROM {target_table} m
            {join_fwd}
            WHERE ({media_url_col} IS NOT NULL AND {media_url_col} != '') OR ({media_name_col} IS NOT NULL AND {media_name_col} != '')
            """
        try:
            cur.execute(query)
            rows = [dict(r) for r in cur.fetchall()]
        except Exception as e:
            sys.stderr.write(f"[DB] Error: Legacy query failed: {e}\n")
            rows = []

        for r in rows:
            if r.get("file_path"):
                r["filename"] = os.path.basename(r["file_path"])
            if not r.get("filename") or r["filename"] == "NULL":
                r["filename"] = ""
    else:
        sys.stderr.write("[DB] Error: No recognized message tables in msgstore.db.\n")

    # Map JID to real name for chat_name if available in contacts/DB mappings
    contacts_map = contacts or {}
    lids_map = lid_to_phone or {}
    chats_map = chat_names or {}
    for r in rows:
        chat_jid = r.get("chat_jid")
        if chat_jid:
            resolved = resolve_jid_name(chat_jid, contacts_map, lids_map, chats_map)
            if resolved:
                r["chat_name"] = resolved

        # Ensure numeric fields default to 0
        r["starred"] = r.get("starred") or 0
        r["from_me"] = r.get("from_me") or 0
        r["forward_score"] = r.get("forward_score") or 0

    conn.close()
    return rows
