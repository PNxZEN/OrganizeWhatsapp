# WhatsApp Offline Media Gallery

> Browse, search, and back up your WhatsApp photos, videos, and documents — fully offline, private, and organized by chat.

---

## Table of Contents

1. [What Problem Does This Solve?](#1-what-problem-does-this-solve)
2. [Quick Start (Windows — Zero Install)](#2-quick-start-windows--zero-install)
3. [Quick Start (macOS / Linux)](#3-quick-start-macos--linux)
4. [Quick Start (Developers / Manual Setup)](#4-quick-start-developers--manual-setup)
5. [Step-by-Step User Guide](#5-step-by-step-user-guide)
6. [Features](#6-features)
7. [Why Direct Wired ADB?](#7-why-direct-wired-adb)
8. [Why the 64-Digit Key?](#8-why-the-64-digit-key)
9. [Project Structure](#9-project-structure)
10. [Configuration Reference](#10-configuration-reference)
11. [Privacy & Security](#11-privacy--security)
12. [Requirements](#12-requirements)
13. [License](#13-license)

---

## 1. What Problem Does This Solve?

WhatsApp is the primary medium for sharing photos, videos, voice notes, and documents. Over months and years, this media consumes tens of gigabytes of phone storage, frequently pushing devices to 95-100% capacity.

WhatsApp includes a **"Manage Storage"** screen, but provides only one action: **DELETE**.

There is no built-in option to:
- "Back up selected chat to PC"
- "Save college trip photos to external hard drive"
- "Export all videos from this group while keeping documents"

Users are forced to choose between running out of storage or permanently losing their memories.

### Why Built-in WhatsApp Backups Don't Help
Even if WhatsApp performs an automatic local backup or a cloud backup (Google Drive / iCloud):
- **Locked Inside WhatsApp**: Media in those backups can **only be accessed and restored inside the WhatsApp mobile app itself**. You cannot plug an external hard drive, USB flash drive, or PC into the backup to browse your photos or play your videos.
- **No Direct Storage Access**: Cloud backups are stored as hidden, proprietary app-data packages that cannot be mounted or explored. Local backups on your phone are cryptographically locked inside proprietary encrypted database blobs (`msgstore.db.crypt14/15`).
- **Cannot Free Up Phone Space Without Losing Access**: If you delete media from WhatsApp to reclaim phone storage, you lose immediate access to those memories on your devices.

**WhatsApp Offline Media Gallery liberates your media**: It connects directly to your phone via USB cable, decrypts and organizes all photos, videos, audio, and documents into clean, human-readable folders organized by chat name and date. You can store them on external hard drives, SSDs, NAS drives, or any computer — accessible anytime via standard file explorers or the built-in 60 FPS offline gallery, completely independent of WhatsApp.

---

## 2. Quick Start (Windows — Zero Install)

The easiest way. No Python, no setup, no installation required.

1. Go to [**GitHub Releases**](../../releases/latest)
2. Download `WhatsAppMediaOrganizer-vX.X.X-Windows-Portable.zip`
3. **Right-click the ZIP → Extract All** (to any folder you like)
4. **Double-click `Start-Gallery.bat`**
5. Your browser opens automatically — follow the interactive setup guide

> **That's it.** The ZIP includes Python 3.13, Google ADB, and all dependencies. Nothing else to install.

---

## 3. Quick Start (macOS / Linux)

```bash
# Download and extract the Unix source archive from GitHub Releases
tar -xzf WhatsAppMediaOrganizer-vX.X.X-Unix-Source.tar.gz
cd WhatsAppMediaOrganizer-vX.X.X

# One-time setup (creates a Python virtual environment + installs dependencies)
./install.sh

# Launch
./start_gallery.sh
```

The launcher will:
- Check for Python 3.10+ and tell you exactly how to install it if missing
- Warn you if ADB or ffmpeg are not found, with OS-specific install commands
- Auto-create/update a `venv` on every run
- Open the browser automatically

> [!NOTE]
> ADB is required for USB sync. Install it with `brew install android-platform-tools` (macOS) or `sudo apt install adb` (Linux).

---

## 4. Quick Start (Developers / Manual Setup)

```bash
git clone <repo-url>
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

**Requirements**: Python 3.10+, ADB on PATH (or bundled in `./bin/platform-tools/`), ffmpeg (optional, for video thumbnails).

---

## 5. Step-by-Step User Guide

### Step 1: Launch & Connect Your Phone

1. Start the app using your platform's launcher (see Quick Start above).
2. **First launch** automatically opens the interactive setup guide. You can reopen it anytime from the **Setup Guide** button in the top navigation bar.
3. In **Step 1 (Phone Connection)**, follow the tailored instructions for your phone brand:
   - **Xiaomi / Redmi / POCO** — Enable MIUI Developer Options via Settings > About Phone (tap MIUI Version 7 times)
   - **Samsung Galaxy** — Enable via Settings > About Phone > Software Information (tap Build Number 7 times)
   - **OnePlus / OPPO / Realme** — Similar Developer Options path, brand-specific
   - **Google Pixel / Stock Android** — Enable via Settings > About Phone (tap Build Number 7 times)
4. Connect your phone via USB cable. When your phone displays **"Allow USB debugging?"**, check **"Always allow from this computer"** and tap **Allow**.

---

### Step 2: Get Your 64-Digit WhatsApp Key

This key decrypts your WhatsApp chat database locally so the app can read chat names and contacts. **It never leaves your device.**

1. On your phone, open WhatsApp → **Settings → Chats → Chat backup → End-to-end encrypted backup**.
   - If a backup is in progress, wait for it to finish.
   - If you set one up without saving the key, tap **Turn off** then **Turn on** to regenerate.
2. Tap **More options** at the bottom. **Do NOT tap "Use passkey"** — passkeys are biometric and cannot decrypt databases on a PC.
3. Choose **Use 64-digit encryption key** → tap **Generate your 64-digit key**.
4. Press and hold anywhere on the 4×4 key grid on your phone to copy all 64 characters.

**Transfer options (choose one):**

| Method | Steps |
| :--- | :--- |
| **1-Tap USB Transfer (recommended)** | Click **"Send Key from Phone via USB"** in the guide. The app opens a local page on your phone browser over USB (`http://localhost:8000/paste-key`). Tap **"Paste & Send to PC"**. Done — zero cloud, zero internet. |
| **Manual paste** | Paste the 64 hex characters directly into the desktop input field. |

---

### Step 3: Sync Your Phone

Click **Sync Phone** in the top navigation bar.

The app will:
- Pull your encrypted WhatsApp databases (`msgstore.db.crypt15`) over USB at 30–60 MB/s
- Decrypt your chat names, sender names, and timestamps locally using AES-256-GCM
- Stream all your media directly into the organized `./output` directory
- Generate optimized gallery thumbnails

---

### Step 4: Browse, Filter & Back Up

| Action | How |
| :--- | :--- |
| **Browse chats** | Left sidebar, sorted by media count and disk size |
| **Filter media type** | Top chip bar: Images, Videos, Audio, Documents |
| **Filter by date** | Calendar button → Month Slider (1–12) or Year Slider |
| **Find duplicates** | Duplicate toggle — red `DUPLICATE` badges, one-click to hide/show |
| **Select & export** | Checkbox on each card, or **Backup Chat** to archive the whole conversation |

---

### Step 5: Reclaim Phone Storage

Once your media is safely backed up and verified on your PC:

1. Open WhatsApp on your phone → **Settings → Storage and Data → Manage Storage**
2. Tap the chats you have backed up
3. Select all media → tap **Delete**

Your phone storage is instantly reclaimed. Your memories remain safely preserved on your PC.

---

### Step 6: Restore Banking App Access

Some banking and payment apps (YONO SBI, Google Pay, PhonePe, BHIM) block access while Developer Options is active.

**To restore access immediately** — before unplugging your cable — click the one-click **"Disable Developer Options"** button in the desktop app.

Alternatively: Phone **Settings → Developer Options → toggle the master switch OFF**.

---

## 6. Features

| Feature | Description |
| :--- | :--- |
| **Zero-install Windows Portable** | Download a ZIP, extract, double-click — no Python required |
| **Direct Wired USB Sync** | Streams media at 30–60 MB/s over USB 3.0/2.0 via ADB — no Wi-Fi, no cloud |
| **AES-256-GCM Decryption** | Decrypts WhatsApp databases locally with your 64-digit key |
| **1-Tap USB Key Transfer** | Securely sends your key from phone to PC over the physical wire, zero internet |
| **Interactive Visual Gallery** | Browse media organized by chat, sender, date, and media type |
| **Month & Year Sliders** | Calendar picker with dedicated sliders for fast date-range filtering |
| **Smart Duplicate Detection** | SHA-256 SQLite cache identifies forwarded and collision-avoided duplicates |
| **60 FPS Virtualization** | DOM recycling renders 50,000+ media files without slowdown |
| **Video Poster Frames** | Pre-renders thumbnails on demand — browser tabs never crash from hardware decoder limits |
| **One-Click ADB Disable** | Turns off USB debugging from the desktop UI before you unplug |
| **100% Offline & Private** | Zero telemetry, zero cloud, strict localhost binding |
| **Cross-Tab Sync** | Closing any tab shuts down the server and notifies all other tabs simultaneously |

---

## 7. Why Direct Wired ADB?

| Method | Problem |
| :--- | :--- |
| **WhatsApp Web / Multi-Device** | Only syncs recent messages (~3 months). Throttled by WhatsApp servers. Cannot access the full 30+ GB local archive. |
| **MTP (Windows USB File Transfer)** | Notoriously unstable over large transfers. 4 GB single-file ceiling. Loses original timestamps. Frequently hangs on thousands of nested files. |
| **Wired ADB** | Binary socket streaming at full USB bus speed. 100% file integrity. Precise timestamps. Zero dropped files. No cloud. |

---

## 8. Why the 64-Digit Key?

On Android 11–15, WhatsApp stores its SQLite database (`msgstore.db`) inside a protected application sandbox (`/data/data/com.whatsapp/databases/`). Android strictly prevents external access to this folder without root.

The only non-root method is WhatsApp's **End-to-End Encrypted Backup** feature, which exports an encrypted snapshot to shared storage (`/sdcard/Android/media/com.whatsapp/WhatsApp/Databases/`) where ADB can read it.

By providing the 64-digit hex key, the app decrypts the database locally using AES-256-GCM, unlocking chat titles, sender names, and timestamps — **without ever sending your data anywhere**.

---

## 9. Project Structure

```text
OrganizeWhatsapp/
├── core/                          # Modular backend engine
│   ├── adb.py                     # ADB binary socket streaming & device control
│   ├── config.py                  # Configuration loader, path helpers, binary finders
│   ├── decrypt.py                 # WhatsApp AES-256-GCM database decryptor
│   ├── organizer.py               # Single-pass media copier & duplicate hasher
│   ├── server.py                  # Multi-threaded local HTTP server & REST APIs
│   ├── thumbnail.py               # On-demand image downscaling & video frame extraction
│   └── assets/
│       └── tutorial/              # Onboarding guide step images (WebP)
├── gallery.html                   # 60 FPS virtualized offline gallery UI
├── wa_media_organizer.py          # Main CLI entrypoint
├── start_gallery.bat              # Windows launcher (portable runtime + dev venv)
├── start_gallery.sh               # macOS / Linux companion launcher
├── install.sh                     # macOS / Linux one-step setup
├── requirements.txt               # Python dependencies
├── config.json.example            # Configuration template
├── scripts/
│   └── build_windows_portable.py  # Builds the Windows Portable ZIP release
├── .github/
│   └── workflows/
│       └── release.yml            # GitHub Actions: builds & publishes releases on git tag
├── tests/                         # Automated unit test suite (75 tests)
├── output/                        # Organized media destination (gitignored)
└── Databases/                     # Encrypted & decrypted databases (gitignored)
```

---

## 10. Configuration Reference

Copy `config.json.example` to `config.json` to customize settings. The app creates a clean `config.json` with defaults on first launch.

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
  "onboarding_completed": false
}
```

| Setting | Default | Description |
| :--- | :--- | :--- |
| `hex_key` | `""` | Your WhatsApp 64-digit hex encryption key. Set by the app UI; do not share this. |
| `mode` | `"copy"` | Media transfer mode: `copy` (keep original on phone) or `move`. |
| `port` | `8000` | Local HTTP server port. Change if 8000 is in use. |
| `idle_timeout` | `45` | Minutes before auto-shutdown after all browser tabs close. Set `0` to disable. |
| `output_dir` | `"./output"` | Where organized media and thumbnails are stored. Can be an external drive path. |
| `media_dir` | `"./output"` | Source directory the gallery reads from. Normally matches `output_dir`. |
| `db_dir` | `"./Databases"` | Where WhatsApp database files are pulled and decrypted. |
| `allow_lan` | `false` | Set `true` to allow access from other devices on your local network. **Use with caution** — this exposes your media to your LAN. |
| `onboarding_completed` | `false` | Set automatically to `true` after completing the setup guide. Reset to `false` to replay the guide. |

---

## 11. Privacy & Security

- **Strict Localhost Binding**: The server binds to `127.0.0.1` by default. No device on your Wi-Fi or LAN can access your data unless you explicitly set `allow_lan: true`.
- **Zero Cloud Communication**: No outgoing network calls. Decryption, thumbnail rendering, and duplicate hashing are 100% local.
- **Key Safety**: Your 64-digit key is stored only in your local `config.json`. It is never transmitted over the internet. The USB transfer path (`/paste-key`) is only reachable over the physical USB cable.
- **Git Ignore**: All media, databases, contact maps, keys, and personal configs are strictly git-ignored and will never be committed to any repository.

---

## 12. Requirements

### Windows Portable (Recommended)
- **Nothing** — Python, ADB, and all dependencies are bundled in the ZIP.

### Windows (Manual / Developer)
- Windows 10 or 11
- Python 3.10 or newer ([python.org](https://www.python.org/downloads/))
- `pip install -r requirements.txt`
- ADB: either installed in system PATH, or placed in `./bin/platform-tools/adb.exe`
- ffmpeg (optional): for video thumbnail generation — [ffmpeg.org](https://ffmpeg.org/download.html) or placed in `./bin/ffmpeg.exe`

### macOS
- macOS 12 Monterey or newer
- Python 3.10+: `brew install python@3.13`
- ADB: `brew install android-platform-tools`
- ffmpeg (optional): `brew install ffmpeg`
- Run `./install.sh` to auto-create the venv and install dependencies

### Linux
- Python 3.10+: `sudo apt install python3.12` (Ubuntu/Debian) or `sudo dnf install python3.12` (Fedora)
- ADB: `sudo apt install adb`
- ffmpeg (optional): `sudo apt install ffmpeg`
- Run `./install.sh` to auto-create the venv and install dependencies

### Python Dependencies (requirements.txt)
```
pycryptodomex>=3.20.0   # AES-256-GCM WhatsApp decryption
pillow>=10.0.0          # Image processing & thumbnail generation
pillow_heif>=0.16.0     # HEIC/HEIF image format support (iPhone photos)
ImageHash>=4.3.1        # Perceptual hash for duplicate detection
wa-crypt-tools>=0.1.0   # WhatsApp crypt14/crypt15 database format support
```

---

## 13. License

MIT License. Free and open source for personal data preservation and storage management.
