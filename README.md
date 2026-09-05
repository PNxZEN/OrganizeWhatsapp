# WhatsApp Media Organizer

An offline, privacy-first desktop application designed to selectively back up, organize, deduplicate, and browse WhatsApp media by contacts and chat groups directly over high-speed USB.

---

## 1. The Core Problem Statement & Product Vision

### The WhatsApp Storage Dilemma
WhatsApp is the primary medium for sharing photos, videos, voice notes, and documents. Over months and years, WhatsApp media consumes tens of gigabytes of device storage, frequently pushing phones to 95%-100% capacity.

WhatsApp includes a built-in **"Manage Storage"** screen (*Settings > Storage and Data > Manage Storage*) which provides:
- A breakdown of media larger than 5 MB.
- A chat-by-chat storage list with file counts and gigabytes used.

**However, WhatsApp provides only one action: DELETE.**
There is no option to "Back up selected chat to PC", "Save college trip photos to external hard drive", or "Export all media for this group while leaving important documents intact". As a result, users are forced to choose between running out of phone storage or permanently losing their memories.

### Our Solution
WhatsApp Media Organizer bridges this exact gap:
1. **Direct High-Speed Wired Sync**: Connect your Android phone to your PC via high-speed USB cable to stream your WhatsApp media directly to your computer.
2. **Interactive Visual Offline Gallery**: Browse your entire media library organized by chat groups, individual contacts, senders, and chronological dates.
3. **Advanced Filtering & Date Sliders**: Search media by month and year using an interactive calendar with dedicated Month and Year sliders.
4. **Smart Duplicate Detection**: Identify forwarded, collision-avoided, or duplicated media across chats with visual badges and one-click filtering.
5. **Safe Deletion Workflow**: Selectively download or archive specific chats or selected media files to your computer or external drive.
6. **Phone Storage Liberation**: Once your media is safely archived and verified on your PC, you can confidently open WhatsApp's "Manage Storage" on your phone and tap **Delete** on those specific chats to instantly reclaim gigabytes of phone storage.

---

## 2. Technical Architecture & Design Decisions

### Why Direct Wired ADB?
- **vs. WhatsApp Web Multi-Device Protocol**: WhatsApp Web only synchronizes recent messages and media (typically the last 3 months). It requires network bandwidth, throttles bulk downloads from WhatsApp servers, and cannot access the complete 30+ GB local storage archive on the device.
- **vs. MTP (Standard Windows USB File Transfer)**: MTP is notoriously unstable over large transfers, has a single-file transfer ceiling of 4 GB, cannot preserve original timestamps accurately, and frequently hangs or disconnects when reading thousands of nested files.
- **Wired ADB Streaming**: Uses binary socket streams over USB 3.0/2.0 at maximum hardware bus speed (30-60 MB/s), ensuring 100% file transfer integrity with zero dropped files and precise error handling.
- **Single-Pass Streaming**: Pulls media directly from your phone into the normalized `./output` directory, eliminating redundant staging folders and saving precious PC disk space.

### Why the 64-Digit End-to-End Encrypted Key?
On Android 11 through Android 15:
- WhatsApp stores its internal SQLite message database (`msgstore.db`) inside a protected application sandbox (`/data/data/com.whatsapp/databases/`). Android strictly prevents any external app or USB connection from reading this folder without root.
- The only non-root method to export this database is WhatsApp's official **End-to-End Encrypted Backup** feature (*Settings > Chats > Chat Backup > End-to-end Encrypted Backup*).
- When enabled, WhatsApp exports an encrypted database snapshot (`msgstore.db.crypt14` or `crypt15`) to shared storage (`/sdcard/Android/media/com.whatsapp/WhatsApp/Databases/`).
- By providing the 64-digit hexadecimal key, our desktop application decrypts the database locally using AES-256-GCM, unlocking the chat titles, sender names, and message timestamps without ever sending your data to any cloud service.

---

## 3. Key Capabilities & Highlights

- **Single-Pass Streaming Pipeline**: Pulls WhatsApp media directly into your organized destination (`./output`) without temporary staging folders.
- **Interactive Calendar with Month & Year Sliders**:
  - Full month-by-month calendar view with smooth navigation arrows.
  - **Month Slider (1-12)**: Slide or click to jump across months or filter all media from that entire month with one click.
  - **Bounded Year Slider**: Dynamically bounded between your oldest and newest media years (e.g., 2020 to 2026), complete with quick-select year chips and a "Filter Entire Year" button.
- **Smart In-Chat Duplicate Detection**:
  - SQLite-backed SHA-256 caching detects identical and forwarded media across groups.
  - Collision-avoided files are tagged with `is_duplicate = true`.
  - The gallery dynamically detects in-chat duplicates: displays `(No duplicates)` when none exist, flags duplicates with red `DUPLICATE` badges, and provides a one-click toggle to isolate or hide them.
- **Two-Way Virtualization**: Renders chats with 50,000+ media files at a locked 60 FPS using DOM recycling and CSS `content-visibility: auto`.
- **Zero OS Video Decoder Exhaustion**: Pre-renders video poster frames on demand so browser tabs never crash from hardware decoder limits.
- **One-Click Developer Options Disabler**: Turn off Android USB debugging directly from the desktop UI before disconnecting your cable to immediately restore access to banking and UPI apps.
- **Cross-Tab Synchronization & Clean Shutdown**: Exiting from any browser tab cleanly shuts down the server and notifies all other open tabs simultaneously via the `BroadcastChannel` API.
- **100% Offline & Private**: Zero cloud leakage. No telemetry, no external servers, complete data sovereignty.

---

## 4. Step-by-Step User Guide

Follow these steps to back up and organize your WhatsApp media:

### Step 1: Launch Setup Guide & Connect Phone
1. Double-click **`start_gallery.bat`** (or run `python wa_media_organizer.py --serve --auto-open`).
2. On first launch, the application automatically welcomes you with the **Interactive Setup & Onboarding Guide**. (You can also open it anytime by clicking **Setup Guide** in the top navigation bar).
3. In **Step 1 (Phone Connection)**:
   - Follow the tailored instructions for your phone brand (**Xiaomi / Redmi / POCO**, **Samsung Galaxy**, **OnePlus / OPPO / Realme**, or **Google Pixel / Stock Android**).
   - Watch the real-time cable docking animation and connect your phone via USB.
   - When the phone displays *"Allow USB debugging?"*, check **"Always allow from this computer"** and tap **Allow**.

### Step 2: Obtain & Transfer Your 64-Digit Key
Follow **Step 2 (WhatsApp 64-Digit Key)** in the guide:
1. In WhatsApp, go to **Settings > Chats > Chat backup > End-to-end encrypted backup**.
   - *Note*: If a backup upload is currently in progress, wait for it to complete.
   - *Note*: If already set up without saving your key, tap "Turn off" and then "Turn on" to regenerate a new 64-digit key.
2. **Crucial**: Tap **More options** at the bottom. **DO NOT tap "Use passkey"** (passkeys are tied to device biometrics and cannot decrypt databases on PC).
3. Choose **Use 64-digit encryption key**, then tap **Generate your 64-digit key**.
4. Press and hold anywhere on the generated 4x4 key table on your phone to copy all 64 characters to your clipboard.
5. **1-Tap Zero-Cloud USB Transfer**:
   - In the desktop guide, click **"Send Key from Phone via USB"**.
   - The desktop securely opens the local transfer portal on your phone browser over the physical USB wire (`http://localhost:8000/paste-key`).
   - On your phone, tap **"Paste & Send to PC"**. The key is transmitted in milliseconds directly across the USB cable with zero internet or cloud leakage!
   - *(Alternative)*: You can also paste the 64 hex characters directly into the desktop input field.

### Step 3: Sync Phone and Decrypt Media
1. Click **Sync Phone** in the top navigation bar.
2. The app pulls your encrypted WhatsApp databases (`msgstore.db.crypt15`) and media over USB at maximum bus speed (30-60 MB/s), decrypts your chat names and contacts, and generates optimized gallery thumbnails directly into `./output`.

### Step 5: Browse, Filter, and Back Up
1. **Browse Chats**: View your chats in the left sidebar, sorted by media count and disk footprint.
2. **Filter by Media Type**: Use the top filter chips to isolate **Images**, **Videos**, **Audio**, or **Documents**.
3. **Filter by Date**: Click the calendar button to open the interactive date picker. Use the **Month Slider** to filter an entire month or the **Year Slider** to filter an entire year.
4. **Hide or Review Duplicates**: Use the duplicate toggle to hide redundant media or inspect flagged duplicate cards.
5. **Export & Back Up**: Select individual files using the card checkbox, or click **Backup Chat** to archive the conversation to your chosen directory.

### Step 6: Confidently Reclaim Phone Storage
Once your media is safely archived and verified on your PC:
1. Open WhatsApp on your phone.
2. Go to **Settings > Storage and Data > Manage Storage**.
3. Tap on the chats you have backed up to your PC.
4. Select all media and tap **Delete**. Your phone storage is instantly reclaimed while your memories remain safely preserved on your PC.

### Step 7: Safely Disable Developer Options (Restore Banking Apps)
Some banking and payment apps (such as YONO SBI, Google Pay, PhonePe, or BHIM) restrict access while Developer Options is active.
- To immediately restore banking app access:
  Click the desktop app's one-click **"Disable Developer Options"** button before unplugging your cable.
- Alternatively, open your phone's **Settings > Developer Options** and toggle the master switch at the very top to **OFF**.

---

## 5. Project Structure

```text
OrganizeWhatsapp/
├── core/                        # Modular backend engine
│   ├── adb.py                   # Pure Python ADB binary socket streaming & device control
│   ├── config.py                # Configuration loader and environment manager
│   ├── decryptor.py             # WhatsApp AES-256-GCM database decryptor
│   ├── indexer.py               # SQLite message parser and contact mapper
│   ├── organizer.py             # Single-pass media copier & duplicate hasher
│   ├── pipeline.py              # End-to-end sync coordinator
│   └── server.py                # Multi-threaded local HTTP server with REST APIs
├── gallery.html                 # 60 FPS virtualized web gallery UI
├── wa_media_organizer.py        # Main CLI and headless execution entrypoint
├── start_gallery.bat            # Quick launcher for Windows
├── config.json.example          # Public configuration template
├── tests/                       # Complete automated unit test suite
├── output/                      # Default destination for organized media (gitignored)
└── Databases/                   # Encrypted and decrypted databases (gitignored)
```

---

## 6. Configuration Options

Copy `config.json.example` to `config.json` to customize your runtime settings:

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
  "skip_db_pull": false
}
```

| Setting | Default | Description |
| :--- | :--- | :--- |
| `hex_key` | `""` | Your WhatsApp 64-digit hex encryption key. |
| `mode` | `"copy"` | Media copy mode (`copy` or `move`). |
| `port` | `8000` | Local HTTP server port. |
| `idle_timeout` | `45` | Auto-shutdown timeout in minutes after closing all browser tabs. |
| `output_dir` | `"./output"` | Path to the output directory where organized media is stored. |
| `media_dir` | `"./output"` | Media storage directory. |
| `db_dir` | `"./Databases"` | Directory for encrypted and decrypted WhatsApp databases. |
| `allow_lan` | `false` | When `false`, binds strictly to `127.0.0.1` (localhost only) for privacy. |
| `skip_db_pull` | `false` | If `true`, skips pulling fresh databases from the phone if already present. |

---

## 7. Privacy & Security

- **Strict Localhost Binding**: The local gallery server binds to `127.0.0.1` by default, preventing any unauthorized devices on your local Wi-Fi or LAN from accessing your chats.
- **Zero Cloud Communication**: The application makes zero outgoing network calls. All decryptions, thumbnail rendering, and duplicate hashing occur 100% locally on your machine.
- **Git Ignore Security**: The repository's `.gitignore` strictly blocks all media, SQLite databases, contact maps, encryption keys, and personal configuration files from ever being staged or committed to Git.

---

## 8. Requirements & Setup

- **Operating System**: Windows 10/11 (cross-platform compatible with Linux and macOS).
- **Python**: Python 3.9 or newer.
- **Dependencies**:
  ```bash
  pip install -r requirements.txt
  ```
  *(or install `cryptography` and `pillow`)*
- **ADB**: Android Debug Bridge (bundled or available via Android Platform Tools).
- **Browser**: Modern web browser (Chrome, Edge, Firefox, Brave).

---

## 9. License

MIT License. Free and open source for personal data preservation and storage management.
