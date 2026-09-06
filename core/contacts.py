"""
WhatsApp Media Organizer - Contacts and Identity Resolution.
Manages contact resolution from Android contacts provider, wa.db, and msgstore.db.
"""

import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path


def sanitize_phone_to_jid(phone_number, default_country_code="91"):
    """
    Converts a phone number string to a WhatsApp JID.
    Handles international prefixes (+, 00) and provides flexible resolution.
    Returns a list of candidate JIDs in priority order.
    """
    if not phone_number:
        return []

    raw = str(phone_number).strip()
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return []

    candidates = []

    # If original number started with '+' or '00', it already contains a country code
    if raw.startswith("+"):
        candidates.append(f"{digits}@s.whatsapp.net")
    elif raw.startswith("00"):
        candidates.append(f"{digits[2:]}@s.whatsapp.net")
    else:
        # If it has 10 digits, it could be a local number without country code
        if len(digits) == 10:
            if default_country_code:
                candidates.append(f"{default_country_code}{digits}@s.whatsapp.net")
            candidates.append(f"{digits}@s.whatsapp.net")
        elif len(digits) == 11 and digits.startswith("0"):
            # Local number with leading zero (e.g. UK 07xxx)
            trimmed = digits[1:]
            if default_country_code:
                candidates.append(f"{default_country_code}{trimmed}@s.whatsapp.net")
            candidates.append(f"{trimmed}@s.whatsapp.net")
        else:
            candidates.append(f"{digits}@s.whatsapp.net")

    return candidates


def load_contacts_mapping(
    cache_path="contacts_map.json",
    adb_path=None,
    skip_pull=False,
    force_pull=False,
    device_checker=None,
    status_callback=None,
):
    """
    Loads contact mappings from local JSON cache or queries the phone via ADB.
    Returns a dictionary mapping JID -> Display Name.
    """
    orig_status_cb = status_callback
    def _emit_status(phase, label, total_files=None, detail=None):
        if not orig_status_cb:
            return
        try:
            orig_status_cb(phase, label, total_files=total_files, detail=detail)
        except TypeError:
            try:
                orig_status_cb(phase, label, total=total_files, detail=detail)
            except TypeError:
                try:
                    orig_status_cb(phase, label, total_files)
                except TypeError:
                    try:
                        orig_status_cb(phase, label)
                    except Exception:
                        pass
    status_callback = _emit_status if orig_status_cb else None

    contacts = {}
    cache_file = Path(cache_path)

    # 1. Load from cache first
    if cache_file.is_file():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                contacts = json.load(f)
        except Exception as e:
            sys.stderr.write(f"[Contacts] Warning: Failed to read {cache_path}: {e}\n")

    # 2. Query phone via ADB if needed
    if not adb_path and not skip_pull:
        try:
            from core.adb import find_adb_binary
            adb_path = find_adb_binary()
        except Exception:
            pass

    should_pull = False
    if adb_path and not skip_pull:
        if force_pull or not contacts:
            should_pull = True

    if should_pull:
        can_proceed = True
        if device_checker:
            status = device_checker(adb_path)
            if hasattr(status, "connected") and hasattr(status, "authorized"):
                connected = status.connected
                authorized = status.authorized
            elif isinstance(status, (tuple, list)):
                connected = status[0] if len(status) > 0 else False
                authorized = status[1] if len(status) > 1 else False
            elif isinstance(status, bool):
                connected = authorized = status
            else:
                connected = authorized = False

            if not connected or not authorized:
                can_proceed = False

        if can_proceed:
            if status_callback:
                status_callback(
                    "decrypting",
                    "Querying phone contacts over ADB...",
                    detail="Reading address book names via content://contacts/phones",
                )
            try:
                cmd = [
                    adb_path,
                    "shell",
                    "content query --uri content://contacts/phones --projection display_name:number",
                ]
                res = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
                if res.returncode == 0:
                    pattern = re.compile(r"display_name=(.*?),\s+number=(.*)")
                    phone_count = 0
                    for line in res.stdout.splitlines():
                        match = pattern.search(line)
                        if match:
                            name = match.group(1).strip()
                            num = match.group(2).strip()
                            jids = sanitize_phone_to_jid(num)
                            for jid in jids:
                                contacts[jid] = name
                            if jids:
                                phone_count += 1

                    if phone_count > 0:
                        if status_callback:
                            status_callback(
                                "decrypting",
                                f"Extracted {phone_count:,} phone contacts",
                                detail=f"Mapped {len(contacts):,} contacts to WhatsApp chat identities",
                            )
                        try:
                            with open(cache_file, "w", encoding="utf-8") as f:
                                json.dump(contacts, f, indent=2, ensure_ascii=False)
                        except Exception as e:
                            sys.stderr.write(f"[Contacts] Warning: Failed to write cache: {e}\n")
            except Exception as e:
                sys.stderr.write(f"[Contacts] Warning: Failed to query contacts via ADB: {e}\n")

    return contacts


def load_db_mappings(msgstore_path):
    """
    Loads chat subjects and LID mappings from msgstore.db.
    Returns (chat_names: dict, lid_to_phone: dict).
    """
    chat_names = {}
    lid_to_phone = {}
    p = Path(msgstore_path)
    if not p.is_file():
        return chat_names, lid_to_phone

    try:
        conn = sqlite3.connect(str(p))
        cur = conn.cursor()

        # Load chat subjects (groups, broadcast lists, individual subjects)
        try:
            cur.execute(
                """
                SELECT j.raw_string, COALESCE(c.subject, j.raw_string)
                FROM chat c
                JOIN jid j ON c.jid_row_id = j._id
            """
            )
            for row in cur.fetchall():
                jid, subject = row[0], row[1]
                if jid and subject and subject != jid:
                    chat_names[jid] = subject
        except Exception:
            pass

        # Load LID mapping (privacy-preserving LIDs to phone JIDs)
        try:
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jid_map'")
            if cur.fetchone():
                cur.execute(
                    """
                    SELECT j_lid.raw_string, j_phone.raw_string
                    FROM jid_map jm
                    JOIN jid j_lid ON jm.lid_row_id = j_lid._id
                    JOIN jid j_phone ON jm.jid_row_id = j_phone._id
                """
                )
                for row in cur.fetchall():
                    lid, phone = row[0], row[1]
                    if lid and phone:
                        lid_to_phone[lid] = phone
        except Exception:
            pass

        conn.close()
    except Exception as e:
        sys.stderr.write(f"[Contacts] Warning: Failed to load db mappings from {msgstore_path}: {e}\n")

    return chat_names, lid_to_phone


def resolve_jid_name(jid, contacts, lid_to_phone, chat_names):
    """
    Translates a JID (phone, LID, or broadcast) into a human-readable contact name.
    """
    if not jid:
        return None

    # 1. If it is a LID, resolve to standard phone JID
    resolved_jid = lid_to_phone.get(jid, jid)

    # 2. Direct lookup in contacts
    if resolved_jid in contacts:
        return contacts[resolved_jid]
    if jid in contacts:
        return contacts[jid]

    # 3. Handle 10-digit / country-code variations in contacts
    if "@s.whatsapp.net" in resolved_jid:
        digits = resolved_jid.split("@")[0]
        # If 12 digits starting with 91, try 10 digits
        if len(digits) == 12 and digits.startswith("91"):
            fallback_jid = f"{digits[2:]}@s.whatsapp.net"
            if fallback_jid in contacts:
                return contacts[fallback_jid]
        # If 10 digits, try 91 prefix
        elif len(digits) == 10:
            fallback_jid = f"91{digits}@s.whatsapp.net"
            if fallback_jid in contacts:
                return contacts[fallback_jid]

    # 4. Check in chat_names (group subjects / broadcast names)
    if jid in chat_names:
        return chat_names[jid]
    if resolved_jid in chat_names:
        return chat_names[resolved_jid]

    # 5. Special broadcast cases
    if jid == "status@broadcast":
        return "Status Update"

    return None
