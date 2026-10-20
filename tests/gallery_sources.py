"""
Loads the gallery frontend sources exactly as the browser does:
gallery.html plus every stylesheet and script it links from gallery_assets/, in page order.
"""

import re
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
GALLERY_HTML_PATH = WORKSPACE_ROOT / "gallery.html"

_ASSET_REF_RE = re.compile(
    r'<link rel="stylesheet" href="(gallery_assets/[^"]+)"|<script src="(gallery_assets/[^"]+)"></script>'
)


def gallery_asset_paths():
    """Returns the CSS/JS asset paths referenced by gallery.html, in load order."""
    html = GALLERY_HTML_PATH.read_text(encoding="utf-8")
    return [WORKSPACE_ROOT / (css or js) for css, js in _ASSET_REF_RE.findall(html)]


def read_gallery_bundle():
    """Returns gallery.html followed by all of its linked CSS and JS module sources."""
    parts = [GALLERY_HTML_PATH.read_text(encoding="utf-8")]
    parts.extend(p.read_text(encoding="utf-8") for p in gallery_asset_paths())
    return "\n".join(parts)
