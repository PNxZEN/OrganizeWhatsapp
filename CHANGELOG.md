# Changelog

All notable changes to the WhatsApp Offline Media Gallery are documented in this file.

---

## [v1.2.5] - 2026-11-10

> [!IMPORTANT]
> **Reclaim Space could promise more than it freed.** In v1.2.4 the estimate counted media that was no longer on the phone. Files whose phone location was never recorded (media from older versions or imports) were looked for in one guessed folder. A file that wasn't there was still counted as deleted and freed, and stayed on the phone if it was somewhere else.
>
> This version checks every file on the phone before counting it, keeps a record of every cleanup, and can show what an earlier cleanup left behind.

### Find out what an earlier cleanup really did
- **Reclaim Space › History › Check phone** compares your library with what is on the phone right now. It works whichever version made the earlier cleanup. It shows:
  - backed-up media that is still on the phone, and how much space it takes;
  - backed-up media that is gone from the phone;
  - files earlier versions looked for in the wrong folder (for example `Sent`), with where they really are.
- **Then Analyze again:** only files that are really on the phone, and identical to their PC copy, are offered.

### An estimate you can trust
- **Every file is looked up on the phone before it is counted** (when the phone is connected while analyzing). Left out, with the reason:
  - files no longer on the phone;
  - a different file at the same path;
  - more than one possible match;
  - the same file listed twice.
- **Files are found where they really are,** in this account's own folders. A file found somewhere other than recorded counts only when its contents (MD5) match the PC copy.
- **Another WhatsApp account's folder is never searched or touched.**
- If the phone wasn't connected while analyzing, the screen says the estimate is unchecked, and every file is checked before anything is deleted.

### Safe, exact deletion
- **Right before each file is deleted, its PC copy is checked again.** It must exist and have the same size as the file on the phone; otherwise the phone file is kept.
- **Every file ends up as exactly one of:**
  - deleted;
  - already not on the phone;
  - listed twice;
  - kept (not safe);
  - could not be deleted (with the phone's reason);
  - not reached;
  - unknown, if the phone was unplugged mid-batch.
- **"Freed" counts only files the phone confirmed gone,** at their size on the phone. The finished screen also shows the phone's free space before and after.
- **Interruptions are safe:**
  - Cancel, an unplugged cable or a closed app stop cleanly, and nothing the phone didn't confirm is counted.
  - Your PC copies are never changed.
  - Analyze again afterwards: only what is still on the phone is offered.
- **One phone job at a time:** no two cleanups at once, and no cleanup while a sync uses the phone (in any account's tab).

### A record of every cleanup
- **History** lists every cleanup with what was freed, what wasn't, and how it compares to the first estimate.
- **Open one to see every file**, filtered by result, searchable, with the reason for each. **Export CSV** saves the full list.
- The record is written as the phone confirms each batch, so even a crash or a pulled cable leaves an exact record up to that point.

### Live progress while deleting
- The bar and the count follow the phone, along with the space freed so far, the time left, the file being deleted now and the last files confirmed deleted.
- Deletion is faster: it runs over one connection to the phone instead of a new one for every 100 files.

### Upgrading
- **From v1.2.4:** open **Settings › About & Updates**, then **Check for updates**, then **Restart & install**.
- **If you ran a cleanup with v1.2.4:** after updating, connect the phone and open **Reclaim Space › History › Check phone**.

---

## [v1.2.4] - 2026-10-24

> [!IMPORTANT]
> This update fixes serious problems. Please update.
> - **Older or newer media could be missing with WhatsApp's account folders.** WhatsApp can keep an account's media both in `Android/media/com.whatsapp/WhatsApp/Media` and in `…/WhatsApp/accounts/<id>/Media`, and moves the account between them. A sync only read the chosen account's folder (and the main one), so media in another account folder never reached the PC. Every sync now reads all of them.
> - **Syncs were dropping media from the gallery.** Every sync after the first rewrote the gallery with only that sync's new files. Earlier photos and videos were still on disk but disappeared from the gallery. They are back after your next sync.
> - **Other websites could reach the app.** While the app was running, a website open in the same browser could read your backup key and media, or delete media, through the app's local server. The server now only answers its own pages.

### Every media file reaches the PC
- **All of WhatsApp's account folders are read:** the main `Media` folder and every `accounts/<id>/Media`.
- **Only your media goes into your chats.** WhatsApp's file names (IMG-20250101-WA0001.jpg) repeat across accounts, so a file from another account folder is filed into a chat only when its contents match what your chats recorded.
  - The rest stays in `_unmatched/From account <id>` or `_unmatched/From main folder`, apart from your own unmatched media. Nothing is left on the phone.
- **The app tells you whose media each account folder holds.** After a sync it counts how much of a folder's media is in your chats.
  - Most of it means the folder is your account's older media.
  - Almost none means it belongs to another WhatsApp account, and the finished-sync screen says to open that account from **Accounts**.
  - The counts per folder are in `.sync_report.json`.
- **A newer backup in another account folder is pointed out.** If WhatsApp moved your account after you chose it, the finished-sync screen says so; open that folder from **Accounts**.
- **Each sync is checked.** The app compares the phone's list of media with the files on the PC.
  - If a file is missing, the finished-sync screen says how many and the next sync fetches them.
  - The details are in `.sync_report.json` in the output folder: files per folder on the phone, files on the PC, files in chats, files unmatched, and attachments the phone doesn't have (never downloaded, deleted, view once).
- **Two different photos with the same name and size are both kept.** Before, the second one was dropped.
- **A file deleted on the phone during a sync no longer fails the whole sync.**
- **Phone cleanup deletes exactly the file that was copied.** It now uses each file's full path on the phone. Before, media of an account folder was looked up in the wrong folder.

### Each WhatsApp account in its own tab
- **One phone, several accounts, no mixing.** WhatsApp Business, a second number, or a second copy of WhatsApp each get their own library:
  - their own folder, beside your first one (`output - WhatsApp Business (+91…)`);
  - their own 64-digit backup key;
  - their own browser tab, on its own port.
- **Open them from Accounts.** The new **Accounts** button lists the phone's accounts with their last backup. Choose **Open in new tab**, or **Go to its tab** if it is open already.
  - The tab's title and a chip at the top name the account it shows.
  - A key that opened an account's backup before is filled in when its tab opens.
- **Your current gallery stays as it is.** It belongs to the account you synced first, and it can't be switched to another account by mistake.
  - A sync never takes another account's media into it: if that account isn't on the connected phone, the sync says so instead.
- **No double copies.** An account folder that has its own tab is copied only there, not into every other account's folder too.
- **Phone cleanup keeps to the tab's own account.** Media kept apart in `_unmatched/From account …` belongs to another account, so cleanup never offers to delete it from the phone.
- **One sync on the phone at a time.** While one tab syncs, the others say which account is syncing and wait.
- **Exit in the first window closes every account's tab.** Updates install from the first window, which closes the other tabs while it updates.
- **A sync never uses another account's chats.** Neither a cut-off backup nor skipping the database download falls back to another account's chat database.

### Damaged backups are not used
- **A backup copied while WhatsApp was still writing it is refused.** Before, it was used as it was, and chats and media links past the cut were missing.
  - Damaged backups are refused too.
  - The chats from your previous sync are used instead, and the finished-sync screen says so.
- **A new backup with exactly the same size as the last one is now copied.** Before, it was taken for the old one, and the old chats were used.

### Unmatched media finds its chat
- **Every sync re-checks `_unmatched`.** Before, a photo newer than the WhatsApp backup used for its sync stayed unmatched for good, because later syncs skip files already on the PC.
- **Files are matched by their contents.** WhatsApp records a fingerprint (SHA-256) of every photo, video and document. The app now compares files against it, so renamed or re-saved files still find their chat.
  - Sent media is matched against the original as well as the compressed copy.
  - A file sent to several chats goes to the chat where it first appeared.
- **No more guessing by file size.** Before, a file whose name wasn't recognised could be filed in the wrong chat just because its size matched. Now that only happens when WhatsApp kept no fingerprint to check it against.
- Phone cleanup knows about the files that moved, so they can still be freed from the phone.

### Stickers, GIFs and voice notes
- **They have their own categories** in the filters, next to Images, Videos, Audio and Documents. Each category shows how many items the chat has.
- **Clear them out in one go.** Pick Stickers (or GIFs, or Voice notes) to get **Select all** and **Move all to Recycle Bin**. The move can be undone.
- Media synced before this version is sorted by WhatsApp's file names: stickers, GIFs and voice notes are recognised from them.

### A cleaner filters pane
- Search, sort and dates in one row. **Clear filters** appears there while any filter is on.
- Categories in one bar, with icons and counts.
- Starred, Forwarded, Often forwarded and Hide duplicates are now one-tap chips, and **All / Sent / Received** is a switch.
- On small windows the rows scroll sideways instead of spilling over.

### Connecting your phone
- **USB debugging steps for 15 brands, checked against current sources.** Covered: Samsung, Xiaomi / Redmi / POCO, OnePlus, OPPO, realme, vivo / iQOO, Motorola / Lenovo, Google Pixel, Nothing / CMF, Honor, Huawei, Tecno / Infinix / itel, Sony, Asus and Nokia / HMD, plus general steps for any other phone.
  - Xiaomi on HyperOS: the guide now says to tap **OS version**.
  - Samsung: a note on **Auto Blocker**, which greys out USB debugging until it is turned off.
  - Xiaomi: a note that **USB debugging (Security settings)** is needed for "Do it for me".
  - Huawei and Honor: choose **File transfer** when plugging in.
- **Your brand is picked automatically** as soon as the phone is plugged in, before USB debugging is on. Otherwise choose it from the list; it is remembered.
- **Can't find a menu?** Each brand has a web-search link for your exact phone model.

### Updating on Mac and Linux
- **After an in-app update, the app now installs what the new version needs by itself**, such as ffmpeg (video thumbnails) and ADB (phone sync). Before, you had to start it once from the terminal. About & Updates shows when this is running.
- **Downloads start sooner.** The update no longer waits for a separate checksum download before it starts. The progress bar says "Connecting to GitHub…" until data arrives.

### Fixes
- Starting a sync twice (a double-click or two tabs) could run two syncs at once. Cancelling and then starting again could restart the cancelled sync.
- Settings saved at the same moment could corrupt `config.json` and lose the backup key.
- Cancelling a sync could delete real documents named like `Thesis.part_1.pdf`.
- Moving media to the Recycle Bin during a sync left broken entries; it now waits for the sync.
- A file name from the phone could run script in the sync banner.
- Browser Back from a chat left its media on screen.
- After a ZIP download, the app said "Backup cancelled". Switching chats or pressing Esc also cancelled a running export.
- A key pasted in groups of four (with spaces) was cut off at 52 digits.
- Arrow keys in the key field changed the setup guide's step. Ctrl+C copied a file path instead of the highlighted text.
- While scrolling, some undated unmatched media was shown twice or skipped.
- Chats and media can now be opened with the keyboard (Tab, then Enter).
- The file count in the chat header updates after restoring from the Recycle Bin.
- The setup guide's header no longer runs off narrow screens.
- Video seeking works in more players.

### Upgrading
- **From v1.2.3:** open **Settings → About & Updates**, then **Check for updates**, then **Restart & install**.
  - On Mac and Linux, the app installs ffmpeg and ADB on its first start if they are missing.
- **From older versions:** download the release and replace your app folder, keeping `config.json` and the `output` folder.
  - On Mac and Linux, run `./install.sh` once in the new folder.

---

## [v1.2.3] - 2026-10-22

### Faster first setup: the app now sets up WhatsApp's backup key for you
Before, you followed 12 slides on the phone and then typed or copied the 64-digit key. Now the **Backup key** step can do it for you over USB:

- **Do it for me:** the app taps through WhatsApp on your phone (Settings → Chats → Chat backup → End-to-end encrypted backup → 64-digit key) and reads the key straight off the screen. Nothing to copy or type.
- **Guide me step by step:** you tap, and the app follows along, telling you the next step as soon as each screen appears.
- The matching tutorial picture is shown next to the live instructions in both modes.
- You can switch between the two modes at any time, and start halfway: if your phone already shows one of the steps, the app carries on from there.
- **I already have my key:** paste it from the clipboard, or take it from an older version of this app's folder.
- If the phone shows something the app doesn't recognise, the step-by-step slides come back. The app still picks up your key if it appears.

#### It is careful on your phone
- It never taps **Use passkey**: a passkey can't unlock the backup on a computer.
- It never enters or sees your screen lock PIN. When WhatsApp asks for it, you confirm it on the phone.
- If your backup is already end-to-end encrypted, it asks first: keep your key (paste it) or make a new one. It only turns the old encryption off if you choose a new key.
- It never guesses: a menu item it can't recognise is never tapped (it could be "Read all"). You get the next step instead.
- The full key is never shown in the browser (only `abcd…wxyz`). What the app reads from the phone screen stays in memory and is never saved or sent anywhere.

#### It handles real phones
- Wakes the phone and asks you to unlock it first, then opens WhatsApp on its main screen, even if it was left in a chat, Status or Calls.
- Works with both WhatsApp layouts:
  - the ⋮ menu → Settings;
  - newer WhatsApp's **You** tab (bottom right).
- If WhatsApp is open on Calls, Updates or Communities, it goes back to Chats first.
- Recognises Settings in other languages, with a "new" badge, or labelled only for screen readers.
- Warns before **Create** if the phone is too full for the backup, and estimates the space needed from your previous backup.
- After **Create**, it waits until WhatsApp has actually made the backup file. If WhatsApp says there isn't enough space, the message is shown with a **Try again** button.
- On phones that block simulated taps (some Xiaomi), it switches to step-by-step mode and says which setting allows it.

#### Interruptions don't make it tap the wrong thing
- **Notification banners:** it waits for one to go before tapping underneath it.
- **Notification panel:** if you pull it down, it closes it after a few seconds.
- **Your own touches:** it waits until you stop touching the phone, so it never taps under your finger.
- **Another app:** if you switch apps or go to the home screen, it pauses. It never pulls you out of the other app; it carries on when you return to WhatsApp, or press **Continue**, from the same step.
- **Calls:** during a phone call or a WhatsApp call, nothing is tapped. A **Continue anyway** link covers phones that keep reporting a call after it has ended.
- **Cable unplugged:** it pauses with "Phone disconnected" and carries on from the same step when you plug it back in.
- **Screen locks while WhatsApp makes the backup:** that's fine; it no longer asks you to unlock.

### Connecting your phone
- The phone step is now a live checklist that ticks itself off: **Plugged in** → **USB debugging on** → **Allowed on the phone**. It replaces the slides.
- If you're stuck on a step, it shows a hint, for example:
  - try another cable or USB port;
  - unplug and replug;
  - where to find Developer options;
  - Samsung phones on Windows may need the Samsung USB Driver;
  - on Linux, the USB rules to install.
- On Mac and Linux, the app can now tell a plugged-in phone apart from a phone that is ready, and shows which step is missing.

### Upgrading
- **From v1.2.2:** open **Settings → About & Updates**, then **Check for updates**, then **Restart & install**. Nothing else is needed on any system.
- **From older versions:** download the release and replace your app folder, keeping `config.json` and the `output` folder.
  - On Mac and Linux, run `./install.sh` once in the new folder.

---

## [v1.2.2] - 2026-10-21

### Deleting media
- **Delete Permanently** is now in the right-click menu, next to the new **Move to Recycle Bin** (which has **Undo**). Keyboard shortcuts: `Del` and `Shift+Del`.
- Each Recycle Bin item has its own **Delete** button, and **Delete Selected** handles several at once.
- Permanent delete really is permanent:
  - The file is removed, along with its thumbnails and video previews;
  - Every record of it is removed too;
  - No list of deleted files is kept.
- If a deleted file is still on your phone, the next sync downloads it again. The delete warning says so.
- Recycle Bin rows are tidier: chat, size, and reason line up in columns, even for long group names.
- Restoring from the Recycle Bin now puts the item back in the gallery with its original details. Before, it only went back to the folder on disk.

### Show in File Explorer / Finder
- The file is now selected in its folder. Before, the folder opened without the file highlighted, especially for chats with a comma in the name.
- The button is labelled for your system: **File Explorer** on Windows, **Finder** on Mac, **Files** on Linux.

### Importing older media
- Media in your Recycle Bin is not brought back by an import.
- The older folder's own Recycle Bin is not imported.
- If the older folder has a different WhatsApp backup key, your current key is kept unless you choose to replace it.
- Selecting your own output folder, even through a shortcut or another drive letter, is refused.
- A cancelled import only lists files that actually arrived.

### Safer closing and multiple tabs
- Closing the browser no longer interrupts an import, ZIP backup, phone cleanup, or restore. The app finishes it first, then closes.
- Opening the app twice for the same library now reuses the running app instead of starting a second copy.
- Several open tabs stay in step: changes in one tab (recycle, restore, import, settings) show up in the others.
- The duplicate detection setting is now shared by every tab and browser.
- The idle timeout setting works again. `0` keeps the app running until you press Exit.
- Opening the app twice in quick succession could make one copy crash on startup with "database is locked". Fixed.

### Interface
- The right-click menu no longer closes by itself.
- Media Properties shows the chat name instead of "Unknown Chat".
- Long chat names take at most two lines and show the full name on hover.
- On laptop-sized windows the top-bar buttons become icons.
- On half-screen windows the chat list slides in from the side.

### Privacy
- On Mac and Linux, starting the app no longer contacts the internet. Tools and dependencies are only downloaded during setup, or on the first launch after they change.

### Mac and Linux
- **USB phone sync and video features now work without Homebrew.** Before, you had to run `brew install android-platform-tools` and `brew install ffmpeg` yourself. Without them, phone sync, video thumbnails, video previews and video duplicate checks didn't work.
  - Setup downloads Google's official ADB (the same one the Windows version includes) into the app folder if you don't already have ADB.
  - ffmpeg is installed with the other dependencies.
  - A Homebrew ADB or ffmpeg you already have is used instead.
  - The launcher shows whether ADB and ffmpeg are ready each time it starts.
  - On ARM Linux (such as a Raspberry Pi), Google doesn't publish ADB, so install it with `sudo apt install adb`.
- The setup commands now paste correctly into the Mac Terminal. Before, pasting them failed with `zsh: number expected`.
- Apple Silicon and Intel Macs are both supported.
- The app now starts in about a second on Mac, instead of about 30 seconds.
- `install.sh` and `start_gallery.sh` now run straight after cloning or downloading the source.
- New automated tests run on Windows, macOS, and Linux for every update. They install the app like a user would and test it in a real browser.

### Upgrading
- **From v1.2.1:** Open **Settings → About & Updates**, then **Check for updates**, then **Restart & install**.
  - On Mac and Linux, close the app and start it once with `./start_gallery.sh` afterwards. That launch installs ffmpeg and downloads ADB.
- **From older versions:** Download the release and replace your app folder, keeping `config.json` and the `output` folder.
  - On Mac and Linux, run `./install.sh` once in the new folder.

---

## [v1.2.1] - 2026-10-21

## What's new in v1.2.1

### Version and updates
- The app now shows its version. Look for the badge next to the title, or open **Settings → About & Updates**.
- You can update from inside the app:
  - **Check for updates** shows the newest release and what changed.
  - **Download update** downloads it and verifies it. Nothing is installed yet.
  - **Restart & install** installs it and restarts the app.
- An update is refused while a phone sync, an import, a phone cleanup, a restore or a ZIP backup is running.
- While the update installs, every open tab shows an "Installing update" screen and reloads by itself when the new version is ready.
- If the new version fails to start, the app restores the previous version automatically.
- If an install is interrupted by a crash or power cut, it is rolled back the next time the app starts.
- Your settings, backup key, databases and media are never touched by an update.
- Copies installed with Git (`git pull`) and releases that need new Python packages are not updated in the app. You get a link to download them manually.

### Privacy
- The app goes online only when you press **Check for updates**.
- **Check for updates automatically** is optional, off by default, and runs at most once a day.
- A check is one anonymous request to GitHub. It carries no version number, account, phone, chat or media information. GitHub only sees your IP address.
- Fonts are now bundled with the app. Before, opening the gallery loaded a font from Google on every launch, which went against the "fully offline" promise.

### Fixes
- After a restart the app now keeps its usual port. It could previously move to the next one (for example 8001) on Linux and macOS.
- An interrupted update can no longer delete an original file that had not been backed up.

### Includes everything from v1.2.0
- Working folder picker, real progress bar, and copy or move when importing older media.
- A faster Start Sync with a preflight checklist.
- Multi-select in the Recycle Bin.
- Faster syncs.

### Upgrading
This is the first version with the updater, so v1.2.0 and older must be updated manually, once. Download the release and replace your app folder, keeping your `config.json` and `output` folder.
From this version on, you can update from **Settings → About & Updates**.

---

## [v1.2.0] - 2026-10-20

**Import older media**
- The **Browse** button now works on Windows. The chosen folder fills the path box and the analysis shows automatically. If the picker can't open, you get a message telling you to paste the path.
- New **Copy / Move** option. Move on the same drive is near-instant, and across drives each file is verified before the original is deleted. Copy is still the default.
- The progress bar is now real. It shows files and MB done, speed, time left and the current file.
- Imports run in the background and can be cancelled. Files already transferred are kept and added to the gallery.
- An interrupted copy no longer leaves half-written files behind.
- Import and sync can't run at the same time.

**Start Sync**
- The phone connection and WhatsApp backups are checked in the background, so Start Sync opens quickly.
- A checklist shows what is being checked: phone, accounts and backups.
- Fixed "no backup found" appearing after importing older media.
- Fixed Start Sync launching twice.

**Recycle Bin**
- Multi-select, with a working **Restore Selected** button.

**Faster syncs**
- Gallery updates during a sync are about 3× faster per update, with fewer updates overall.
- Chats created mid-sync open straight away.
- WhatsApp's dated daily backup copies are skipped, so less data is pulled from the phone.
- Decryption is skipped when your backup and key haven't changed.
- The already-pulled check no longer scans the whole app folder.
- Your phone number lookup is cached per phone.

**Under the hood**
- The 18,000-line `gallery.html` is split into modular CSS and JS files in `gallery_assets/`.
- Fixed several frontend bugs.
- Added about 50 new automated tests.

---

## [v1.1.0] - 2026-10-20

### What's Changed in v1.1.0

* Dedicated Phone Storage Reclaim Studio inside the main gallery with 3 cleanup strategies (Smart Reclaim, Video Offload, Custom Profile), visual indicators of what stays on phone vs. PC, and a fine-tuning drawer.
* Safety-first pre-flight backup verification that confirms every single file targeted for deletion is intact on the PC before sending any ADB deletion command to the phone.
* Direct sidebar chat targeting allowing you to select or exclude individual chats for phone cleanup with live selection count badges and bulk toggles.
* Two-way USB sync ("Push to Phone") to restore selective chat media back to Android, triggering native media scanner broadcasts so files appear in the phone's gallery immediately without rebooting.
* Multi-account and Dual Messenger directory routing supporting standard WhatsApp, WhatsApp Business, Samsung Dual Messenger, App Clone, and Android Work Profiles.
* Background video duplicate detection prioritizing the currently selected chat without freezing or interrupting gallery navigation.
* 3-frame visual video sampling at 25%, 50%, and 75% duration with 64-bit luminance hashes to confirm visual matches before grouping video duplicates.
* Synchronized side-by-side video comparison lightbox with simultaneous playback, seeking, keeper swapping, and direct move-to-Recycle-Bin actions.
* Layered image duplicate heuristics with tighter perceptual hash thresholds and compression ratio checks, eliminating false positives from burst camera shots and sequential takes.
* Elimination of blind timestamp and counter pairing fallbacks so forwarded albums and batch-received media are no longer falsely flagged as duplicates.
* In-gallery Duplicates Recycle Bin that safely quarantines deleted copies in a local folder with options to review, restore files to their original chat folders, or empty permanently.
* Reversible "Keep Both" duplicate dismissal with an Ignored Pairs review tab and Ctrl+Z undo support.
* Global keyboard shortcuts including Ctrl+A for fast select/deselect all, Ctrl+C to copy relative media paths to clipboard, Escape to dismiss modals, and click-outside deselection.
* Adaptive heartbeat polling that scales down to a 15-second idle pulse and speeds up only during active transfers, cutting background network overhead by over 80%.
* Native dark mode dropdown styling for select and option elements, preventing bright white popups on Windows Chromium browsers.
* Transcoded preview playback in the comparison lightbox for legacy or unplayable video containers like AVI, MKV, and 3GP.
* Automatic image preloading for the WhatsApp end-to-end setup guide carousel, ensuring phone mockups switch instantly between slides without lag.
* Clear first-time welcome card for new installations with zero chats, providing direct buttons to start phone sync, import older backups, or view the setup guide.
* Immediate progress feedback upon clicking Start Sync, transitioning straight to the progress view with live status messages instead of a frozen spinner.
* Incremental backup migration engine that recognizes previously organized media folders so users upgrading versions only download newer media files.
* Fixed HTTP 206 video range streaming in the local server to prevent black screens, player hangs, or socket resets during video seeking.
* Full-resolution media loading in the lightbox with proper URL encoding, replacing low-resolution thumbnails with original photos and videos.
* Catalog export optimization with in-memory video frame caching to eliminate freezes when finalizing large media archives.
* Browser Back and Forward button history navigation that cleanly closes open lightboxes, duplicate viewers, and modals without closing or reloading the tab.
* Multi-account unmatched media routing that preserves folder categories under unindexed media instead of dumping files into the root folder.
* Automatic filtering of web link preview cache files (.Links) so preview junk never gets pulled into the saved media archive.
* Contact name resolution from decrypted wa.db tables with 10-digit phone suffix matching, correctly displaying saved phonebook names instead of raw phone numbers.
* Live WhatsApp backup freshness indicator in the sync modal that checks backup age on the phone and prompts users to tap "Back up" before syncing recent chats.
* Many UI bugs fixed.
* Comprehensive test suite expanded to 149 passing automated unit and integration tests covering the full pipeline.

---

## [v1.0.5.1] - 2026-09-07

* Bundled a static `ffmpeg.exe` binary to guarantee server-side video thumbnail generation across all formats, paired with an in-browser canvas snapshot fallback.
* Implemented a 4-stage phone number discovery pipeline (SIM querying, AccountManager inspection, and SQLite registration JID extraction) to resolve masked account names on devices like Samsung OneUI.
* Introduced Media Union scanning for multi-account setups to capture 100% of files across both legacy root (`/WhatsApp/Media`) and account-specific directories without duplication.
* Added automatic USB reconnect handling that resumes interrupted sync sessions immediately upon device reconnection.
* Accelerated in-session resumes by caching device file inventories and skipping redundant database pulls and decryption.
* Resolved onboarding stalls by automatically prompting account selection on multi-account devices before starting sync.
* Stabilized the gallery filter panel with a scroll runway guard, input focus protection, gesture intent detection, and optimized transition easing.
* Hardened Windows configuration saves with retry backoff to eliminate `[WinError 5] Access is denied` file-locking conflicts.
* Fixed phase progress counter reset glitches during database extraction.
* Fixed the account selector modal reappearing bug.

---

## [v1.0.4] - 2026-09-06

- Added recursive detection for WhatsApp native multi-account directories (`Android/media/com.whatsapp/WhatsApp/accounts/*`). Fixes an issue on Samsung Galaxy and modern Android devices where backup synchronization stalled for 4 minutes due to active backups residing in sub-folders (e.g. `accounts/1002`) while a stale `.crypt14` file lingered in the root directory.
- Added first-class detection and synchronization for WhatsApp Business alongside personal WhatsApp.
- Auto-discovers cloned and secondary user spaces, including Samsung Dual Messenger (`user 95`), Xiaomi Dual Apps (`user 999`), Parallel Spaces, and Work Profiles.
- Queries Android's AccountManager over ADB shell to identify registered phone numbers for all accounts, presenting recognizable phone numbers (e.g. `+91 98765 43210`) in the UI rather than internal opaque folder names.
- Introduced a dedicated Account Selector modal (`#modalAccountSelector`) and an active account status badge in the Device Status modal, allowing users to inspect and switch between multiple detected accounts on connected devices.
- Persists the selected account path, ID, and phone number in `config.json` (`selected_account_path`), guaranteeing subsequent syncs strictly adhere to the chosen account to prevent accidental cross-account overwrites.
- Media is strictly pulled from the companion `Media/` folder within the selected account directory, preventing cross-contamination between personal and business or multi-account archives.
- Hardened shell discovery and tar streaming routines to preserve paths with spaces (e.g. `WhatsApp Business`) and prioritize modern `.crypt15` files over legacy backups during account scoring.
- Automatically re-checks connected phone storage during the 4-minute backup wait loop to instantly pick up newly generated account backups even if they were created after the initial scan.

---

## [v1.0.3] - 2026-09-06

- Resolved a false-positive hardware detection issue where internal PC Bluetooth adapters and USB peripherals were misidentified as connected Android devices.
- Added USB vendor recognition and brand-tailored onboarding guides for Nothing Phone, Infinix, TCL, and Fairphone devices.
- Refactored the onboarding cable connection illustration to be state-reactive, dynamically reflecting disconnected, authorizing, and ready states based on live hardware events.
- Implemented automatic ADB polling (up to 4 minutes) to wait for WhatsApp to finish generating modern End-to-End Encrypted backups (`.crypt15`), preventing premature sync failures when older legacy backups are present.
- Added strict SQLite magic header validation during database decryption to proactively detect file corruption or mismatched encryption keys.
- Enhanced the onboarding flow with automatic progression to the WhatsApp Key Guide immediately upon successful ADB authorization, now updated to 12 guided steps.
- Upgraded the 1-tap mobile key transfer interface (`/paste-key`) with real-time USB connection heartbeat detection, automatic key persistence, and an automated tab-close countdown.
- Slashed the Windows Portable ZIP archive size from ~84 MB down to ~35 MB by replacing heavy runtime dependencies with an optimized pure-NumPy DCT implementation and stripping non-runtime package overhead.
- Added strict Python environment isolation (`PYTHONNOUSERSITE=1`) to portable launchers and build scripts to prevent host system library conflicts.

---

## [v1.0.2] - 2026-09-05

- Expanded the onboarding tutorial carousel from 8 to 11 comprehensive steps, covering every essential WhatsApp backup and key generation screen.
- Implemented a two-stage guided interaction for Step 11 (confirming initial backup creation, followed by secure retrieval of the 64-digit key).
- Refined all tutorial slide imagery with high-efficiency WebP assets to improve modal responsiveness and reduce initial load times.
- Enhanced ADB connection state animations and device detection transitions inside the setup guide.
- Accelerated Windows Portable ZIP extraction times significantly by removing pip and non-essential build packages, and bundling pure-Python libraries into an internal zipimport archive.
- Applied general UI/UX polish and resolved minor layout bugs across the gallery interface and onboarding modals.

---

## [v1.0.1] - 2026-09-05

- Initial public release of WhatsApp Offline Media Gallery.
- Fully offline, private, zero-install portable package for Windows with bundled Python 3.13, Google ADB, and dependencies.
- Companion shell scripts (`install.sh`, `start_gallery.sh`) for macOS and Linux.
- End-to-end encrypted backup decryption (`.crypt12`, `.crypt14`, `.crypt15`) using 64-digit hex key.
- Offline gallery UI with search, date filters, media categories, and chat organization.
