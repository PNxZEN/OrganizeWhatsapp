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


def sanitize_phone_to_jid(phone_number, default_country_code=None):
    """
    Converts a phone number string to a WhatsApp JID.
    Handles international prefixes (+, 00) and provides flexible resolution.
    Returns a list of candidate JIDs in priority order.
    """
    if not phone_number:
        return []

    if default_country_code is None:
        default_country_code = get_account_country_code()

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


def infer_country_code_from_phone(phone_number):
    """
    Heuristic country-code extraction from an E.164 / WhatsApp registration number.
    Uses everything before the final 10 digits (IN 91+10, US/CA 1+10, UK 44+10).
    """
    digits = re.sub(r"\D", "", str(phone_number or ""))
    if len(digits) >= 11:
        return digits[:-10]
    return ""


def get_account_country_code():
    """Country code for the currently selected WhatsApp account, or empty if unknown."""
    try:
        from core.config import load_config

        phone = load_config().get("selected_account_phone") or ""
        return infer_country_code_from_phone(phone)
    except Exception:
        return ""


def load_wa_contacts(wa_db_path):
    """
    Extracts saved contacts and display names directly from decrypted wa.db.
    Returns a dict mapping JID -> display_name and phone JIDs.
    """
    contacts = {}
    if not wa_db_path or not os.path.isfile(wa_db_path):
        return contacts
    conn = None
    try:
        conn = sqlite3.connect(str(wa_db_path))
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cur.fetchall()}
        if "wa_contacts" in tables:
            cur.execute("PRAGMA table_info(wa_contacts)")
            cols = {row[1] for row in cur.fetchall()}
            jid_col = "jid" if "jid" in cols else None
            name_col = "display_name" if "display_name" in cols else ("wa_name" if "wa_name" in cols else None)
            number_col = "number" if "number" in cols else ("phone_number" if "phone_number" in cols else None)

            if jid_col and name_col:
                cur.execute(f"SELECT {jid_col}, {name_col}, {number_col or 'NULL'} FROM wa_contacts")
                for row in cur.fetchall():
                    raw_jid = row[0]
                    name = row[1]
                    num = row[2]
                    if raw_jid and name and str(name).strip() and str(name).strip() != str(raw_jid).strip():
                        clean_name = str(name).strip()
                        contacts[str(raw_jid).strip()] = clean_name
                        digits = re.sub(r"\D", "", str(raw_jid).split("@")[0])
                        if len(digits) >= 10:
                            contacts[f"suffix10_{digits[-10:]}"] = clean_name
                        if num:
                            num_digits = re.sub(r"\D", "", str(num))
                            if num_digits:
                                contacts[f"{num_digits}@s.whatsapp.net"] = clean_name
                                if len(num_digits) >= 10:
                                    contacts[f"suffix10_{num_digits[-10:]}"] = clean_name
    except Exception as e:
        sys.stderr.write(f"[Contacts] Warning: Failed to read wa.db: {e}\n")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
    return contacts


def load_contacts_mapping(
    cache_path="contacts_map.json",
    adb_path=None,
    skip_pull=False,
    force_pull=False,
    device_checker=None,
    status_callback=None,
    wa_db_path=None,
):
    """
    Loads contact mappings from local JSON cache, wa.db, or queries the phone via ADB.
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
                    phone_count = 0
                    for line in res.stdout.splitlines():
                        name = None
                        num = None
                        for part in re.split(r",\s*(?=[a-zA-Z_]+=)", line):
                            part = part.strip()
                            if part.startswith("display_name="):
                                name = part[len("display_name="):].strip()
                            elif part.startswith("number="):
                                num = part[len("number="):].strip()
                        if name and num:
                            jids = sanitize_phone_to_jid(num)
                            for jid in jids:
                                contacts[jid] = name
                            digits = re.sub(r"\D", "", num)
                            if len(digits) >= 10:
                                contacts[f"suffix10_{digits[-10:]}"] = name
                            if jids or len(digits) >= 10:
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

    # 3. Augment with wa.db if available
    if not wa_db_path:
        for cand in ("wa.db", str(cache_file.parent / "wa.db"), str(cache_file.parent / "databases" / "wa.db")):
            if os.path.isfile(cand):
                wa_db_path = cand
                break
    if wa_db_path and os.path.isfile(wa_db_path):
        wa_map = load_wa_contacts(wa_db_path)
        for k, v in wa_map.items():
            if k not in contacts:
                contacts[k] = v
            digits = re.sub(r"\D", "", k.split("@")[0])
            if len(digits) >= 10:
                contacts[f"suffix10_{digits[-10:]}"] = v

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

    conn = None
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
    except Exception as e:
        sys.stderr.write(f"[Contacts] Warning: Failed to load db mappings from {msgstore_path}: {e}\n")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    return chat_names, lid_to_phone


def extract_self_account_info(msgstore_path):
    """
    Extracts the user's own WhatsApp registration phone number, self JID,
    and profile push name from msgstore.db.
    Checks:
    1. 'user_push_name' in props table.
    2. 'call_log' table where from_me = 1 and creator device JID ends with @s.whatsapp.net.
    3. Self-created group JIDs in 'jid' table (<phone>-<timestamp>@g.us).
    Returns:
    {
        "phone_number": "+...",  # e.g. "+919348426067" or ""
        "push_name": "...",      # e.g. "Prabhu Nandan" or ""
        "self_jid": "...",       # e.g. "919348426067@s.whatsapp.net" or ""
    }
    """
    info = {
        "phone_number": "",
        "push_name": "",
        "self_jid": "",
    }
    p = Path(msgstore_path)
    if not p.is_file():
        return info

    conn = None
    try:
        conn = sqlite3.connect(str(p))
        cur = conn.cursor()

        # 1. Profile push name from props table
        try:
            cur.execute("SELECT value FROM props WHERE key = 'user_push_name'")
            row = cur.fetchone()
            if row and row[0]:
                info["push_name"] = str(row[0]).strip()
        except Exception:
            pass

        # 2. Outgoing call log (from_me = 1) containing creator phone JID
        try:
            cur.execute(
                """
                SELECT j.raw_string
                FROM call_log cl
                JOIN jid j ON cl.call_creator_device_jid_row_id = j._id
                WHERE cl.from_me = 1 AND j.raw_string LIKE '%@s.whatsapp.net'
                ORDER BY cl._id DESC
                LIMIT 10
                """
            )
            for row in cur.fetchall():
                raw = row[0] or ""
                m = re.match(r"^(\d{10,15})\b", raw)
                if m:
                    digits = m.group(1)
                    info["phone_number"] = f"+{digits}"
                    info["self_jid"] = f"{digits}@s.whatsapp.net"
                    break
        except Exception:
            pass

        # 3. Check group creation JIDs in jid table (pattern: <phone>-<epoch>@g.us)
        if not info["phone_number"]:
            try:
                cur.execute(
                    """
                    SELECT raw_string
                    FROM jid
                    WHERE raw_string LIKE '%-%@g.us'
                    LIMIT 50
                    """
                )
                for row in cur.fetchall():
                    raw = row[0] or ""
                    m = re.match(r"^(\d{10,15})-\d+@g\.us$", raw)
                    if m:
                        digits = m.group(1)
                        if 10 <= len(digits) <= 15:
                            info["phone_number"] = f"+{digits}"
                            info["self_jid"] = f"{digits}@s.whatsapp.net"
                            break
            except Exception:
                pass
    except Exception as e:
        sys.stderr.write(f"[Contacts] Warning: Failed to extract self account info from {msgstore_path}: {e}\n")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    return info


def load_chat_metadata(msgstore_path):
    """
    Loads rich chat metadata (subject, archived status, last active timestamp, is_group)
    from msgstore.db.
    Returns dict mapping JID -> {
        "subject": str,
        "archived": bool,
        "sort_timestamp": int, # ms Unix epoch
        "is_group": bool,
    }
    """
    chat_meta = {}
    p = Path(msgstore_path)
    if not p.is_file():
        return chat_meta

    conn = None
    try:
        conn = sqlite3.connect(str(p))
        cur = conn.cursor()

        cur.execute("PRAGMA table_info(chat)")
        cols = {row[1] for row in cur.fetchall()}

        arch_expr = "COALESCE(c.archived, 0)" if "archived" in cols else "0"
        sort_expr = "COALESCE(c.sort_timestamp, 0)" if "sort_timestamp" in cols else "0"

        cur.execute(
            f"""
            SELECT 
                j.raw_string, 
                COALESCE(c.subject, j.raw_string),
                {arch_expr},
                {sort_expr}
            FROM chat c
            JOIN jid j ON c.jid_row_id = j._id
            """
        )
        for row in cur.fetchall():
            jid, subject, archived, sort_ts = row[0], row[1], row[2], row[3]
            if jid:
                chat_meta[jid] = {
                    "subject": subject if (subject and subject != jid) else "",
                    "archived": bool(archived == 1),
                    "sort_timestamp": int(sort_ts or 0),
                    "is_group": bool(jid.endswith("@g.us")),
                }
    except Exception as e:
        sys.stderr.write(f"[Contacts] Warning: Failed to load chat metadata from {msgstore_path}: {e}\n")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    return chat_meta


def resolve_jid_name(jid, contacts, lid_to_phone, chat_names, country_code=None):
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

    # 3. Trailing 10-digit suffix matching (bridges international/local format differences)
    if contacts and ("@s.whatsapp.net" in resolved_jid or "@s.whatsapp.net" in jid):
        target = resolved_jid if "@s.whatsapp.net" in resolved_jid else jid
        digits = re.sub(r"\D", "", target.split("@")[0])
        if len(digits) >= 10:
            s10 = f"suffix10_{digits[-10:]}"
            if s10 in contacts:
                return contacts[s10]
            for c_jid, c_name in contacts.items():
                if "@s.whatsapp.net" in c_jid:
                    c_digits = re.sub(r"\D", "", c_jid.split("@")[0])
                    if len(c_digits) >= 10 and c_digits[-10:] == digits[-10:]:
                        return c_name

    # 4. Handle national / country-code variations in contacts
    if "@s.whatsapp.net" in resolved_jid:
        digits = resolved_jid.split("@")[0]
        cc = country_code if country_code is not None else get_account_country_code()
        if not cc and len(digits) == 10:
            cc = "91"
        if cc:
            if digits.startswith(cc) and len(digits) > len(cc):
                fallback_jid = f"{digits[len(cc):]}@s.whatsapp.net"
                if fallback_jid in contacts:
                    return contacts[fallback_jid]
            elif not digits.startswith(cc):
                fallback_jid = f"{cc}{digits}@s.whatsapp.net"
                if fallback_jid in contacts:
                    return contacts[fallback_jid]

    # 5. Check in chat_names (group subjects / broadcast names)
    if jid in chat_names:
        return chat_names[jid]
    if resolved_jid in chat_names:
        return chat_names[resolved_jid]

    # 6. Special broadcast cases
    if jid == "status@broadcast":
        return "Status Update"

    return None
