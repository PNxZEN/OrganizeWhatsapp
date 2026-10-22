"""
WhatsApp Media Organizer - Multi-threaded Local HTTP Server and Video Streaming API.
Provides HTTP 206 Partial Content Range streaming, on-the-fly transcoding, and control REST APIs.
"""

import json
import os
import platform
import re
import shutil
import socket
import socketserver
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Optional

from core.adb import (
    batch_delete_phone_files,
    broadcast_media_scan,
    check_adb_device,
    detect_device_oem,
    disable_developer_options,
    discover_whatsapp_accounts,
    find_adb_binary,
    get_device_storage_info,
    open_url_on_phone,
    restore_chat_to_phone,
    setup_reverse_port,
    wait_for_adb_device,
)
from core.clean_planner import (
    CleanProfile,
    discard_plan,
    execute_clean_plan,
    generate_clean_plan,
    get_active_plan,
)
from core.config import find_ffmpeg_binary, is_ffmpeg_available, load_config, mask_key, save_config
from core.decrypt import create_key_file, validate_hex_key
from core.gallery import (
    delete_media_permanently,
    empty_recycle_bin,
    list_recycled_items,
    purge_recycled_items,
    recycle_media_items,
    restore_media_items,
)

_latest_received_key: Optional[str] = None
_active_backup_cancel = threading.Event()
_active_restore_cancel = threading.Event()
_active_clean_cancel = threading.Event()


def is_subpath(child: Path, parent: Path) -> bool:
    """Safely verifies child path is strictly inside parent directory (prevents path traversal)."""
    try:
        c_res = Path(child).resolve()
        p_res = Path(parent).resolve()
        try:
            return c_res.is_relative_to(p_res)
        except AttributeError:
            return os.path.commonpath([str(c_res), str(p_res)]) == str(p_res)
    except Exception:
        return False


PASTE_KEY_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>WhatsApp 64-Digit Key Transfer</title>
    <style>
        :root {
            --bg: #0b141a;
            --surface: #111b21;
            --surface-card: #182229;
            --accent: #00a884;
            --accent-hover: #02906f;
            --text-primary: #e9edef;
            --text-secondary: #8696a0;
            --danger: #ef4444;
            --border: rgba(134, 150, 160, 0.15);
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background: var(--bg);
            color: var(--text-primary);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 24px 16px;
        }
        .container {
            width: 100%;
            max-width: 440px;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 20px;
            padding: 28px 20px;
            box-shadow: 0 12px 32px rgba(0,0,0,0.4);
            text-align: center;
        }
        .shield-icon {
            width: 56px;
            height: 56px;
            fill: var(--accent);
            margin: 0 auto 16px;
            display: block;
        }
        h1 { font-size: 1.25rem; font-weight: 600; margin-bottom: 8px; }
        .subtitle { font-size: 0.88rem; color: var(--text-secondary); line-height: 1.45; margin-bottom: 24px; }
        .usb-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: rgba(0, 168, 132, 0.12);
            border: 1px solid rgba(0, 168, 132, 0.3);
            color: var(--accent);
            font-size: 0.75rem;
            font-weight: 600;
            padding: 4px 12px;
            border-radius: 12px;
            margin-bottom: 20px;
        }
        .btn-paste {
            width: 100%;
            background: var(--accent);
            color: #0b141a;
            border: none;
            border-radius: 14px;
            padding: 16px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            transition: background 0.15s, transform 0.1s;
        }
        .btn-paste:active { background: var(--accent-hover); transform: scale(0.98); }
        .divider {
            display: flex;
            align-items: center;
            margin: 20px 0;
            color: var(--text-secondary);
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .divider::before, .divider::after {
            content: "";
            flex: 1;
            height: 1px;
            background: var(--border);
        }
        .divider span { padding: 0 10px; }
        textarea {
            width: 100%;
            background: var(--surface-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            color: var(--text-primary);
            padding: 12px;
            font-family: monospace;
            font-size: 0.85rem;
            line-height: 1.4;
            height: 72px;
            resize: none;
            outline: none;
            margin-bottom: 12px;
        }
        textarea:focus { border-color: var(--accent); }
        .btn-submit {
            width: 100%;
            background: transparent;
            border: 1px solid var(--accent);
            color: var(--accent);
            border-radius: 12px;
            padding: 12px;
            font-size: 0.92rem;
            font-weight: 600;
            cursor: pointer;
        }
        .btn-submit:active { background: rgba(0,168,132,0.1); }
        .status-msg {
            margin-top: 16px;
            font-size: 0.85rem;
            padding: 10px;
            border-radius: 8px;
            display: none;
            line-height: 1.4;
        }
        .status-msg.error {
            display: block;
            background: rgba(239, 68, 68, 0.12);
            color: var(--danger);
            border: 1px solid rgba(239, 68, 68, 0.25);
        }
        .status-msg.success {
            display: block;
            background: rgba(0, 168, 132, 0.12);
            color: var(--accent);
            border: 1px solid rgba(0, 168, 132, 0.25);
        }
        .char-counter {
            font-size: 0.75rem;
            color: var(--text-secondary);
            text-align: right;
            margin-top: -6px;
            margin-bottom: 10px;
        }
        .btn-resend {
            width: 100%;
            background: rgba(0, 168, 132, 0.15);
            border: 1px solid var(--accent);
            color: var(--accent);
            border-radius: 14px;
            padding: 14px;
            font-size: 0.95rem;
            font-weight: 600;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            margin-top: 16px;
            transition: all 0.2s;
        }
        .btn-resend:active { background: rgba(0, 168, 132, 0.28); }
        .success-card {
            background: rgba(0, 168, 132, 0.08);
            border: 1px solid rgba(0, 168, 132, 0.3);
            border-radius: 16px;
            padding: 20px 16px;
            margin-bottom: 16px;
        }
    </style>
</head>
<body>
    <div class="container">
        <svg class="shield-icon" viewBox="0 0 24 24"><path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm-2 16l-4-4 1.41-1.41L10 14.17l6.59-6.59L18 9l-8 8z"/></svg>
        <div class="usb-badge">Direct USB Transfer (100% Offline)</div>

        <!-- SUCCESS SECTION: Shown when key is received or already present -->
        <div id="successSection" style="display:none;">
            <div class="success-card">
                <div style="width:52px;height:52px;border-radius:50%;background:rgba(0,168,132,0.18);border:2px solid var(--accent);display:flex;align-items:center;justify-content:center;margin:0 auto 14px;">
                    <svg style="width:28px;height:28px;fill:var(--accent);" viewBox="0 0 24 24"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
                </div>
                <h1 id="successTitle" style="color:var(--accent);font-size:1.15rem;">Key Received on PC!</h1>
                <p class="subtitle" id="successSubtitle" style="margin-bottom:0;font-size:0.85rem;">
                    Your 64-digit WhatsApp key has been received and safely encrypted on your PC.
                </p>
                <button type="button" class="btn-submit" onclick="tryCloseTab()" style="margin-top:14px;width:100%;font-size:0.88rem;padding:10px;">
                    Close Tab
                </button>
            </div>
            <button class="btn-resend" id="btnResend" onclick="enableResendMode()">
                <svg style="width:16px;height:16px;fill:currentColor;" viewBox="0 0 24 24"><path d="M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg>
                <span id="btnResendText">Resend or Update Key</span>
            </button>
        </div>

        <!-- INPUT SECTION: Shown when entering key or resending -->
        <div id="inputSection">
            <div id="disconnectBanner" class="status-msg error" style="display:none;margin-bottom:14px;text-align:left;">
                USB connection interrupted. Reconnecting automatically when the cable is plugged back in...
            </div>

            <h1 id="inputTitle">Send 64-Digit Key to PC</h1>
            <p class="subtitle" id="inputSubtitle">Tap the button below to paste your copied 64-digit key directly into your PC via the USB cable.</p>

            <button class="btn-paste" id="btnPaste" onclick="handlePasteFromClipboard()" style="box-shadow:0 4px 18px rgba(0,168,132,0.35);">
                <svg style="width:20px;height:20px;fill:currentColor;" viewBox="0 0 24 24"><path d="M19 2h-4.18C14.4 0.84 13.3 0 12 0c-1.3 0-2.4 0.84-2.82 2H5c-1.1 0-2 0.9-2 2v16c0 1.1 0.9 2 2 2h14c1.1 0 2-0.9 2-2V4c0-1.1-0.9-2-2-2zm-7 0c0.55 0 1 0.45 1 1s-0.45 1-1 1-1-0.45-1-1 0.45-1 1-1zm7 18H5V4h2v3h10V4h2v16z"/></svg>
                <span id="btnPasteText">Paste &amp; Send to PC</span>
            </button>
            <div style="font-size:0.75rem;color:var(--text-secondary);margin-top:8px;margin-bottom:4px;">Reads key directly from your phone clipboard</div>

            <div class="divider"><span>Or paste into box below</span></div>

            <textarea id="keyInput" placeholder="Long-press here to paste..." spellcheck="false" oninput="onKeyChange()"></textarea>
            <div class="char-counter" id="charCounter">0 / 64 hex characters (auto-sends on paste)</div>
            <button class="btn-submit" id="btnSubmit" onclick="submitCurrentKey()">
                <span id="btnSubmitText">Send Key to PC</span>
            </button>
        </div>

        <div id="statusMsg" class="status-msg"></div>
    </div>

    <script>
        let isResendMode = false;
        let isSubmitting = false;
        let autoCloseTimer = null;

        window.addEventListener('DOMContentLoaded', () => {
            checkInitialStatus();
            const inputEl = document.getElementById('keyInput');
            if (inputEl) {
                inputEl.addEventListener('paste', () => setTimeout(onKeyChange, 40));
            }
            startHeartbeat();
        });

        function startHeartbeat() {
            setInterval(async () => {
                const inputSec = document.getElementById('inputSection');
                if (inputSec && inputSec.style.display !== 'none') {
                    try {
                        const controller = new AbortController();
                        const to = setTimeout(() => controller.abort(), 2000);
                        const r = await fetch('/api/key-status', { signal: controller.signal });
                        clearTimeout(to);
                        const banner = document.getElementById('disconnectBanner');
                        if (banner) {
                            if (r.ok) {
                                banner.style.display = 'none';
                            } else {
                                banner.style.display = 'block';
                            }
                        }
                    } catch (e) {
                        const banner = document.getElementById('disconnectBanner');
                        if (banner) banner.style.display = 'block';
                    }
                }
            }, 2500);
        }

        async function checkInitialStatus() {
            try {
                const resp = await fetch('/api/key-status');
                if (resp.ok) {
                    const data = await resp.json();
                    if (data.hex_key_set) {
                        showSuccessCard('Key Already Configured on PC!', 'A 64-digit WhatsApp key is already configured on your PC. You can resend or update it if needed.');
                    }
                }
            } catch (e) {}
        }

        function showSuccessCard(title, subtitle) {
            document.getElementById('inputSection').style.display = 'none';
            document.getElementById('successSection').style.display = 'block';
            if (title) document.getElementById('successTitle').innerText = title;
            if (subtitle) document.getElementById('successSubtitle').innerText = subtitle;
            const statusEl = document.getElementById('statusMsg');
            statusEl.className = 'status-msg';
            statusEl.style.display = 'none';
            isSubmitting = false;
        }

        function tryCloseTab() {
            try {
                window.open('', '_self', '');
                window.close();
            } catch (e) {}
        }

        function startAutoCloseCountdown() {
            let seconds = 5;
            const subtitleEl = document.getElementById('successSubtitle');
            if (autoCloseTimer) clearInterval(autoCloseTimer);
            autoCloseTimer = setInterval(() => {
                if (seconds > 0) {
                    if (subtitleEl) {
                        subtitleEl.innerHTML = 'Your 64-digit WhatsApp key was securely saved on your PC.<br><span style="display:inline-block;margin-top:8px;font-size:0.8rem;color:var(--text-secondary);">This tab will close automatically in <strong>' + seconds + 's</strong>.</span>';
                    }
                    seconds--;
                } else {
                    clearInterval(autoCloseTimer);
                    autoCloseTimer = null;
                    tryCloseTab();
                }
            }, 1000);
        }

        function enableResendMode() {
            if (autoCloseTimer) {
                clearInterval(autoCloseTimer);
                autoCloseTimer = null;
            }
            isResendMode = true;
            isSubmitting = false;
            document.getElementById('successSection').style.display = 'none';
            document.getElementById('inputSection').style.display = 'block';
            document.getElementById('inputTitle').innerText = 'Resend Key to PC';
            document.getElementById('inputSubtitle').innerText = 'Paste your 64-digit key below to update the key stored on your PC.';
            document.getElementById('btnPasteText').innerText = 'Paste &amp; Resend';
            document.getElementById('btnSubmitText').innerText = 'Resend Key to PC';
            document.getElementById('btnPaste').disabled = false;
            document.getElementById('btnPaste').style.opacity = '1';
            document.getElementById('btnSubmit').disabled = false;
            const statusEl = document.getElementById('statusMsg');
            statusEl.className = 'status-msg';
            statusEl.style.display = 'none';
        }

        function cleanHex(raw) {
            if (!raw) return "";
            return raw.replace(/[^0-9a-fA-F]/g, "").toLowerCase();
        }

        function onKeyChange() {
            const raw = document.getElementById('keyInput').value;
            const val = cleanHex(raw);
            const counter = document.getElementById('charCounter');
            counter.textContent = val.length + ' / 64 hex characters' + (val.length === 64 ? ' (Ready!)' : '');
            if (val.length === 64) {
                counter.style.color = 'var(--accent)';
                if (!isSubmitting) {
                    submitCurrentKey();
                }
            } else {
                counter.style.color = 'var(--text-secondary)';
            }
        }

        async function handlePasteFromClipboard() {
            const statusEl = document.getElementById('statusMsg');
            statusEl.className = 'status-msg';
            try {
                let text = "";
                if (navigator.clipboard && navigator.clipboard.readText) {
                    text = await navigator.clipboard.readText();
                }
                if (!text) {
                    statusEl.className = 'status-msg error';
                    statusEl.style.display = 'block';
                    statusEl.textContent = 'Clipboard permission denied or empty. Please long-press in the box below to paste.';
                    return;
                }
                const cleaned = cleanHex(text);
                if (cleaned.length !== 64) {
                    document.getElementById('keyInput').value = text;
                    onKeyChange();
                    statusEl.className = 'status-msg error';
                    statusEl.style.display = 'block';
                    statusEl.textContent = 'Found ' + cleaned.length + ' hex characters. A valid WhatsApp key must be exactly 64 hex characters.';
                    return;
                }
                document.getElementById('keyInput').value = cleaned;
                onKeyChange();
            } catch (err) {
                statusEl.className = 'status-msg error';
                statusEl.style.display = 'block';
                statusEl.textContent = 'Could not access clipboard directly: ' + err.message + '. Please long-press in the box below to paste.';
            }
        }

        async function submitCurrentKey() {
            if (isSubmitting) return;
            const raw = document.getElementById('keyInput').value;
            const cleaned = cleanHex(raw);
            const statusEl = document.getElementById('statusMsg');
            if (cleaned.length !== 64) {
                statusEl.className = 'status-msg error';
                statusEl.style.display = 'block';
                statusEl.textContent = 'Please enter exactly 64 hex characters (currently ' + cleaned.length + ').';
                return;
            }
            isSubmitting = true;
            await sendKeyToBackend(cleaned);
        }

        async function sendKeyToBackend(hexKey) {
            const statusEl = document.getElementById('statusMsg');
            statusEl.className = 'status-msg';
            statusEl.style.display = 'block';
            statusEl.textContent = 'Sending key over USB...';

            try {
                const resp = await fetch('/api/submit-key', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ hex_key: hexKey, auto_save: true })
                });
                const res = await resp.json();
                if (resp.ok && res.status === 'success') {
                    showSuccessCard(
                        isResendMode ? 'Key Resent to PC!' : 'Key Received on PC!',
                        'Your 64-digit WhatsApp key was securely saved on your PC.'
                    );
                    startAutoCloseCountdown();
                } else {
                    statusEl.className = 'status-msg error';
                    statusEl.textContent = res.message || 'Error saving key on PC.';
                }
            } catch (err) {
                statusEl.className = 'status-msg error';
                statusEl.textContent = 'Connection error: ' + err.message + '. Ensure the USB cable remains connected.';
            } finally {
                isSubmitting = false;
            }
        }
    </script>
</body>
</html>
"""
from core.gallery import (
    GALLERY_ASSETS_DIRNAME,
    GALLERY_HTML_NAME,
    get_chat_media,
    get_chats_summary,
    install_gallery_frontend,
    is_subpath,
    resolve_frontend_root,
    update_gallery_data_js,
    update_media_index_csv,
)

from core.device_inventory import DeviceInventory
from core.wa_guide import AdbPhone, WaGuide

# Shared USB connection + WhatsApp account inventory. The lambdas resolve this module's names at
# call time so the ADB functions stay patchable from tests.
_device_inventory = DeviceInventory(
    check_fn=lambda: check_adb_device(),
    discover_fn=lambda **kwargs: discover_whatsapp_accounts(**kwargs),
)

# Guided WhatsApp backup setup (reads the phone's screen, can tap for the user; see core/wa_guide.py)
_wa_guide_output_dir: Dict[str, Optional[str]] = {"path": None}


def _wa_guide_phone():
    snap = _device_inventory.snapshot()
    if not (snap["connected"] and snap["authorized"] and snap["serial"]):
        raise RuntimeError("the phone is not connected, or USB debugging is not allowed")
    return AdbPhone(find_adb_binary(), snap["serial"])


def _wa_guide_save_key(hex_key: str) -> bool:
    """Saves a key read off the phone's screen, like a key sent from the phone's paste page."""
    ok, _ = validate_hex_key(hex_key)
    if not ok:
        return False
    cfg = load_config()
    cfg["hex_key"] = hex_key
    save_config(cfg)
    if _wa_guide_output_dir["path"]:
        try:
            create_key_file(hex_key, Path(_wa_guide_output_dir["path"]).resolve() / "encrypted_backup.key")
        except Exception:
            pass
    return True


_wa_guide = WaGuide(_wa_guide_phone, _wa_guide_save_key)

# Output dirs whose gallery frontend copy was refreshed recently (avoids re-scanning assets on every request)
_frontend_install_checked: Dict[str, float] = {}
_FRONTEND_INSTALL_RECHECK_SECS = 5.0


def _ensure_frontend_installed(output_dir: Path) -> None:
    key = str(output_dir)
    now = time.time()
    if now - _frontend_install_checked.get(key, 0.0) < _FRONTEND_INSTALL_RECHECK_SECS:
        return
    _frontend_install_checked[key] = now
    install_gallery_frontend(output_dir)
from core.organizer import zip_chat, zip_file_list
from core.thumbnail import get_or_create_thumbnail
from core.sync_session import SyncSessionManager
from core.migrator import (
    IMPORT_MODE_COPY,
    IMPORT_MODE_MOVE,
    PICK_SELECTED,
    PICK_UNAVAILABLE,
    analyze_import_folder,
    extract_key_from_folder,
    pick_folder,
    pick_folder_dialog,
    validate_paths,
)
from core.import_job import ImportJobManager
from core.activity import MaintenanceActive, activity
from core.updater import UpdateError, UpdateManager, app_root as _app_root, env_overrides as _updater_env_overrides
from core.update_helper import recover_interrupted_update
from core.version import GITHUB_REPO, __version__
from core import instance as _instance
from core.reveal import reveal_in_file_manager

# Background "Import Older Media" job (one at a time; polled by the gallery for progress)
_import_job = ImportJobManager()
_IMPORT_BUSY_MESSAGE = "An import of older media is running. Please wait for it to finish before syncing."
import uuid

_session_manager = SyncSessionManager()
_sync_cancellation_token = threading.Event()
_sync_skip_db_token = threading.Event()

# Browser tab lifecycle tracking for graceful auto-shutdown
_active_tabs: Dict[str, float] = {}
_tab_lock = threading.Lock()
_tab_shutdown_timer: Optional[threading.Timer] = None
_has_had_browser_tab = False


_last_tab_seen = {"at": 0.0}
# Bumped whenever the library or settings change outside a sync (recycle, restore, import,
# settings). Every tab sees it in its heartbeat and refreshes, so open tabs never show stale media.
_library_version = {"n": 0}


def _bump_library_version():
    _library_version["n"] += 1

_TAB_CLOSE_GRACE_SECS = 3.5
_SHUTDOWN_RETRY_SECS = 5.0
_IDLE_WATCH_INTERVAL_SECS = 30.0
_shutdown_wait_notice = {"text": ""}


def _auto_shutdown_blockers():
    """
    Work that must finish before the app may close by itself. A phone sync is not listed: it is
    paused safely and resumes next time. Imports, ZIP backups, phone cleanups and restores
    cannot be resumed half-way, so the app waits for them.
    """
    busy = set(activity.running())
    if _import_job.is_running():
        busy.add("import of older media")
    return sorted(busy)


def _schedule_auto_shutdown(server, reason, delay):
    global _tab_shutdown_timer
    if _tab_shutdown_timer and _tab_shutdown_timer.is_alive():
        _tab_shutdown_timer.cancel()
    _tab_shutdown_timer = threading.Timer(delay, _try_auto_shutdown, args=[server, reason])
    _tab_shutdown_timer.daemon = True
    _tab_shutdown_timer.start()


def _try_auto_shutdown(server, reason):
    """Closes the app when no tab is open and nothing unresumable is running; otherwise waits."""
    if float(_server_runtime.get("idle_timeout") or 0) <= 0:
        return  # automatic shutdown is disabled (--idle-timeout 0, e.g. live mode)
    with _tab_lock:
        now = time.time()
        if any((now - ts) < 25.0 for ts in _active_tabs.values()):
            return  # a tab came back (reload, new tab)
    blockers = _auto_shutdown_blockers()
    if blockers:
        text = ", ".join(blockers)
        if _shutdown_wait_notice["text"] != text:
            _shutdown_wait_notice["text"] = text
            print(f"\n[Server] {reason}. Waiting for {text} to finish before closing...")
        _schedule_auto_shutdown(server, reason, _SHUTDOWN_RETRY_SECS)
        return
    _shutdown_wait_notice["text"] = ""
    print(f"\n[Server] {reason}. Performing clean shutdown...")
    _perform_clean_shutdown(server, reason=reason)


def _idle_watchdog(server):
    """
    Covers tabs that vanish without saying goodbye (browser crash, laptop sleep, killed browser):
    after idle_timeout minutes without any heartbeat, the app closes the same safe way.
    """
    while True:
        time.sleep(_IDLE_WATCH_INTERVAL_SECS)
        minutes = float(_server_runtime.get("idle_timeout") or 0)
        if minutes <= 0 or not _has_had_browser_tab:
            continue
        if time.time() - _last_tab_seen["at"] >= minutes * 60:
            _try_auto_shutdown(server, f"No open browser tab for {minutes:g} minutes")
            return


def _perform_clean_shutdown(server=None, reason="Server shutdown"):
    global sync_status
    if sync_status.get("active"):
        _sync_cancellation_token.set()
        sess_id = sync_status.get("session_id")
        if sess_id:
            try:
                _session_manager.pause_session(sess_id, reason)
            except Exception:
                pass
        sync_status["status"] = "paused"
        sync_status["phase"] = "paused"
        sync_status["active"] = False
    if server:
        try:
            threading.Timer(0.5, server.shutdown).start()
        except Exception:
            pass


def check_has_local_db(output_dir=None, db_dir=None):
    """Checks if a previously pulled or existing WhatsApp database exists locally."""
    dirs_to_check = []
    if db_dir:
        dirs_to_check.append(Path(db_dir))
    dirs_to_check.append(Path("./Databases"))
    if output_dir:
        dirs_to_check.append(Path(output_dir) / "Databases")

    valid_exts = (".crypt15", ".crypt14", ".crypt12", ".crypt8", ".crypt")
    for d in dirs_to_check:
        try:
            if d.is_dir():
                for f in d.iterdir():
                    if f.is_file() and f.stat().st_size > 0:
                        if f.name == "msgstore.db" or (
                            f.name.startswith("msgstore") and any(f.name.endswith(ext) for ext in valid_exts)
                        ):
                            return True
        except Exception:
            pass
    return False

# Global sync status tracking dictionary
sync_status = {
    "active": False,
    "version": 1,
    "phase": "idle",
    "phase_label": "Ready",
    "status": "idle",
    "session_id": None,
    "device_serial": None,
    "device_model": None,
    "total_files": 0,
    "synced_files": 0,
    "total_bytes": 0,
    "synced_bytes": 0,
    "progress_percent": 0,
    "current_file": None,
    "error": None,
    "can_resume": False,
}


def _updater_busy_probe():
    """What currently prevents an update from being installed (besides tracked short operations)."""
    busy = []
    if sync_status.get("active"):
        busy.append("phone sync")
    if _import_job.is_running():
        busy.append("import of older media")
    return busy


_update_manager = UpdateManager(busy_probe=_updater_busy_probe, **_updater_env_overrides())
# Options of the running server, so an update can restart it the same way
_server_runtime = {"output_dir": "./output", "port": 8000, "idle_timeout": 0, "allow_lan": False}
_UPDATING_MESSAGE = "The app is installing an update. Please wait a moment."


_AUTO_CHECK_INTERVAL_SECS = 24 * 3600


def _auto_update_check_enabled() -> bool:
    return bool(load_config().get("auto_check_updates", False))


def _auto_update_check_due() -> bool:
    """True only when the user opted in to automatic checks AND the last check is over a day old."""
    cfg = load_config()
    if not cfg.get("auto_check_updates", False):
        return False
    try:
        last = float(cfg.get("last_update_check") or 0)
    except (TypeError, ValueError):
        last = 0.0
    return time.time() - last >= _AUTO_CHECK_INTERVAL_SECS


def _is_updating() -> bool:
    return activity.maintenance_message() is not None

# Restore any paused session on server startup
def _restore_paused_session():
    try:
        cfg = load_config()
        out_dir = cfg.get("output_dir", "./output")
        target_db = Path(out_dir) / ".sync_state.sqlite3"
        _session_manager.set_db_path(str(target_db))
        _session_manager.recover_abandoned_sessions()
        paused = _session_manager.get_latest_paused_session()
        if paused:
            sync_status["status"] = "paused"
            sync_status["phase"] = "paused"
            sync_status["session_id"] = paused["session_id"]
            sync_status["device_serial"] = paused["device_serial"]
            sync_status["device_model"] = paused["device_model"]
            sync_status["total_files"] = paused["total_files"]
            sync_status["synced_files"] = paused["synced_files"]
            sync_status["total_bytes"] = paused["total_bytes"]
            sync_status["synced_bytes"] = paused["synced_bytes"]
            pct = round((paused["synced_files"] / max(1, paused["total_files"])) * 100, 1) if paused["total_files"] > 0 else 0
            sync_status["progress_percent"] = pct
            sync_status["phase_label"] = f"Paused ({pct}% - {paused['synced_files']}/{paused['total_files']} files)"
            sync_status["can_resume"] = True
    except Exception:
        pass

_restore_paused_session()


_active_runtime_sessions = set()


def _start_background_sync(output_dir, resume_session_id=None, skip_db_pull=None):
    """Launches the organization pipeline in a separate background thread with session tracking and pause/resume."""
    global sync_status
    target_db = Path(output_dir) / ".sync_state.sqlite3"
    _session_manager.set_db_path(str(target_db))
    _sync_cancellation_token.clear()
    _sync_skip_db_token.clear()
    sync_status["active"] = True
    sync_status["user_action"] = None
    sync_status["status"] = "syncing"
    sync_status["error"] = None
    sync_status["can_resume"] = False
    sync_status["interrupted_by_device"] = False
    sync_status["phase"] = "database"
    sync_status["phase_label"] = "Connecting to phone over ADB..."
    sync_status["phase_detail"] = "Checking USB connection and scanning WhatsApp accounts"

    session_id = resume_session_id
    is_same_runtime_session = (session_id in _active_runtime_sessions) if session_id else False
    if not session_id:
        session_id = str(uuid.uuid4())
        dev = check_adb_device()
        serial = dev.device_serial or "unknown"
        model = dev.model or "Android Device"
        _session_manager.create_session(
            session_id=session_id,
            device_serial=serial,
            device_model=model,
        )
        sync_status["session_id"] = session_id
        sync_status["device_serial"] = serial
        sync_status["device_model"] = model
    else:
        sync_status["session_id"] = session_id
        sess = _session_manager.get_session(session_id)
        if sess:
            sync_status["total_files"] = sess.get("total_files", 0)
            sync_status["synced_files"] = sess.get("synced_files", 0)
            sync_status["device_serial"] = sess.get("device_serial")
            sync_status["device_model"] = sess.get("device_model")

    _active_runtime_sessions.add(session_id)

    def _worker():
        global sync_status
        sess = _session_manager.get_session(session_id)
        if sess:
            sync_status["total_files"] = sess.get("total_files", sync_status.get("total_files", 0))
            sync_status["synced_files"] = sess.get("synced_files", sync_status.get("synced_files", 0))
            sync_status["device_serial"] = sess.get("device_serial")
            sync_status["device_model"] = sess.get("device_model")

        sync_status["phase_label"] = "Scanning WhatsApp on phone..."
        sync_status["phase_detail"] = "Probing storage directories and account paths over ADB"

        def _on_status(phase, label, total_files=None, detail=None):
            sync_status["phase"] = phase
            sync_status["phase_label"] = label
            if detail is not None:
                sync_status["phase_detail"] = detail
            elif phase in ("indexing", "decrypting", "building_gallery", "database"):
                sync_status["phase_detail"] = label
            if phase in ("indexing", "decrypting", "building_gallery"):
                sync_status["current_file"] = None
            if phase == "database":
                sync_status["progress_percent"] = 0
            elif total_files is not None and total_files > 0:
                sync_status["total_files"] = total_files
                tot = total_files
                synced = sync_status.get("synced_files", 0)
                sync_status["progress_percent"] = min(100.0, round((synced / tot) * 100, 1))

        def _on_progress(filename, file_size):
            sync_status["current_file"] = filename
            is_db_file = (sync_status.get("phase") == "database" or filename.startswith("Databases/") or "/Databases/" in filename)
            if is_db_file:
                sync_status["phase"] = "database"
                sync_status["phase_label"] = f"Transferring chat database ({os.path.basename(filename)})"
            else:
                sync_status["synced_files"] = sync_status.get("synced_files", 0) + 1
                sync_status["synced_bytes"] = sync_status.get("synced_bytes", 0) + file_size
                tot = max(1, sync_status.get("total_files", 1))
                sync_status["progress_percent"] = min(100.0, round((sync_status["synced_files"] / tot) * 100, 1))
                sync_status["phase"] = "syncing"
                sync_status["phase_label"] = f"Transferring media ({sync_status['synced_files']:,} / {tot:,} files)"
                if sync_status["synced_files"] % 50 == 0:
                    sync_status["version"] = sync_status.get("version", 1) + 1

        def _on_in_flight(filename, total_bytes, written_bytes):
            mb_written = round(written_bytes / (1024 * 1024), 1)
            mb_tot = round(total_bytes / (1024 * 1024), 1)
            pct = round((written_bytes / max(1, total_bytes)) * 100, 1)
            fn_base = os.path.basename(filename)
            sync_status["current_file"] = f"{fn_base} ({mb_written} MB / {mb_tot} MB - {pct}%)"
            if sync_status.get("phase") == "database" or filename.startswith("Databases/"):
                sync_status["phase"] = "database"
                sync_status["phase_label"] = f"Transferring chat database ({mb_written} MB / {mb_tot} MB)"
            else:
                sync_status["phase"] = "syncing"
                sync_status["phase_label"] = f"Transferring {fn_base} ({mb_written} MB / {mb_tot} MB)"

        try:
            from core.pipeline import run_streaming_pipeline

            cfg = load_config()
            effective_skip_db = cfg.get("skip_db_pull", False) if skip_db_pull is None else bool(skip_db_pull)

            success = run_streaming_pipeline(
                hex_key=cfg.get("hex_key"),
                key_file=cfg.get("key_file", "encrypted_backup.key"),
                db_dir=cfg.get("db_dir", "./Databases"),
                media_dir=cfg.get("media_dir", "./output"),
                output_dir=output_dir,
                mode=cfg.get("mode", "copy"),
                skip_db_pull=effective_skip_db,
                is_same_session_resume=is_same_runtime_session,
                session_manager=_session_manager,
                session_id=session_id,
                cancellation_token=_sync_cancellation_token,
                skip_db_token=_sync_skip_db_token,
                progress_callback=_on_progress,
                status_callback=_on_status,
                in_flight_callback=_on_in_flight,
            )
            if sync_status.get("user_action") == "cancel":
                _active_runtime_sessions.discard(session_id)
                _session_manager.cancel_session(session_id)
                sync_status["status"] = "idle"
                sync_status["phase"] = "idle"
                sync_status["can_resume"] = False
                sync_status["interrupted_by_device"] = False
                sync_status["phase_label"] = "Ready"
                sync_status["current_file"] = None
            elif _sync_cancellation_token.is_set() or sync_status.get("user_action") == "pause":
                _session_manager.pause_session(session_id, "User requested pause")
                sync_status["status"] = "paused"
                sync_status["phase"] = "paused"
                sync_status["can_resume"] = True
                sync_status["interrupted_by_device"] = False
                pct = sync_status.get("progress_percent", 0)
                sync_status["phase_label"] = f"Paused ({pct}% completed - ready to resume)"
            elif success:
                _active_runtime_sessions.discard(session_id)
                _session_manager.complete_session(session_id)
                sync_status["status"] = "done"
                sync_status["phase"] = "done"
                sync_status["phase_label"] = "Synchronization complete"
                sync_status["phase_detail"] = "All databases decrypted and media files organized"
                sync_status["progress_percent"] = 100
                sync_status["can_resume"] = False
                sync_status["has_completed_sync"] = True
                sync_status["interrupted_by_device"] = False
                sync_status["version"] = sync_status.get("version", 0) + 1
                try:
                    c = load_config()
                    c["last_sync_time"] = time.time()
                    save_config(c)
                except Exception:
                    pass

                # Auto-transition from transient done state to idle after 10 seconds
                def _reset_done_to_idle():
                    if not sync_status.get("active") and sync_status.get("status") == "done":
                        sync_status["status"] = "idle"
                        sync_status["phase"] = "idle"
                        sync_status["phase_label"] = "Ready"

                threading.Timer(10.0, _reset_done_to_idle).start()
            else:
                if sync_status.get("user_action") == "cancel":
                    _active_runtime_sessions.discard(session_id)
                    _session_manager.cancel_session(session_id)
                    sync_status["status"] = "idle"
                    sync_status["phase"] = "idle"
                    sync_status["can_resume"] = False
                    sync_status["interrupted_by_device"] = False
                    sync_status["phase_label"] = "Ready"
                else:
                    _session_manager.pause_session(session_id, "Sync stopped or interrupted")
                    sync_status["status"] = "paused"
                    sync_status["phase"] = "paused"
                    sync_status["can_resume"] = True
                    sync_status["error"] = sync_status.get("error") or "Sync stopped before completion"
                    dev = check_adb_device()
                    if not dev.connected or not dev.authorized:
                        sync_status["interrupted_by_device"] = True
                        sync_status["phase_label"] = "Sync interrupted (Phone disconnected). Waiting for phone reconnection to resume automatically..."
                    else:
                        sync_status["interrupted_by_device"] = False
                        sync_status["phase"] = "error"
                        sync_status["phase_label"] = "Sync failed. Progress is saved - fix the issue and resume."
        except Exception as e:
            if sync_status.get("user_action") == "cancel":
                _active_runtime_sessions.discard(session_id)
                sync_status["status"] = "idle"
                sync_status["phase"] = "idle"
                sync_status["can_resume"] = False
                sync_status["interrupted_by_device"] = False
                sync_status["phase_label"] = "Ready"
            else:
                _session_manager.pause_session(session_id, str(e))
                sync_status["status"] = "paused"
                sync_status["phase"] = "error"
                sync_status["error"] = str(e)
                sync_status["can_resume"] = True
                dev = check_adb_device()
                if not dev.connected or not dev.authorized:
                    sync_status["interrupted_by_device"] = True
                    sync_status["phase_label"] = "Sync interrupted (Phone disconnected). Waiting for phone reconnection to resume automatically..."
                else:
                    sync_status["interrupted_by_device"] = False
                    sync_status["phase_label"] = "Sync interrupted"
        finally:
            sync_status["active"] = False

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


def find_open_port(preferred_port=8000, max_attempts=10, host="127.0.0.1"):
    """
    Finds an available TCP port starting from preferred_port.
    Prevents WinError 10048 startup crashes.
    """
    for p in range(preferred_port, preferred_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if os.name != "nt":
                # Connections of a server that just exited linger in TIME_WAIT; the real listener
                # (HTTPServer) reuses the port, so the probe must too or a restart lands on port+1.
                # (Not on Windows, where SO_REUSEADDR would let a second server share a live port.)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, p))
                return p
            except OSError:
                continue
    return preferred_port


def purge_all_backup_keys(output_dir=None, key_file=None):
    """
    Deletes all encrypted_backup.key files across workspace and output folders,
    guaranteeing no trace of the key remains on disk.
    """
    targets = [
        "encrypted_backup.key",
        "Backups/encrypted_backup.key",
        "Backups/temp/encrypted_backup.key",
        "Databases/encrypted_backup.key",
    ]
    if key_file:
        targets.append(str(key_file))
    if output_dir:
        out_p = Path(output_dir)
        targets.extend([
            str(out_p / "encrypted_backup.key"),
            str(out_p / "Backups" / "encrypted_backup.key"),
            str(out_p / "Backups" / "temp" / "encrypted_backup.key"),
            str(out_p / "Databases" / "encrypted_backup.key"),
        ])
    for t in targets:
        try:
            p = Path(t)
            if p.is_file():
                p.unlink(missing_ok=True)
        except Exception:
            pass

    # Targeted search in Backups, Databases, and output
    for sub in [Path("./Backups"), Path("./Databases")]:
        if sub.is_dir():
            try:
                for k in sub.rglob("encrypted_backup.key"):
                    try:
                        if k.is_file():
                            k.unlink(missing_ok=True)
                    except Exception:
                        pass
            except Exception:
                pass


class GalleryHTTPRequestHandler(SimpleHTTPRequestHandler):
    """
    Multi-threaded HTTP request handler serving static files, RFC 7233 video streaming,
    and zero-terminal control REST APIs.
    """

    # Explicit types: on Windows, mimetypes reads the registry and may map .js/.css to text/plain,
    # which makes browsers refuse the gallery stylesheets.
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".html": "text/html; charset=utf-8",
        ".json": "application/json",
        ".svg": "image/svg+xml",
        ".webp": "image/webp",
        ".woff2": "font/woff2",
    }

    def __init__(self, *args, directory=None, **kwargs):
        self.output_dir = Path(directory).resolve() if directory else Path(".").resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        _ensure_frontend_installed(self.output_dir)
        super().__init__(*args, directory=str(self.output_dir), **kwargs)

    def translate_path(self, path):
        clean_path = urllib.parse.unquote(path.split("?", 1)[0].split("#", 1)[0])
        frontend_root = resolve_frontend_root()
        if clean_path in ("/" + GALLERY_HTML_NAME, "/"):
            root_gallery = frontend_root / GALLERY_HTML_NAME
            if root_gallery.is_file():
                return str(root_gallery)
        # Serve gallery CSS/JS modules straight from the application so they always match gallery.html
        assets_prefix = "/" + GALLERY_ASSETS_DIRNAME + "/"
        if clean_path.startswith(assets_prefix):
            assets_root = frontend_root / GALLERY_ASSETS_DIRNAME
            candidate = assets_root / clean_path[len(assets_prefix):]
            if candidate.is_file() and is_subpath(candidate, assets_root):
                return str(candidate.resolve())
        return super().translate_path(path)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "X-Requested-With, Content-Type, Range")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format_str, *args):
        # Suppress logging for ping/health/sync-status polling to keep logs clean
        if len(args) > 0 and isinstance(args[0], str):
            first_arg = args[0]
            if any(
                endpoint in first_arg
                for endpoint in (
                    "/api/ping",
                    "/api/health",
                    "/api/sync-status",
                    "/api/device-status",
                    "/api/phone/status",
                    "/api/heartbeat",
                    "/api/tab-closed",
                    "/api/import/status",
                    "/api/wa-guide/status",
                    "/api/update/status",
                )
            ):
                return
        if sys.stdout is not None:
            try:
                sys.stdout.write(f"[Server] {format_str % args}\n")
                sys.stdout.flush()
            except Exception:
                pass

    def _send_json(self, status_code, data):
        """Sends a JSON response with proper Content-Length and caching headers."""
        body = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

    def _read_json_body(self):
        """Safely parses JSON request body."""
        try:
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len <= 0:
                return {}
            body_bytes = self.rfile.read(content_len)
            return json.loads(body_bytes.decode("utf-8"))
        except Exception:
            return None

    def handle_range_request(self, filepath, range_header):
        """Handles HTTP 206 Partial Content requests for smooth browser video seeking."""
        match = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if not match:
            self.send_error(400, "Bad Request (Invalid Range header)")
            return

        file_size = os.path.getsize(filepath)
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else file_size - 1

        if start >= file_size or end >= file_size or start > end:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{file_size}")
            self.end_headers()
            return

        chunk_size = end - start + 1
        content_type = self.guess_type(filepath)

        self.send_response(206)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.send_header("Content-Length", str(chunk_size))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        try:
            with open(filepath, "rb") as f:
                f.seek(start)
                remaining = chunk_size
                buffer_size = 64 * 1024
                while remaining > 0:
                    to_read = min(buffer_size, remaining)
                    data = f.read(to_read)
                    if not data:
                        break
                    self.wfile.write(data)
                    remaining -= len(data)
        except Exception:
            pass

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        # /favicon.ico (prevent browser 404 logs)
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        # /api/health or /api/ping
        if path in ("/api/health", "/api/ping"):
            # "app" and "instance" let launchers check it is really this app answering
            self._send_json(200, {"status": "ok", "app": _instance.APP_MARKER, "version": __version__,
                                  "instance": _instance.INSTANCE_ID})
            return

        # /api/version (what is installed, how it was installed, and the outcome of the last update)
        if path == "/api/version":
            self._send_json(200, {
                "version": __version__,
                "repo": GITHUB_REPO,
                "install": _update_manager.install_info(),
                "auto_check_updates": _auto_update_check_enabled(),
                "auto_check_due": _auto_update_check_due(),
                "last_update": _update_manager.consume_last_result() if "consume" in urllib.parse.parse_qs(parsed_url.query) else None,
            })
            return

        # /api/update/status (progress of a download/installation; polled by the UI)
        if path == "/api/update/status":
            self._send_json(200, _update_manager.status())
            return

        # /api/sync-status
        if path == "/api/sync-status":
            sess_id = sync_status.get("session_id")
            if sess_id:
                sess = _session_manager.get_session(sess_id)
                if sess:
                    tf = sess.get("total_files", 0)
                    sf = sess.get("synced_files", 0)
                    tb = sess.get("total_bytes", 0)
                    sb = sess.get("synced_bytes", 0)
                    if tf > 0:
                        sync_status["total_files"] = tf
                    if sf > sync_status.get("synced_files", 0):
                        sync_status["synced_files"] = sf
                    if tb > 0:
                        sync_status["total_bytes"] = tb
                    if sb > sync_status.get("synced_bytes", 0):
                        sync_status["synced_bytes"] = sb
                    if sync_status.get("total_files", 0) > 0:
                        pct = min(100.0, round((sync_status["synced_files"] / sync_status["total_files"]) * 100, 1))
                        sync_status["progress_percent"] = pct
            resp_data = dict(sync_status)
            cfg = load_config()
            has_db = check_has_local_db(str(self.output_dir))
            resp_data["has_local_db"] = has_db
            resp_data["has_completed_sync"] = bool(
                sync_status.get("has_completed_sync", False)
                or cfg.get("last_sync_time")
            )
            self._send_json(200, resp_data)
            return

        # /api/device-status or /api/phone/status
        # Never blocks on the account scan unless asked: ?refresh=1 forces a rescan,
        # ?wait=<seconds> (max 30) waits for an in-flight scan to finish.
        if path in ("/api/device-status", "/api/phone/status"):
            query = urllib.parse.parse_qs(parsed_url.query)
            refresh = query.get("refresh", ["0"])[0] in ("1", "true")
            try:
                wait_secs = min(30.0, max(0.0, float(query.get("wait", ["0"])[0])))
            except ValueError:
                wait_secs = 0.0
            snap = _device_inventory.snapshot(refresh=refresh, wait_timeout=wait_secs)
            accounts = snap["accounts"]

            cfg = load_config()
            selected_path = cfg.get("selected_account_path", "")
            selected_acc = None
            if accounts:
                if selected_path:
                    for acc in accounts:
                        if acc["path"] == selected_path:
                            selected_acc = acc
                            break
                if not selected_acc:
                    selected_acc = accounts[0]

            self._send_json(
                200,
                {
                    "connected": snap["connected"],
                    "authorized": snap["authorized"],
                    "usb_debugging": snap["usb_debugging"],
                    "stage": snap["stage"],
                    "stage_seconds": snap["stage_seconds"],
                    "vendor": snap["vendor"],
                    "serial": snap["serial"],
                    "model": snap["model"],
                    "error": snap["error"],
                    "accounts": accounts,
                    "accounts_scan": snap["accounts_scan"],
                    "selected_account": selected_acc,
                    "selected_account_path": selected_path,
                    "has_selected_account": bool(selected_path and any(acc["path"] == selected_path for acc in accounts)),
                    "has_multiple_accounts": len(accounts) > 1,
                },
            )
            return

        # /api/import/status (progress of the background "Import Older Media" job)
        if path == "/api/import/status":
            self._send_json(200, _import_job.status())
            return

        # /api/config
        if path == "/api/config":
            cfg = load_config()
            hex_key = cfg.get("hex_key", "")
            self._send_json(
                200,
                {
                    "hex_key_set": bool(hex_key),
                    "masked_key": mask_key(hex_key) if hex_key else "",
                    "port": cfg.get("port", 8000),
                    "mode": cfg.get("mode", "copy"),
                    "output_dir": cfg.get("output_dir", "./output"),
                    "has_local_db": check_has_local_db(str(self.output_dir), cfg.get("db_dir")),
                    "onboarding_completed": cfg.get("onboarding_completed", False),
                    "selected_account_path": cfg.get("selected_account_path", ""),
                    "selected_account_id": cfg.get("selected_account_id", ""),
                    "selected_account_phone": cfg.get("selected_account_phone", ""),
                    "selected_app_type": cfg.get("selected_app_type", ""),
                    "selected_account_label": cfg.get("selected_account_label", ""),
                    # Shared by every tab and browser (None until first chosen)
                    "duplicate_detection": cfg.get("duplicate_detection"),
                },
            )
            return

        # /api/phone/oem (detect connected phone brand/OEM)
        if path == "/api/phone/oem":
            oem_info = detect_device_oem()
            self._send_json(200, oem_info)
            return

        # /api/phone/storage (queries live free and total storage on phone)
        if path == "/api/phone/storage":
            storage = get_device_storage_info()
            resp = dict(storage)
            resp["status"] = "success" if storage.get("success") else "error"
            resp["connected"] = storage.get("connected", storage.get("success", False))
            resp["authorized"] = storage.get("authorized", storage.get("success", False))
            resp["storage"] = storage
            self._send_json(200, resp)
            return

        # /api/wa-guide/status (guided WhatsApp backup setup: current phone screen and next step)
        if path == "/api/wa-guide/status":
            self._send_json(200, _wa_guide.status())
            return

        # /api/key-status (status of 64-digit key and received key from mobile)
        if path == "/api/key-status":
            cfg = load_config()
            dev_res = check_adb_device()
            self._send_json(
                200,
                {
                    "hex_key_set": bool(cfg.get("hex_key")),
                    "latest_received_key": _latest_received_key,
                    "received_key": _latest_received_key,
                    "onboarding_completed": cfg.get("onboarding_completed", False),
                    "device_connected": bool(dev_res.connected),
                    "device_authorized": bool(dev_res.authorized),
                },
            )
            return

        # /paste-key (Mobile USB reverse tethered page)
        if path == "/paste-key":
            content = PASTE_KEY_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(content)
            return

        # /assets/tutorial/ (Serve tutorial WebP slides)
        if path.startswith("/assets/tutorial/"):
            filename = os.path.basename(path)
            asset_path = Path(__file__).parent / "assets" / "tutorial" / filename
            if not asset_path.is_file():
                asset_path = self.output_dir / "assets" / "tutorial" / filename
            if asset_path.is_file():
                try:
                    with open(asset_path, "rb") as f:
                        data = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/webp")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.end_headers()
                    self.wfile.write(data)
                    return
                except Exception as e:
                    self._send_json(500, {"error": f"Failed to serve asset: {e}"})
                    return
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Asset not found")
                return

        # /api/chats (lightweight chat summary list: ~70KB instead of 28.4MB)
        if path == "/api/chats":
            summary = get_chats_summary(self.output_dir)
            self._send_json(200, {"chats": summary})
            return

        # /api/chats/<jid>/media (on-demand media for a single chat with pagination)
        chat_media_match = re.match(r"^/api/chats/([^/]+)/media$", path)
        if chat_media_match:
            jid = urllib.parse.unquote(chat_media_match.group(1))
            query = urllib.parse.parse_qs(parsed_url.query)
            offset = int(query.get("offset", [0])[0])
            limit = int(query["limit"][0]) if "limit" in query else None

            res = get_chat_media(self.output_dir, jid, offset=offset, limit=limit)
            if res is None:
                self._send_json(404, {"error": f"Chat with JID '{jid}' not found"})
            else:
                self._send_json(200, res)
            return

        # /api/download-backup (serves generated ZIP archives directly to browser)
        if path == "/api/download-backup":
            query = urllib.parse.parse_qs(parsed_url.query)
            filename = query.get("file", [None])[0]
            if not filename:
                self._send_json(400, {"error": "Missing file parameter"})
                return

            backups_dir = (self.output_dir / "backups").resolve()
            safe_name = os.path.basename(filename)
            target_path = (backups_dir / safe_name).resolve()

            # Prevent directory traversal attacks
            if not is_subpath(target_path, backups_dir) or not target_path.is_file():
                self._send_json(404, {"error": "Backup file not found"})
                return

            try:
                file_size = target_path.stat().st_size
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                ascii_fallback = re.sub(r"[^\x20-\x7E]", "_", safe_name).replace('"', '')
                encoded_name = urllib.parse.quote(safe_name, encoding="utf-8")
                self.send_header(
                    "Content-Disposition",
                    f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded_name}',
                )
                self.send_header("Content-Length", str(file_size))
                self.end_headers()

                with open(target_path, "rb") as f:
                    shutil.copyfileobj(f, self.wfile, length=64 * 1024)
            except Exception as e:
                sys.stderr.write(f"[Server] Error streaming backup {ascii_fallback}: {e}\n")
            return

        # /api/thumbnail?path=<rel_path> (on-demand image and video thumbnail generation)
        if path == "/api/thumbnail":
            query = urllib.parse.parse_qs(parsed_url.query)
            rel_path = query.get("path", [None])[0]
            if not rel_path:
                self._send_json(400, {"error": "Missing path parameter"})
                return

            try:
                thumb_path = get_or_create_thumbnail(self.output_dir, rel_path)
            except Exception as e:
                self._send_json(404, {"error": f"Thumbnail generation failed: {e}"})
                return

            if not thumb_path or not thumb_path.is_file():
                is_video = rel_path.lower().endswith((".mp4", ".3gp", ".mov", ".m4v", ".avi", ".mkv"))
                if is_video and not is_ffmpeg_available():
                    self._send_json(404, {"error": "ffmpeg_not_available"})
                else:
                    self._send_json(404, {"error": "Thumbnail not found or could not be generated"})
                return

            try:
                with open(thumb_path, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "public, max-age=31536000, immutable")
                self.end_headers()
                self.wfile.write(content)
            except Exception as e:
                self._send_json(500, {"error": f"Failed to serve thumbnail: {e}"})
            return

        # /api/media?path=<rel_path> (serves high-res original media with RFC 7233 Range support)
        if path == "/api/media":
            query = urllib.parse.parse_qs(parsed_url.query)
            rel_path = query.get("path", [None])[0]
            if not rel_path:
                self._send_json(400, {"error": "Missing path parameter"})
                return

            clean_rel = rel_path.lstrip("/\\").replace("\\", "/")
            target_path = (self.output_dir / clean_rel).resolve()
            base_dir = self.output_dir.resolve()
            if not (is_subpath(target_path, base_dir) and target_path.is_file()):
                # Also check workspace root if server is run from workspace root
                ws_root = Path(__file__).resolve().parent.parent
                alt_path = (ws_root / clean_rel).resolve()
                if is_subpath(alt_path, ws_root) and alt_path.is_file():
                    target_path = alt_path
                else:
                    self._send_json(404, {"error": "Media file not found"})
                    return

            content_type = self.guess_type(str(target_path))
            range_header = self.headers.get("Range")
            if range_header:
                self.handle_range_request(str(target_path), range_header)
                return

            try:
                file_size = target_path.stat().st_size
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(file_size))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Cache-Control", "public, max-age=31536000, immutable")
                self.end_headers()
                with open(target_path, "rb") as f:
                    shutil.copyfileobj(f, self.wfile, length=64 * 1024)
            except Exception as e:
                pass
            return

        # /api/duplicates/recycle-bin
        if path == "/api/duplicates/recycle-bin":
            items = list_recycled_items(str(self.output_dir))
            total_bytes = sum(int(it.get("size_bytes", 0)) for it in items)
            self._send_json(
                200,
                {
                    "status": "success",
                    "success": True,
                    "count": len(items),
                    "total_bytes": total_bytes,
                    "items": items,
                },
            )
            return

        # /api/open-folder
        if path == "/api/open-folder":
            query = urllib.parse.parse_qs(parsed_url.query)
            rel_path = query.get("rel_path", [None])[0]
            if not rel_path:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Missing rel_path")
                return

            clean_rel = rel_path.lstrip("/\\")
            target_path = (self.output_dir / clean_rel).resolve()
            base_dir = self.output_dir.resolve()
            if not is_subpath(target_path, base_dir):
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b"Access denied")
                return

            if target_path.exists():
                try:
                    reveal_in_file_manager(target_path)
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"OK")
                except Exception as e:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(str(e).encode("utf-8"))
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"File not found")
            return

        # /api/transcode
        if path == "/api/transcode":
            query = urllib.parse.parse_qs(parsed_url.query)
            rel_path = query.get("rel_path", [None])[0]
            if not rel_path:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Missing rel_path")
                return

            actual_path = (self.output_dir / rel_path).resolve()
            if not actual_path.is_file():
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"File not found")
                return

            chat_name = actual_path.parent.parent.name
            date_folder = actual_path.parent.name
            dest_filename = actual_path.name

            cache_dir = self.output_dir / ".cache" / chat_name / date_folder
            cache_dir.mkdir(parents=True, exist_ok=True)
            preview_file = cache_dir / (dest_filename + "_preview.mp4")

            success = True
            thumb_path_rel = None

            if not preview_file.is_file() or preview_file.stat().st_size == 0:
                try:
                    cmd = [
                        find_ffmpeg_binary(),
                        "-y",
                        "-i",
                        str(actual_path),
                        "-c:v",
                        "libx264",
                        "-crf",
                        "30",
                        "-preset",
                        "fast",
                        "-c:a",
                        "aac",
                        "-b:a",
                        "96k",
                        str(preview_file),
                    ]
                    subprocess.run(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=True,
                    )
                except Exception as e:
                    sys.stderr.write(
                        f"[Server] Warning: Failed to transcode video {dest_filename}: {e}\n"
                    )
                    success = False

            if success:
                thumb_dir = self.output_dir / ".thumbnails" / chat_name / date_folder
                thumb_file = thumb_dir / (dest_filename + ".jpg")
                if not thumb_file.is_file() or thumb_file.stat().st_size == 0:
                    try:
                        thumb_dir.mkdir(parents=True, exist_ok=True)
                        cmd_thumb = [
                            find_ffmpeg_binary(),
                            "-y",
                            "-ss",
                            "00:00:00.500",
                            "-i",
                            str(actual_path),
                            "-frames:v",
                            "1",
                            "-q:v",
                            "4",
                            str(thumb_file),
                        ]
                        subprocess.run(
                            cmd_thumb,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            check=False,
                        )
                    except Exception:
                        pass

                if thumb_file.is_file() and thumb_file.stat().st_size > 0:
                    thumb_path_rel = f".thumbnails/{chat_name}/{date_folder}/{dest_filename}.jpg"

            if success and preview_file.is_file() and preview_file.stat().st_size > 0:
                preview_path_rel = f".cache/{chat_name}/{date_folder}/{dest_filename}_preview.mp4"
                update_gallery_data_js(
                    str(self.output_dir), rel_path, preview_path_rel, thumb_path=thumb_path_rel
                )
                update_media_index_csv(
                    str(self.output_dir), rel_path, preview_path_rel, thumb_path=thumb_path_rel
                )

                self._send_json(200, {"status": "success", "preview_path": preview_path_rel})
            else:
                self._send_json(500, {"status": "error", "message": "Transcode failed"})
            return

        # Check for Range header on media files
        range_header = self.headers.get("Range")
        local_path = self.translate_path(self.path)
        if os.path.isfile(local_path) and range_header:
            self.handle_range_request(local_path, range_header)
            return
        try:
            super().do_GET()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

    def copyfile(self, source, outputfile):
        """Copies file to client socket while gracefully absorbing client socket aborts."""
        try:
            super().copyfile(source, outputfile)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

    def do_POST(self):
        global _latest_received_key
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        # /api/duplicates/recycle (safely moves duplicates to local recycle bin)
        if path == "/api/duplicates/recycle":
            body = self._read_json_body() or {}
            rel_paths = body.get("rel_paths", [])
            if not isinstance(rel_paths, list) or not rel_paths:
                self._send_json(400, {"status": "error", "message": "rel_paths list is required"})
                return
            res = recycle_media_items(str(self.output_dir), rel_paths)
            _bump_library_version()
            self._send_json(200, res)
            return

        # /api/duplicates/restore (restores duplicates from local recycle bin)
        if path == "/api/duplicates/restore":
            body = self._read_json_body() or {}
            rel_paths = body.get("rel_paths", [])
            restore_all = body.get("all", False)
            res = restore_media_items(str(self.output_dir), rel_paths, restore_all=restore_all)
            _bump_library_version()
            self._send_json(200, res)
            return

        # /api/duplicates/purge-items (permanently deletes selected Recycle Bin items)
        if path == "/api/duplicates/purge-items":
            body = self._read_json_body() or {}
            rel_paths = body.get("rel_paths", [])
            if not isinstance(rel_paths, list) or not rel_paths:
                self._send_json(400, {"status": "error", "message": "rel_paths list is required"})
                return
            res = purge_recycled_items(str(self.output_dir), rel_paths)
            _bump_library_version()
            self._send_json(200, res)
            return

        # /api/media/delete (permanently deletes gallery media, skipping the Recycle Bin)
        if path == "/api/media/delete":
            body = self._read_json_body() or {}
            rel_paths = body.get("rel_paths", [])
            if not isinstance(rel_paths, list) or not rel_paths:
                self._send_json(400, {"status": "error", "message": "rel_paths list is required"})
                return
            if sync_status.get("active") or _import_job.is_running():
                self._send_json(409, {"status": "busy", "message": "Wait for the sync or import to finish before deleting media."})
                return
            res = delete_media_permanently(str(self.output_dir), rel_paths)
            _bump_library_version()
            self._send_json(200, res)
            return

        # /api/duplicates/empty-recycle-bin (permanently purges quarantined items)
        if path in ("/api/duplicates/empty-recycle-bin", "/api/duplicates/purge"):
            res = empty_recycle_bin(str(self.output_dir))
            _bump_library_version()
            self._send_json(200, res)
            return

        # /api/import/browse (triggers native OS Explorer / Finder folder picker dialog)
        if path == "/api/import/browse":
            try:
                pick_status, selected = pick_folder()
                if pick_status == PICK_SELECTED and selected:
                    self._send_json(200, {"status": "success", "folder": selected})
                elif pick_status == PICK_UNAVAILABLE:
                    self._send_json(200, {
                        "status": "unavailable",
                        "folder": "",
                        "message": "The folder picker could not be opened on this computer. Paste the folder path into the field instead.",
                    })
                else:
                    self._send_json(200, {"status": "canceled", "folder": ""})
            except Exception as e:
                self._send_json(500, {"status": "error", "message": str(e)})
            return

        # /api/import/analyze (pre-flight checks and metrics for older output directory)
        if path == "/api/import/analyze":
            body = self._read_json_body() or {}
            source_path = body.get("source_path", "").strip()
            if not source_path:
                self._send_json(400, {"status": "error", "message": "source_path is required"})
                return
            res = analyze_import_folder(source_path, str(self.output_dir))
            if not res.get("valid"):
                self._send_json(400, {"status": "error", "message": res.get("error", "Invalid folder")})
                return
            self._send_json(200, {"status": "success", "data": res})
            return

        # /api/import/execute (runs media and database migration)
        if path == "/api/import/execute":
            body = self._read_json_body() or {}
            source_path = body.get("source_path", "").strip()
            if not source_path:
                self._send_json(400, {"status": "error", "message": "source_path is required"})
                return

            if _is_updating():
                self._send_json(409, {"status": "updating", "message": _UPDATING_MESSAGE})
                return
            mode = body.get("mode", IMPORT_MODE_COPY)
            if mode not in (IMPORT_MODE_COPY, IMPORT_MODE_MOVE):
                self._send_json(400, {"status": "error", "message": f"Unknown import mode: {mode}"})
                return
            if sync_status.get("active"):
                self._send_json(409, {"status": "busy", "message": "A phone sync is running. Import older media after it finishes."})
                return
            valid, err, src_resolved, _ = validate_paths(source_path, str(self.output_dir))
            if not valid:
                self._send_json(400, {"status": "error", "message": err})
                return
            if not ((src_resolved / "gallery_data.js").is_file() or (src_resolved / "gallery.js").is_file()):
                self._send_json(400, {
                    "status": "error",
                    "message": "The selected folder is not a valid WhatsApp Media Organizer output folder (missing gallery_data.js).",
                })
                return

            def _on_import_finished(_snapshot):
                # Bump sync version so open galleries reload the merged chats
                sync_status["version"] = sync_status.get("version", 0) + 1
                _bump_library_version()

            started = _import_job.start(
                source_path, str(self.output_dir), mode=mode,
                import_key=bool(body.get("import_key", True)), on_finished=_on_import_finished,
                replace_key=body.get("replace_key") is True,
            )
            if not started:
                self._send_json(409, {"status": "busy", "message": "An import is already running."})
                return
            self._send_json(202, {"status": "started", "job": _import_job.status()})
            return

        # /api/import/cancel (stops the running import after the current file)
        if path == "/api/import/cancel":
            if _import_job.cancel():
                self._send_json(200, {"status": "cancelling"})
            else:
                self._send_json(409, {"status": "idle", "message": "No import is running."})
            return

        # /api/key/import-previous (directly import and save WhatsApp backup key from an older version)
        if path == "/api/key/import-previous":
            body = self._read_json_body() or {}
            source_path = body.get("source_path", "").strip()

            if not source_path:
                try:
                    source_path = pick_folder_dialog()
                    if not source_path:
                        self._send_json(200, {"status": "canceled", "message": "Folder selection was canceled."})
                        return
                except Exception as e:
                    self._send_json(500, {"status": "error", "message": f"Failed to open folder picker: {e}"})
                    return

            found_key = extract_key_from_folder(source_path)
            if not found_key:
                self._send_json(200, {
                    "status": "not_found",
                    "source_path": source_path,
                    "message": "No valid WhatsApp backup key (config.json, encrypted_backup.key, or whatsapp.cryptkey) was found in the selected folder. Please ensure you selected the previous installation or output folder.",
                })
                return

            try:
                save_config({"hex_key": found_key})
                create_key_file(found_key, "encrypted_backup.key")
                self._send_json(200, {
                    "status": "success",
                    "hex_key": found_key,
                    "masked_key": mask_key(found_key),
                    "source_path": source_path,
                    "message": f"Successfully imported WhatsApp backup key from previous version ({mask_key(found_key)})!",
                })
            except Exception as e:
                self._send_json(500, {"status": "error", "message": f"Failed to save imported key: {e}"})
            return

        # /api/config (save key and configuration)
        if path == "/api/config":
            body = self._read_json_body()
            if body is None:
                self._send_json(400, {"status": "error", "message": "Invalid JSON body"})
                return

            hex_key = body.get("hex_key", "").strip()
            if hex_key:
                is_valid, err = validate_hex_key(hex_key)
                if not is_valid:
                    self._send_json(400, {"status": "error", "message": err})
                    return
                # Create encrypted_backup.key file
                try:
                    create_key_file(hex_key, "encrypted_backup.key")
                except Exception as e:
                    self._send_json(
                        500, {"status": "error", "message": f"Failed to create key file: {e}"}
                    )
                    return

            if "hex_key" in body and not hex_key:
                # Key is being cleared: clean up files and memory
                _latest_received_key = None
                cfg_curr = load_config()
                purge_all_backup_keys(output_dir=self.output_dir, key_file=cfg_curr.get("key_file"))

            config_payload = dict(body)
            config_payload.pop("skip_db_pull", None)
            save_config(config_payload)
            _bump_library_version()
            self._send_json(
                200,
                {
                    "status": "success",
                    "message": "Configuration saved successfully",
                    "masked_key": mask_key(hex_key) if hex_key else "",
                    "has_local_db": check_has_local_db(str(self.output_dir)),
                },
            )
            return

        # /api/delete-key (permanently removes backup key and deletes key files)
        if path == "/api/delete-key":
            _latest_received_key = None
            cfg = load_config()
            purge_all_backup_keys(output_dir=self.output_dir, key_file=cfg.get("key_file"))
            save_config({"hex_key": ""})
            self._send_json(
                200,
                {
                    "status": "success",
                    "message": "Key deleted successfully",
                    "masked_key": "",
                    "has_local_db": check_has_local_db(str(self.output_dir)),
                },
            )
            return

        # /api/submit-key (received from mobile /paste-key or direct transfer)
        if path == "/api/submit-key":
            body = self._read_json_body()
            if not body or "hex_key" not in body:
                self._send_json(400, {"status": "error", "message": "Missing hex_key"})
                return
            raw_key = body.get("hex_key", "").strip()
            clean_key = re.sub(r"[^0-9a-fA-F]", "", raw_key).lower()
            is_valid, err = validate_hex_key(clean_key)
            if not is_valid:
                self._send_json(400, {"status": "error", "message": err})
                return
            # Staged in memory for review and user confirmation
            _latest_received_key = clean_key
            # If auto_save requested (e.g. from mobile /paste-key or tutorial carousel), persist to config
            if body.get("auto_save", False):
                cfg = load_config()
                cfg["hex_key"] = clean_key
                save_config(cfg)
                out_p = Path(self.output_dir).resolve()
                try:
                    create_key_file(clean_key, out_p / "encrypted_backup.key")
                except Exception:
                    pass
            self._send_json(200, {"status": "success", "message": "Key transferred to PC successfully!"})
            return

        # /api/phone/clear-received-key (clears staged in-memory transferred key)
        if path == "/api/phone/clear-received-key":
            _latest_received_key = None
            self._send_json(200, {"status": "success"})
            return

        # /api/wa-guide/* (guided WhatsApp backup setup; see core/wa_guide.py)
        if path.startswith("/api/wa-guide/"):
            body = self._read_json_body() or {}
            action = path.rsplit("/", 1)[-1]
            try:
                if action == "start":
                    _wa_guide_output_dir["path"] = str(self.output_dir)
                    cfg = load_config()
                    package = "com.whatsapp.w4b" if cfg.get("selected_app_type") == "whatsapp_business" else "com.whatsapp"
                    if body.get("package") in ("com.whatsapp", "com.whatsapp.w4b"):
                        package = body["package"]
                    self._send_json(200, _wa_guide.start(body.get("mode", "auto"), package))
                elif action == "choose":
                    _wa_guide.choose(body.get("choice"))
                    self._send_json(200, _wa_guide.status())
                elif action == "mode":
                    _wa_guide.set_mode(body.get("mode", "guide"))
                    self._send_json(200, _wa_guide.status())
                elif action == "allow-low-storage":
                    _wa_guide.allow_low_storage()
                    self._send_json(200, _wa_guide.status())
                elif action == "key-provided":
                    hex_key = load_config().get("hex_key", "")
                    if not hex_key:
                        self._send_json(400, {"status": "error", "message": "No key is saved yet."})
                        return
                    _wa_guide.key_provided(mask_key(hex_key))
                    self._send_json(200, _wa_guide.status())
                elif action == "stop":
                    _wa_guide.stop()
                    self._send_json(200, _wa_guide.status())
                else:
                    self._send_json(404, {"status": "error", "message": "Unknown guide action."})
            except ValueError as e:
                self._send_json(400, {"status": "error", "message": str(e)})
            return

        # /api/phone/open-key-portal (opens http://localhost:PORT/paste-key on phone via adb reverse)
        if path == "/api/phone/open-key-portal":
            cfg = load_config()
            port = cfg.get("port", 8000)
            rev_ok, rev_msg = setup_reverse_port(port)
            if not rev_ok:
                self._send_json(400, {"status": "error", "message": rev_msg})
                return
            open_ok, open_msg = open_url_on_phone(f"http://localhost:{port}/paste-key")
            if not open_ok:
                self._send_json(400, {"status": "error", "message": open_msg})
                return
            self._send_json(200, {"status": "success", "message": "Portal opened on phone screen."})
            return

        # /api/onboarding/complete
        if path == "/api/onboarding/complete":
            save_config({"onboarding_completed": True})
            self._send_json(200, {"status": "success"})
            return

        # /api/wait-authorize (polling loop for USB debugging)
        if path == "/api/wait-authorize":
            body = self._read_json_body() or {}
            timeout = int(body.get("timeout", 30))

            ready, msg, serial, model = wait_for_adb_device(timeout=timeout)
            self._send_json(
                200,
                {
                    "ready": ready,
                    "message": msg,
                    "serial": serial,
                    "model": model,
                },
            )
            return

        # /api/disable-developer-options (turn off developer options on connected phone)
        if path == "/api/disable-developer-options":
            success, msg = disable_developer_options()
            if success:
                self._send_json(200, {"status": "success", "message": msg})
            else:
                self._send_json(500, {"status": "error", "message": msg})
            return

        # /api/sync (trigger background synchronization)
        if path == "/api/sync":
            if _is_updating():
                self._send_json(409, {"status": "updating", "message": _UPDATING_MESSAGE})
                return
            if sync_status["active"]:
                self._send_json(
                    409,
                    {"status": "busy", "message": "Synchronization is already active."},
                )
                return
            if _import_job.is_running():
                self._send_json(409, {"status": "import_running", "message": _IMPORT_BUSY_MESSAGE})
                return

            # Pre-flight Check 1: Device connected
            dev = check_adb_device()
            if not dev.connected:
                self._send_json(
                    400,
                    {
                        "status": "device_disconnected",
                        "message": "No Android phone detected. Please connect your device via USB.",
                    },
                )
                return

            # Pre-flight Check 2: Device authorized
            if not dev.authorized:
                self._send_json(
                    400,
                    {
                        "status": "device_unauthorized",
                        "message": "Phone is unauthorized. Please unlock your phone and tap 'Allow USB debugging'.",
                    },
                )
                return

            # Pre-flight Check 3: 64-character hex backup key configured
            cfg = load_config()
            key_file = cfg.get("key_file", "encrypted_backup.key")
            has_key = bool(cfg.get("hex_key")) or os.path.isfile(key_file)
            if not has_key:
                self._send_json(
                    400,
                    {
                        "status": "key_required",
                        "message": "A 64-character WhatsApp backup key is required before synchronizing. Please configure your key in Key & Settings.",
                    },
                )
                return

            body = self._read_json_body() or {}
            skip_db_pull = body.get("skip_db_pull", None)
            account_path = body.get("account_path")
            if account_path:
                phone = body.get("phone_number", "")
                acc_id = Path(account_path).name if "/accounts/" in account_path else "main"
                app_type = (
                    "whatsapp_business"
                    if ("w4b" in account_path or "WhatsApp Business" in account_path)
                    else "whatsapp"
                )
                label = f"{'WhatsApp Business' if app_type == 'whatsapp_business' else 'WhatsApp'} ({phone or acc_id})"
                save_config({
                    "selected_account_path": account_path,
                    "selected_account_id": acc_id,
                    "selected_account_phone": phone,
                    "selected_app_type": app_type,
                    "selected_account_label": label,
                })

            _start_background_sync(str(self.output_dir), skip_db_pull=skip_db_pull)
            self._send_json(
                200,
                {"status": "started", "message": "Synchronization initiated in background."},
            )
            return

        # /api/phone/select-account (save selected WhatsApp or Business account)
        if path == "/api/phone/select-account":
            body = self._read_json_body() or {}
            account_path = (body.get("account_path") or "").strip()
            if not account_path:
                self._send_json(400, {"status": "error", "message": "account_path is required"})
                return
            phone = body.get("phone_number", "")
            acc_id = Path(account_path).name if "/accounts/" in account_path else "main"
            app_type = (
                "whatsapp_business"
                if ("w4b" in account_path or "WhatsApp Business" in account_path)
                else "whatsapp"
            )
            label = f"{'WhatsApp Business' if app_type == 'whatsapp_business' else 'WhatsApp'} ({phone or acc_id})"
            save_config({
                "selected_account_path": account_path,
                "selected_account_id": acc_id,
                "selected_account_phone": phone,
                "selected_app_type": app_type,
                "selected_account_label": label,
            })
            self._send_json(200, {
                "status": "success",
                "selected_account_path": account_path,
                "selected_account_label": label,
            })
            return

        # /api/clean/plan (generates verified phone storage clean plan)
        if path == "/api/clean/plan":
            body = self._read_json_body() or {}
            profile = body.get("profile", CleanProfile.SMART_RECLAIM)
            if profile not in (CleanProfile.SMART_RECLAIM, CleanProfile.VIDEO_OFFLOAD, CleanProfile.CUSTOM):
                self._send_json(400, {"status": "error", "message": f"Invalid profile '{profile}'"})
                return
            custom_cfg = body.get("custom_config", {})
            try:
                plan = generate_clean_plan(str(self.output_dir), profile=profile, custom_config=custom_cfg)
                self._send_json(200, {"status": "success", "plan": plan})
            except Exception as e:
                self._send_json(500, {"status": "error", "message": f"Failed to generate clean plan: {e}"})
            return

        # /api/clean/execute (executes verified clean plan on phone via ADB)
        if path == "/api/clean/execute":
            body = self._read_json_body() or {}
            plan_id = body.get("plan_id")
            if not plan_id:
                self._send_json(400, {"status": "error", "message": "plan_id is required"})
                return

            plan = get_active_plan(plan_id)
            if not plan:
                self._send_json(404, {"status": "error", "message": f"Plan '{plan_id}' not found or already executed"})
                return

            dev = check_adb_device()
            if not dev.connected or not dev.authorized:
                msg = "Phone not connected: No USB device detected" if not dev.connected else "Phone is connected but unauthorized. Please allow USB debugging on your device."
                self._send_json(400, {
                    "success": False,
                    "status": "error",
                    "error": msg,
                    "message": msg,
                })
                return

            try:
                with activity.track("phone storage cleanup"):
                    _active_clean_cancel.clear()
                    res = execute_clean_plan(
                        plan_id,
                        str(self.output_dir),
                        cancel_event=_active_clean_cancel,
                        exclude_jids=body.get("exclude_jids"),
                    )
                resp = dict(res)
                resp["status"] = "success" if res.get("success") else "error"
                resp["result"] = res
                self._send_json(200, resp)
            except MaintenanceActive:
                self._send_json(409, {"success": False, "status": "updating", "error": _UPDATING_MESSAGE, "message": _UPDATING_MESSAGE})
            except Exception as e:
                self._send_json(500, {"success": False, "status": "error", "error": f"Execution failed: {e}", "message": f"Execution failed: {e}"})
            return

        # /api/clean/cancel (cancel active phone storage cleanup purge)
        if path == "/api/clean/cancel":
            _active_clean_cancel.set()
            self._send_json(200, {"status": "success", "message": "Cleanup cancellation requested."})
            return

        # /api/restore/cancel (cancel active restore push to phone)
        if path == "/api/restore/cancel":
            _active_restore_cancel.set()
            self._send_json(200, {"status": "success", "message": "Restore cancellation requested."})
            return

        # /api/restore/chat (restores chat media back to phone with storage safety check)
        if path == "/api/restore/chat":
            body = self._read_json_body() or {}
            chat_jid = body.get("chat_jid")
            if not chat_jid:
                self._send_json(400, {"status": "error", "message": "chat_jid is required"})
                return

            dev = check_adb_device()
            if not dev.connected or not dev.authorized:
                msg = "Phone not connected: No USB device detected" if not dev.connected else "Phone is connected but unauthorized. Please allow USB debugging on your device."
                self._send_json(400, {
                    "success": False,
                    "status": "error",
                    "error": msg,
                    "message": msg,
                })
                return

            try:
                with activity.track("restore to phone"):
                    _active_restore_cancel.clear()
                    res = restore_chat_to_phone(chat_jid, str(self.output_dir), cancel_event=_active_restore_cancel)
                resp = dict(res)
                resp["status"] = "success" if res.get("success") else "error"
                resp["result"] = res
                if res.get("success"):
                    self._send_json(200, resp)
                else:
                    self._send_json(400, resp)
            except MaintenanceActive:
                self._send_json(409, {"success": False, "status": "updating", "error": _UPDATING_MESSAGE, "message": _UPDATING_MESSAGE})
            except Exception as e:
                self._send_json(500, {"success": False, "status": "error", "error": f"Restore failed: {e}", "message": f"Restore failed: {e}"})
            return

        # /api/sync/skip-db or /api/skip-db (cancel Phase 1 DB pull in flight and use existing local DB)
        if path in ("/api/sync/skip-db", "/api/skip-db"):
            if sync_status.get("active") and sync_status.get("phase") == "database":
                _sync_skip_db_token.set()
                self._send_json(
                    200,
                    {
                        "status": "skipped",
                        "message": "Database download skipped, continuing with existing local database.",
                    },
                )
            else:
                self._send_json(
                    400,
                    {
                        "status": "error",
                        "message": "Database download is not currently active.",
                    },
                )
            return

        # /api/sync/pause or /api/pause-sync
        if path in ("/api/sync/pause", "/api/pause-sync"):
            if sync_status["active"]:
                sync_status["user_action"] = "pause"
                _sync_cancellation_token.set()
                sync_status["status"] = "pausing"
                sync_status["phase_label"] = "Pausing safely after current file..."
                self._send_json(200, {"status": "pausing", "message": "Pausing synchronization safely."})
            else:
                self._send_json(400, {"status": "error", "message": "No active synchronization to pause."})
            return

        # /api/sync/resume or /api/resume-sync
        if path in ("/api/sync/resume", "/api/resume-sync"):
            if _is_updating():
                self._send_json(409, {"status": "updating", "message": _UPDATING_MESSAGE})
                return
            if sync_status["active"]:
                self._send_json(409, {"status": "busy", "message": "Synchronization is already active."})
                return
            if _import_job.is_running():
                self._send_json(409, {"status": "import_running", "message": _IMPORT_BUSY_MESSAGE})
                return

            sess_id = sync_status.get("session_id")
            paused_sess = _session_manager.get_session(sess_id) if sess_id else _session_manager.get_latest_paused_session()
            if not paused_sess:
                self._send_json(400, {"status": "error", "message": "No paused session found to resume."})
                return

            dev = check_adb_device()
            if not dev.connected:
                self._send_json(400, {"status": "device_disconnected", "message": "Please connect your phone via USB first."})
                return
            if not dev.authorized:
                self._send_json(400, {"status": "device_unauthorized", "message": "Please tap 'Allow' on your phone screen to authorize."})
                return

            # Pre-flight Check: Key configured
            cfg = load_config()
            key_file = cfg.get("key_file", "encrypted_backup.key")
            has_key = bool(cfg.get("hex_key")) or os.path.isfile(key_file)
            if not has_key:
                self._send_json(
                    400,
                    {
                        "status": "key_required",
                        "message": "A 64-character WhatsApp backup key is required to decrypt databases on resume. Please configure your key in Key & Settings.",
                    },
                )
                return

            if dev.device_serial and paused_sess.get("device_serial") and dev.device_serial != paused_sess["device_serial"]:
                self._send_json(
                    400,
                    {
                        "status": "device_mismatch",
                        "message": f"Connected device ({dev.model or dev.device_serial}) does not match paused session device ({paused_sess.get('device_model') or paused_sess.get('device_serial')}).",
                    },
                )
                return

            body = self._read_json_body() or {}
            skip_db_pull = body.get("skip_db_pull", None)

            _start_background_sync(str(self.output_dir), resume_session_id=paused_sess["session_id"], skip_db_pull=skip_db_pull)
            self._send_json(200, {"status": "resumed", "message": "Resuming synchronization from checkpoint."})
            return

        # /api/sync/cancel or /api/cancel-sync
        if path in ("/api/sync/cancel", "/api/cancel-sync"):
            sync_status["user_action"] = "cancel"
            if sync_status["active"]:
                _sync_cancellation_token.set()
            sess_id = sync_status.get("session_id")
            if sess_id:
                _session_manager.cancel_session(sess_id)
            cfg = load_config()
            _session_manager.cleanup_orphaned_part_files([
                cfg.get("db_dir", "./Databases"),
                cfg.get("media_dir", "./output"),
                os.path.join(str(self.output_dir), "Databases"),
                os.path.join(str(self.output_dir), "Media"),
                "./Databases",
                "./Media",
                "./Backups",
            ])
            sync_status["active"] = False
            sync_status["status"] = "idle"
            sync_status["phase"] = "idle"
            sync_status["can_resume"] = False
            sync_status["phase_label"] = "Ready"
            sync_status["current_file"] = None
            self._send_json(200, {"status": "cancelled", "message": "Synchronization cancelled and temporary files cleaned up."})
            return

        # /api/backup-chat (in-browser ZIP creation for a chat)
        if path == "/api/backup-chat":
            body = self._read_json_body()
            if not body or not body.get("chat_name"):
                self._send_json(400, {"status": "error", "message": "Missing chat_name parameter"})
                return

            chat_name = body["chat_name"]
            try:
                with activity.track("ZIP backup"):
                    _active_backup_cancel.clear()
                    success, zip_path, count = zip_chat(chat_name, str(self.output_dir), verify=True, cancel_event=_active_backup_cancel)
            except MaintenanceActive:
                self._send_json(409, {"status": "updating", "message": _UPDATING_MESSAGE})
                return
            if success:
                fname = os.path.basename(zip_path)
                self._send_json(
                    200,
                    {
                        "status": "success",
                        "download_url": f"/api/download-backup?file={urllib.parse.quote(fname)}",
                        "file_count": count,
                        "zip_name": fname,
                    },
                )
            else:
                is_cancelled = "cancelled" in str(zip_path).lower()
                status_code = 200 if is_cancelled else 500
                self._send_json(status_code, {"status": "cancelled" if is_cancelled else "error", "message": str(zip_path)})
            return

        # /api/backup-files (in-browser ZIP creation for a list of selected files)
        if path == "/api/backup-files":
            body = self._read_json_body()
            if not body or not body.get("files"):
                self._send_json(400, {"status": "error", "message": "Missing files list"})
                return

            files = body["files"]
            try:
                with activity.track("ZIP backup"):
                    _active_backup_cancel.clear()
                    success, zip_path, count = zip_file_list(files, str(self.output_dir), verify=True, cancel_event=_active_backup_cancel)
            except MaintenanceActive:
                self._send_json(409, {"status": "updating", "message": _UPDATING_MESSAGE})
                return
            if success:
                fname = os.path.basename(zip_path)
                self._send_json(
                    200,
                    {
                        "status": "success",
                        "download_url": f"/api/download-backup?file={urllib.parse.quote(fname)}",
                        "file_count": count,
                        "zip_name": fname,
                    },
                )
            else:
                is_cancelled = "cancelled" in str(zip_path).lower()
                status_code = 200 if is_cancelled else 500
                self._send_json(status_code, {"status": "cancelled" if is_cancelled else "error", "message": str(zip_path)})
            return

        # /api/backup/cancel (cancels ongoing backup ZIP generation)
        if path in ("/api/backup/cancel", "/api/backup-cancel"):
            _active_backup_cancel.set()
            self._send_json(200, {"status": "cancelled", "message": "Backup cancellation requested"})
            return

        # /api/heartbeat (periodic client ping to track active browser tabs)
        if path == "/api/heartbeat":
            global _has_had_browser_tab, _tab_shutdown_timer
            body = self._read_json_body() or {}
            tab_id = body.get("tab_id")
            if tab_id:
                with _tab_lock:
                    _has_had_browser_tab = True
                    _active_tabs[tab_id] = time.time()
                    _last_tab_seen["at"] = _active_tabs[tab_id]
                    now = time.time()
                    stale = [t for t, ts in _active_tabs.items() if (now - ts) > 30.0]
                    for t in stale:
                        del _active_tabs[t]
                    if _tab_shutdown_timer and _tab_shutdown_timer.is_alive():
                        _tab_shutdown_timer.cancel()
                        _tab_shutdown_timer = None
            self._send_json(200, {
                "status": "ok",
                "active_tabs": len(_active_tabs),
                "version": __version__,
                "maintenance": activity.maintenance_message(),
                "data_version": _library_version["n"],
            })
            return

        # /api/tab-closed (beacon sent when a browser tab unloads/closes)
        if path == "/api/tab-closed":
            body = self._read_json_body() or {}
            tab_id = body.get("tab_id")
            with _tab_lock:
                if tab_id and tab_id in _active_tabs:
                    del _active_tabs[tab_id]
                now = time.time()
                # Prune stale tabs (> 30.0s without heartbeat)
                stale = [t for t, ts in _active_tabs.items() if (now - ts) > 30.0]
                for t in stale:
                    del _active_tabs[t]

                # If no tabs remain, shut down after a short grace period (a reload re-registers
                # the tab within it). Running work is never cut off: see _try_auto_shutdown.
                if len(_active_tabs) == 0:
                    _schedule_auto_shutdown(self.server, "All browser tabs closed", _TAB_CLOSE_GRACE_SECS)

            self._send_json(200, {"status": "tab_closed", "remaining_tabs": len(_active_tabs)})
            return

        # /api/update/check | download | apply | cancel
        if path.startswith("/api/update/"):
            body = self._read_json_body() or {}
            action = path[len("/api/update/"):]
            try:
                if action == "settings":
                    if not isinstance(body.get("auto_check"), bool):
                        self._send_json(400, {"status": "error", "message": "auto_check must be true or false"})
                        return
                    save_config({"auto_check_updates": body["auto_check"]})
                    self._send_json(200, {"status": "success", "auto_check_updates": body["auto_check"]})
                elif action == "check":
                    if body.get("auto") and not _auto_update_check_due():
                        # Privacy: the app never goes online on its own unless the user turned this on
                        self._send_json(200, {"status": "skipped"})
                        return
                    result = _update_manager.check(force=bool(body.get("force")))
                    save_config({"last_update_check": time.time()})
                    self._send_json(200, {"status": "success", **result})
                elif action == "download":
                    self._send_json(202, {"status": "started", **_update_manager.start_download()})
                elif action == "apply":
                    server = self.server
                    result = _update_manager.apply(
                        lambda: _perform_clean_shutdown(server, reason="Installing an update"),
                        port=server.server_address[1],
                        output_dir=str(self.output_dir),
                        idle_timeout=_server_runtime["idle_timeout"],
                        allow_lan=_server_runtime["allow_lan"],
                    )
                    self._send_json(202, {"status": "restarting", **result})
                elif action == "cancel":
                    self._send_json(200, {"status": "cancelled", **_update_manager.cancel()})
                else:
                    self._send_json(404, {"status": "error", "message": "Endpoint not found"})
            except UpdateError as e:
                http_status = 409 if e.code in ("busy", "not_ready") else 400 if e.code in (
                    "unsupported_install", "up_to_date", "no_package") else 502
                payload = {"status": "error", "code": e.code, "message": e.message}
                if e.code == "busy":
                    payload["busy"] = _update_manager.current_busy()
                self._send_json(http_status, payload)
            return

        # /api/shutdown (graceful server shutdown)
        if path == "/api/shutdown":
            _perform_clean_shutdown(self.server, reason="Manual exit from UI")
            self._send_json(200, {"status": "shutting_down", "message": "Server shutting down."})
            return

        self._send_json(404, {"status": "error", "message": "Endpoint not found"})


class LocalHTTPServer(ThreadingHTTPServer):
    """
    HTTPServer.server_bind looks up the computer's full DNS name (socket.getfqdn) for a value this
    app never uses. On some Macs and networks that lookup waits ~30 s for a DNS timeout, which
    delayed every start of the app; skipping it makes the server answer at once.
    """

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port


def start_gallery_server(
    output_dir,
    port=8000,
    idle_timeout=45,
    auto_open=False,
    allow_lan=False,
):
    """
    Launches a multi-threaded ThreadingHTTPServer rooted at output_dir.
    Binds to 127.0.0.1 for local security unless allow_lan is True.
    Automatically handles port conflicts and browser opening.
    """
    out_path = Path(output_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    # One server per output folder: a second launch opens the running one instead
    running = _instance.find_running_instance(out_path)
    if running:
        url = f"http://127.0.0.1:{running['port']}/gallery.html"
        print(f"[Server] The gallery for {out_path} is already running at {url}")
        if auto_open:
            import webbrowser

            webbrowser.open(url)
        return None

    # An update that was cut short (crash, power loss) is rolled back before anything is served
    try:
        if recover_interrupted_update(_app_root()):
            print("[Updater] A previous update was interrupted; the earlier version was restored.")
        _update_manager.cleanup_stale()
    except Exception as e:
        print(f"[Updater] Warning: could not check for an interrupted update: {e}")

    # Auto-synthesize gallery.html and its CSS/JS modules in output directory if missing or outdated
    install_gallery_frontend(out_path)

    # Auto-synthesize initial empty gallery_data.js if missing
    dest_data_js = out_path / "gallery_data.js"
    if not dest_data_js.is_file():
        try:
            dest_data_js.write_text(
                '// Auto-generated initial gallery dataset\nwindow.GALLERY_DATA = {"chats": [], "media": []};\n',
                encoding="utf-8",
            )
        except Exception:
            pass

    host = "0.0.0.0" if allow_lan else "127.0.0.1"
    bound_port = find_open_port(preferred_port=port, host=host)

    server_address = (host, bound_port)

    class BoundHandler(GalleryHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(out_path), **kwargs)

    httpd = LocalHTTPServer(server_address, BoundHandler)
    _server_runtime.update(output_dir=str(out_path), port=bound_port, idle_timeout=idle_timeout, allow_lan=allow_lan)
    threading.Thread(target=_idle_watchdog, args=(httpd,), daemon=True, name="idle-watchdog").start()
    _instance.claim(out_path, bound_port, host)

    def _yield_if_duplicate():
        time.sleep(1.5)
        other = _instance.lost_claim(out_path)
        if other:
            print(f"[Server] Another gallery server started for this folder at the same time; "
                  f"using it (port {other['port']}) and closing this one.")
            if auto_open:
                import webbrowser

                webbrowser.open(f"http://127.0.0.1:{other['port']}/gallery.html")
            httpd.shutdown()

    threading.Thread(target=_yield_if_duplicate, daemon=True, name="instance-check").start()

    print("\n" + "=" * 60)
    print("STARTING LOCAL GALLERY SERVER")
    print("=" * 60)
    print(f" Serving folder: {out_path}")
    print(f" Host interface: {host} ({'Localhost Only' if not allow_lan else 'LAN Accessible'})")
    print(f" Gallery URL:    http://127.0.0.1:{bound_port}/gallery.html")
    print(f" API URL:        http://127.0.0.1:{bound_port}/api/chats")
    if idle_timeout > 0:
        print(f" Idle timeout:   {idle_timeout} minutes")
    else:
        print(" Idle timeout:   Disabled")
    print("=" * 60 + "\n")

    if auto_open:
        import webbrowser

        cfg_onboard = load_config()
        query = "?onboarding=1" if not cfg_onboard.get("onboarding_completed", False) else ""
        url = f"http://127.0.0.1:{bound_port}/gallery.html{query}"
        print(f"[Server] Opening {url} in your default browser...")
        threading.Timer(1.0, webbrowser.open, args=[url]).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[Server] Shutting down.")
    finally:
        httpd.server_close()
        _instance.release(out_path)

    return httpd
