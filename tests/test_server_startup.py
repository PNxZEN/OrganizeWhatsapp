"""
The app's web server must start at once on every system.

Python's HTTPServer looks up the computer's full DNS name (socket.getfqdn) when it opens its
port. On some Macs and networks that lookup waits ~30 s for a DNS timeout (seen on GitHub's
macOS runners: the app took 37 s to answer). The app never uses that name, so it must not ask.
"""

import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import core.server as srv
from update_fixtures import free_port


def _no_dns_lookup(*args, **kwargs):
    raise AssertionError("socket.getfqdn must not be called while starting the server")


class TestServerStartup(unittest.TestCase):
    def test_01_local_server_never_looks_up_the_dns_name(self):
        with mock.patch.object(socket, "getfqdn", _no_dns_lookup):
            server = srv.LocalHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        try:
            self.assertEqual(server.server_name, "127.0.0.1")
            self.assertEqual(server.server_port, server.server_address[1])
        finally:
            server.server_close()

    def test_02_the_app_answers_quickly_even_when_dns_lookups_hang(self):
        tmp = Path(tempfile.mkdtemp(prefix="wa_test_startup_"))
        port = free_port()

        def slow_lookup(*args, **kwargs):
            time.sleep(30)
            return "slow.example"

        try:
            with mock.patch.object(socket, "getfqdn", slow_lookup):
                started = time.time()
                threading.Thread(target=srv.start_gallery_server, args=(str(tmp / "out"),),
                                 kwargs=dict(port=port, idle_timeout=0), daemon=True).start()
                answered = None
                while time.time() - started < 10:
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1):
                            answered = time.time() - started
                            break
                    except Exception:
                        time.sleep(0.1)
            self.assertIsNotNone(answered, "the server did not answer within 10 s")
            self.assertLess(answered, 5)
        finally:
            try:
                urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/api/shutdown", method="POST"), timeout=2)
            except Exception:
                pass
            time.sleep(1)
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
