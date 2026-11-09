"""
A simulated Android phone for sync tests: a folder tree standing in for the phone's storage and an
`adb` executable that runs the app's real shell commands (sh, find, stat, readlink, tar) against it.

Paths the app sends (/storage, /sdcard, /data/local/tmp) are rewritten into the folder and written
back in what the phone prints, so the app sees ordinary phone paths. Linux only (GNU find and tar).

    phone = FakePhone(tmp_dir)
    phone.add("/storage/emulated/0/WhatsApp/Media/WhatsApp Images/IMG-1.jpg", b"...", mtime=...)
    adb = phone.adb_path  # give this to find_adb_binary
"""

import os
import shutil
import sys
from pathlib import Path

SERIAL = "FAKE0001"

_ADB = r'''#!{python}
import os, re, shutil, subprocess, sys

ROOT = {root!r}
BIN = {bin!r}
LOG = {log!r}
SKIP_FILE = {skip!r}
UNPLUG_FILE = {unplug!r}
SLOW_FILE = {slow!r}
_PHONE_PATH = re.compile(r"(?<![\w./-])(/storage|/sdcard|/data/local/tmp)")


def to_host(text):
    return _PHONE_PATH.sub(lambda m: ROOT + m.group(1), text)


def to_phone(text):
    return text.replace(ROOT, "")


def run_sh(script, binary=False, stdin_text=None):
    env = dict(os.environ, PATH=BIN + ":" + os.environ.get("PATH", ""))
    if binary:
        proc = subprocess.run(["sh", "-c", script], env=env, stdout=subprocess.PIPE)
        sys.stdout.buffer.write(proc.stdout)
        return proc.returncode
    proc = subprocess.run(["sh", "-c", script] if stdin_text is None else ["sh"], input=stdin_text,
                          env=env, capture_output=True, text=True, errors="replace")
    sys.stdout.write(to_phone(proc.stdout))
    sys.stderr.write(to_phone(proc.stderr))
    return proc.returncode


def run_interactive_sh():
    """Like adb shell sh: each line is passed on as it arrives, each output line as it is printed."""
    import threading
    env = dict(os.environ, PATH=BIN + ":" + os.environ.get("PATH", ""))
    proc = subprocess.Popen(["sh"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env)

    slow = float(open(SLOW_FILE).read().strip() or 0) if SLOW_FILE and os.path.exists(SLOW_FILE) else 0.0
    unplug_after = None
    if UNPLUG_FILE and os.path.exists(UNPLUG_FILE):
        unplug_after = int(open(UNPLUG_FILE).read().strip() or 0)

    def feed():
        try:
            for n, raw in enumerate(iter(sys.stdin.buffer.readline, b"")):
                if unplug_after is not None and n >= unplug_after:
                    # The cable is pulled: the session ends without answering
                    proc.kill()
                    os._exit(1)
                if slow:
                    import time
                    time.sleep(slow)  # a slow phone: each command line takes this long
                proc.stdin.write(to_host(raw.decode("utf-8", "replace")).encode("utf-8"))
                proc.stdin.flush()
        except OSError:
            pass
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass

    threading.Thread(target=feed, daemon=True).start()
    for raw in iter(proc.stdout.readline, b""):
        sys.stdout.write(to_phone(raw.decode("utf-8", "replace")))
        sys.stdout.flush()
    sys.stderr.write(to_phone(proc.stderr.read().decode("utf-8", "replace")))
    return proc.wait()


def main(argv):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(" ".join(argv) + "\n")
    while argv and argv[0] in ("-s", "-t", "-H", "-P"):
        argv = argv[2:]
    if not argv:
        return 1
    verb, rest = argv[0], argv[1:]
    if verb == "devices":
        print("List of devices attached")
        print("{serial}\tdevice usb:1-1 product:fake model:Fake_Phone device:fake transport_id:1")
        return 0
    if verb == "get-state":
        print("device")
        return 0
    if verb == "get-serialno":
        print("{serial}")
        return 0
    if verb in ("start-server", "kill-server", "reconnect", "wait-for-device", "reverse", "forward"):
        return 0
    if verb == "push":
        dst = to_host(rest[1])
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(rest[0], dst)
        if dst.endswith(".txt"):  # a file list: its phone paths, like the app's commands, are rewritten
            with open(dst, encoding="utf-8") as f:
                text = to_host(f.read())
            with open(dst, "w", encoding="utf-8") as f:
                f.write(text)
        if dst.endswith(".txt"):
            with open(LOG, "a", encoding="utf-8") as f:
                f.write("LIST " + to_phone(open(dst, encoding="utf-8").read()).replace("\n", "\t") + "\n")
        if SKIP_FILE and os.path.exists(SKIP_FILE):
            # Simulates a file the phone fails to send (unreadable, removed mid-sync)
            skip = open(SKIP_FILE, encoding="utf-8").read().strip()
            lines = open(dst, encoding="utf-8").read().splitlines()
            with open(dst, "w", encoding="utf-8") as f:
                f.write("".join(l + "\n" for l in lines if not l.endswith(skip)))
        return 0
    if verb == "pull":
        src = to_host(rest[0])
        if not os.path.exists(src):
            sys.stderr.write("adb: error: remote object does not exist\n")
            return 1
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(rest[1], os.path.basename(src)), dirs_exist_ok=True)
        else:
            shutil.copyfile(src, rest[1] if not os.path.isdir(rest[1]) else os.path.join(rest[1], os.path.basename(src)))
        return 0
    if verb == "shell" and (not rest or rest == ["sh"]):
        return run_interactive_sh()
    if verb in ("shell", "exec-out"):
        script = to_host(" ".join(rest))
        if verb == "exec-out" and re.match(r"\s*tar\b", script):
            # The phone's tar names absolute members without their leading "/": the same here
            prefix = ROOT.lstrip("/")
            script = re.sub(r"^\s*tar\b", "tar --transform 's|^%s||' " % prefix.replace("|", "\\|"), script, count=1)
            return run_sh(script, binary=True)
        return run_sh(script, binary=(verb == "exec-out"))
    sys.stderr.write("fake adb: unsupported command: " + " ".join(argv) + "\n")
    return 1


sys.exit(main(sys.argv[1:]))
'''

# Phone programs the app calls that a PC does not have: answer like a phone with nothing to say
_STUBS = {
    "getprop": 'case "$1" in ro.product.model) echo Fake_Phone;; ro.product.manufacturer) echo Google;; '
               'ro.build.version.release) echo 14;; ro.build.version.sdk) echo 34;; *) echo;; esac',
    "dumpsys": "exit 0",
    "content": "exit 0",
    "settings": "echo 1",
    "am": "exit 0",
    "pm": "exit 0",
    "cmd": "exit 0",
    "service": "exit 0",
    "input": "exit 0",
}


class FakePhone:
    def __init__(self, base_dir):
        base = Path(base_dir)
        self.root = base / "phone"
        (self.root / "storage" / "emulated" / "0").mkdir(parents=True, exist_ok=True)
        (self.root / "data" / "local" / "tmp").mkdir(parents=True, exist_ok=True)
        os.symlink(self.root / "storage" / "emulated" / "0", self.root / "sdcard")
        bin_dir = base / "phone_bin"
        bin_dir.mkdir(exist_ok=True)
        for name, body in _STUBS.items():
            p = bin_dir / name
            p.write_text(f"#!/bin/sh\n{body}\n")
            p.chmod(0o755)
        self.log = base / "adb_calls.log"
        self.skip_file = base / "skip_in_transfer.txt"
        self.unplug_file = base / "unplug_after_lines.txt"
        self.slow_file = base / "seconds_per_shell_line.txt"
        self.adb_path = str(base / "adb")
        Path(self.adb_path).write_text(_ADB.format(
            python=sys.executable, root=str(self.root), bin=str(bin_dir), log=str(self.log),
            skip=str(self.skip_file), unplug=str(self.unplug_file), slow=str(self.slow_file), serial=SERIAL,
        ))
        os.chmod(self.adb_path, 0o755)

    def host(self, phone_path):
        return self.root / phone_path.lstrip("/")

    def add(self, phone_path, data, mtime=None):
        p = self.host(phone_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        if mtime:
            os.utime(p, (mtime, mtime))
        return p

    def fail_transfer_of(self, filename):
        """The next transfers leave this file out, as a phone that cannot read it would."""
        self.skip_file.write_text(filename, encoding="utf-8")

    def slow_shell(self, seconds_per_line):
        """Each line sent to a shell session takes this long, like a slow phone (for watching progress)."""
        self.slow_file.write_text(str(seconds_per_line))

    def unplug_after(self, lines):
        """The next shell session (adb shell sh) ends, as if unplugged, after this many input lines."""
        self.unplug_file.write_text(str(lines))

    def transfer_lists(self):
        """Each file list sent to the phone for a transfer, as a list of its phone paths."""
        return [[p for p in line[5:].split("\t") if p] for line in self.calls() if line.startswith("LIST ")]

    def calls(self):
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []


def supported():
    if not sys.platform.startswith("linux") or not shutil.which("sh") or not shutil.which("tar"):
        return False
    import subprocess
    out = subprocess.run(["tar", "--version"], capture_output=True, text=True).stdout
    return "GNU tar" in out


__all__ = ["FakePhone", "SERIAL", "supported"]
