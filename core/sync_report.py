"""
After a sync: proof that every media file found on the phone is on the PC.

The check is independent of how the sync decided what to transfer. It takes the list of files the
phone reported and looks each one up on the PC: by the phone path media_index.csv recorded for a
file, else by its name and size. Files WhatsApp never had (not downloaded, deleted, view once) are
not on the phone, so they are counted separately, from the chat database.

It also says whose media each account folder holds (the storage root and each accounts/<id>): a
file goes into a chat only when the synced account's database knows it, and from another account
folder only when its contents match, so the share of a folder's chat media that went into chats
tells this account's older media (most of it) from another account's (almost none: only what was
forwarded between the two).
"""

import csv
import json
import os
import time
from pathlib import Path

from core.adb import _already_on_pc_check, is_skippable_system_path

REPORT_NAME = ".sync_report.json"
_MAX_LISTED = 200


def _is_media(path: str) -> bool:
    p = path.replace("\\", "/").lstrip("/")
    return p.startswith("Media/") or "/Media/" in p


def _absolute(path: str, tar_root: str) -> str:
    p = path.replace("\\", "/")
    return p if p.startswith("/") else f"{tar_root.rstrip('/')}/{p.lstrip('/')}"


def _media_folder(path: str) -> str:
    p = path.replace("\\", "/").lstrip("/")
    return p.split("Media/", 1)[0] + "Media"


# Folders of chat attachments (stickers, statuses, profile photos say nothing about the account)
_CHAT_MEDIA = ("WhatsApp Images", "WhatsApp Video", "WhatsApp Audio", "WhatsApp Documents",
               "WhatsApp Animated Gifs", "WhatsApp Voice Notes", "WhatsApp Video Notes")
THIS_ACCOUNT, OTHER_ACCOUNT, UNCLEAR, TOO_FEW = "this_account", "other_account", "unclear", "too_few"


def folder_verdict(in_chats, chat_media):
    """Whose media an account folder holds, from the share of its chat media that went into chats."""
    if chat_media < 30:
        return TOO_FEW
    share = in_chats / chat_media
    if share >= 0.70:
        return THIS_ACCOUNT
    if share <= 0.15:
        return OTHER_ACCOUNT
    return UNCLEAR


def verify_sync_completeness(output_dir, inventory, media_rows=None, own_account=None):
    """
    inventory: {"tar_root": str, "files": [(phone path, size)]} as the pull saw the phone.
    own_account: the synced account's folder ("" for the root, "accounts/<id>").
    Writes output/.sync_report.json and returns the report.
    """
    out = Path(output_dir).resolve()
    tar_root = inventory.get("tar_root") or ""
    phone_files = [
        (p, int(sz)) for p, sz in inventory.get("files") or []
        if _is_media(p) and not is_skippable_system_path(p)
    ]

    in_chats = unmatched = 0
    pc_copy = {}  # absolute phone path -> where its PC copy is
    csv_path = out / "media_index.csv"
    if csv_path.is_file():
        with open(csv_path, "r", encoding="utf-8", errors="replace", newline="") as f:
            for r in csv.DictReader(f):
                rel = r.get("rel_path") or ""
                if not rel or not (out / rel).is_file():
                    continue
                if rel.startswith("_unmatched/"):
                    unmatched += 1
                else:
                    in_chats += 1
                if r.get("phone_path"):
                    pc_copy[_absolute(r["phone_path"], tar_root)] = rel
    # By the phone path media_index.csv recorded for each PC file; by name and size only where
    # that is unknown (files synced by older versions). The Recycle Bin counts: still on the PC.
    on_pc = _already_on_pc_check(str(out), tar_root)

    missing = []
    found_bytes = 0
    for path, size in phone_files:
        if on_pc(path, size):
            found_bytes += size
        else:
            missing.append({"phone_path": _absolute(path, tar_root), "size": size})

    # Attachments the chats mention that the phone does not have
    on_phone = {os.path.basename(p).lower() for p, _ in phone_files}
    not_on_phone = 0
    for r in media_rows or []:
        names = {os.path.basename(x).lower() for x in (r.get("file_path"), r.get("filename")) if x}
        if names and not (names & on_phone):
            not_on_phone += 1

    folders = {}
    for path, _ in phone_files:
        f = folders.setdefault(_media_folder(path), {"files": 0, "chat_media": 0, "in_chats": 0})
        f["files"] += 1
        sub = path.replace("\\", "/").lstrip("/").split("Media/", 1)[1].split("/", 1)[0]
        rel = pc_copy.get(_absolute(path, tar_root))
        if sub in _CHAT_MEDIA and rel:
            f["chat_media"] += 1
            if not rel.startswith(("_unmatched/", "Stickers/")):
                f["in_chats"] += 1
    for name, f in folders.items():
        f["share_in_chats"] = round(f["in_chats"] / f["chat_media"], 3) if f["chat_media"] else None
        folder_dir = name[: -len("/Media")] if name.endswith("/Media") else ""
        f["synced_account"] = own_account is not None and folder_dir == own_account
        f["verdict"] = folder_verdict(f["in_chats"], f["chat_media"])

    report = {
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "phone_root": tar_root,
        # per Media folder (the root's and each accounts/<id>/Media): files, chat media, how many
        # of those went into the synced account's chats, and so whose media it is
        "phone_folders": dict(sorted(folders.items())),
        "phone_media_files": len(phone_files),
        "phone_media_bytes": sum(sz for _, sz in phone_files),
        "on_pc": len(phone_files) - len(missing),
        "on_pc_bytes": found_bytes,
        "missing_count": len(missing),
        "missing": missing[:_MAX_LISTED],
        "in_chats": in_chats,
        "in_unmatched": unmatched,
        "chat_attachments_not_on_phone": not_on_phone,
    }
    tmp = out / f"{REPORT_NAME}.tmp"
    try:
        tmp.write_text(json.dumps(report, indent=2), encoding="utf-8")
        os.replace(tmp, out / REPORT_NAME)
    except OSError:
        pass
    return report
