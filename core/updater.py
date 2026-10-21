"""
In-app updater: checks GitHub Releases, downloads and verifies the new version, stages it,
and (once the app is idle and the user confirms) hands over to core/update_helper.py, which
swaps the files and restarts the app with an automatic rollback if the new version fails.

Nothing here talks to the network until the user asks (Settings -> About & Updates).

What an update replaces: only the application code listed in APPLICATION_ENTRIES. The user's
config.json, output folder, Databases, keys, the bundled Python runtime and ADB are never
touched. The package comes from the release's Unix-Source archive, which holds exactly the
application code for every platform; its SHA-256 is verified before anything is staged.
"""

import hashlib
import json
import os
import re
import shutil
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional
from urllib.parse import urlparse

from core.activity import ActivityTracker, activity
from core.version import GITHUB_REPO, __version__, is_newer, parse_version

UPDATE_DIRNAME = ".update"

# Everything the archive is allowed to place in the app folder (anything else is ignored,
# in particular config.json which ships in the archive as a clean template).
APPLICATION_ENTRIES = (
    "core",
    "gallery_assets",
    "gallery.html",
    "wa_media_organizer.py",
    "requirements.txt",
    "README.md",
    "start_gallery.sh",
    "install.sh",
)
REQUIRED_ENTRIES = ("core", "gallery_assets", "gallery.html", "wa_media_organizer.py")

PACKAGE_ASSET_RE = re.compile(r"Unix-Source\.tar\.gz$")
CHECKSUM_SUFFIX = ".sha256"

ALLOWED_HOST_SUFFIXES = ("github.com", "githubusercontent.com")
API_BASE = "https://api.github.com"

MAX_PACKAGE_BYTES = 200 * 1024 * 1024
MAX_EXTRACTED_BYTES = 600 * 1024 * 1024
MAX_EXTRACTED_FILES = 20000
MAX_NOTES_CHARS = 8000
CHECK_CACHE_SECS = 600
HTTP_TIMEOUT_SECS = 20
DOWNLOAD_CHUNK = 256 * 1024
SHUTDOWN_GRACE_SECS = 20

STATE_IDLE = "idle"
STATE_DOWNLOADING = "downloading"
STATE_VERIFYING = "verifying"
STATE_STAGING = "staging"
STATE_READY = "ready"
STATE_APPLYING = "applying"
STATE_ERROR = "error"
_WORKING_STATES = (STATE_DOWNLOADING, STATE_VERIFYING, STATE_STAGING)


class UpdateError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class UpdateCancelled(Exception):
    pass


# --------------------------------------------------------------------------- helpers

def app_root() -> Path:
    return Path(__file__).resolve().parent.parent


def update_dir(root: Optional[Path] = None) -> Path:
    return (root or app_root()) / UPDATE_DIRNAME


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _host_allowed(url: str, allowed_suffixes: Iterable[str]) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("https", "http"):
        return False
    return any(host == s or host.endswith("." + s) for s in allowed_suffixes)


def detect_install(root: Optional[Path] = None) -> dict:
    """Describes how this copy was installed and whether it can update itself."""
    root = root or app_root()
    kind = "source"
    if (root / ".git").exists():
        kind = "git"
    elif (root / "runtime").is_dir():
        kind = "portable"

    info = {"kind": kind, "can_self_update": True, "reason": ""}
    if kind == "git":
        info.update(can_self_update=False, reason=(
            "This copy was installed with Git, so an in-app update would overwrite your working files. "
            "Update it with: git pull"))
        return info
    try:
        probe_dir = update_dir(root)
        probe_dir.mkdir(exist_ok=True)
        probe = probe_dir / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError:
        info.update(can_self_update=False, reason=(
            "The application folder is not writable (for example it is in Program Files or on a read-only "
            "drive). Download the new release and replace the folder manually."))
    return info


def _normalize_requirement_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requirements(text: str) -> Dict[str, str]:
    reqs: Dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*(.*)$", line)
        if m:
            reqs[_normalize_requirement_name(m.group(1))] = m.group(2).replace(" ", "")
    return reqs


def _version_tuple(text: str):
    parts = re.findall(r"\d+", text.split("+", 1)[0])
    return tuple(int(p) for p in parts[:6]) if parts else None


def _satisfies(installed: str, spec: str) -> bool:
    """Minimal PEP 440 clause check (>=, >, <=, <, ==, !=, ~=) on the numeric part of versions."""
    have = _version_tuple(installed)
    if have is None:
        return False
    for clause in filter(None, spec.split(",")):
        m = re.match(r"^(>=|<=|==|!=|~=|>|<)(.+)$", clause)
        if not m:
            return False
        want = _version_tuple(m.group(2))
        if want is None:
            return False
        n = max(len(have), len(want))
        h, w = have + (0,) * (n - len(have)), want + (0,) * (n - len(want))
        op = m.group(1)
        if op == "~=":
            ok = h >= w and h[: max(n - 1, 1)] == w[: max(n - 1, 1)]
        else:
            ok = {">=": h >= w, "<=": h <= w, "==": h == w, "!=": h != w, ">": h > w, "<": h < w}[op]
        if not ok:
            return False
    return True


def unmet_requirements(old_text: str, new_text: str, installed_version: Callable[[str], Optional[str]] = None) -> List[str]:
    """
    Requirements that the new version added or changed AND the current Python environment does
    not already satisfy. An update that needs new packages cannot be applied safely from inside
    the app (the portable build ships a fixed set of wheels), so it is offered as a manual download.
    """
    if installed_version is None:
        from importlib import metadata

        def installed_version(name):
            try:
                return metadata.version(name)
            except metadata.PackageNotFoundError:
                return None

    old, new = parse_requirements(old_text), parse_requirements(new_text)
    unmet = []
    for name, spec in new.items():
        if old.get(name) == spec:
            continue
        have = installed_version(name)
        if have is None or (spec and not _satisfies(have, spec)):
            unmet.append(f"{name}{spec}")
    return unmet


def extract_package(archive: Path, dest: Path, cancel: Optional[threading.Event] = None) -> List[str]:
    """
    Safely unpacks the application files of a release archive into dest and returns the
    top-level entries that were extracted. Rejects links, device files, absolute paths and
    path traversal, ignores everything that is not application code, and caps the size.
    """
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    total = 0
    count = 0
    extracted = set()
    try:
        tar = tarfile.open(archive, "r:gz")
    except (tarfile.TarError, OSError, EOFError) as e:
        raise UpdateError("bad_package", f"The downloaded package is not a valid archive ({e}).")
    with tar:
        members = tar.getmembers()
        tops = {m.name.replace("\\", "/").split("/", 1)[0] for m in members if m.name not in (".", "")}
        if len(tops) != 1:
            raise UpdateError("bad_package", "The downloaded package has an unexpected layout.")
        for member in members:
            if cancel is not None and cancel.is_set():
                raise UpdateCancelled()
            name = member.name.replace("\\", "/")
            parts = [p for p in name.split("/") if p not in ("", ".")]
            if len(parts) < 2:
                continue  # the top-level folder itself
            rel_parts = parts[1:]
            if any(p == ".." or ":" in p for p in rel_parts) or name.startswith("/"):
                raise UpdateError("bad_package", f"The package contains an unsafe path: {name}")
            if member.issym() or member.islnk() or not (member.isreg() or member.isdir()):
                raise UpdateError("bad_package", f"The package contains a link or special file: {name}")
            if rel_parts[0] not in APPLICATION_ENTRIES:
                continue
            target = dest.joinpath(*rel_parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                extracted.add(rel_parts[0])
                continue
            count += 1
            total += member.size
            if count > MAX_EXTRACTED_FILES or total > MAX_EXTRACTED_BYTES:
                raise UpdateError("bad_package", "The package is unexpectedly large.")
            target.parent.mkdir(parents=True, exist_ok=True)
            src = tar.extractfile(member)
            if src is None:
                continue
            with src, open(target, "wb") as out:
                shutil.copyfileobj(src, out, 1024 * 1024)
            if member.mode & 0o111:
                try:
                    os.chmod(target, 0o755)
                except OSError:
                    pass
            extracted.add(rel_parts[0])
    return [e for e in APPLICATION_ENTRIES if e in extracted]


def validate_staged(staging: Path, expected_version: str) -> None:
    missing = [e for e in REQUIRED_ENTRIES if not (staging / e).exists()]
    if missing:
        raise UpdateError("bad_package", f"The package is incomplete (missing {', '.join(missing)}).")
    version_file = staging / "core" / "version.py"
    try:
        text = version_file.read_text(encoding="utf-8")
    except OSError:
        raise UpdateError("bad_package", "The package does not contain a version file.")
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.M)
    if not m or parse_version(m.group(1)) != parse_version(expected_version):
        raise UpdateError("bad_package", f"The package contains version {m.group(1) if m else 'unknown'}, "
                                         f"not {expected_version}.")
    for py in staging.rglob("*.py"):
        try:
            compile(py.read_bytes(), str(py), "exec")
        except (SyntaxError, ValueError) as e:
            raise UpdateError("bad_package", f"The package contains a broken file ({py.name}: {e}).")


def build_relaunch_command(exe: str, root: Path, output_dir: str, port: int,
                           idle_timeout: int = 0, allow_lan: bool = False) -> List[str]:
    """Always restarts in plain server mode: never repeats a one-off pipeline such as --live."""
    cmd = [exe, str(root / "wa_media_organizer.py"), "--serve",
           "--output", str(output_dir), "--port", str(int(port)), "--idle-timeout", str(int(idle_timeout))]
    if allow_lan:
        cmd.append("--allow-lan")
    return cmd


def env_overrides() -> dict:
    """
    WA_UPDATE_API_BASE points the updater at another GitHub-compatible API (a mirror, GitHub
    Enterprise, or a test server). Only that host is then trusted in addition to GitHub.
    """
    base = os.environ.get("WA_UPDATE_API_BASE", "").strip()
    if not base:
        return {}
    host = urlparse(base).hostname
    if not host:
        return {}
    return {"api_base": base, "allowed_hosts": ALLOWED_HOST_SUFFIXES + (host,)}


# --------------------------------------------------------------------------- manager

class UpdateManager:
    def __init__(
        self,
        root: Optional[Path] = None,
        repo: str = GITHUB_REPO,
        api_base: str = API_BASE,
        current_version: str = __version__,
        tracker: ActivityTracker = activity,
        busy_probe: Optional[Callable[[], Iterable[str]]] = None,
        urlopen: Callable = None,
        allowed_hosts: Iterable[str] = ALLOWED_HOST_SUFFIXES,
    ):
        self.root = root or app_root()
        self.repo = repo
        self.api_base = api_base.rstrip("/")
        self.current_version = current_version
        self.tracker = tracker
        self.busy_probe = busy_probe or (lambda: [])
        self._urlopen = urlopen or urllib.request.urlopen
        self.allowed_hosts = tuple(allowed_hosts)

        self._lock = threading.RLock()
        self._state = STATE_IDLE
        self._error: Optional[dict] = None
        self._progress = {"percent": 0.0, "bytes_done": 0, "bytes_total": 0, "message": ""}
        self._release: Optional[dict] = None
        self._checked_at = 0.0
        self._staged: Optional[dict] = None
        self._cancel = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._install: Optional[dict] = None
        self._install_checked_at = 0.0
        self._hard_exit = os._exit
        self._pid = os.getpid()

    # ----- HTTP

    def _request(self, url: str, accept: str = "application/vnd.github+json"):
        if not _host_allowed(url, self.allowed_hosts):
            raise UpdateError("blocked_host", "Refusing to contact an unexpected server.")
        req = urllib.request.Request(url, headers={
            # No version, machine or user information is sent: only what any web request carries
            "User-Agent": "WhatsAppMediaOrganizer-update-check",
            "Accept": accept,
        })
        try:
            resp = self._urlopen(req, timeout=HTTP_TIMEOUT_SECS)
        except urllib.error.HTTPError as e:
            if e.code in (403, 429) and e.headers and e.headers.get("X-RateLimit-Remaining") == "0":
                raise UpdateError("rate_limited", "GitHub is limiting requests from this network. Try again in a few minutes.")
            if e.code == 404:
                raise UpdateError("not_found", "No published release was found.")
            raise UpdateError("http_error", f"GitHub answered with an error ({e.code}).")
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise UpdateError("offline", "Could not reach GitHub. Check your internet connection and try again.")
        final_url = getattr(resp, "geturl", lambda: url)()
        if not _host_allowed(final_url, self.allowed_hosts):
            resp.close()
            raise UpdateError("blocked_host", "The download was redirected to an unexpected server.")
        return resp

    def _get_text(self, url: str, limit: int = 1024 * 1024) -> str:
        with self._request(url, "*/*") as resp:
            return resp.read(limit).decode("utf-8", errors="replace")

    # ----- checking

    def check(self, force: bool = False) -> dict:
        with self._lock:
            fresh = self._release is not None and (time.time() - self._checked_at) < CHECK_CACHE_SECS
            if fresh and not force:
                return self._check_result()
            if self._state in _WORKING_STATES + (STATE_APPLYING,) and self._release is not None:
                return self._check_result()
        url = f"{self.api_base}/repos/{self.repo}/releases/latest"
        with self._request(url) as resp:
            data = json.loads(resp.read(2 * 1024 * 1024).decode("utf-8"))
        release = self._parse_release(data)
        with self._lock:
            self._release = release
            self._checked_at = time.time()
            return self._check_result()

    def _parse_release(self, data: dict) -> dict:
        tag = str(data.get("tag_name") or "")
        if parse_version(tag) is None:
            raise UpdateError("bad_release", f"The latest release has an unusual version ({tag or 'none'}).")
        assets = data.get("assets") or []
        package = next((a for a in assets if PACKAGE_ASSET_RE.search(a.get("name", ""))), None)
        checksum = None
        if package:
            checksum = next((a for a in assets if a.get("name") == package["name"] + CHECKSUM_SUFFIX), None)
        digest = ""
        if package and str(package.get("digest", "")).startswith("sha256:"):
            digest = package["digest"].split(":", 1)[1].lower()
        notes = str(data.get("body") or "")
        if len(notes) > MAX_NOTES_CHARS:
            notes = notes[:MAX_NOTES_CHARS].rstrip() + "\n…"
        return {
            "tag": tag,
            "version": ".".join(str(p) for p in parse_version(tag)),
            "name": data.get("name") or tag,
            "notes": notes,
            "html_url": data.get("html_url") or f"https://github.com/{self.repo}/releases",
            "published_at": data.get("published_at") or "",
            "package": None if not package else {
                "name": package["name"],
                "url": package.get("browser_download_url", ""),
                "size": int(package.get("size") or 0),
                "sha256": digest,
                "checksum_url": (checksum or {}).get("browser_download_url", ""),
            },
        }

    def _check_result(self) -> dict:
        rel = self._release
        return {
            "current_version": self.current_version,
            "latest_version": rel["version"],
            "update_available": is_newer(rel["version"], self.current_version),
            "release": {k: rel[k] for k in ("tag", "name", "notes", "html_url", "published_at")},
            "package_size": (rel["package"] or {}).get("size", 0),
            "has_package": bool(rel["package"]),
            "checked_at": self._checked_at,
        }

    # ----- state

    def install_info(self) -> dict:
        # status() is polled twice a second; probing the folder for write access every time is wasteful
        if self._install is None or time.time() - self._install_checked_at > 60:
            self._install = detect_install(self.root)
            self._install_checked_at = time.time()
        return self._install

    def _set(self, state: str, message: str = "", percent: Optional[float] = None, error: Optional[dict] = None):
        with self._lock:
            self._state = state
            self._error = error
            self._progress["message"] = message
            if percent is not None:
                self._progress["percent"] = percent

    def current_busy(self) -> List[str]:
        busy = list(self.busy_probe()) + self.tracker.running()
        return sorted(set(busy))

    def status(self) -> dict:
        with self._lock:
            st = {
                "state": self._state,
                "error": self._error,
                "percent": round(self._progress["percent"], 1),
                "bytes_done": self._progress["bytes_done"],
                "bytes_total": self._progress["bytes_total"],
                "message": self._progress["message"],
                "current_version": self.current_version,
                "target_version": (self._staged or {}).get("version") or (self._release or {}).get("version"),
                "install": self.install_info(),
            }
        st["busy"] = self.current_busy() if st["state"] == STATE_READY else []
        return st

    # ----- download (background)

    def start_download(self) -> dict:
        info = self.install_info()
        if not info["can_self_update"]:
            raise UpdateError("unsupported_install", info["reason"])
        result = self.check()
        if not result["update_available"]:
            raise UpdateError("up_to_date", "You already have the latest version.")
        if not result["has_package"]:
            raise UpdateError("no_package", "The latest release has no downloadable update package. "
                                            "Use the release page to download it manually.")
        with self._lock:
            if self._state in _WORKING_STATES or self._state == STATE_APPLYING:
                raise UpdateError("busy", "An update is already in progress.")
            if self._state == STATE_READY and (self._staged or {}).get("version") == self._release["version"]:
                return self.status()
            self._cancel.clear()
            self._progress.update(percent=0.0, bytes_done=0, bytes_total=0, message="Starting download…")
            self._set(STATE_DOWNLOADING, "Starting download…", 0.0)
            self._staged = None
            release = dict(self._release)
        self._worker = threading.Thread(target=self._download_worker, args=(release,), daemon=True, name="update-download")
        self._worker.start()
        return self.status()

    def _download_worker(self, release: dict):
        udir = update_dir(self.root)
        work = udir / "download"
        staging = udir / "staging"
        try:
            shutil.rmtree(work, ignore_errors=True)
            shutil.rmtree(staging, ignore_errors=True)
            work.mkdir(parents=True, exist_ok=True)
            package = release["package"]
            expected = self._expected_checksum(package)

            size = package["size"]
            if size > MAX_PACKAGE_BYTES:
                raise UpdateError("bad_package", "The update package is unexpectedly large.")
            free = shutil.disk_usage(self.root).free
            needed = max(size, 1) * 6 + 32 * 1024 * 1024
            if free < needed:
                raise UpdateError("no_space", f"Not enough free disk space for the update "
                                              f"(need about {needed // (1024 * 1024)} MB).")

            archive = work / package["name"]
            self._download(package["url"], archive, size)
            self._check_cancel()

            self._set(STATE_VERIFYING, "Verifying download…", 100.0)
            actual = sha256_file(archive)
            if actual != expected:
                raise UpdateError("checksum_mismatch", "The downloaded file failed its integrity check "
                                                       "and was discarded. Please try again.")

            self._set(STATE_STAGING, "Preparing files…", 100.0)
            entries = extract_package(archive, staging, self._cancel)
            validate_staged(staging, release["version"])
            self._check_requirements(staging)
            self._check_cancel()

            archive.unlink(missing_ok=True)
            with self._lock:
                self._staged = {"version": release["version"], "entries": entries, "staging": str(staging)}
            self._set(STATE_READY, f"Version {release['version']} is ready to install.", 100.0)
        except UpdateCancelled:
            self._discard_files()
            self._set(STATE_IDLE, "")
        except UpdateError as e:
            self._discard_files()
            self._set(STATE_ERROR, e.message, error={"code": e.code, "message": e.message})
        except Exception as e:  # never leave the UI waiting on a dead worker
            self._discard_files()
            self._set(STATE_ERROR, str(e), error={"code": "unexpected", "message": f"Unexpected error: {e}"})

    def _expected_checksum(self, package: dict) -> str:
        from_api = package.get("sha256") or ""
        from_file = ""
        if package.get("checksum_url"):
            try:
                text = self._get_text(package["checksum_url"], 4096)
                m = re.search(r"\b([0-9a-fA-F]{64})\b", text)
                from_file = m.group(1).lower() if m else ""
            except UpdateError:
                if not from_api:
                    raise
        if from_api and from_file and from_api != from_file:
            raise UpdateError("checksum_mismatch", "The release's checksums disagree; refusing to install it.")
        expected = from_api or from_file
        if not expected:
            raise UpdateError("no_checksum", "The release has no checksum, so the download cannot be verified.")
        return expected

    def _download(self, url: str, dest: Path, expected_size: int):
        with self._request(url, "application/octet-stream") as resp:
            length = int(resp.headers.get("Content-Length") or expected_size or 0)
            if length > MAX_PACKAGE_BYTES:
                raise UpdateError("bad_package", "The update package is unexpectedly large.")
            with self._lock:
                self._progress["bytes_total"] = length
            done = 0
            tmp = dest.with_name(dest.name + ".part")
            try:
                with open(tmp, "wb") as out:
                    while True:
                        self._check_cancel()
                        chunk = resp.read(DOWNLOAD_CHUNK)
                        if not chunk:
                            break
                        out.write(chunk)
                        done += len(chunk)
                        if done > MAX_PACKAGE_BYTES:
                            raise UpdateError("bad_package", "The update package is unexpectedly large.")
                        with self._lock:
                            self._progress["bytes_done"] = done
                            if length:
                                self._progress["percent"] = min(99.0, done * 100.0 / length)
                            self._progress["message"] = "Downloading…"
                if length and done != length:
                    raise UpdateError("incomplete", "The download was interrupted. Please try again.")
                os.replace(tmp, dest)
            finally:
                tmp.unlink(missing_ok=True)

    def _check_requirements(self, staging: Path):
        new_req = staging / "requirements.txt"
        old_req = self.root / "requirements.txt"
        if not new_req.is_file():
            return
        old_text = old_req.read_text(encoding="utf-8") if old_req.is_file() else ""
        unmet = unmet_requirements(old_text, new_req.read_text(encoding="utf-8"))
        if unmet:
            raise UpdateError("needs_reinstall", "This version needs new components (" + ", ".join(unmet) +
                                                 "), which cannot be installed from inside the app. "
                                                 "Please download the full release from the release page.")

    def _check_cancel(self):
        if self._cancel.is_set():
            raise UpdateCancelled()

    def _discard_files(self):
        udir = update_dir(self.root)
        shutil.rmtree(udir / "download", ignore_errors=True)
        shutil.rmtree(udir / "staging", ignore_errors=True)
        with self._lock:
            self._staged = None

    # ----- cancel / discard

    def cancel(self) -> dict:
        with self._lock:
            state = self._state
            if state == STATE_APPLYING:
                raise UpdateError("busy", "The update is already being installed and can no longer be cancelled.")
            if state in _WORKING_STATES:
                self._cancel.set()
                return self.status()
        if state in (STATE_READY, STATE_ERROR):
            self._discard_files()
            self._set(STATE_IDLE, "")
        return self.status()

    # ----- apply

    def apply(self, request_shutdown: Callable[[], None], port: int, output_dir: str,
              idle_timeout: int = 0, allow_lan: bool = False) -> dict:
        """
        Installs the staged update: refuses while anything is running, then starts the helper
        and asks the server to shut down. The helper finishes the job and restarts the app.
        """
        with self._lock:
            if self._state != STATE_READY or not self._staged:
                raise UpdateError("not_ready", "There is no downloaded update to install.")
            staged = dict(self._staged)

        busy = self.tracker.block("Installing an update. Please wait…", extra_busy=self.busy_probe)
        if busy:
            raise UpdateError("busy", "Finish or cancel what is running first: " + ", ".join(busy) + ".")
        try:
            udir = update_dir(self.root)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            plan = {
                "app_root": str(self.root),
                "update_dir": str(udir),
                "staging": staged["staging"],
                "backup": str(udir / f"backup-{stamp}-v{self.current_version}"),
                "entries": staged["entries"],
                "from_version": self.current_version,
                "to_version": staged["version"],
                "old_pid": self._pid,
                "port": int(port),
                "cwd": os.getcwd(),
                "command": build_relaunch_command(sys.executable, self.root, output_dir, port, idle_timeout, allow_lan),
            }
            helper = udir / "update_helper.py"
            shutil.copy2(Path(__file__).with_name("update_helper.py"), helper)
            plan_path = udir / "plan.json"
            plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
            self._spawn_helper(helper, plan_path)
        except Exception as e:
            self.tracker.unblock()
            raise UpdateError("apply_failed", f"Could not start the installer: {e}")

        self._set(STATE_APPLYING, "Restarting to finish the update…", 100.0)
        request_shutdown()
        # A stuck non-daemon thread must not keep the old process alive and block the file swap
        timer = threading.Timer(SHUTDOWN_GRACE_SECS, lambda: self._hard_exit(0))
        timer.daemon = True
        timer.start()
        return self.status()

    @staticmethod
    def _spawn_helper(helper: Path, plan_path: Path):
        import subprocess

        kwargs = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
        if sys.platform == "win32":
            kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen([sys.executable, str(helper), str(plan_path)], **kwargs)

    # ----- results of the previous update

    def consume_last_result(self) -> Optional[dict]:
        """Returns the outcome of the last installed update once (so the UI can tell the user)."""
        path = update_dir(self.root) / "last_result.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        try:
            path.replace(path.with_name("last_result.shown.json"))
        except OSError:
            pass
        return data

    def cleanup_stale(self):
        """On startup: drop leftovers of an update that never finished (unless a helper is working)."""
        from core.update_helper import STATUS_APPLYING, STATUS_LAUNCHING, STATUS_WAITING, pid_alive

        udir = update_dir(self.root)
        try:
            journal = json.loads((udir / "journal.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            journal = None
        if journal and journal.get("status") in (STATUS_WAITING, STATUS_APPLYING, STATUS_LAUNCHING) \
                and pid_alive(journal.get("helper_pid")):
            return
        shutil.rmtree(udir / "download", ignore_errors=True)
        shutil.rmtree(udir / "staging", ignore_errors=True)
