"""
One gallery server per output folder:
- a second launch on the same folder opens the running server instead of starting another one
- a different folder still gets its own server
- stale claims (crashed server, or a port now used by another program) are ignored
- /api/health identifies the app, so launchers do not mistake another program on port 8000 for it
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import instance
from update_fixtures import free_port

SERVE = ("import sys; sys.path.insert(0, {root!r}); "
         "from core.server import start_gallery_server; "
         "r = start_gallery_server({out!r}, port={port}, idle_timeout=0); "
         "print('RESULT', 'started' if r is not None else 'deferred', flush=True)")


class TestSingleInstance(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wa_test_instance_"))
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.wait(5)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def start(self, out, port):
        p = subprocess.Popen([sys.executable, "-c", SERVE.format(root=str(ROOT), out=str(out), port=port)],
                             cwd=str(self.tmp), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.procs.append(p)
        return p

    def health(self, port, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as r:
                    return json.loads(r.read())
            except Exception:
                time.sleep(0.2)
        self.fail(f"no server on port {port}")

    def test_01_health_identifies_the_app(self):
        out = self.tmp / "out"
        port = free_port()
        self.start(out, port)
        data = self.health(port)
        self.assertEqual(data["app"], instance.APP_MARKER)
        self.assertTrue(data["instance"])
        lock = json.loads((out / instance.LOCK_NAME).read_text())
        self.assertEqual((lock["port"], lock["instance"]), (port, data["instance"]))

    def test_02_second_launch_on_the_same_folder_uses_the_running_server(self):
        out = self.tmp / "out"
        first_port = free_port()
        first = self.start(out, first_port)
        first_id = self.health(first_port)["instance"]
        second = self.start(out, free_port())
        stdout, _ = second.communicate(timeout=30)
        self.assertIn("already running", stdout)
        self.assertIn("RESULT deferred", stdout)
        self.assertIsNone(first.poll(), "the first server keeps running")
        self.assertEqual(self.health(first_port)["instance"], first_id)

    def test_03_a_different_folder_gets_its_own_server(self):
        p1, p2 = free_port(), free_port()
        self.start(self.tmp / "out1", p1)
        self.start(self.tmp / "out2", p2)
        self.assertNotEqual(self.health(p1)["instance"], self.health(p2)["instance"])

    def test_04_stale_claims_are_ignored(self):
        out = self.tmp / "out"
        out.mkdir()
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        (out / instance.LOCK_NAME).write_text(json.dumps(
            {"app": instance.APP_MARKER, "instance": "old", "pid": dead.pid, "port": free_port()}))
        self.assertIsNone(instance.find_running_instance(out), "crashed server")

        other_program = free_port()  # a live pid, but the port does not answer as this app
        (out / instance.LOCK_NAME).write_text(json.dumps(
            {"app": instance.APP_MARKER, "instance": "x", "pid": os.getpid(), "port": other_program}))
        with unittest.mock.patch.object(instance, "_CLAIM_WAIT_SECS", 0.3):
            self.assertIsNone(instance.find_running_instance(out))

        port = free_port()
        self.start(out, port)
        self.health(port)
        self.assertEqual(json.loads((out / instance.LOCK_NAME).read_text())["port"], port,
                         "a new server takes over a stale claim")

    def test_05_claim_is_released_on_clean_shutdown(self):
        out = self.tmp / "out"
        out.mkdir()
        instance.claim(out, 1234, "127.0.0.1")
        self.assertTrue((out / instance.LOCK_NAME).exists())
        instance.release(out)
        self.assertFalse((out / instance.LOCK_NAME).exists())
        # never removes someone else's claim
        (out / instance.LOCK_NAME).write_text(json.dumps({"instance": "someone-else"}))
        instance.release(out)
        self.assertTrue((out / instance.LOCK_NAME).exists())

    def test_06_loser_of_a_simultaneous_start_steps_aside(self):
        out = self.tmp / "out"
        port = free_port()
        self.start(out, port)
        winner = self.health(port)["instance"]
        # This process "also started" and claimed first, but the running server overwrote it
        self.assertEqual(instance.lost_claim(out)["instance"], winner)


if __name__ == "__main__":
    unittest.main()
