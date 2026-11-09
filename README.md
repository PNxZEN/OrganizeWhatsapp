# WhatsApp Offline Media Gallery

> Browse, search, and back up your WhatsApp photos, videos, and documents — fully offline, private, and organized by chat.

<div align="center">

[![Latest Release](https://img.shields.io/github/v/release/PNxZEN/OrganizeWhatsapp?style=for-the-badge&color=10b981&logo=github&label=Latest%20Release)](https://github.com/PNxZEN/OrganizeWhatsapp/releases/latest)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-blue?style=for-the-badge)](https://github.com/PNxZEN/OrganizeWhatsapp/releases/latest)
[![Offline & Private](https://img.shields.io/badge/100%25-Offline%20%26%20Private-success?style=for-the-badge)](https://github.com/PNxZEN/OrganizeWhatsapp)
[![Changelog](https://img.shields.io/badge/Changelog-v1.2.5-orange?style=for-the-badge)](CHANGELOG.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](LICENSE)

<br/>

### [**Download Latest Release (Windows Portable & Unix Source)**](https://github.com/PNxZEN/OrganizeWhatsapp/releases/latest)

**Zero installation required for Windows:** Embedded Python 3.13 and Google ADB included. Just extract and double-click `Start-Gallery.bat`.

</div>

---

## Table of Contents

1. [What Problem Does This Solve?](#1-what-problem-does-this-solve)
2. [Quick Start (Windows — Zero Install)](#2-quick-start-windows--zero-install)
3. [Quick Start (macOS / Linux)](#3-quick-start-macos--linux)
4. [Quick Start (Developers / Manual Setup)](#4-quick-start-developers--manual-setup)
5. [Step-by-Step User Guide](#5-step-by-step-user-guide)
6. [Key Features](#6-key-features)
7. [Why Direct Wired ADB?](#7-why-direct-wired-adb)
8. [Why the 64-Digit Key?](#8-why-the-64-digit-key)
9. [Project Structure](#9-project-structure)
10. [Configuration Reference](#10-configuration-reference)
11. [In-App Updates & Versioning](#11-in-app-updates--versioning)
12. [Privacy & Security](#12-privacy--security)
13. [Requirements](#13-requirements)
14. [Changelog & Release Notes](#14-changelog--release-notes)
15. [License](#15-license)

---

## 1. What Problem Does This Solve?

WhatsApp is the primary medium for sharing photos, videos, voice notes, and documents. Over months and years, this media consumes tens of gigabytes of phone storage, frequently pushing devices to capacity.

WhatsApp includes a **"Manage Storage"** screen, but provides only one action: **DELETE**.

There is no built-in option to:
- "Back up selected chat to PC"
- "Save college trip photos to an external drive"
- "Export all videos from this group while keeping documents"

Users are forced to choose between running out of storage or permanently losing their memories.

### Why Built-in WhatsApp Backups Don't Help
- **Locked Inside WhatsApp**: Media in cloud or local backups can **only be restored inside the WhatsApp mobile app itself**. You cannot mount the backup on a PC to view photos or play videos.
- **No Direct Storage Access**: Cloud backups are stored as hidden proprietary app-data packages. Local backups are cryptographically locked database blobs (`msgstore.db.crypt14/15`).
- **Cannot Free Up Phone Space Without Losing Access**: Deleting media from WhatsApp deletes your access to those files.

**WhatsApp Offline Media Gallery liberates your media**: It connects directly to your phone via USB cable, decrypts and organizes all photos, videos, audio, and documents into clean, human-readable folders organized by chat name and date. You can store them on external drives, SSDs, NAS storage, or any computer — accessible anytime via standard file explorers or the built-in 60 FPS offline gallery, completely independent of WhatsApp.

---

## 2. Quick Start (Windows — Zero Install)

The easiest way. No Python, no setup, no installation required.

1. Download the latest zero-install portable ZIP from [**GitHub Releases**](https://github.com/PNxZEN/OrganizeWhatsapp/releases/latest) (`WhatsAppMediaOrganizer-vX.X.X-Windows-Portable.zip`).
2. **Right-click the ZIP → Extract All** (to any folder).
3. **Double-click `Start-Gallery.bat`**.
4. Your browser opens automatically — follow the interactive setup guide.

> The ZIP includes embedded Python 3.13, Google ADB, and all dependencies.

---

## 3. Quick Start (macOS / Linux)

Download `WhatsAppMediaOrganizer-vX.X.X-Unix-Source.tar.gz` from [GitHub Releases](https://github.com/PNxZEN/OrganizeWhatsapp/releases/latest), then extract and run the one-time setup:

```bash
tar -xzf WhatsAppMediaOrganizer-vX.X.X-Unix-Source.tar.gz
cd WhatsAppMediaOrganizer-vX.X.X
./install.sh
```

Then launch it (the only command you need from now on):

```bash
./start_gallery.sh
```

Setup will:
- Check for Python 3.10+ (and explain how to install it if missing)
- Create a virtual environment and install dependencies (including FFmpeg)
- Download Google's official Android platform-tools (ADB) into `./bin/platform-tools/` if not present. No Homebrew required.

> [!NOTE]
> On Linux, Google publishes ADB for x86-64 only. On ARM Linux (e.g. Raspberry Pi), install it via `sudo apt install adb`.

---

## 4. Quick Start (Developers / Manual Setup)

```bash
git clone https://github.com/PNxZEN/OrganizeWhatsapp.git
cd OrganizeWhatsapp

python -m venv venv

# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt

# Launch gallery server with auto-open
python wa_media_organizer.py --serve --auto-open
```

---

## 5. Step-by-Step User Guide

### Step 1: Connect Your Phone (Live Connection Checklist)

1. Start the app. The interactive setup guide opens automatically on first launch (or click **Setup Guide** anytime).
2. The app includes a **live connection checklist** that automatically detects your phone brand when plugged in:
   - **Plugged in** → **USB debugging enabled** → **Authorized on phone**.
   - If stuck on any step, brand-tailored hints appear for 15+ manufacturers (Samsung, Xiaomi/HyperOS, OnePlus, OPPO, Vivo, Pixel, Motorola, Nothing, Huawei, etc.).
3. When your phone displays **"Allow USB debugging?"**, check **"Always allow from this computer"** and tap **Allow**.

---

### Step 2: Capture Your 64-Digit WhatsApp Key

This key decrypts your WhatsApp chat database locally to resolve chat names and contacts. **It never leaves your machine.**

The setup guide offers two effortless modes:
- **"Do it for me" (Automated USB Capture)**: The app navigates through WhatsApp on your phone via ADB and reads the 64-digit key directly off the screen. Nothing to type or copy.
- **"Guide me step by step"**: The app monitors your phone screen and shows live instructions and matching screenshots as you tap.
- **Manual / 1-Tap USB Transfer**: If you already know your key, paste it directly or use 1-Tap USB transfer over the local wire (`/paste-key`).

---

### Step 3: Complete Media Sync Across All Folders

Click **Sync Phone** in the top navigation bar.

The app will:
- Read media from **all WhatsApp account folders** (both the main `Media` directory and modern `accounts/<id>/Media` subdirectories).
- Match files by **content fingerprint (SHA-256)** against chat records, ensuring renamed or shared media reaches the right chat.
- Pull encrypted databases (`msgstore.db.crypt15`) over USB at 30–60 MB/s and decrypt locally using AES-256-GCM.
- Stream media directly into clean `./output/<Chat Name>/<YYYY-MM>/` folders.
- Generate a comprehensive `.sync_report.json` auditing every file on phone vs. PC.

---

### Step 4: Browse, Filter & Export

| Action | How |
| :--- | :--- |
| **Browse chats** | Left sidebar, sorted by media count and disk size |
| **Categories** | Dedicated tabs: Images, Videos, Audio, Documents, Stickers, GIFs, Voice notes |
| **Fast filters** | Search text, All / Sent / Received switch, Starred, Forwarded, and Hide Duplicates chips |
| **Date navigation** | Calendar filter with Month and Year slider rails |
| **Duplicate review** | Visual side-by-side video & image comparison lightbox; soft-delete to Recycle Bin |
| **Export ZIP** | One-click **Backup Chat** to download an entire conversation as an offline ZIP archive |

---

### Step 5: Multi-Account Browser Tabs

If your phone runs multiple accounts (WhatsApp Business, a second SIM, Samsung Dual Messenger, or Work Profiles):
- Click the **Accounts** button in the top navigation bar.
- Open each account in its own dedicated browser tab.
- Each account maintains its **own independent library folder**, its own port, and its own saved 64-digit backup key with zero cross-contamination.

---

### Step 6: Verified Phone Storage Reclaim & Audit History

Free up phone storage safely without risking data loss:
- **Phone-Checked Estimates**: Every file is verified to exist on the phone before being counted in the cleanup estimate.
- **Strict Verification Before Delete**: Right before any file is deleted on the phone, its PC copy is re-checked to ensure it exists and matches file size.
- **Live Deletion Progress**: Watch live progress with current file names, speed, space freed, and confirmed deletions.
- **Reclaim History & Check Phone**: Audit past cleanups, export full CSV logs, or click **Check Phone** to see what media is still on the phone vs. PC.

---

### Step 7: Restore Developer Options / Banking App Access

Some banking and UPI payment apps (Google Pay, PhonePe, YONO SBI) restrict access while Developer Options is active.

**To restore access immediately** before unplugging:
- Click the one-click **"Disable Developer Options"** button in the desktop app UI.
- Alternatively: Phone **Settings → Developer Options → toggle master switch OFF**.

---

## 6. Key Features

| Feature | Description |
| :--- | :--- |
| **Zero-Install Portable** | Single-click standalone ZIP for Windows with embedded Python 3.13 and ADB |
| **Automated Key Capture** | "Do it for me" mode automatically captures 64-digit key over USB |
| **Phone-Verified Reclaim Studio** | Checks phone inventory before estimating; verifies PC copy before every deletion |
| **Cleanup Audit History** | Detailed log of every cleanup run, CSV export, and live "Check Phone" inspector |
| **Multi-Account Tabs** | Run personal, Business, and Dual Messenger accounts in separate isolated tabs |
| **Complete Account Folder Sync** | Reads all `accounts/<id>/Media` and legacy folders with SHA-256 content-hash matching |
| **In-App Self-Updater** | Opt-in updates with download verification, atomic swap, and offline rollback |
| **Full Media Categories** | Filter by Photos, Videos, Audio, Documents, Stickers, GIFs, and Voice Notes |
| **Duplicate Comparison Lightbox** | 3-frame visual video hash comparison with side-by-side synchronized playback |
| **In-Gallery Recycle Bin** | Soft-delete duplicates with full Ctrl+Z undo and restore back to original chat folders |
| **Selective Push-to-Phone** | Restore archived media back to your Android phone over USB with media scanner broadcast |
| **Wired USB Speed** | Fast socket streaming over USB (30–60 MB/s) — no Wi-Fi, no cloud limits |
| **100% Offline & Private** | Localhost binding, bundled Inter fonts, zero telemetry, and origin validation |

---

## 7. Why Direct Wired ADB?

| Method | Problem |
| :--- | :--- |
| **WhatsApp Web / Multi-Device** | Only syncs recent messages (~3 months). Heavily throttled. Cannot access full historical media archives. |
| **MTP (Windows File Transfer)** | Unstable over large transfers. 4 GB single-file limit. Strips original timestamps. Frequently freezes. |
| **Wired ADB** | Binary socket streaming at full USB bus speed. 100% file integrity. Preserves timestamps. Zero dropped files. |

---

## 8. Why the 64-Digit Key?

On Android 11–15, WhatsApp stores its internal database (`msgstore.db`) inside a protected sandbox (`/data/data/com.whatsapp/databases/`), which Android shields from external USB access without root.

WhatsApp's **End-to-End Encrypted Backup** exports an encrypted snapshot to shared storage (`/sdcard/Android/media/com.whatsapp/WhatsApp/Databases/`) where ADB can read it. With the 64-digit key, the app decrypts the database locally using AES-256-GCM to map media to contact names and chat titles — entirely offline on your PC.

---

## 9. Project Structure

```text
OrganizeWhatsapp/
├── core/                          # Modular backend engine
│   ├── activity.py                # Activity coordinator & operation concurrency lock
│   ├── adb.py                     # ADB binary socket streaming & device control
│   ├── clean_planner.py           # Phone-verified cleanup planner & candidate matching
│   ├── config.py                  # Configuration loader, path helpers, binary finders
│   ├── database.py                # SQLite query engine for msgstore & media indexes
│   ├── decrypt.py                 # WhatsApp AES-256-GCM database decryptor
│   ├── device_inventory.py        # Fast device storage & account discoverer
│   ├── import_job.py              # Background importer for historical/external media
│   ├── instance.py                # Single-instance lock & active session focus
│   ├── libraries.py               # Multi-account tab & library coordinator
│   ├── migrator.py                # Media folder structure migrator & index builder
│   ├── organizer.py               # Media organizer & content-hash matching engine
│   ├── pipeline.py                # Multi-stage backup & sync execution pipeline
│   ├── platform_tools.py          # Platform ADB and companion tool manager
│   ├── reclaim_history.py         # Cleanup run audit history & phone status inspector
│   ├── reveal.py                  # OS-native file reveal (Explorer / Finder / Files)
│   ├── server.py                  # Local HTTP server with origin validation & REST APIs
│   ├── sync_report.py             # Post-sync media reconciliation & audit reporter
│   ├── thumbnail.py               # On-demand image downscaling & video frame extraction
│   ├── update_helper.py           # Atomic update installer & background process restarter
│   ├── updater.py                 # GitHub releases updater with SHA-256 validation
│   ├── version.py                 # Single source of truth for version (__version__)
│   └── assets/tutorial/           # Onboarding guide step images (WebP)
├── gallery.html                   # Modular gallery layout & modal container
├── gallery_assets/                # Modular frontend client (zero external CDN dependencies)
│   ├── css/                       # Modular stylesheets (cascade order)
│   ├── fonts/                     # Self-hosted offline Inter font files (WOFF2)
│   └── js/
│       ├── core/                  # State, formatting, modal stack, navigation, lifecycle
│       ├── features/              # Sidebar, grid, lightbox, sync, reclaim, updater, wa-guide...
│       └── app.js                 # Frontend application bootstrap
├── wa_media_organizer.py          # Main CLI & server entrypoint
├── start_gallery.bat              # Windows portable launcher
├── start_gallery.sh               # macOS / Linux companion launcher
├── install.sh                     # macOS / Linux one-step setup
├── requirements.txt               # Python dependencies
├── config.json.example            # Configuration template
├── CHANGELOG.md                   # Complete release notes history (v1.0.1 – v1.2.5)
├── scripts/
│   └── build_windows_portable.py  # Builds the Windows Portable ZIP release
├── .github/workflows/             # GitHub Actions CI/CD (release & cross-platform test matrix)
├── tests/                         # Automated test suite (490+ unit tests + 12 JS test suites)
├── output/                        # Default organized media destination (gitignored)
└── Databases/                     # Encrypted & decrypted databases (gitignored)
```

---

## 10. Configuration Reference

The app creates a clean `config.json` with defaults on first launch.

```json
{
  "hex_key": "",
  "mode": "copy",
  "port": 8000,
  "idle_timeout": 45,
  "output_dir": "./output",
  "media_dir": "./output",
  "db_dir": "./Databases",
  "allow_lan": false,
  "auto_check_updates": false,
  "onboarding_completed": false
}
```

| Setting | Default | Description |
| :--- | :--- | :--- |
| `hex_key` | `""` | Your WhatsApp 64-digit hex encryption key. Saved automatically by the guide. |
| `mode` | `"copy"` | Media transfer mode: `copy` (keeps original on phone) or `move`. |
| `port` | `8000` | Local HTTP server port. Assigned per account tab when running multiple accounts. |
| `idle_timeout` | `45` | Minutes without open tabs before idle shutdown (set `0` to disable). Active operations never get cut off. |
| `output_dir` | `"./output"` | Where organized media is stored. Can point to external drives or NAS folders. |
| `allow_lan` | `false` | Binds strictly to `127.0.0.1` when `false`. Only enable if you intentionally want LAN access. |
| `auto_check_updates` | `false` | Opt-in anonymous daily check on GitHub for new releases. Off by default. |

---

## 11. In-App Updates & Versioning

Open **Settings → About & Updates** (or click the version badge):

1. **Check for updates** queries GitHub anonymously for new releases and shows release notes.
2. **Download update** streams the update package and validates its SHA-256 checksum sidecar.
3. **Restart & install** atomically replaces application files and restarts the server. Active operations (sync, cleanup, backup) block updates until completed.
4. **Automatic Offline Rollback**: If a new version fails health check on launch, the previous version is restored instantly from the local `.update/backup` snapshot.

---

## 12. Privacy & Security

- **Strict Localhost & Origin Validation**: Server binds to `127.0.0.1` and validates HTTP Host and Origin headers, protecting against cross-site requests from other browser tabs.
- **100% Offline by Default**: Decryption, thumbnailing, hashing, and fonts (Inter) are entirely local. Zero telemetry, zero analytics, zero external network calls.
- **Key Isolation**: The 64-digit key is stored only on your local disk in `config.json`. It is never transmitted over the internet.
- **Atomic Operations & Consistency**: Multi-tab synchronization ensures that changes in one tab immediately reflect across others without data race conditions.
- **Permanent Deletion**: Permanently deleted media removes file binaries, thumbnails, and index records completely.

---

## 13. Requirements

### Windows Portable (Recommended)
- **Nothing to install** — Python 3.13 runtime, ADB, and dependencies are bundled in the portable ZIP.

### macOS / Linux
- Python 3.10 or newer (`brew install python@3.13` or `sudo apt install python3.12`)
- Run `./install.sh` once (installs dependencies and downloads official Google ADB).

---

## 14. Changelog & Release Notes

For a full historical record of all improvements and fixes across every version, see **[CHANGELOG.md](CHANGELOG.md)**.

---

## 15. License

MIT License. Free and open source for personal data preservation and storage management.
