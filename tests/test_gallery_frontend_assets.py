"""
Verification Suite for the modular gallery frontend (gallery.html + gallery_assets/):
- Every CSS/JS module referenced by gallery.html exists
- The server serves modules with explicit MIME types and blocks path traversal
- install_gallery_frontend copies gallery.html + gallery_assets into an output folder
  (so the gallery also opens via file://) and prunes stale module files
"""

import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT))

import core.server as srv
from core.gallery import GALLERY_ASSETS_DIRNAME, install_gallery_frontend
from gallery_sources import gallery_asset_paths


class TestGalleryFrontendAssets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp(prefix="wa_test_assets_")
        cls.output_dir = Path(cls.temp_dir) / "output"
        cls.output_dir.mkdir(parents=True, exist_ok=True)
        cls.port = srv.find_open_port(preferred_port=8890, host="127.0.0.1")
        out = str(cls.output_dir)

        class BoundHandler(srv.GalleryHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=out, **kwargs)

        cls.httpd = ThreadingHTTPServer(("127.0.0.1", cls.port), BoundHandler)
        cls.server_thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def _get(self, path):
        return urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=10)

    def test_01_all_referenced_modules_exist(self):
        paths = gallery_asset_paths()
        self.assertGreater(len(paths), 20, "gallery.html should reference its CSS/JS modules")
        for p in paths:
            self.assertTrue(p.is_file(), f"Referenced gallery module missing: {p}")
        self.assertTrue(any(p.name == "app.js" for p in paths))
        self.assertEqual(paths[-1].name, "app.js", "app.js must load last so every module is defined before boot")

    def test_02_modules_served_with_explicit_mime_types(self):
        with self._get("/gallery_assets/js/app.js") as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/javascript", resp.headers.get("Content-Type", ""))
        with self._get("/gallery_assets/css/base.css") as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/css", resp.headers.get("Content-Type", ""))

    def test_03_path_traversal_blocked(self):
        for path in ("/gallery_assets/../core/server.py", "/gallery_assets/%2e%2e/core/server.py"):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self._get(path)
            self.assertEqual(ctx.exception.code, 404)

    def test_04_install_copies_frontend_and_prunes_stale_files(self):
        target = Path(self.temp_dir) / "file_mode_output"
        stale = target / GALLERY_ASSETS_DIRNAME / "js" / "obsolete_module.js"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_text("// stale", encoding="utf-8")

        self.assertTrue(install_gallery_frontend(target))
        self.assertTrue((target / "gallery.html").is_file())
        for p in gallery_asset_paths():
            rel = p.relative_to(WORKSPACE_ROOT)
            self.assertTrue((target / rel).is_file(), f"{rel} not copied for file:// mode")
        self.assertFalse(stale.exists(), "Stale module files should be removed")


if __name__ == "__main__":
    unittest.main()
