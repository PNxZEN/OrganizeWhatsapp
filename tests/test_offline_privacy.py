"""
The gallery must work completely offline and never contact an outside server by itself:
no remote stylesheets, scripts, fonts or images; the bundled font is present and served.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import core.server as srv
from gallery_sources import GALLERY_HTML_PATH, WORKSPACE_ROOT, gallery_asset_paths


class TestOfflinePrivacy(unittest.TestCase):
    def test_01_page_loads_nothing_from_outside(self):
        html = GALLERY_HTML_PATH.read_text(encoding="utf-8")
        remote_tags = re.findall(r"<(?:link|script|img|iframe|source|video|audio)\b[^>]*?(?:src|href)=[\"']https?://[^\"']+", html, re.I)
        self.assertEqual(remote_tags, [], "gallery.html must not load remote resources")
        for path in gallery_asset_paths():
            if path.suffix != ".css":
                continue
            css = path.read_text(encoding="utf-8")
            self.assertNotRegex(css, r"@import\s+(?:url\()?['\"]?https?://", path.name)
            self.assertNotRegex(css, r"url\(['\"]?https?://", path.name)

    def test_02_inter_font_is_bundled_and_served_with_the_right_type(self):
        fonts_css = (WORKSPACE_ROOT / "gallery_assets" / "css" / "fonts.css").read_text(encoding="utf-8")
        for name in re.findall(r"fonts/([\w.-]+\.woff2)", fonts_css):
            self.assertTrue((WORKSPACE_ROOT / "gallery_assets" / "fonts" / name).is_file(), name)
        self.assertEqual(srv.GalleryHTTPRequestHandler.extensions_map[".woff2"], "font/woff2")
        self.assertIn("fonts.css", GALLERY_HTML_PATH.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
