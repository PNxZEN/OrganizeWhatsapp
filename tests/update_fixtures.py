"""
Test doubles for the in-app updater: a local stand-in for the GitHub Releases API and release
archives, plus a tiny "application" the update helper can install, start and health-check.
"""

import hashlib
import io
import json
import socket
import sys
import tarfile
import textwrap
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FAKE_APP_MAIN = textwrap.dedent('''
    import json, os, re, sys
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from pathlib import Path

    root = Path(__file__).resolve().parent
    text = (root / "core" / "version.py").read_text()
    version = re.search(r'__version__ = "([^"]+)"', text).group(1)
    if "CRASH_ON_START" in text:
        sys.exit(3)
    port = int(sys.argv[sys.argv.index("--port") + 1])

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"status": "ok", "version": version, "pid": os.getpid()}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *a):
            pass

    class Quick(HTTPServer):
        def server_bind(self):  # skip socket.getfqdn: it can stall ~30 s on macOS runners
            import socketserver
            socketserver.TCPServer.server_bind(self)
            self.server_name, self.server_port = self.server_address[:2]

    Quick(("127.0.0.1", port), H).serve_forever()
''')


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_app_files(version, extra=None):
    """Files of a minimal application at `version` (path -> text)."""
    files = {
        "core/__init__.py": "",
        "core/version.py": f'__version__ = "{version}"\n' + (extra or ""),
        "gallery_assets/css/app.css": f"/* css {version} */",
        "gallery_assets/js/app.js": f"// js {version}",
        "gallery.html": f"<html>{version}</html>",
        "wa_media_organizer.py": FAKE_APP_MAIN,
        "requirements.txt": "pillow>=10.0.0\n",
        "README.md": f"# {version}",
        "config.json": '{"onboarding_completed": false}',  # shipped as a template; must never be installed
    }
    return files


def build_archive(version, files=None, top=None, mutate=None):
    """Returns the bytes of a release tar.gz laid out like the real Unix-Source archive."""
    files = dict(make_app_files(version) if files is None else files)
    top = top or f"WhatsAppMediaOrganizer-v{version}"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        dirs = set()
        for rel in files:
            parts = rel.split("/")[:-1]
            for i in range(1, len(parts) + 1):
                dirs.add("/".join(parts[:i]))
        info = tarfile.TarInfo(top)
        info.type = tarfile.DIRTYPE
        tar.addfile(info)
        for d in sorted(dirs):
            info = tarfile.TarInfo(f"{top}/{d}")
            info.type = tarfile.DIRTYPE
            tar.addfile(info)
        for rel, text in files.items():
            data = text if isinstance(text, bytes) else text.encode()
            info = tarfile.TarInfo(f"{top}/{rel}")
            info.size = len(data)
            info.mode = 0o755 if rel.endswith(".sh") else 0o644
            tar.addfile(info, io.BytesIO(data))
        if mutate:
            mutate(tar, top)
    return buf.getvalue()


class QuickHTTPServer(ThreadingHTTPServer):
    """A test server that skips socket.getfqdn (it can stall ~30 s per process on macOS runners)."""

    def server_bind(self):
        import socketserver

        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class FakeGitHub:
    """Serves /repos/<repo>/releases/latest and the release assets from memory."""

    def __init__(self, repo="owner/repo"):
        self.repo = repo
        self.release = None          # dict returned by the API, or None for 404
        self.assets = {}             # path -> bytes
        self.api_status = 200
        self.api_headers = {}
        self.slow_download = None    # threading.Event the download waits for before finishing
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                outer.requests.append(self.path)
                if self.path == f"/repos/{outer.repo}/releases/latest":
                    if outer.api_status != 200:
                        self.send_response(outer.api_status)
                        for k, v in outer.api_headers.items():
                            self.send_header(k, v)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    body = json.dumps(outer.release).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                data = outer.assets.get(self.path)
                if data is None:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                half = len(data) // 2
                self.wfile.write(data[:half])
                self.wfile.flush()
                if outer.slow_download is not None:
                    outer.slow_download.wait(10)
                try:
                    self.wfile.write(data[half:])
                except OSError:
                    pass

        self.httpd = QuickHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def publish(self, version, archive=None, with_digest=True, with_checksum_file=True, bad_checksum=False,
                tag=None, notes="Release notes"):
        tag = tag or f"v{version}"
        name = f"WhatsAppMediaOrganizer-v{version}-Unix-Source.tar.gz"
        archive = archive if archive is not None else build_archive(version)
        digest = hashlib.sha256(archive).hexdigest()
        advertised = hashlib.sha256(b"tampered").hexdigest() if bad_checksum else digest
        self.assets[f"/dl/{name}"] = archive
        asset = {"name": name, "size": len(archive), "browser_download_url": f"{self.base}/dl/{name}"}
        if with_digest:
            asset["digest"] = f"sha256:{advertised}"
        assets = [asset]
        if with_checksum_file:
            self.assets[f"/dl/{name}.sha256"] = f"{advertised}  {name}\n".encode()
            assets.append({"name": name + ".sha256", "size": 100,
                           "browser_download_url": f"{self.base}/dl/{name}.sha256"})
        self.release = {"tag_name": tag, "name": f"Release {tag}", "body": notes,
                        "html_url": f"https://github.com/{self.repo}/releases/tag/{tag}",
                        "published_at": "2026-10-21T10:00:00Z", "assets": assets}
        return archive
