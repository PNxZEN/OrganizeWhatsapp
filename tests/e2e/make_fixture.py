"""
Builds two small output folders for the release smoke test:
  <current>  a gallery with awkward chat names (comma, emoji, very long), and a few recycled items
  <older>    an older output folder to import (different backup key, overlapping files)
Usage: python tests/e2e/make_fixture.py <current_dir> <older_dir>
"""

import json
import os
import random
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PIL import Image, ImageDraw  # noqa: E402

from core.gallery import recycle_media_items, update_gallery_data_live  # noqa: E402

CHATS = [
    ("Andi mandi shandi , jisne photo nahi bheje vo gande \U0001F648 (College 2019-23)", "120363@g.us"),
    ("VPN \U0001F480\U0001FAF6", "911234567890@s.whatsapp.net"),
    ("Mom", "919876543210@s.whatsapp.net"),
]


def build(out: Path, chats, per_chat: int, seed: int):
    random.seed(seed)
    items = []
    for name, jid in chats:
        for i in range(per_chat):
            rel = f"{name}/2024-0{1 + i % 3}/IMG-2024010{i % 9}-WA00{i:02d}.jpg"
            p = out / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            im = Image.new("RGB", (320, 240), tuple(random.randint(40, 220) for _ in range(3)))
            ImageDraw.Draw(im).text((8, 8), f"{i}", fill=(255, 255, 255))
            im.save(p, "JPEG")
            items.append({"chat_jid": jid, "chat_name": name, "filename": p.name, "rel_path": rel,
                          "size_bytes": p.stat().st_size, "mime_type": "image/jpeg",
                          "received_at": f"2024-0{1 + i % 3}-1{i % 9} 10:00:00"})
    update_gallery_data_live(items, str(out))
    return items


def main():
    current, older = Path(sys.argv[1]), Path(sys.argv[2])
    for d in (current, older):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
    items = build(current, CHATS, 6, 1)
    recycle_media_items(str(current), [items[0]["rel_path"], items[7]["rel_path"]])
    build(older, CHATS[:2] + [("Old Friends", "old@g.us")], 4, 2)
    (older / "config.json").write_text(json.dumps({"hex_key": "b" * 64}), encoding="utf-8")
    print(f"fixture ready: {current} ({len(items)} items), {older}")


if __name__ == "__main__":
    main()
