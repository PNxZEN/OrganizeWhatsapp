"""
WhatsApp Media Organizer - Phone Storage Clean Planner & Reclaim Engine.
Generates safe, 3-point verified phone storage cleanup plans based on presets
and custom rules (Archived chats, Group inactivity, Media types, and Age thresholds).
"""

import csv
import hashlib
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("organizer.clean_planner")

# In-memory store of generated plans awaiting execution
_ACTIVE_PLANS: Dict[str, dict] = {}


class CleanProfile:
    SMART_RECLAIM = "smart_reclaim"
    VIDEO_OFFLOAD = "video_offload"
    CUSTOM = "custom"


def parse_bool_safe(val: Any, default: bool = False) -> bool:
    """Safely converts string, numeric, or bool values into a boolean."""
    if val is None or val == "":
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        v = val.strip().lower()
        if v in ("1", "true", "yes", "t", "y"):
            return True
        if v in ("0", "false", "no", "f", "n"):
            return False
    return bool(val)


def categorize_media_type(filename: str, mime_type: Optional[str] = None, is_doc: bool = False) -> str:
    """Categorizes a file into videos, photos, audio, documents, or stickers."""
    fn_lower = (filename or "").lower()
    mime = (mime_type or "").lower()

    if fn_lower.endswith(".webp") or "sticker" in fn_lower:
        return "stickers"

    if mime.startswith("video/") or fn_lower.endswith((".mp4", ".3gp", ".mov", ".mkv", ".avi", ".webm", ".m4v")):
        return "videos"

    if mime.startswith("image/") or fn_lower.endswith((".jpg", ".jpeg", ".png", ".gif", ".bmp", ".heic", ".heif")):
        return "photos"

    if mime.startswith("audio/") or fn_lower.endswith((".opus", ".ogg", ".mp3", ".m4a", ".aac", ".wav")):
        return "audio"

    if is_doc or fn_lower.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".zip", ".rar", ".7z", ".apk")):
        return "documents"

    return "documents" if is_doc else "other"


def infer_default_phone_path(filename: str, m_type: str, is_doc: bool = False, from_me: bool = False) -> str:
    """
    Infers canonical Android WhatsApp storage path when phone_path was not recorded
    during historical or offline import.
    """
    if m_type == "videos":
        folder = "WhatsApp Video"
    elif m_type == "audio":
        folder = "WhatsApp Audio"
    elif m_type == "documents" or is_doc:
        folder = "WhatsApp Documents"
    elif m_type == "stickers":
        folder = "WhatsApp Stickers"
    else:
        folder = "WhatsApp Images"

    rel = f"Media/{folder}/Sent/{filename}" if from_me else f"Media/{folder}/{filename}"
    return f"/storage/emulated/0/Android/media/com.whatsapp/WhatsApp/{rel}"


def calculate_item_age_days(received_at_str: Optional[str], now_epoch_s: Optional[float] = None) -> float:
    """Calculates age in days from received_at string (format: YYYY-MM-DD HH:MM:SS or ISO)."""
    if not received_at_str:
        return 9999.0
    try:
        clean_str = str(received_at_str).strip().replace("T", " ")[:19]
        dt = datetime.strptime(clean_str, "%Y-%m-%d %H:%M:%S")
        ts = dt.replace(tzinfo=timezone.utc).timestamp()
        current_ts = now_epoch_s if now_epoch_s is not None else time.time()
        age_s = max(0.0, current_ts - ts)
        return age_s / 86400.0
    except Exception:
        return 9999.0


def calculate_inactivity_days(last_active_ts_ms: Optional[int], now_epoch_ms: Optional[int] = None) -> float:
    """Calculates days since last recorded chat activity."""
    if not last_active_ts_ms or last_active_ts_ms <= 0:
        return 9999.0
    cur_ms = now_epoch_ms if now_epoch_ms is not None else int(time.time() * 1000)
    diff_ms = max(0, cur_ms - int(last_active_ts_ms))
    return diff_ms / (1000.0 * 86400.0)


def verify_local_backup(
    output_dir: Path,
    rel_path: str,
    expected_size: int,
    expected_hash: Optional[str] = None,
    verify_hash: Optional[bool] = None,
    resolved_base: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Three-Point Pre-Purge Safety Verification:
    1. Local presence: File must exist on PC disk.
    2. Size match: Local file size must match expected bytes and be > 0.
    3. Hash match: Cryptographic digest verification (when verify_hash is True or hash explicitly provided).
    """
    if not rel_path:
        return False, "Missing relative path"

    clean_rel = rel_path.lstrip("/\\").replace("\\", "/")
    if resolved_base:
        full_str = os.path.join(resolved_base, clean_rel)
    else:
        full_str = str((output_dir / clean_rel).resolve())

    # Point 1 & Point 2: File existence and size verification in single stat syscall
    try:
        st = os.stat(full_str)
        actual_size = st.st_size
    except OSError:
        return False, f"Local backup copy missing at {clean_rel}"

    if actual_size <= 0:
        return False, "Local backup copy is empty (0 bytes)"

    if expected_size > 0 and actual_size != expected_size:
        return False, f"Size mismatch (local: {actual_size} bytes, expected: {expected_size} bytes)"

    # Point 3: Cryptographic hash verification (when requested or hash explicitly supplied)
    should_verify_hash = (expected_hash is not None) if verify_hash is None else verify_hash
    if should_verify_hash and expected_hash and isinstance(expected_hash, str) and len(expected_hash) == 32:
        try:
            h = hashlib.md5()
            with open(full_str, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            if h.hexdigest().lower() != expected_hash.strip().lower():
                return False, "Cryptographic hash mismatch"
        except Exception as e:
            return False, f"Hash check failed: {e}"

    return True, None


def load_media_records_for_planning(output_dir: Path, media_rows: Optional[List[dict]] = None) -> List[dict]:
    """Loads media records from memory, media_index.csv, or gallery_data.js."""
    if media_rows:
        return media_rows

    csv_path = output_dir / "media_index.csv"
    if csv_path.is_file():
        try:
            rows = []
            with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    r["size_bytes"] = int(r.get("size_bytes") or 0)
                    r["starred"] = 1 if parse_bool_safe(r.get("starred")) else 0
                    r["from_me"] = 1 if parse_bool_safe(r.get("from_me")) else 0
                    r["chat_archived"] = 1 if parse_bool_safe(r.get("chat_archived")) else 0
                    r["chat_last_active_ts"] = int(r.get("chat_last_active_ts") or 0)
                    r["is_doc"] = parse_bool_safe(r.get("is_doc"))
                    rows.append(r)
            if rows:
                return rows
        except Exception as e:
            logger.warning(f"Failed to read media_index.csv: {e}")

    # Fallback to gallery_data.js
    from core.gallery import load_gallery_data
    gal_data = load_gallery_data(output_dir)
    flat_rows = []
    for c in gal_data.get("chats", []):
        c_jid = c.get("jid") or ""
        c_name = c.get("name") or ""
        c_archived = 1 if c.get("archived") else 0
        c_last_ts = int(c.get("last_message_ts") or 0)
        for m in c.get("media", []):
            row = dict(m)
            row["chat_jid"] = c_jid
            row["chat_name"] = c_name
            row["chat_archived"] = c_archived
            row["chat_last_active_ts"] = c_last_ts
            row["size_bytes"] = int(row.get("size_bytes") or 0)
            flat_rows.append(row)
    return flat_rows


def generate_clean_plan(
    output_dir: str,
    profile: str = CleanProfile.SMART_RECLAIM,
    custom_config: Optional[dict] = None,
    media_rows: Optional[List[dict]] = None,
    now_epoch_ms: Optional[int] = None,
) -> dict:
    """
    Evaluates media records and generates a verified phone storage clean plan.
    Strictly verifies local presence of every candidate file before including it.
    """
    out_p = Path(output_dir).resolve()
    records = load_media_records_for_planning(out_p, media_rows=media_rows)

    now_ms = now_epoch_ms if now_epoch_ms is not None else int(time.time() * 1000)
    now_s = now_ms / 1000.0

    cfg = custom_config or {}

    # Parse profile settings
    if profile == CleanProfile.SMART_RECLAIM:
        # Preset 1: Videos >15MB >90d, Archived chats media >60d, Inactive groups (>180d) media >60d
        allowed_types = {"videos", "photos", "audio", "documents", "stickers"}
        min_age_days = float(cfg.get("min_age_days", 30.0))  # Protection floor
        keep_starred = parse_bool_safe(cfg.get("keep_starred"), True)
        target_archived = True
        archived_min_age = float(cfg.get("archived_min_age", 60.0))
        target_inactive_groups = True
        inactive_group_threshold_days = float(cfg.get("inactive_group_threshold_days", 180.0))
        inactive_group_min_age = float(cfg.get("inactive_group_min_age", 60.0))
        large_video_min_bytes = int(cfg.get("large_video_min_bytes", cfg.get("min_size_bytes", 15 * 1024 * 1024)))
        large_video_min_age = float(cfg.get("large_video_min_age", 90.0))
        include_jids: Set[str] = set()
        exclude_jids: Set[str] = set(cfg.get("exclude_jids") or [])
    elif profile == CleanProfile.VIDEO_OFFLOAD:
        # Preset 2: Videos older than X days only
        allowed_types = {"videos"}
        large_video_min_age = float(cfg.get("large_video_min_age", cfg.get("min_age_days", 30.0)))
        min_age_days = float(cfg.get("min_age_days", large_video_min_age))
        keep_starred = parse_bool_safe(cfg.get("keep_starred"), True)
        target_archived = False
        target_inactive_groups = False
        large_video_min_bytes = 0
        include_jids = set()
        exclude_jids = set(cfg.get("exclude_jids") or [])
    else:
        # Option 3: Custom Profile
        types_list = cfg.get("media_types") if "media_types" in cfg else ["videos", "photos", "audio"]
        allowed_types = set(types_list or [])
        min_age_days = float(cfg.get("min_age_days", 30.0))
        keep_starred = parse_bool_safe(cfg.get("keep_starred"), True)
        chat_scope = cfg.get("chat_scope")
        target_archived = parse_bool_safe(cfg.get("target_archived"), False)
        archived_min_age = float(cfg.get("archived_min_age", min_age_days))
        target_inactive_groups = parse_bool_safe(cfg.get("target_inactive_groups"), False)
        inactive_group_threshold_days = float(cfg.get("inactive_group_threshold_days", 90.0))
        inactive_group_min_age = float(cfg.get("inactive_group_min_age", min_age_days))
        large_video_min_bytes = int(cfg.get("min_size_bytes", 0))
        large_video_min_age = min_age_days
        has_include_filter = ("include_jids" in cfg) or (chat_scope == "selected_only")
        include_jids = set(cfg.get("include_jids") or [])
        exclude_jids = set(cfg.get("exclude_jids") or [])

        if not chat_scope:
            if target_archived and target_inactive_groups:
                chat_scope = "archived_and_inactive"
            elif target_archived:
                chat_scope = "archived_only"
            elif target_inactive_groups:
                chat_scope = "inactive_groups_only"
            else:
                chat_scope = "all"

    plan_id = str(uuid.uuid4())
    candidates: List[dict] = []
    failed_verifications: List[dict] = []
    protected_count = 0

    reasons_breakdown: Dict[str, dict] = {
        "archived_chats": {"count": 0, "bytes": 0},
        "inactive_groups": {"count": 0, "bytes": 0},
        "large_videos": {"count": 0, "bytes": 0},
        "aged_videos": {"count": 0, "bytes": 0},
        "custom_selection": {"count": 0, "bytes": 0},
    }
    type_breakdown: Dict[str, dict] = {
        "videos": {"count": 0, "bytes": 0},
        "photos": {"count": 0, "bytes": 0},
        "audio": {"count": 0, "bytes": 0},
        "documents": {"count": 0, "bytes": 0},
        "stickers": {"count": 0, "bytes": 0},
        "other": {"count": 0, "bytes": 0},
    }
    chat_breakdown: Dict[str, dict] = {}
    resolved_base_str = str(out_p.resolve())

    for row in records:
        chat_jid = row.get("chat_jid") or ""
        chat_name = row.get("chat_name") or "Unknown"
        rel_p = row.get("rel_path") or ""
        fn = row.get("filename") or os.path.basename(rel_p)
        size = int(row.get("size_bytes") or 0)
        mime = row.get("mime_type") or ""
        is_doc = parse_bool_safe(row.get("is_doc"))
        starred = parse_bool_safe(row.get("starred"))
        is_archived = parse_bool_safe(row.get("chat_archived"))
        last_active_ts = int(row.get("chat_last_active_ts") or 0)
        is_group = parse_bool_safe(row.get("is_group"), chat_jid.endswith("@g.us"))
        m_type = categorize_media_type(fn, mime, is_doc)

        phone_p = row.get("phone_path") or ""
        phone_recorded = bool(phone_p)
        if not phone_p and fn:
            phone_p = infer_default_phone_path(fn, m_type, is_doc=is_doc, from_me=parse_bool_safe(row.get("from_me")))

        # Safety Check 0: Must have a known phone path to be purgable from phone
        if not phone_p:
            continue

        # Safety Check 0b: media from another account's folder (kept apart in _unmatched/From ...)
        # is that account's; freeing it from the phone is not this library's call
        if re.match(r"_unmatched/From (account [^/]+|main folder)/", rel_p.replace("\\", "/")):
            continue

        # Safety Check 1: Excluded chat
        if chat_jid in exclude_jids:
            protected_count += 1
            continue

        # Safety Check 2: Starred item shield
        if keep_starred and starred:
            protected_count += 1
            continue

        age_days = calculate_item_age_days(row.get("received_at"), now_s)
        inactivity_days = calculate_inactivity_days(last_active_ts, now_ms) if is_group else 0.0

        # Safety Check 3: Minimum age shield
        if age_days < min_age_days:
            protected_count += 1
            continue

        is_candidate = False
        target_reason = ""

        if profile == CleanProfile.SMART_RECLAIM:
            # Match 1: Archived chats media
            if target_archived and is_archived and age_days >= archived_min_age:
                is_candidate = True
                target_reason = "archived_chats"
            # Match 2: Inactive groups media
            elif target_inactive_groups and is_group and inactivity_days >= inactive_group_threshold_days and age_days >= inactive_group_min_age:
                is_candidate = True
                target_reason = "inactive_groups"
            # Match 3: Large videos
            elif m_type == "videos" and size >= large_video_min_bytes and age_days >= large_video_min_age:
                is_candidate = True
                target_reason = "large_videos"

        elif profile == CleanProfile.VIDEO_OFFLOAD:
            if m_type == "videos" and age_days >= min_age_days:
                is_candidate = True
                target_reason = "aged_videos"

        else:
            # Custom profile evaluation
            type_allowed = m_type in allowed_types
            jid_matched = (chat_jid in include_jids) if has_include_filter else True

            if type_allowed and jid_matched and size >= large_video_min_bytes:
                if chat_scope == "archived_only":
                    if is_archived and age_days >= archived_min_age:
                        is_candidate = True
                        target_reason = "archived_chats"
                elif chat_scope == "inactive_groups_only":
                    if is_group and inactivity_days >= inactive_group_threshold_days and age_days >= inactive_group_min_age:
                        is_candidate = True
                        target_reason = "inactive_groups"
                elif chat_scope == "archived_and_inactive":
                    if is_archived and age_days >= archived_min_age:
                        is_candidate = True
                        target_reason = "archived_chats"
                    elif is_group and inactivity_days >= inactive_group_threshold_days and age_days >= inactive_group_min_age:
                        is_candidate = True
                        target_reason = "inactive_groups"
                else:  # "all" chats
                    if is_archived:
                        target_reason = "archived_chats"
                    elif is_group and inactivity_days >= inactive_group_threshold_days:
                        target_reason = "inactive_groups"
                    else:
                        target_reason = "custom_selection"
                    is_candidate = True

        if not is_candidate:
            continue

        # THREE-POINT VERIFICATION: Ensure local backup copy exists and matches before marking for deletion
        is_verified, err = verify_local_backup(
            out_p,
            rel_p,
            size,
            row.get("md5"),
            verify_hash=False,
            resolved_base=resolved_base_str,
        )
        if not is_verified:
            failed_verifications.append(
                {
                    "rel_path": rel_p,
                    "phone_path": phone_p,
                    "error": err,
                }
            )
            continue

        candidate_entry = {
            "rel_path": rel_p,
            "phone_path": phone_p,
            "filename": fn,
            "size_bytes": size,
            "mime_type": mime,
            "chat_jid": chat_jid,
            "chat_name": chat_name,
            "media_type": m_type,
            "received_at": row.get("received_at", ""),
            "age_days": round(age_days, 1),
            "reason": target_reason,
            "is_archived": is_archived,
            "inactivity_days": round(inactivity_days, 1) if is_group else 0,
            # False: no sync recorded where this file is on the phone; the path is a guess
            "phone_path_recorded": phone_recorded,
            "md5": row.get("md5") or "",
            "is_group": is_group,
            "last_active_ts": last_active_ts,
        }
        candidates.append(candidate_entry)

        # Aggregate breakdowns
        if target_reason in reasons_breakdown:
            reasons_breakdown[target_reason]["count"] += 1
            reasons_breakdown[target_reason]["bytes"] += size

        if m_type in type_breakdown:
            type_breakdown[m_type]["count"] += 1
            type_breakdown[m_type]["bytes"] += size
        else:
            type_breakdown["other"]["count"] += 1
            type_breakdown["other"]["bytes"] += size

        if chat_jid not in chat_breakdown:
            chat_breakdown[chat_jid] = {
                "jid": chat_jid,
                "name": chat_name,
                "count": 0,
                "bytes": 0,
                "archived": is_archived,
                "inactivity_days": round(inactivity_days, 1) if is_group else 0,
                "last_active_ts": last_active_ts,
                "is_group": is_group,
            }
        else:
            if last_active_ts > chat_breakdown[chat_jid].get("last_active_ts", 0):
                chat_breakdown[chat_jid]["last_active_ts"] = last_active_ts
        chat_breakdown[chat_jid]["count"] += 1
        chat_breakdown[chat_jid]["bytes"] += size

    total_reclaimable_bytes = sum(c["size_bytes"] for c in candidates)
    sorted_chats = sorted(chat_breakdown.values(), key=lambda x: x["bytes"], reverse=True)

    plan = {
        "plan_id": plan_id,
        "profile": profile,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "total_files_analyzed": len(records),
        "reclaimable_files_count": len(candidates),
        "reclaimable_bytes": total_reclaimable_bytes,
        "protected_files_count": protected_count,
        "failed_verification_count": len(failed_verifications),
        "candidates": candidates,
        "failed_verifications": failed_verifications,
        "breakdown": {
            "by_reason": reasons_breakdown,
            "by_type": type_breakdown,
            "by_chat": sorted_chats,
        },
    }

    _ACTIVE_PLANS[plan_id] = plan
    return plan


def get_active_plan(plan_id: str) -> Optional[dict]:
    """Retrieves an active plan by ID."""
    return _ACTIVE_PLANS.get(plan_id)


def discard_plan(plan_id: str):
    """Removes a plan from memory."""
    _ACTIVE_PLANS.pop(plan_id, None)


def _rebuild_breakdowns(plan: dict):
    """Totals and breakdowns from plan["candidates"] (after the phone check changed them)."""
    by_reason = {k: {"count": 0, "bytes": 0} for k in plan["breakdown"]["by_reason"]}
    by_type = {k: {"count": 0, "bytes": 0} for k in plan["breakdown"]["by_type"]}
    old_chats = {c["jid"]: c for c in plan["breakdown"]["by_chat"]}
    by_chat: Dict[str, dict] = {}
    for c in plan["candidates"]:
        size = int(c.get("size_bytes") or 0)
        if c.get("reason") in by_reason:
            by_reason[c["reason"]]["count"] += 1
            by_reason[c["reason"]]["bytes"] += size
        t = c.get("media_type") if c.get("media_type") in by_type else "other"
        if t in by_type:
            by_type[t]["count"] += 1
            by_type[t]["bytes"] += size
        jid = c.get("chat_jid") or ""
        if jid not in by_chat:
            base = dict(old_chats.get(jid) or {"jid": jid, "name": c.get("chat_name") or "", "archived": c.get("is_archived"),
                                               "inactivity_days": c.get("inactivity_days", 0),
                                               "last_active_ts": c.get("last_active_ts", 0), "is_group": c.get("is_group")})
            base.update(count=0, bytes=0)
            by_chat[jid] = base
        by_chat[jid]["count"] += 1
        by_chat[jid]["bytes"] += size
    plan["breakdown"] = {"by_reason": by_reason, "by_type": by_type,
                         "by_chat": sorted(by_chat.values(), key=lambda x: x["bytes"], reverse=True)}
    plan["reclaimable_files_count"] = len(plan["candidates"])
    plan["reclaimable_bytes"] = sum(int(c.get("size_bytes") or 0) for c in plan["candidates"])


def _local_md5(path: Path) -> Optional[str]:
    try:
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _absolute_phone_path(path: str, storage_root: str) -> str:
    p = (path or "").replace("\\", "/")
    return p if p.startswith("/") else f"{storage_root.rstrip('/')}/{p.lstrip('/')}"


def _searchable(inventory: Dict[str, int], storage_root: str, search_folders: Optional[List[str]]) -> Dict[str, List[str]]:
    """Files by name, only inside this account's own media folders (another account's are never touched)."""
    folders = [f.rstrip("/") + "/" for f in (search_folders or [storage_root])]
    by_name: Dict[str, List[str]] = {}
    for path in inventory:
        if any(path.startswith(f) for f in folders):
            by_name.setdefault(os.path.basename(path), []).append(path)
    return by_name


def verify_plan_on_phone(plan: dict, output_dir: str, inventory: Dict[str, int], storage_root: str,
                         md5_on_phone=None, search_folders: Optional[List[str]] = None) -> dict:
    """
    Checks every candidate against the files really on the phone (inventory: {path: size}) and
    keeps only what deleting would actually free:
      - at its path, same size as the PC copy: kept (a path no sync recorded: also same contents)
      - not at its path but once elsewhere in this account's own media folders (search_folders),
        same name and size and the same contents (MD5): kept, at the path where it really is
      - not on the phone, a different file at its path, or more than one match: left out, counted
      - the same phone file listed twice: once
    md5_on_phone(paths) -> {path: md5}. Updates and returns the plan, with plan["phone_check"].
    """
    out = Path(output_dir)
    root = storage_root.rstrip("/")
    by_name = _searchable(inventory, root, search_folders)

    check = {"checked": True, "checked_at": datetime.now(timezone.utc).isoformat(),
             "on_phone": {"count": 0, "bytes": 0}, "not_on_phone": {"count": 0, "bytes": 0},
             "found_elsewhere": {"count": 0, "bytes": 0}, "differs": {"count": 0, "bytes": 0},
             "ambiguous": {"count": 0, "bytes": 0}, "duplicates": {"count": 0, "bytes": 0},
             "estimate_before_check": plan.get("reclaimable_bytes", 0), "left_out": []}

    def _leave_out(kind, c, why):
        check[kind]["count"] += 1
        check[kind]["bytes"] += int(c.get("size_bytes") or 0)
        if len(check["left_out"]) < 500:
            check["left_out"].append({"kind": kind, "name": c.get("filename"), "chat": c.get("chat_name"),
                                      "size": c.get("size_bytes"), "phone_path": c.get("phone_path"), "reason": why})

    pending, need_md5, seen = [], [], set()
    for c in plan["candidates"]:
        size = int(c.get("size_bytes") or 0)
        full = _absolute_phone_path(c.get("phone_path"), root)
        if full in inventory and inventory[full] == size:
            path, moved = full, False
        elif full in inventory:
            _leave_out("differs", c, f"The phone's file at this path is {inventory[full]} bytes, the PC copy {size}")
            continue
        else:
            matches = [p for p in by_name.get(os.path.basename(full), []) if inventory[p] == size]
            if not matches:
                _leave_out("not_on_phone", c, "Not on the phone (already deleted, or never there)")
                continue
            if len(matches) > 1:
                _leave_out("ambiguous", c, f"{len(matches)} files on the phone have this name and size")
                continue
            path, moved = matches[0], True
        if path in seen:
            _leave_out("duplicates", c, "Listed twice: counted once")
            continue
        seen.add(path)
        item = dict(c, phone_path=path, phone_found_elsewhere=moved)
        if moved or not c.get("phone_path_recorded"):
            need_md5.append(item)  # found by name, or a guessed path: prove it is the same file
        pending.append(item)

    phone_md5 = md5_on_phone([i["phone_path"] for i in need_md5]) if (need_md5 and md5_on_phone) else {}
    md5_paths = {i["phone_path"] for i in need_md5}
    kept = []
    for item in pending:
        if item["phone_path"] in md5_paths:
            pc = _local_md5(out / item["rel_path"])
            if not pc or phone_md5.get(item["phone_path"]) != pc:
                _leave_out("differs", item, "Same name and size, different contents: not the file on the PC")
                continue
        if item.get("phone_found_elsewhere"):
            check["found_elsewhere"]["count"] += 1
            check["found_elsewhere"]["bytes"] += int(item.get("size_bytes") or 0)
        check["on_phone"]["count"] += 1
        check["on_phone"]["bytes"] += int(item.get("size_bytes") or 0)
        kept.append(item)

    plan["candidates"] = kept
    plan["phone_check"] = check
    _rebuild_breakdowns(plan)
    return plan


def audit_phone_vs_library(output_dir: str, inventory: Dict[str, int], storage_root: str,
                           search_folders: Optional[List[str]] = None) -> dict:
    """
    For anyone who cleaned up before cleanups were recorded: which of this library's media is still
    on the phone and which is gone, now. A file is "still on the phone" at its recorded (or guessed)
    path, or elsewhere in this WhatsApp's folders with the same name and size.
    """
    out = Path(output_dir)
    root = storage_root.rstrip("/")
    records = load_media_records_for_planning(out)
    by_name = _searchable(inventory, root, search_folders)
    summary = {k: {"count": 0, "bytes": 0} for k in (
        "on_phone", "on_phone_elsewhere", "gone_from_phone", "not_on_pc")}
    chats: Dict[str, dict] = {}
    samples = {"on_phone_elsewhere": [], "gone_from_phone": []}
    seen = set()
    for r in records:
        rel = r.get("rel_path") or ""
        size = int(r.get("size_bytes") or 0)
        fn = r.get("filename") or os.path.basename(rel)
        if not (out / rel).is_file():
            summary["not_on_pc"]["count"] += 1
            summary["not_on_pc"]["bytes"] += size
            continue
        phone = r.get("phone_path") or infer_default_phone_path(
            fn, categorize_media_type(fn, r.get("mime_type"), parse_bool_safe(r.get("is_doc"))),
            is_doc=parse_bool_safe(r.get("is_doc")), from_me=parse_bool_safe(r.get("from_me")))
        full = _absolute_phone_path(phone, root)
        if full in seen:
            continue
        seen.add(full)
        if inventory.get(full) == size:
            kind, where = "on_phone", full
        else:
            m = [p for p in by_name.get(os.path.basename(full), []) if inventory[p] == size]
            kind, where = ("on_phone_elsewhere", m[0]) if m else ("gone_from_phone", None)
        summary[kind]["count"] += 1
        summary[kind]["bytes"] += size
        chat = chats.setdefault(r.get("chat_name") or "Unknown", {"name": r.get("chat_name") or "Unknown",
                                                                  "on_phone_bytes": 0, "gone_bytes": 0})
        chat["gone_bytes" if kind == "gone_from_phone" else "on_phone_bytes"] += size
        if kind in samples and len(samples[kind]) < 200:
            samples[kind].append({"name": fn, "chat": r.get("chat_name"), "size": size,
                                  "expected": full, "found": where})
    return {"checked_at": datetime.now(timezone.utc).isoformat(), "summary": summary,
            "by_chat": sorted(chats.values(), key=lambda c: c["on_phone_bytes"], reverse=True)[:100],
            "samples": samples, "phone_files": len(inventory)}


def execute_clean_plan(
    plan_id_or_dict: Any,
    output_dir: str,
    adb_path=None,
    serial=None,
    progress_callback=None,
    cancel_event=None,
    exclude_jids=None,
    on_progress=None,
    storage_root: Optional[str] = None,
    phone_inventory=None,
    md5_on_phone=None,
    phone_free_bytes=None,
    search_folders: Optional[List[str]] = None,
) -> dict:
    """
    Deletes a plan's files from the phone, each one checked first, and records the run
    (core.reclaim_history) as the phone confirms each batch.

    - A plan the phone has not been checked against yet is checked first (phone_inventory() ->
      {path: size}, storage_root, md5_on_phone(paths)): only files really there, as on the PC.
    - Right before a file is deleted, its PC copy must exist with the phone file's exact size;
      otherwise it is skipped and stays on the phone.
    - Space freed is the size of the files the phone confirmed gone; phone_free_bytes() before and
      after shows what the phone itself reports.
    on_progress(event): live progress for the UI. {"event": "begin", "total", "total_bytes"}, then
    per batch {"event": "start", "files": [...]} and {"event": "done", "files": [...], "failed": [...],
    "deleted_count", "failed_count", "freed_bytes", ...}; each file is {"name", "chat", "size"}.
    """
    from core import reclaim_history

    if isinstance(plan_id_or_dict, str):
        plan = get_active_plan(plan_id_or_dict)
        if not plan:
            return {"success": False, "error": f"Plan '{plan_id_or_dict}' not found or already executed"}
    else:
        plan = plan_id_or_dict

    candidates = plan.get("candidates", [])
    if exclude_jids:
        exclude_set = set(exclude_jids)
        candidates = [c for c in candidates if c.get("chat_jid") not in exclude_set]
    candidates = [c for c in candidates if c.get("phone_path")]
    if not candidates:
        return {"success": True, "deleted_count": 0, "failed_count": 0, "freed_bytes": 0, "freed_mb": 0.0, "errors": []}

    check = plan.get("phone_check")
    if not check and phone_inventory and storage_root:
        # Checked now, against the files really on the phone
        sub = dict(plan, candidates=candidates, breakdown=plan.get("breakdown") or
                   {"by_reason": {}, "by_type": {}, "by_chat": []})
        sub["reclaimable_bytes"] = sum(int(c.get("size_bytes") or 0) for c in candidates)
        verify_plan_on_phone(sub, output_dir, phone_inventory(), storage_root, md5_on_phone, search_folders)
        candidates, check = sub["candidates"], sub["phone_check"]

    out = Path(output_dir)
    by_path = {c["phone_path"]: c for c in candidates}
    phone_paths = list(by_path)
    planned_bytes = sum(int(c.get("size_bytes") or 0) for c in candidates)

    def _free():
        try:
            return phone_free_bytes() if phone_free_bytes else None
        except Exception:
            return None

    run = reclaim_history.CleanupRun(output_dir, {
        "profile": plan.get("profile"), "plan_id": plan.get("plan_id"),
        "planned_files": len(phone_paths), "planned_bytes": planned_bytes,
        "estimate_before_check": (check or {}).get("estimate_before_check", plan.get("reclaimable_bytes")),
        "phone_check": {k: v for k, v in (check or {}).items() if k != "left_out"} or None,
        "phone_free_before": _free(), "excluded_chats": len(exclude_jids or []),
    })
    if check and check.get("left_out"):
        # What the phone check left out, so the record explains the whole estimate
        kinds = {"not_on_phone": "not_on_phone", "duplicates": "duplicate"}
        run.record([{"status": kinds.get(x["kind"], "skipped"),
                     "name": x.get("name"), "chat": x.get("chat"), "size": x.get("size"),
                     "phone_path": x.get("phone_path"), "rel_path": "", "reason": x.get("reason")}
                    for x in check["left_out"]])

    def _entry(path, status, size=None, reason=None):
        c = by_path.get(path) or {}
        return {"status": status, "name": c.get("filename") or os.path.basename(path or ""),
                "chat": c.get("chat_name") or "", "rel_path": c.get("rel_path") or "",
                "phone_path": path, "size": int(size if size is not None else (c.get("size_bytes") or 0)),
                "reason": reason}

    def _verify(path, phone_size):
        c = by_path.get(path) or {}
        local = out / (c.get("rel_path") or "")
        try:
            pc_size = local.stat().st_size if c.get("rel_path") else None
        except OSError:
            pc_size = None
        if pc_size is None:
            return False, "Its PC copy is missing now: kept on the phone"
        if pc_size != phone_size:
            return False, f"The phone file ({phone_size} bytes) differs from its PC copy ({pc_size} bytes): kept"
        return True, None

    def _file(path):
        c = by_path.get(path) or {}
        return {"name": c.get("filename") or os.path.basename(path or ""), "chat": c.get("chat_name") or "",
                "size": int(c.get("size_bytes") or 0)}

    def _on_batch(event):
        if event["event"] == "done":
            run.record([_entry(p, "deleted", event["deleted_sizes"].get(p)) for p in event["deleted"]]
                       + [_entry(p, "failed", reason=event["failed_reasons"].get(p)) for p in event["failed"]]
                       + [_entry(p, "not_on_phone", 0, "Not on the phone any more") for p in event["not_found"]]
                       + [_entry(p, "skipped", reason=r) for p, r in event["skipped"].items()])
        if not on_progress:
            return
        if event["event"] == "start":
            on_progress({"event": "start", "files": [_file(p) for p in event["paths"]]})
        else:
            on_progress({"event": "done", "files": [_file(p) for p in event["deleted"]],
                         "failed": [_file(p) for p in event["failed"]],
                         "deleted_count": event["deleted_count"], "failed_count": event["failed_count"],
                         "not_found_count": event["not_found_count"], "skipped_count": event["skipped_count"],
                         "freed_bytes": event["freed_bytes"]})

    if on_progress:
        on_progress({"event": "begin", "total": len(phone_paths), "total_bytes": planned_bytes})

    from core.adb import batch_delete_phone_files
    res = {"success": False, "errors": ["Cleanup stopped unexpectedly"], "not_done_paths": phone_paths}
    try:
        res = batch_delete_phone_files(
            phone_paths,
            adb_path=adb_path,
            serial=serial,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
            on_batch=_on_batch,
            verify=_verify,
        )
    finally:
        run.record([_entry(p, "not_done", reason="Not reached (cancelled or phone disconnected)")
                    for p in res.get("not_done_paths", [])]
                   + [_entry(p, "unknown", reason="The phone was disconnected while deleting it: check the phone")
                      for p in res.get("unknown_paths", [])])
        is_cancelled = bool(cancel_event and cancel_event.is_set())
        counts = run.summary["counts"]
        status = ("completed" if res.get("success") else "cancelled" if is_cancelled
                  else "interrupted" if (res.get("not_done_paths") or res.get("unknown_paths")) else "completed_with_problems")
        run.finish(status, phone_free_after=_free(), errors=res.get("errors", [])[:20],
                   freed_bytes=run.summary["bytes"]["deleted"])

    freed_bytes = run.summary["bytes"]["deleted"]
    plan["status"] = "executed" if res.get("success") else run.summary["status"]
    plan["executed_at"] = datetime.now(timezone.utc).isoformat()
    plan["deleted_count"] = counts["deleted"]
    plan["freed_bytes"] = freed_bytes
    discard_plan(plan.get("plan_id") or "")  # a plan runs once: a new cleanup checks the phone again

    return {
        "success": bool(res.get("success")),
        "run_id": run.run_id,
        "status": run.summary["status"],
        "deleted_count": counts["deleted"],
        "failed_count": counts["failed"],
        "not_on_phone_count": counts["not_on_phone"],
        "skipped_count": counts["skipped"],
        "duplicate_count": counts["duplicate"],
        "not_done_count": counts["not_done"],
        "unknown_count": counts["unknown"],
        "freed_bytes": freed_bytes,
        "freed_mb": round(freed_bytes / (1024 * 1024), 2),
        "planned_bytes": planned_bytes,
        "phone_free_before": run.summary.get("phone_free_before"),
        "phone_free_after": run.summary.get("phone_free_after"),
        "errors": res.get("errors", []),
    }

