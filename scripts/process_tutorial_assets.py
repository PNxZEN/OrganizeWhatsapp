"""
Process and annotate WhatsApp 64-digit encryption key tutorial screenshots.
Applies pixel-accurate bounding boxes, vibrant directional arrows,
prominent red cross-out on 'Use passkey', and realistic Slide 7 without desktop buttons.
"""

import os
import math
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(ROOT_DIR, 'scratch', 'tutorial_raw', '64digit_wa_tutorial')
DEST_DIR_CORE = os.path.join(ROOT_DIR, 'core', 'assets', 'tutorial')
DEST_DIR_OUTPUT = os.path.join(ROOT_DIR, 'output', 'assets', 'tutorial')

os.makedirs(DEST_DIR_CORE, exist_ok=True)
os.makedirs(DEST_DIR_OUTPUT, exist_ok=True)

# Color Palette
BG_DARK = (11, 20, 26)             # WhatsApp dark theme background #0b141a
CARD_BG = (18, 27, 34)             # Dark card surface #121b22
TEXT_PRIMARY = (233, 237, 239)     # White-ish #e9edef
TEXT_MUTED = (134, 150, 160)       # Grey #8696a0
WA_GREEN = (0, 168, 132)           # Emerald green #00a884
ACCENT_GREEN = (16, 185, 129)      # Glow green #10b981
BRIGHT_GREEN = (52, 211, 153)      # High-vis green #34d399
WARNING_RED = (239, 68, 68)        # Red alert #ef4444

def get_font(size, bold=False):
    font_names = ['segoeuib.ttf', 'arialbd.ttf'] if bold else ['segoeui.ttf', 'arial.ttf']
    for fn in font_names:
        fp = os.path.join('C:/Windows/Fonts', fn)
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                pass
    return ImageFont.load_default()

def draw_clean_status_bar(im):
    """Replaces personal status bar (y: 0 to 115) with a clean neutral status bar."""
    draw = ImageDraw.Draw(im)
    draw.rectangle([0, 0, im.width, 115], fill=BG_DARK)
    
    # Time 9:41
    font_time = get_font(38, bold=True)
    draw.text((60, 42), "9:41", font=font_time, fill=TEXT_PRIMARY)
    
    # 5G and Signal
    rx = im.width - 240
    ry = 70
    font_net = get_font(28, bold=True)
    draw.text((rx - 90, 48), "5G", font=font_net, fill=TEXT_PRIMARY)
    
    for b in range(4):
        bh = 10 + b * 6
        bx = rx + b * 10
        draw.rectangle([bx, ry - bh, bx + 6, ry], fill=TEXT_PRIMARY)
        
    # Battery icon
    bat_x = im.width - 120
    bat_y = 48
    draw.rounded_rectangle([bat_x, bat_y, bat_x + 60, bat_y + 30], radius=6, outline=TEXT_PRIMARY, width=3)
    draw.rectangle([bat_x + 60, bat_y + 8, bat_x + 64, bat_y + 22], fill=TEXT_PRIMARY)
    draw.rounded_rectangle([bat_x + 4, bat_y + 4, bat_x + 56, bat_y + 26], radius=3, fill=WA_GREEN)

def draw_arrow(draw, start, end, color=BRIGHT_GREEN, width=8, head_len=36):
    """Draws a glowing directional arrow pointing from start to end."""
    x1, y1 = start
    x2, y2 = end
    
    # Outer soft glow
    draw.line([x1, y1, x2, y2], fill=(color[0], color[1], color[2], 80), width=width + 8)
    # Main shaft
    draw.line([x1, y1, x2, y2], fill=color, width=width)
    
    # Arrow head
    angle = math.atan2(y2 - y1, x2 - x1)
    p1 = (x2 - head_len * math.cos(angle - math.pi / 6), y2 - head_len * math.sin(angle - math.pi / 6))
    p2 = (x2 - head_len * math.cos(angle + math.pi / 6), y2 - head_len * math.sin(angle + math.pi / 6))
    draw.polygon([end, p1, p2], fill=color)

def draw_focus_spotlight(im, bbox, color=ACCENT_GREEN, label=None, badge_pos="above", arrow_dir=None, arrow_from_y=None):
    """Draws an ultra-clean focus spotlight with optional long directional arrow and tightly attached pill label."""
    overlay = Image.new('RGBA', im.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    
    x1, y1, x2, y2 = bbox
    # Outer glow rings
    for w, a in [(18, 25), (12, 55), (6, 130), (3, 240)]:
        glow_col = (color[0], color[1], color[2], a)
        draw.rounded_rectangle([x1 - w//2, y1 - w//2, x2 + w//2, y2 + w//2], radius=22, outline=glow_col, width=w)
    
    # Pulse rings at center right of box
    cx = x2 - 90
    cy = (y1 + y2) // 2
    draw.ellipse([cx - 36, cy - 36, cx + 36, cy + 36], outline=(color[0], color[1], color[2], 75), width=4)
    draw.ellipse([cx - 24, cy - 24, cx + 24, cy + 24], outline=(color[0], color[1], color[2], 160), width=5)
    draw.ellipse([cx - 12, cy - 12, cx + 12, cy + 12], fill=(color[0], color[1], color[2], 255))
    
    # Directional arrow: long, prominent attention drawer from top/center of screen
    if arrow_dir == 'down':
        start_y = arrow_from_y if arrow_from_y is not None else (y1 - 100)
        mid_x = (x1 + x2) // 2
        draw_arrow(draw, (mid_x, start_y), (mid_x, y1 - 10), color=BRIGHT_GREEN, width=8, head_len=36)
    elif arrow_dir == 'up':
        mid_x = (x1 + x2) // 2
        start_y = arrow_from_y if arrow_from_y is not None else (y2 + 100)
        draw_arrow(draw, (mid_x, start_y), (mid_x, y2 + 10), color=BRIGHT_GREEN, width=8, head_len=36)
    elif arrow_dir == 'right':
        mid_y = (y1 + y2) // 2
        draw_arrow(draw, (x1 - 110, mid_y), (x1 - 12, mid_y), color=BRIGHT_GREEN, width=8, head_len=32)

    # Merge overlay
    im_rgba = im.convert('RGBA')
    merged = Image.alpha_composite(im_rgba, overlay)
    draw_m = ImageDraw.Draw(merged)
    
    if label:
        badge_font = get_font(32, bold=True)
        bbox_text = draw_m.textbbox((0, 0), label, font=badge_font)
        tw = bbox_text[2] - bbox_text[0]
        th = bbox_text[3] - bbox_text[1]
        bw = tw + 44
        bh = th + 24
        
        # Position label tightly attached to the box with standard 14px gap (no huge gap!)
        if badge_pos == "above":
            bx = x1 + 40
            by = y1 - bh - 14
        elif badge_pos == "below":
            bx = x1 + 40
            by = y2 + 14
        elif badge_pos == "below_center":
            bx = (x1 + x2 - bw) // 2
            by = y2 + 14
        elif badge_pos == "left":
            bx = x1 - bw - 20
            by = cy - bh // 2
        else: # inside
            bx = x1 + 30
            by = y1 + 16
            
        # Draw badge pill
        draw_m.rounded_rectangle([bx, by, bx + bw, by + bh], radius=18, fill=(color[0], color[1], color[2], 250))
        draw_m.text((bx + 22, by + 10), label, font=badge_font, fill=(0, 0, 0) if color == ACCENT_GREEN else (255, 255, 255))
        
    return merged.convert('RGB')

def process_slide_0():
    """Slide 0: WhatsApp Main Screen -> 3-Dot Menu -> Settings."""
    src = os.path.join(RAW_DIR, '0.png')
    im = Image.open(src).convert('RGBA')
    
    # 1. Background blur of all chats below the header (y > 255)
    blurred = im.filter(ImageFilter.GaussianBlur(radius=32))
    dim = Image.new('RGBA', im.size, (11, 20, 26, 175))
    blurred_dimmed = Image.alpha_composite(blurred, dim)
    
    # 2. Mask to preserve top bar (y: 115..255) and 3-dot menu card [555, 260, 1070, 1335]
    mask = Image.new('L', im.size, 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.rectangle([0, 115, im.width, 255], fill=255)
    draw_mask.rounded_rectangle([555, 260, 1070, 1335], radius=24, fill=255)
    
    comp = Image.composite(im, blurred_dimmed, mask).convert('RGB')
    draw_clean_status_bar(comp)
    
    # Highlight 'Settings' row inside menu [560, 1160, 1060, 1320] with right-pointing arrow
    out = draw_focus_spotlight(comp, [560, 1160, 1060, 1320], color=ACCENT_GREEN, label="1. Tap Settings", badge_pos="left", arrow_dir="right")
    return out

def process_slide_1():
    """Slide 1: Settings Screen -> Chats (Box shifted up a slight bit to perfectly frame Chats)."""
    src = os.path.join(RAW_DIR, '1.png')
    im = Image.open(src).convert('RGB')
    draw_clean_status_bar(im)
    # Box shifted up slightly to [40, 1220, 1040, 1390] with tight label and long downward arrow from Y=850
    out = draw_focus_spotlight(im, [40, 1220, 1040, 1390], color=ACCENT_GREEN, label="2. Tap Chats", badge_pos="above", arrow_dir="down", arrow_from_y=850)
    return out

def process_slide_2():
    """Slide 2: Chats Screen -> Chat backup (Long attention-drawing arrow from top/center to bottom)."""
    src = os.path.join(RAW_DIR, '2.png')
    im = Image.open(src).convert('RGB')
    draw_clean_status_bar(im)
    # Exact box for Chat backup [40, 1920, 1040, 2065] with tight label and long arrow starting at Y=1300
    out = draw_focus_spotlight(im, [40, 1920, 1040, 2065], color=ACCENT_GREEN, label="3. Tap Chat backup", badge_pos="above", arrow_dir="down", arrow_from_y=1300)
    return out

def process_slide_3():
    """Slide 3: Chat backup -> End-to-end encrypted backup (Perfect symmetric box alignment & long arrow)."""
    src = os.path.join(RAW_DIR, '3.png')
    im = Image.open(src).convert('RGB')
    draw_clean_status_bar(im)
    
    draw = ImageDraw.Draw(im)
    # Redact Google Account email precisely
    draw.rectangle([30, 930, 750, 1025], fill=BG_DARK)
    font_email = get_font(44)
    draw.text((38, 940), "user@example.com", font=font_email, fill=TEXT_MUTED)
    
    # Redact Google Storage info precisely
    draw.rectangle([30, 1145, 750, 1240], fill=BG_DARK)
    draw.text((38, 1155), "15 GB of 100 GB used", font=font_email, fill=TEXT_MUTED)
    
    # Perfectly centered box for End-to-end encrypted backup [40, 2080, 1040, 2240] with tight label and long arrow from Y=1450
    out = draw_focus_spotlight(im, [40, 2080, 1040, 2240], color=ACCENT_GREEN, label="4. Tap E2E Backup", badge_pos="above", arrow_dir="down", arrow_from_y=1450)
    return out

def process_slide_4():
    """Slide 4: More options vs Passkey (Darkened passkey with bold red cross & centered label below More options)."""
    src = os.path.join(RAW_DIR, '4.png')
    im = Image.open(src).convert('RGBA')
    draw_clean_status_bar(im)
    
    overlay = Image.new('RGBA', im.size, (0, 0, 0, 0))
    d_over = ImageDraw.Draw(overlay)
    
    # 1. Darken and red-tint the 'Use passkey' button [58, 2066, 1021, 2199] to kill the bright green fill
    d_over.rounded_rectangle([58, 2066, 1021, 2199], radius=66, fill=(36, 12, 16, 245), outline=(239, 68, 68, 255), width=5)
    
    # Prominent bold red X across the button
    d_over.line([(140, 2085), (940, 2180)], fill=(239, 68, 68, 255), width=8)
    d_over.line([(940, 2085), (140, 2180)], fill=(239, 68, 68, 255), width=8)
    
    # Crisp warning pill in the center: '✕ DO NOT USE PASSKEY'
    font_w = get_font(32, bold=True)
    d_over.rounded_rectangle([250, 2106, 830, 2162], radius=14, fill=(220, 38, 38, 255), outline=(255, 255, 255, 200), width=2)
    d_over.text((285, 2116), "✕  DO NOT USE PASSKEY", font=font_w, fill=(255, 255, 255))
    
    im_merged = Image.alpha_composite(im, overlay).convert('RGB')
    
    # 2. Spotlight on 'More options' [40, 2208, 1040, 2288] with label centered directly below
    out = draw_focus_spotlight(
        im_merged, 
        [40, 2208, 1040, 2288], 
        color=ACCENT_GREEN, 
        label="5. Tap More options", 
        badge_pos="below_center"
    )
    d_out = ImageDraw.Draw(out)
    
    # Upward-pointing neon arrow from the badge into the 'More options' button
    draw_arrow(d_out, (540, 2302), (540, 2284), color=BRIGHT_GREEN, width=6, head_len=14)
    
    return out

def process_slide_5():
    """Slide 5: More options popup -> 64-digit encryption key (Long arrow from center to bottom)."""
    src = os.path.join(RAW_DIR, '5.png')
    im = Image.open(src).convert('RGB')
    draw_clean_status_bar(im)
    # Box [40, 2125, 1040, 2295] with tight label and long arrow starting at Y=1550
    out = draw_focus_spotlight(im, [40, 2125, 1040, 2295], color=ACCENT_GREEN, label="6. Tap 64-digit key", badge_pos="above", arrow_dir="down", arrow_from_y=1550)
    return out

def process_slide_6():
    """Slide 6: Generate your 64-digit key (Long arrow from center to bottom)."""
    src = os.path.join(RAW_DIR, '6.png')
    im = Image.open(src).convert('RGB')
    draw_clean_status_bar(im)
    # Box [50, 2185, 1030, 2305] with tight label and long arrow starting at Y=1500
    out = draw_focus_spotlight(im, [50, 2185, 1030, 2305], color=ACCENT_GREEN, label="7. Tap Generate key", badge_pos="above", arrow_dir="down", arrow_from_y=1500)
    return out

def generate_slide_7():
    """
    Slide 7: Realistic WhatsApp screen showing the 4x4 matrix,
    native Android Copy popup tooltip, and authentic WhatsApp bottom button (NO arrows on slide 7).
    """
    im = Image.new('RGB', (1080, 2412), BG_DARK)
    draw = ImageDraw.Draw(im)
    draw_clean_status_bar(im)
    
    # Back arrow (<)
    draw.polygon([(80, 185), (55, 170), (80, 155)], fill=TEXT_PRIMARY)
    draw.rectangle([55, 166, 110, 174], fill=TEXT_PRIMARY)
    
    # Header
    font_h1 = get_font(56, bold=True)
    draw.text((280, 140), "Your encryption key", font=font_h1, fill=TEXT_PRIMARY)
    
    # Subtitle
    font_sub = get_font(36)
    draw.text((180, 270), "Write down your 64-digit key or copy it.", font=font_sub, fill=TEXT_MUTED)
    draw.text((140, 320), "You will need this key to decrypt your media.", font=font_sub, fill=TEXT_MUTED)
    
    # 4x4 Key Grid Container Card
    card_x1, card_y1, card_x2, card_y2 = 60, 460, 1020, 1420
    draw.rounded_rectangle([card_x1, card_y1, card_x2, card_y2], radius=28, fill=CARD_BG, outline=(32, 44, 51), width=2)
    
    sample_blocks = [
        ["a874", "3d1e", "663d", "ee5f"],
        ["b94a", "ff69", "02e3", "179b"],
        ["93d0", "c92a", "be97", "342a"],
        ["976b", "c1f8", "6843", "65ca"]
    ]
    
    font_mono = get_font(46, bold=True)
    col_width = (card_x2 - card_x1) / 4
    row_height = (card_y2 - card_y1) / 4
    
    for r in range(4):
        for c in range(4):
            bx = card_x1 + c * col_width + col_width / 2
            by = card_y1 + r * row_height + row_height / 2
            txt = sample_blocks[r][c]
            pw, ph = 180, 70
            draw.rounded_rectangle([bx - pw//2, by - ph//2, bx + pw//2, by + ph//2], radius=12, fill=(11, 20, 26))
            draw.text((bx - 55, by - 26), txt, font=font_mono, fill=(233, 237, 239))
            
    # Floating Native Android Text Selection Popup [ Copy | Select all ]
    popup_x1, popup_y1, popup_x2, popup_y2 = 280, 880, 800, 985
    draw.rounded_rectangle([popup_x1, popup_y1, popup_x2, popup_y2], radius=26, fill=(30, 41, 59), outline=(16, 185, 129), width=3)
    
    font_pop = get_font(40, bold=True)
    draw.text((340, 910), "Copy", font=font_pop, fill=(52, 211, 153))
    draw.line([490, 900, 490, 965], fill=(71, 85, 105), width=2)
    draw.text((540, 910), "Select all", font=font_pop, fill=TEXT_PRIMARY)
    
    # Tap instruction badge directly above popup (NO arrows on slide 7)
    font_badge = get_font(32, bold=True)
    draw.rounded_rectangle([280, 810, 620, 868], radius=16, fill=(16, 185, 129))
    draw.text((305, 822), "Long-press & Copy", font=font_badge, fill=(11, 20, 26))
    
    # Selection glow box around the key card
    draw.rounded_rectangle([card_x1 - 6, card_y1 - 6, card_x2 + 6, card_y2 + 6], radius=32, outline=ACCENT_GREEN, width=4)
    
    # WhatsApp instructions text
    font_inst = get_font(36)
    draw.text((100, 1550), "1. Press and hold anywhere on the numbers to copy.", font=font_inst, fill=TEXT_PRIMARY)
    draw.text((100, 1630), "2. Keep this key safe. WhatsApp cannot recover it.", font=font_inst, fill=TEXT_PRIMARY)
    draw.text((100, 1710), "3. Never share your 64-digit key with anyone.", font=font_inst, fill=TEXT_MUTED)
    
    # Authentic WhatsApp bottom button: "I saved my 64-digit key"
    btn_x1, btn_y1, btn_x2, btn_y2 = 60, 2240, 1020, 2350
    draw.rounded_rectangle([btn_x1, btn_y1, btn_x2, btn_y2], radius=55, fill=WA_GREEN)
    font_btn = get_font(42, bold=True)
    draw.text((290, 2270), "I saved my 64-digit key", font=font_btn, fill=(11, 20, 26))
    
    return im

def main():
    print("[1/8] Processing Slide 0 (Main Menu -> Settings)...")
    s0 = process_slide_0()
    s0.save(os.path.join(DEST_DIR_CORE, 'wa_step0.webp'), 'WEBP', quality=90)
    s0.save(os.path.join(DEST_DIR_OUTPUT, 'wa_step0.webp'), 'WEBP', quality=90)
    
    print("[2/8] Processing Slide 1 (Settings -> Chats)...")
    s1 = process_slide_1()
    s1.save(os.path.join(DEST_DIR_CORE, 'wa_step1.webp'), 'WEBP', quality=90)
    s1.save(os.path.join(DEST_DIR_OUTPUT, 'wa_step1.webp'), 'WEBP', quality=90)
    
    print("[3/8] Processing Slide 2 (Chats -> Chat backup)...")
    s2 = process_slide_2()
    s2.save(os.path.join(DEST_DIR_CORE, 'wa_step2.webp'), 'WEBP', quality=90)
    s2.save(os.path.join(DEST_DIR_OUTPUT, 'wa_step2.webp'), 'WEBP', quality=90)
    
    print("[4/8] Processing Slide 3 (Chat backup -> E2E Backup)...")
    s3 = process_slide_3()
    s3.save(os.path.join(DEST_DIR_CORE, 'wa_step3.webp'), 'WEBP', quality=90)
    s3.save(os.path.join(DEST_DIR_OUTPUT, 'wa_step3.webp'), 'WEBP', quality=90)
    
    print("[5/8] Processing Slide 4 (More options vs Passkey Alert)...")
    s4 = process_slide_4()
    s4.save(os.path.join(DEST_DIR_CORE, 'wa_step4.webp'), 'WEBP', quality=90)
    s4.save(os.path.join(DEST_DIR_OUTPUT, 'wa_step4.webp'), 'WEBP', quality=90)
    
    print("[6/8] Processing Slide 5 (More options -> 64-digit key)...")
    s5 = process_slide_5()
    s5.save(os.path.join(DEST_DIR_CORE, 'wa_step5.webp'), 'WEBP', quality=90)
    s5.save(os.path.join(DEST_DIR_OUTPUT, 'wa_step5.webp'), 'WEBP', quality=90)
    
    print("[7/8] Processing Slide 6 (Generate key)...")
    s6 = process_slide_6()
    s6.save(os.path.join(DEST_DIR_CORE, 'wa_step6.webp'), 'WEBP', quality=90)
    s6.save(os.path.join(DEST_DIR_OUTPUT, 'wa_step6.webp'), 'WEBP', quality=90)
    
    print("[8/8] Generating Slide 7 (Key Generated & Native Copy)...")
    s7 = generate_slide_7()
    s7.save(os.path.join(DEST_DIR_CORE, 'wa_step7.webp'), 'WEBP', quality=90)
    s7.save(os.path.join(DEST_DIR_OUTPUT, 'wa_step7.webp'), 'WEBP', quality=90)
    
    print("Successfully processed and exported all 8 tutorial slides in WebP format!")

if __name__ == '__main__':
    main()
