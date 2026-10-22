"""
Single source of truth for the application version.

Release builds stamp __version__ from the Git tag (see .github/workflows/release.yml and
scripts/build_windows_portable.py), so it can never drift from the published release.
"""

import re
from typing import Optional, Tuple

__version__ = "1.2.3"

GITHUB_REPO = "PNxZEN/OrganizeWhatsapp"

_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)*)$")


def parse_version(text) -> Optional[Tuple[int, ...]]:
    """'v1.2.0' -> (1, 2, 0). Returns None for anything that is not a plain numeric version
    (pre-release tags such as 'v2.0.0-beta' are deliberately not treated as updates)."""
    m = _VERSION_RE.match(str(text or "").strip())
    if not m:
        return None
    return tuple(int(part) for part in m.group(1).split("."))


def is_newer(candidate, current=__version__) -> bool:
    """True when candidate is a strictly newer version than current ('1.2' == '1.2.0')."""
    a, b = parse_version(candidate), parse_version(current)
    if a is None or b is None:
        return False
    width = max(len(a), len(b))
    pad = lambda v: v + (0,) * (width - len(v))
    return pad(a) > pad(b)
