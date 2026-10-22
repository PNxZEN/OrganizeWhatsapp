"""
Draws the two tutorial pictures for newer WhatsApp, where Settings is the bottom-right "You" tab:

    core/assets/tutorial/wa_step_you_home.webp   the chat list, everything blurred but the bottom
                                                 bar, with "You" highlighted
    core/assets/tutorial/wa_step_you_page.webp   the You page (it is the Settings page), everything
                                                 blurred but the Chats row, with a swipe hint

They are drawn mock-ups in the style of the other slides (made from real screenshots by
process_tutorial_assets.py), with no real names or chats in them. Re-run after changing them:

    python scripts/make_you_tab_slides.py
"""

import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "core" / "assets" / "tutorial"
W, H = 1080, 2412

BG = (11, 20, 26)
SURFACE = (24, 34, 41)
TEXT = (233, 237, 239)
MUTED = (134, 150, 160)
ICON = (210, 216, 220)
WA_GREEN = (37, 211, 102)
ACCENT = (16, 185, 129)
PILL_GREEN = (21, 128, 61)
NAV_BG = (17, 27, 33)

FONT_DIRS = ["/usr/share/fonts/opentype/inter", "/usr/share/fonts/truetype/inter", "C:/Windows/Fonts",
             "/Library/Fonts", "/System/Library/Fonts/Supplemental", "/usr/share/fonts/truetype/dejavu"]
FONT_FILES = {
    "regular": ["Inter-Regular.otf", "Inter-Regular.ttf", "segoeui.ttf", "Arial.ttf", "DejaVuSans.ttf"],
    "medium": ["Inter-Medium.otf", "Inter-Medium.ttf", "segoeui.ttf", "Arial.ttf", "DejaVuSans.ttf"],
    "semibold": ["Inter-SemiBold.otf", "Inter-SemiBold.ttf", "segoeuib.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"],
    "bold": ["Inter-Bold.otf", "Inter-Bold.ttf", "segoeuib.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"],
}


def font(size, weight="regular"):
    for d in FONT_DIRS:
        for name in FONT_FILES[weight]:
            path = os.path.join(d, name)
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
    return ImageFont.load_default()


# ---------------------------------------------------------------- shared pieces

def status_bar(d):
    d.text((60, 70), "9:41", font=font(38, "semibold"), fill=TEXT, anchor="lm")
    d.text((760, 72), "5G", font=font(28, "semibold"), fill=TEXT, anchor="lm")
    for i, hgt in enumerate((14, 22, 30, 38)):
        d.rectangle((830 + i * 12, 88 - hgt, 838 + i * 12, 88), fill=TEXT)
    d.rounded_rectangle((955, 50, 1020, 90), radius=10, fill=ACCENT)
    d.rectangle((1022, 62, 1028, 78), fill=ACCENT)


def nav_icon(d, kind, cx, cy, color):
    if kind == "chats":
        d.rounded_rectangle((cx - 26, cy - 22, cx + 26, cy + 18), radius=8, outline=color, width=5)
        d.polygon([(cx - 14, cy + 16), (cx - 22, cy + 30), (cx - 2, cy + 16)], fill=color)
    elif kind == "updates":
        d.ellipse((cx - 24, cy - 24, cx + 24, cy + 24), outline=color, width=5)
        d.ellipse((cx - 9, cy - 9, cx + 9, cy + 9), outline=color, width=5)
    elif kind == "communities":
        for dx, r in ((-24, 12), (24, 12), (0, 14)):
            d.ellipse((cx + dx - r, cy - 20 - r, cx + dx + r, cy - 20 + r), outline=color, width=5)
        d.arc((cx - 40, cy - 6, cx + 40, cy + 40), 180, 360, fill=color, width=5)
    elif kind == "calls":
        # A handset: the curved grip with an earpiece and a mouthpiece
        d.arc((cx - 30, cy - 30, cx + 22, cy + 22), 95, 265, fill=color, width=10)
        d.rounded_rectangle((cx - 12, cy - 34, cx + 10, cy - 18), radius=6, fill=color)
        d.rounded_rectangle((cx + 6, cy + 4, cx + 22, cy + 26), radius=6, fill=color)
    elif kind == "you":
        d.ellipse((cx - 28, cy - 28, cx + 28, cy + 28), fill=(84, 101, 111))
        d.ellipse((cx - 11, cy - 18, cx + 11, cy + 4), fill=(200, 208, 212))
        d.pieslice((cx - 22, cy + 2, cx + 22, cy + 40), 180, 360, fill=(200, 208, 212))


def qr_icon(d, cx, cy):
    for dx, dy in ((-18, -18), (18, -18), (-18, 18)):
        d.rectangle((cx + dx - 13, cy + dy - 13, cx + dx + 13, cy + dy + 13), outline=ICON, width=5)
    d.rectangle((cx + 10, cy + 10, cx + 20, cy + 20), fill=ICON)
    d.rectangle((cx + 24, cy + 24, cx + 31, cy + 31), fill=ICON)


def camera_icon(d, cx, cy):
    d.rounded_rectangle((cx - 32, cy - 20, cx + 32, cy + 26), radius=9, outline=ICON, width=5)
    d.rectangle((cx - 12, cy - 30, cx + 12, cy - 20), fill=ICON)
    d.ellipse((cx - 12, cy - 8, cx + 12, cy + 16), outline=ICON, width=5)


def bottom_bar(d, selected):
    top = 2150
    d.rectangle((0, top, W, H), fill=NAV_BG)
    tabs = [("chats", "Chats"), ("updates", "Updates"), ("communities", "Communities"), ("calls", "Calls"), ("you", "You")]
    centers = []
    for i, (kind, label) in enumerate(tabs):
        cx = int(W * (i + 0.5) / len(tabs))
        cy = top + 72
        if kind == selected:
            d.rounded_rectangle((cx - 66, cy - 40, cx + 66, cy + 40), radius=40, fill=(16, 63, 46))
        nav_icon(d, kind, cx, cy, TEXT if kind == selected else ICON)
        d.text((cx, top + 160), label, font=font(30, "semibold" if kind == selected else "medium"),
               fill=TEXT, anchor="mm")
        centers.append((cx, cy))
    d.rounded_rectangle((W // 2 - 140, H - 34, W // 2 + 140, H - 24), radius=5, fill=(200, 205, 208))
    return top, centers


def glow_box(img, box, radius=28):
    """The green highlight with a soft glow, as on the other slides."""
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.rounded_rectangle(box, radius=radius, outline=ACCENT + (190,), width=14)
    glow = glow.filter(ImageFilter.GaussianBlur(14))
    img.alpha_composite(glow)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(box, radius=radius, outline=ACCENT, width=6)


def radio_mark(d, cx, cy):
    d.ellipse((cx - 30, cy - 30, cx + 30, cy + 30), outline=ACCENT, width=4)
    d.ellipse((cx - 16, cy - 16, cx + 16, cy + 16), fill=ACCENT)


def label_pill(d, text, x, y, anchor="right"):
    f = font(36, "bold")
    tw = d.textlength(text, font=f)
    pad = 26
    left = x - tw - 2 * pad if anchor == "right" else x
    d.rounded_rectangle((left, y - 34, left + tw + 2 * pad, y + 34), radius=16, fill=ACCENT)
    d.text((left + pad, y), text, font=f, fill=(6, 26, 18), anchor="lm")
    return left, left + tw + 2 * pad


def blur_except(sharp, keep_boxes, radius=26):
    """Everything blurred except `keep_boxes` (so no text can be read there)."""
    blurred = sharp.filter(ImageFilter.GaussianBlur(radius))
    mask = Image.new("L", sharp.size, 0)
    md = ImageDraw.Draw(mask)
    for box in keep_boxes:
        md.rectangle(box, fill=255)
    return Image.composite(sharp, blurred, mask)


# ---------------------------------------------------------------- slide 1: the chat list

def you_home():
    img = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(img)
    # Header (sharp): the same as on the home screen
    d.text((50, 200), "WhatsApp", font=font(66, "bold"), fill=TEXT, anchor="lm")
    qr_icon(d, 790, 200)
    camera_icon(d, 910, 200)
    for dy in (-22, 0, 22):
        d.ellipse((1010 - 6, 200 + dy - 6, 1010 + 6, 200 + dy + 6), fill=ICON)
    # Content to blur: search, chips, chat rows (no real names: just shapes)
    d.rounded_rectangle((40, 290, 1040, 400), radius=55, fill=SURFACE)
    x = 50
    for wdt in (110, 170, 180, 220, 80):
        d.rounded_rectangle((x, 450, x + wdt, 530), radius=40, outline=(52, 64, 72), width=4)
        x += wdt + 22
    colors = [(52, 120, 140), (150, 110, 80), (120, 80, 60), (60, 110, 130), (40, 120, 70), (90, 96, 100)]
    for i in range(7):
        top = 600 + i * 205
        d.ellipse((40, top, 180, top + 140), fill=colors[i % len(colors)])
        d.rounded_rectangle((220, top + 25, 220 + 230 + (i * 37) % 160, top + 62), radius=14, fill=(200, 205, 208))
        d.rounded_rectangle((220, top + 90, 220 + 340 + (i * 53) % 220, top + 122), radius=12, fill=(120, 132, 140))
        d.rounded_rectangle((880, top + 30, 1040, top + 60), radius=10, fill=(100, 110, 116))
    d.rounded_rectangle((870, 1920, 1030, 2080), radius=36, fill=WA_GREEN)
    _, centers = bottom_bar(d, "chats")
    status_bar(d)
    img = blur_except(img.convert("RGB"), [(0, 0, W, 260), (0, 2150, W, H)]).convert("RGBA")

    # Highlight the You tab (bottom right)
    cx, cy = centers[-1]
    glow_box(img, (cx - 100, 2165, cx + 100, 2355))
    d = ImageDraw.Draw(img)
    radio_mark(d, cx, 2060)
    d.line((cx, 2092, cx, 2160), fill=ACCENT, width=6)
    label_pill(d, "1. Tap You", cx - 50, 2060)
    return img.convert("RGB")


# ---------------------------------------------------------------- slide 2: the You page

ROWS = [
    ("Avatar", "Create, edit, profile photo"),
    ("Lists", "Manage people and groups"),
    ("Chats", "Theme, wallpapers, chat history"),
    ("Broadcasts", "Manage lists and send broadcasts"),
    ("Notifications", "Message, group & call tones"),
    ("Storage and data", "Network usage, auto-download"),
    ("Accessibility", "Increase contrast, animation"),
    ("App language", "English (device's language)"),
]


def row_icon(d, cx, cy, n):
    shape = n % 4
    if shape == 0:
        d.rounded_rectangle((cx - 24, cy - 24, cx + 24, cy + 24), radius=8, outline=ICON, width=5)
    elif shape == 1:
        d.ellipse((cx - 24, cy - 24, cx + 24, cy + 24), outline=ICON, width=5)
    elif shape == 2:
        d.rounded_rectangle((cx - 26, cy - 20, cx + 26, cy + 16), radius=8, outline=ICON, width=5)
        d.polygon([(cx - 14, cy + 14), (cx - 22, cy + 28), (cx - 2, cy + 14)], fill=ICON)
    else:
        d.arc((cx - 24, cy - 24, cx + 24, cy + 24), 200, 520, fill=ICON, width=5)


def you_page():
    img = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(img)
    # Header: the profile (blurred below: no name shown)
    d.ellipse((40, 150, 160, 270), fill=(84, 101, 111))
    d.rounded_rectangle((190, 180, 600, 236), radius=16, fill=(200, 205, 208))
    qr_icon(d, 880, 205)
    d.ellipse((960, 178, 1006, 224), outline=ICON, width=5)
    d.line((1000, 218, 1024, 242), fill=ICON, width=6)
    chats_box = None
    for i, (title, sub) in enumerate(ROWS):
        top = 340 + i * 200
        row_icon(d, 95, top + 70, i)
        d.text((180, top + 45), title, font=font(46, "medium"), fill=TEXT, anchor="lm")
        d.text((180, top + 108), sub, font=font(34), fill=MUTED, anchor="lm")
        if title == "Chats":
            chats_box = (20, top + 5, W - 20, top + 155)
    _, _ = bottom_bar(d, "you")
    status_bar(d)
    img = blur_except(img.convert("RGB"), [(0, 0, W, 130), chats_box, (0, 2150, W, H)]).convert("RGBA")

    glow_box(img, chats_box)
    d = ImageDraw.Draw(img)
    radio_mark(d, W - 110, (chats_box[1] + chats_box[3]) // 2)
    label_pill(d, "2. Tap Chats", chats_box[0] + 30, chats_box[1] - 40, anchor="left")
    # Scroll hint: it is a little further down at first
    ax = W - 90
    d.line((ax, 1650, ax, 1250), fill=ACCENT, width=8)
    d.polygon([(ax - 30, 1270), (ax + 30, 1270), (ax, 1225)], fill=ACCENT)
    label_pill(d, "Swipe up to see Chats", ax - 30, 1700)
    return img.convert("RGB")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, make in (("wa_step_you_home.webp", you_home), ("wa_step_you_page.webp", you_page)):
        path = OUT / name
        make().save(path, "WEBP", quality=82, method=6)
        print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
