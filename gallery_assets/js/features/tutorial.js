/* Interactive setup and onboarding tutorial
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */


/* ==========================================================================
   INTERACTIVE SETUP & ONBOARDING TUTORIAL CONTROLLER
   ========================================================================== */
let activeTutTab = 'phone';
let activeTutSlide = 0;
let activeTutOem = 'generic';  // until the phone is recognised or the user picks a brand
let tutDevicePollInterval = null;
let tutKeyStatusPollTimer = null;
let tutOemDetected = false;
let tutUserManuallySelectedOem = false;
let tutDetectedModel = '';  // the model name USB detection found (before ADB can read it)
let tutHasAutoSwitchedToKey = false;
let tutUserManuallySelectedTab = false;

const TUTORIAL_SLIDES_DATA = [
    {
        badge: 'Step 1 of 12',
        title: 'Open WhatsApp Settings',
        desc: 'On your Android phone, open WhatsApp. Tap the <strong>3-dot menu</strong> (top right) and select <strong>Settings</strong>. If your WhatsApp has a <strong>You</strong> tab at the bottom right, see the tip below.',
        alert: {
            type: 'tip',
            icon: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><path d="M12 16v-4"></path><path d="M12 8h.01"></path></svg>',
            title: 'Newer WhatsApp with a "You" tab?',
            text: 'If the bottom-right tab is <strong>You</strong>, the 3-dot menu has no Settings. Tap <strong>You</strong> instead: that page is the Settings page. Swipe up a little, tap <strong>Chats</strong>, and continue from step 3. '
                + '<button type="button" class="wag-link" onclick="toggleTutYouVersion()">Show the \u201cYou\u201d version</button>'
        }
    },
    {
        badge: 'Step 2 of 12',
        title: 'Select "Chats"',
        desc: 'In WhatsApp Settings, scroll slightly down and tap <strong>Chats</strong> (located between Account and Notifications).',
        alert: null
    },
    {
        badge: 'Step 3 of 12',
        title: 'Select "Chat backup"',
        desc: 'Scroll all the way to the bottom of the Chats screen and tap <strong>Chat backup</strong>.',
        alert: null
    },
    {
        badge: 'Step 4 of 12',
        title: 'Open "End-to-end encrypted backup"',
        desc: 'At the bottom of the Chat backup screen, tap <strong>End-to-end encrypted backup</strong>.',
        alert: {
            type: 'warning',
            icon: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>',
            title: 'Upload in Progress &amp; Existing Key Note',
            text: 'If a Google Drive backup is currently uploading or preparing, the "End-to-end encrypted backup" option will be greyed out; wait for the upload to complete. If already turned on with a forgotten password, tap "Turn off" first, then turn it back on to generate a fresh 64-digit key.'
        }
    },
    {
        badge: 'Step 5 of 12',
        title: 'Tap "More options" (Crucial Step)',
        desc: 'On the setup screen, tap <strong>More options</strong> at the bottom of the page.',
        alert: {
            type: 'danger',
            icon: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>',
            title: 'CRITICAL: Do NOT Tap "Use passkey"!',
            text: 'Passkeys are tied to device biometrics and CANNOT decrypt your database on PC. You MUST tap "More options" at the bottom to generate the 64-digit encryption key.'
        }
    },
    {
        badge: 'Step 6 of 12',
        title: 'Select "Use 64-digit encryption key"',
        desc: 'In the options dialog, select <strong>Use 64-digit encryption key</strong>. WhatsApp provides this key specifically for physical backup access.',
        alert: null
    },
    {
        badge: 'Step 7 of 12',
        title: 'Generate Your 64-Digit Key',
        desc: 'Tap the green button <strong>Generate your 64-digit key</strong> (or "Turn on"). WhatsApp will generate your 16-block hexadecimal key.',
        alert: null
    },
    {
        badge: 'Step 8 of 12',
        title: 'Long-Press Table & Tap "Copy"',
        desc: 'WhatsApp displays your 64-digit key in a 16-block grid. <strong>Press and hold anywhere inside the key box</strong> until the floating menu appears, then tap <strong>Copy</strong>.',
        alert: {
            type: 'tip',
            icon: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="8" height="4" x="8" y="2" rx="1" ry="1"></rect><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"></path><path d="m9 14 2 2 4-4"></path></svg>',
            title: 'Key Copied to Phone Clipboard',
            text: 'Your phone now holds the 64-digit key in its clipboard. Proceed to the next step to confirm and save it in WhatsApp.'
        }
    },
    {
        badge: 'Step 9 of 12',
        title: 'Tap "Continue"',
        desc: 'After copying your 64-digit key to clipboard, tap the green <strong>Continue</strong> button at the bottom of the screen.',
        alert: null
    },
    {
        badge: 'Step 10 of 12',
        title: 'Confirm "I Saved My 64-digit Key"',
        desc: 'WhatsApp prompts to verify that you have safely stored your key. Tap <strong>"I Saved My 64-digit Key"</strong> to confirm.',
        alert: null
    },
    {
        badge: 'Step 11 of 12',
        title: 'Tap "Create" on Phone',
        desc: 'Look at your mobile device and tap the green <strong>Create</strong> button (highlighted on the left). WhatsApp will start generating your encrypted backup in the background.',
        alert: {
            type: 'tip',
            icon: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>',
            title: 'Backup Generates in Background',
            text: 'Tapping Create initiates the WhatsApp encryption process. Proceed to Step 12 to transfer your key while it finishes.'
        }
    },
    {
        badge: 'Step 12 of 12',
        title: 'Send Key to PC while Backup Finishes',
        desc: 'Your phone now displays the <em>"Backing up..."</em> screen with the spinning progress circle. While WhatsApp finishes packaging your messages, transfer the 64-digit key copied in Step 8 to your PC.',
        alert: {
            type: 'tip',
            icon: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>',
            title: 'Pro-Tip for Future Incremental Syncs',
            text: 'Your 64-digit key never expires. Whenever you sync in the future, open WhatsApp on your phone (Settings &gt; Chats &gt; Chat backup) and tap "Back up" right before syncing so WhatsApp creates a fresh database containing all messages up to that minute.'
        }
    }
];

// How to turn on USB debugging, per brand. Checked against current sources (October 2026): the
// brands' own help pages where they exist (Samsung, Google, Asus, Huawei, Honor), otherwise recent
// guides. Menu paths move between OS versions, so where sources disagree both are named, and every
// brand gets the "search Settings" tip and a web search for the exact model.
// Keys match core/adb.py BRAND_KEYWORDS (the phone's USB vendor picks the brand automatically).
const brandPath = (path) => `<strong>${path}</strong>`;
const PHONE_BRANDS = [
    { key: 'samsung', label: 'Samsung Galaxy', search: 'Samsung Galaxy', steps: [
        { title: 'Tap Build number 7 times', text: `Open ${brandPath('Settings › About phone › Software information')} and tap ${brandPath('Build number')} 7 times. Enter your PIN if asked.` },
        { title: 'Open Developer options', text: `Go back to ${brandPath('Settings')}: ${brandPath('Developer options')} is now at the very bottom.` },
        { title: 'Turn on USB debugging', text: `Turn on ${brandPath('USB debugging')} and tap OK.` }],
      note: `USB debugging greyed out or switching itself off? Turn off ${brandPath('Auto Blocker')} (Settings › Security and privacy › Auto Blocker). It blocks commands over USB cables.` },
    { key: 'xiaomi', label: 'Xiaomi / Redmi / POCO', search: 'Xiaomi HyperOS', steps: [
        { title: 'Tap OS version 7 times', text: `Open ${brandPath('Settings › About phone')} and tap ${brandPath('OS version')} (HyperOS) or ${brandPath('MIUI version')} 7 times, until it says you are a developer. Enter your PIN if asked.` },
        { title: 'Open Developer options', text: `Go to ${brandPath('Settings › Additional settings › Developer options')}.` },
        { title: 'Turn on USB debugging', text: `Turn on ${brandPath('USB debugging')} and confirm.` }],
      note: `For "Do it for me" (the app tapping on the phone) also turn on ${brandPath('USB debugging (Security settings)')} in Developer options. Xiaomi only allows it when you are signed in to a Xiaomi account and a SIM card is in; restart the phone afterwards.` },
    { key: 'oneplus', label: 'OnePlus', search: 'OnePlus OxygenOS', steps: [
        { title: 'Tap Build number 7 times', text: `Open ${brandPath('Settings › About device › Version')} and tap ${brandPath('Build number')} 7 times. Enter your PIN if asked.` },
        { title: 'Open Developer options', text: `Go to ${brandPath('Settings › System settings › Developer options')} (older OxygenOS: ${brandPath('Settings › Additional settings')}).` },
        { title: 'Turn on USB debugging', text: `Turn on ${brandPath('USB debugging')} and tap OK.` }] },
    { key: 'oppo', label: 'OPPO', search: 'OPPO ColorOS', steps: [
        { title: 'Tap Build number 7 times', text: `Open ${brandPath('Settings › About device › Version')} and tap ${brandPath('Build number')} 7 times. Enter your PIN if asked.` },
        { title: 'Open Developer options', text: `Go to ${brandPath('Settings › System settings › Developer options')} (on some models: ${brandPath('Settings › Additional settings')}).` },
        { title: 'Turn on USB debugging', text: `Turn on ${brandPath('USB debugging')} and tap OK.` }] },
    { key: 'realme', label: 'realme', search: 'realme UI', steps: [
        { title: 'Tap Build number 7 times', text: `Open ${brandPath('Settings › About device')} (or About phone) › ${brandPath('Version')} and tap ${brandPath('Build number')} 7 times. Enter your PIN if asked.` },
        { title: 'Open Developer options', text: `Go to ${brandPath('Settings › Additional settings › Developer options')} (newer realme UI: ${brandPath('Settings › System settings')}).` },
        { title: 'Turn on USB debugging', text: `Turn on ${brandPath('USB debugging')} and tap OK.` }] },
    { key: 'vivo', label: 'vivo / iQOO', search: 'vivo Funtouch OS', steps: [
        { title: 'Tap Software version 7 times', text: `Open ${brandPath('Settings › About phone')} and tap ${brandPath('Software version')} 7 times (some models need a few more). Enter your PIN if asked.` },
        { title: 'Open Developer options', text: `Go to ${brandPath('Settings › System management › Developer options')} (on some models: ${brandPath('Settings › System')} or ${brandPath('More settings')}).` },
        { title: 'Turn on USB debugging', text: `Turn on ${brandPath('USB debugging')} and tap OK.` }] },
    { key: 'motorola', label: 'Motorola / Lenovo', search: 'Motorola', steps: [
        { title: 'Tap Build number 7 times', text: `Open ${brandPath('Settings › About phone')} and tap ${brandPath('Build number')} 7 times (at the bottom). Enter your PIN if asked.` },
        { title: 'Open Developer options', text: `Go to ${brandPath('Settings › System › Developer options')}.` },
        { title: 'Turn on USB debugging', text: `Turn on ${brandPath('USB debugging')} and tap OK.` }] },
    { key: 'pixel', label: 'Google Pixel', search: 'Google Pixel', steps: [
        { title: 'Tap Build number 7 times', text: `Open ${brandPath('Settings › About phone')} and tap ${brandPath('Build number')} 7 times (at the bottom). Enter your PIN if asked.` },
        { title: 'Open Developer options', text: `Go to ${brandPath('Settings › System › Developer options')}.` },
        { title: 'Turn on USB debugging', text: `Turn on ${brandPath('USB debugging')} and tap OK.` }] },
    { key: 'nothing', label: 'Nothing / CMF', search: 'Nothing Phone', steps: [
        { title: 'Tap Build number 7 times', text: `Open ${brandPath('Settings › About phone')}, tap the ${brandPath('Nothing OS')} tile at the top, then tap ${brandPath('Build number')} 7 times. Enter your PIN if asked.` },
        { title: 'Open Developer options', text: `Go to ${brandPath('Settings › System › Developer options')}.` },
        { title: 'Turn on USB debugging', text: `Turn on ${brandPath('USB debugging')} and tap OK.` }] },
    { key: 'honor', label: 'Honor', search: 'Honor MagicOS', steps: [
        { title: 'Tap Build number 7 times', text: `Open ${brandPath('Settings › About phone')} and tap ${brandPath('Build number')} 7 times (on some versions: tap the ${brandPath('Version')} number). Enter your PIN if asked.` },
        { title: 'Open Developer options', text: `Go to ${brandPath('Settings › System & updates › Developer options')}.` },
        { title: 'Turn on USB debugging', text: `Turn on ${brandPath('USB debugging')} and tap OK.` }],
      note: `When you plug in the cable, choose ${brandPath('File transfer')} in the USB notification.` },
    { key: 'huawei', label: 'Huawei', search: 'Huawei HarmonyOS EMUI', steps: [
        { title: 'Tap Build number 7 times', text: `Open ${brandPath('Settings › About phone')} and tap ${brandPath('Build number')} (EMUI) or ${brandPath('HarmonyOS version')} 7 times. Enter your PIN if asked.` },
        { title: 'Open Developer options', text: `Go to ${brandPath('Settings › System & updates › Developer options')} (or ${brandPath('Settings › System')}).` },
        { title: 'Turn on USB debugging', text: `Turn on ${brandPath('USB debugging')} and tap OK.` }],
      note: `When you plug in the cable, choose ${brandPath('Transfer files')} in the USB notification (Huawei's own advice; with "Charge only" the phone is not found).` },
    { key: 'transsion', label: 'Tecno / Infinix / itel', search: 'Tecno Infinix', steps: [
        { title: 'Tap Build number 7 times', text: `Open ${brandPath('Settings › My phone')} (or About phone) and tap ${brandPath('Build number')} 7 times. Enter your PIN if asked.` },
        { title: 'Open Developer options', text: `Go to ${brandPath('Settings › System › Developer options')} (on some models: ${brandPath('Additional settings')}).` },
        { title: 'Turn on USB debugging', text: `Turn on ${brandPath('USB debugging')} and tap OK.` }],
      note: `If Developer options also has ${brandPath('USB debugging (Security settings)')}, turn it on for "Do it for me".` },
    { key: 'sony', label: 'Sony Xperia', search: 'Sony Xperia', steps: [
        { title: 'Tap Build number 7 times', text: `Open ${brandPath('Settings › About phone')} and tap ${brandPath('Build number')} 7 times. Enter your PIN if asked.` },
        { title: 'Open Developer options', text: `Go to ${brandPath('Settings › System › Developer options')}.` },
        { title: 'Turn on USB debugging', text: `Turn on ${brandPath('USB debugging')} and tap OK.` }] },
    { key: 'asus', label: 'Asus / ROG Phone', search: 'Asus Zenfone', steps: [
        { title: 'Tap Build number 7 times', text: `Open ${brandPath('Settings › About phone › Software information')} and tap ${brandPath('Build number')} 7 times. Enter your PIN if asked.` },
        { title: 'Open Developer options', text: `Go to ${brandPath('Settings › System › Developer options')}.` },
        { title: 'Turn on USB debugging', text: `Turn on ${brandPath('USB debugging')} and tap OK.` }] },
    { key: 'nokia', label: 'Nokia / HMD', search: 'Nokia', steps: [
        { title: 'Tap Build number 7 times', text: `Open ${brandPath('Settings › About phone')} and tap ${brandPath('Build number')} 7 times. Enter your PIN if asked.` },
        { title: 'Open Developer options', text: `Go to ${brandPath('Settings › System › Developer options')}.` },
        { title: 'Turn on USB debugging', text: `Turn on ${brandPath('USB debugging')} and tap OK.` }] },
    { key: 'generic', label: 'Other brand / not listed', search: 'Android', steps: [
        { title: 'Tap Build number 7 times', text: `Open ${brandPath('Settings › About phone')} and tap ${brandPath('Build number')} 7 times (it may be under Software information or Version). Enter your PIN if asked.` },
        { title: 'Open Developer options', text: `Look in ${brandPath('Settings › System')} (or Additional settings, or at the bottom of Settings) for ${brandPath('Developer options')}.` },
        { title: 'Turn on USB debugging', text: `Turn on ${brandPath('USB debugging')} and tap OK.` }] },
];
const PHONE_BRAND_BY_KEY = Object.fromEntries(PHONE_BRANDS.map(b => [b.key, b]));

function phoneBrand(key) {
    return PHONE_BRAND_BY_KEY[key] || PHONE_BRAND_BY_KEY.generic;
}

// A web search for this exact phone, for when the steps above look different on it
function usbDebuggingSearchUrl(brandKey, model) {
    const brand = phoneBrand(brandKey);
    const what = [brand.key === 'generic' ? '' : brand.search, model || ''].filter(Boolean).join(' ') || 'Android phone';
    return 'https://www.google.com/search?q=' + encodeURIComponent(`how to turn on USB debugging ${what}`);
}

// Older name, still used by some callers: brand -> its steps
const OEM_INSTRUCTIONS = Object.fromEntries(PHONE_BRANDS.map(b => [b.key, b.steps]));

function handleTutImgError(img) {
    // If WebP is served via static file protocol or missing, try core assets once.
    // The fallback URL also contains '/assets/tutorial/', so guard against an endless onerror loop.
    const src = img.getAttribute('src') || '';
    if (src.indexOf('/assets/tutorial/') === -1) return;
    const fallback = 'core/assets/tutorial/' + src.substring(src.lastIndexOf('/') + 1);
    if (src === fallback) return;
    img.src = fallback;
}

const _preloadedTutImages = {};
function preloadTutorialImages() {
    for (let i = 0; i < 12; i++) {
        if (!_preloadedTutImages[i]) {
            const im = new Image();
            im.src = '/assets/tutorial/wa_step' + i + '.webp';
            _preloadedTutImages[i] = im;
        }
    }
    TUT_YOU_PICTURES.forEach((src, i) => {
        if (!_preloadedTutImages['you' + i]) {
            const im = new Image();
            im.src = src;
            _preloadedTutImages['you' + i] = im;
        }
    });
}

async function openTutorialModal(tab = null, slide = 0) {
    tutHasAutoSwitchedToKey = false;
    tutUserManuallySelectedTab = false;
    tutUserManuallySelectedOem = false;
    tutOemDetected = false;
    preloadTutorialImages();
    initTutStoryBars();
    switchTutOem(rememberedTutBrand() || activeTutOem);

    if (tab) {
        switchTutTab(tab, true);
    } else {
        // If device is already connected and authorized, default to key guide
        if (currentDeviceStatus && currentDeviceStatus.connected && currentDeviceStatus.authorized) {
            switchTutTab('key', false);
        } else {
            switchTutTab('phone', false);
        }
    }

    setTutSlide(slide);
    openModal('modalTutorial');

    // Detect OEM hardware
    if (isHttpServer) {
        try {
            const r = await fetch('/api/phone/oem');
            if (r.ok) {
                const info = await r.json();
                if (info && info.model) tutDetectedModel = info.model;
                if (info && info.oem_key && info.oem_key !== 'generic' && !tutUserManuallySelectedOem) {
                    tutOemDetected = true;
                    switchTutOem(info.oem_key, true, false);
                }
            }
        } catch (e) {}
    }

    // Start live ADB polling in Tutorial 1
    tutPollDeviceStatus();
    if (tutDevicePollInterval) clearInterval(tutDevicePollInterval);
    tutDevicePollInterval = setInterval(tutPollDeviceStatus, 1500);
}

function switchTutTab(tab, isUserAction = true) {
    activeTutTab = tab;
    if (isUserAction) {
        if (tab === 'phone') {
            tutUserManuallySelectedTab = true;
        } else {
            tutUserManuallySelectedTab = false;
        }
    }

    const btnPhone = document.getElementById('tabTutPhone');
    const btnKey = document.getElementById('tabTutKey');
    const secPhone = document.getElementById('tutSectionPhone');
    const secKey = document.getElementById('tutSectionKey');
    const footPhone = document.getElementById('tutFooterPhone');
    const footKey = document.getElementById('tutFooterKey');

    if (tab === 'phone') {
        btnPhone.classList.add('active');
        btnKey.classList.remove('active');
        secPhone.style.display = 'flex';
        secKey.style.display = 'none';
        if (footPhone) footPhone.style.display = 'flex';
        if (footKey) footKey.style.display = 'none';
    } else {
        btnKey.classList.add('active');
        btnPhone.classList.remove('active');
        secPhone.style.display = 'none';
        secKey.style.display = 'flex';
        if (footPhone) footPhone.style.display = 'none';
        if (footKey) footKey.style.display = 'flex';
        setTutSlide(activeTutSlide);
    }
    if (typeof waGuideOnTabShown === 'function') waGuideOnTabShown(tab);
}

function fillTutBrandSelect(select) {
    select.innerHTML = PHONE_BRANDS.map(b => `<option value="${b.key}">${escapeHtml(b.label)}</option>`).join('');
}

function rememberedTutBrand() {
    try {
        const key = localStorage.getItem('tutPhoneBrand');
        return PHONE_BRAND_BY_KEY[key] ? key : null;
    } catch (e) {
        return null;
    }
}

function switchTutOem(oemKey, isHardwareAuto = false, isUserManual = false) {
    if (isUserManual) {
        tutUserManuallySelectedOem = true;
    }
    activeTutOem = PHONE_BRAND_BY_KEY[oemKey] ? oemKey : 'generic';
    const select = document.getElementById('tutBrandSelect');
    if (select) {
        if (!select.options.length) fillTutBrandSelect(select);
        select.value = activeTutOem;
    }
    if (isUserManual) {
        try { localStorage.setItem('tutPhoneBrand', activeTutOem); } catch (e) {}
    }

    const badge = document.getElementById('tutOemSuggestedBadge');
    if (badge) {
        badge.style.display = (isHardwareAuto && !tutUserManuallySelectedOem) ? 'inline-block' : 'none';
    }

    renderTutOemContent(oemKey);
}

// ---------------------------------------------------------------- live connection checklist
// The phone tab shows three steps that tick themselves off from /api/device-status "stage":
//   unplugged -> usb_only -> unauthorized -> ready   (plus no_adb, no_permission, offline)
// Every step stays readable and the brand chips stay clickable, so a phone the app cannot
// recognise on USB (unknown vendor) is simply set up by following the steps by hand.

const CONNECTION_STAGE_ORDER = { unplugged: 0, usb_only: 1, no_adb: 1, unauthorized: 2, no_permission: 2, offline: 2, ready: 3 };

function connectionStageOf(st) {
    st = st || {};
    if (st.stage && st.stage in CONNECTION_STAGE_ORDER) return st.stage;
    if (st.connected && st.authorized) return 'ready';
    if (st.connected) return st.usb_debugging === false ? 'usb_only' : 'unauthorized';
    return 'unplugged';
}

function clientOsName() {
    const fm = fileManagerName();
    return fm === 'Finder' ? 'mac' : fm === 'File Explorer' ? 'windows' : 'linux';
}

// Pure: what the checklist shows for a device status. Exposed for tests.
function buildConnectionChecklist(st, oemKey, os) {
    st = st || {};
    const stage = connectionStageOf(st);
    const level = CONNECTION_STAGE_ORDER[stage];
    const secs = Number(st.stage_seconds) || 0;
    const brand = phoneBrand(oemKey);
    const brandSteps = brand.steps;  // "Allow" is checklist step 3, not repeated here
    const phoneName = st.model || st.vendor || '';

    const steps = [
        {
            key: 'plug',
            title: level >= 1 ? (phoneName ? `Phone plugged in (${phoneName})` : 'Phone plugged in') : 'Plug your phone into this computer',
            detail: 'Use a USB cable that can transfer data, not only charge.',
            substeps: [],
            hint: ''
        },
        {
            key: 'debugging',
            title: level >= 2 ? 'USB debugging is on' : 'Turn on USB debugging',
            detail: brand.key === 'generic' ? 'Do this once on your phone:' : `Do this once on your ${escapeHtml(brand.label)} phone:`,
            substeps: brandSteps,
            note: brand.note || '',
            more: `Can't find it? Search your phone's Settings for <strong>Developer options</strong>, or <a href="${escapeHtml(usbDebuggingSearchUrl(brand.key, st.model))}" target="_blank" rel="noopener noreferrer">search the web for your ${escapeHtml(st.model || (brand.key === 'generic' ? 'phone' : brand.label))}</a>.`,
            hint: ''
        },
        {
            key: 'allow',
            title: level >= 3 ? `Connected${phoneName ? ': ' + phoneName : ''}` : 'Tap "Allow" on your phone',
            detail: 'Unlock your phone. In the <strong>"Allow USB debugging?"</strong> popup, tick <strong>"Always allow from this computer"</strong> and tap <strong>Allow</strong>.',
            substeps: [],
            hint: ''
        }
    ];

    // done / active / todo. The debugging steps stay open before the cable is in (they can be
    // done first), and step 2 is the fallback for phones that only appear once debugging is on.
    const activeIndex = level >= 3 ? -1 : level === 0 ? 0 : level === 1 ? 1 : 2;
    steps.forEach((step, i) => {
        step.state = level >= 3 || i < activeIndex ? 'done' : i === activeIndex ? 'active' : 'todo';
        step.open = step.state === 'active' || (level === 0 && i === 1);
    });

    // Hints for someone who is stuck on a step
    if (stage === 'unplugged' && secs >= 20) {
        steps[0].hint = 'Already plugged in? Some phones only show up once USB debugging is on, so carry on with step 2. Otherwise try another cable or USB port.';
    }
    if (stage === 'usb_only' && secs >= 45) {
        steps[1].hint = 'Already turned it on? Unplug the cable and plug it back in. Can\'t find "Developer options"? It only appears after tapping the version or build number 7 times.'
            + (os === 'windows' && /samsung/i.test(st.vendor || st.model || '') ? ' Samsung phones on Windows may also need the Samsung USB Driver.' : '');
    }
    if (stage === 'no_adb') {
        const setup = st.tools_setup || {};
        steps[1].hint = setup.state === 'running'
            ? 'Setting up the phone tool (ADB) for this version. This takes a minute, once.'
            : os === 'windows'
            ? 'The phone tool (ADB) is missing from this app folder. Download the Windows ZIP again and extract it fully.'
            : 'The phone tool (ADB) is missing. Run <code>./install.sh</code> again in the app folder.';
    }
    if (stage === 'unauthorized' && secs >= 15) {
        steps[2].hint = 'No popup? Unlock the phone and check the notifications. Or turn USB debugging off and on again, then unplug and plug back in.';
    }
    if (stage === 'offline') {
        steps[2].hint = 'The phone stopped answering. Unplug the cable and plug it back in.';
    }
    if (stage === 'no_permission') {
        steps[2].hint = 'Linux does not let this app open the phone yet. Install the Android USB rules (Ubuntu/Debian: <code>sudo apt install android-sdk-platform-tools-common</code>), then unplug and plug back in.';
    }
    return { stage, steps };
}

function renderTutOemContent(oemKey) {
    const container = document.getElementById('tutOemContent');
    if (!container) return;
    const st = Object.assign({}, currentDeviceStatus);
    if (!st.model && tutDetectedModel && connectionStageOf(st) !== 'unplugged') st.model = tutDetectedModel;
    const model = buildConnectionChecklist(st, oemKey, clientOsName());
    const html = model.steps.map((step, i) => {
        const mark = step.state === 'done' ? '&#10003;' : String(i + 1);
        const sub = step.open && step.substeps.length ? `
                    <ol class="tut-check-substeps">${step.substeps.map(s => `<li>${s.text}</li>`).join('')}</ol>` : '';
        const extra = step.open ? (step.note ? `<div class="tut-check-note">${step.note}</div>` : '')
            + (step.more ? `<div class="tut-check-more">${step.more}</div>` : '') : '';
        const detail = step.open ? `<div class="tut-check-detail">${step.detail}</div>${sub}${extra}` : '';
        const hint = step.hint ? `<div class="tut-check-hint">${step.hint}</div>` : '';
        return `
                <div class="tut-check tut-check-${step.state}" data-step="${step.key}">
                    <div class="tut-check-mark">${mark}</div>
                    <div class="tut-check-body">
                        <div class="tut-check-title">${step.title}</div>${detail}${hint}
                    </div>
                </div>`;
    }).join('');
    if (html === container._checklistHtml) return;  // re-rendered every poll: avoid flicker
    container._checklistHtml = html;
    container.innerHTML = html;
    container.setAttribute('data-stage', model.stage);
}

async function tutPollDeviceStatus() {
    const modal = document.getElementById('modalTutorial');
    if (!modal || !modal.classList.contains('open')) {
        if (tutDevicePollInterval) {
            clearInterval(tutDevicePollInterval);
            tutDevicePollInterval = null;
        }
        return;
    }

    if (isHttpServer) {
        try {
            await checkDeviceStatus();
        } catch (e) {}
    }

    const dot = document.getElementById('tutPhoneStatusDot');
    const title = document.getElementById('tutPhoneStatusTitle');
    const sub = document.getElementById('tutPhoneStatusSub');
    const svgBox = document.getElementById('tutPhoneSvgBox');
    if (!dot || !title || !sub) return;

    const st = currentDeviceStatus || {};
    if (st.connected && st.authorized) {
        if (svgBox) svgBox.className = 'tut-svg-cable-box state-ready';
        dot.className = 'tut-pulse-indicator ready';
        title.innerText = (st.model || st.serial || 'Android Device') + ': Ready';
        sub.innerText = 'USB Debugging authorized. Proceed to WhatsApp Key guide.';

        // Auto-advance from Tutorial 1 to Tutorial 2 when ADB connection is detected
        if (activeTutTab === 'phone' && !tutHasAutoSwitchedToKey && !tutUserManuallySelectedTab) {
            tutHasAutoSwitchedToKey = true;
            sub.innerText = 'USB Debugging authorized! Opening WhatsApp Key Guide...';
            setTimeout(() => {
                const m = document.getElementById('modalTutorial');
                if (m && m.classList.contains('open') && !tutUserManuallySelectedTab) {
                    switchTutTab('key', false);
                }
            }, 800);
        }
    } else if (st.connected && !st.authorized) {
        if (svgBox) svgBox.className = 'tut-svg-cable-box state-authorizing';
        dot.className = 'tut-pulse-indicator action';
        const stage = connectionStageOf(st);
        if (stage === 'no_adb') {
            title.innerText = (st.model || 'Phone') + ' Connected: Phone Tool Missing';
            sub.innerText = 'The ADB tool this app needs was not found. See the steps below.';
        } else if (stage === 'offline' || stage === 'no_permission') {
            title.innerText = 'Device Detected: Not Responding';
            sub.innerText = 'See the tip in step 3 below.';
        } else if (st.usb_debugging === false) {
            title.innerText = (st.model || 'Phone') + ' Connected: USB Debugging OFF';
            sub.innerText = 'Phone detected, but USB Debugging is not enabled. Follow the steps below.';
        } else {
            title.innerText = 'Device Detected: Authorization Required';
            sub.innerText = 'Unlock your phone and tap "Allow USB debugging" on screen.';
        }
    } else {
        if (svgBox) svgBox.className = 'tut-svg-cable-box state-disconnected';
        dot.className = 'tut-pulse-indicator';
        title.innerText = 'No Device Detected';
        sub.innerText = 'Plug your phone into PC with a USB data cable.';
    }

    renderTutOemContent(activeTutOem);

    // Hardware suggested brand detection if plugged in and user hasn't manually selected
    // The brand is known from USB before USB debugging is on, which is when its steps are needed
    if (isHttpServer && !tutUserManuallySelectedOem && !tutOemDetected
        && (st.connected || st.authorized || connectionStageOf(st) === 'usb_only')) {
        fetch('/api/phone/oem').then(r => r.json()).then(info => {
            if (info && info.model) tutDetectedModel = info.model;
            if (info && info.oem_key && info.oem_key !== 'generic' && !tutUserManuallySelectedOem) {
                tutOemDetected = true;
                switchTutOem(info.oem_key, true, false);
            }
        }).catch(() => {});
    }
}

function initTutStoryBars() {
    const container = document.getElementById('tutStoryBars');
    if (!container) return;
    container.innerHTML = '';
    const total = TUTORIAL_SLIDES_DATA.length;
    for (let i = 0; i < total; i++) {
        const bar = document.createElement('div');
        bar.className = 'tut-story-bar';
        bar.title = 'Jump to Step ' + (i + 1);
        bar.onclick = () => setTutSlide(i);
        const fill = document.createElement('div');
        fill.className = 'tut-story-bar-fill';
        bar.appendChild(fill);
        container.appendChild(bar);
    }
}

function setTutSlide(idx) {
    const total = TUTORIAL_SLIDES_DATA.length;
    if (idx < 0) idx = 0;
    if (idx > total - 1) idx = total - 1;
    activeTutSlide = idx;

    // Update Progress Bar
    const bars = document.querySelectorAll('.tut-story-bar');
    bars.forEach((b, i) => {
        b.classList.remove('active', 'completed');
        if (i < idx) b.classList.add('completed');
        else if (i === idx) b.classList.add('active');
    });

    // Update Image
    const img = document.getElementById('tutSlideImg');
    if (img) {
        const targetSrc = '/assets/tutorial/wa_step' + idx + '.webp';
        img.style.opacity = '0.35';
        img.style.transform = 'scale(0.98)';
        const loader = new Image();
        loader.onload = () => {
            img.src = targetSrc;
            img.style.opacity = '1';
            img.style.transform = 'scale(1)';
        };
        loader.onerror = () => {
            img.src = targetSrc;
            img.style.opacity = '1';
            img.style.transform = 'scale(1)';
        };
        loader.src = targetSrc;
        if (loader.complete) {
            img.src = targetSrc;
            img.style.opacity = '1';
            img.style.transform = 'scale(1)';
        }
    }

    // Update Step Text
    const data = TUTORIAL_SLIDES_DATA[idx];
    document.getElementById('tutStepBadge').innerText = data.badge;
    document.getElementById('tutStepTitle').innerText = data.title;
    document.getElementById('tutStepDesc').innerHTML = data.desc;
    
    const countStr = 'Step ' + (idx + 1) + ' of ' + total;
    const cntFooter = document.getElementById('tutSlideCounterFooter');
    if (cntFooter) cntFooter.innerText = countStr;

    // Alerts
    const alertEl = document.getElementById('tutStepAlert');
    if (data.alert) {
        alertEl.className = 'tut-alert tut-alert-' + data.alert.type;
        alertEl.innerHTML = `
                    <div style="width:18px;height:18px;min-width:18px;margin-top:1px;display:flex;align-items:center;justify-content:center;color:currentColor;">${data.alert.icon}</div>
                    <div>
                        <div style="font-weight:700;margin-bottom:2px;">${data.alert.title}</div>
                        <div>${data.alert.text}</div>
                    </div>
                `;
        alertEl.style.display = 'flex';
    } else {
        alertEl.style.display = 'none';
    }

    // Slide 10 (Step 11) Specific USB Action Box & Footer Controls
    const usbBox = document.getElementById('tutSlide7UsbBox');
    const btnPrevFooter = document.getElementById('btnTutPrevFooter');
    const btnNextFooter = document.getElementById('btnTutNextFooter');
    const btnFinishFooter = document.getElementById('btnTutFinishFooter');

    if (btnPrevFooter) btnPrevFooter.disabled = (idx === 0);

    if (idx === total - 1) {
        if (usbBox) usbBox.style.display = 'flex';
        if (btnNextFooter) btnNextFooter.style.display = 'none';
        if (btnFinishFooter) btnFinishFooter.style.display = 'inline-flex';

        // Check if key is already configured on load of Step 12
        if (isHttpServer) {
            fetch('/api/config').then(r => r.json()).then(cfg => {
                const btnText = document.getElementById('btnTutSendUsbText');
                if (cfg && cfg.hex_key_set && btnText) {
                    btnText.innerText = 'Resend Key from Phone via USB';
                }
            }).catch(() => {});
        }
    } else {
        if (usbBox) usbBox.style.display = 'none';
        if (btnNextFooter) btnNextFooter.style.display = 'inline-flex';
        if (btnFinishFooter) btnFinishFooter.style.display = 'none';
    }
    if (typeof waGuideSyncFooter === 'function') waGuideSyncFooter();  // guided setup hides the slide controls
}

// Slide 1's tip: cycle the picture through the newer "You" tab version and back
const TUT_YOU_PICTURES = ['/assets/tutorial/wa_step_you_home.webp', '/assets/tutorial/wa_step_you_page.webp'];
function toggleTutYouVersion() {
    const img = document.getElementById('tutSlideImg');
    if (!img) return;
    const current = TUT_YOU_PICTURES.findIndex(src => img.getAttribute('src') === src);
    img.setAttribute('src', current === -1 ? TUT_YOU_PICTURES[0]
        : current + 1 < TUT_YOU_PICTURES.length ? TUT_YOU_PICTURES[current + 1] : '/assets/tutorial/wa_step0.webp');
}

function nextTutSlide() {
    if (activeTutSlide < TUTORIAL_SLIDES_DATA.length - 1) {
        setTutSlide(activeTutSlide + 1);
    }
}

function prevTutSlide() {
    if (activeTutSlide > 0) {
        setTutSlide(activeTutSlide - 1);
    }
}

async function handleSendKeyViaUsb() {
    const btn = document.getElementById('btnTutSendUsb');
    const text = document.getElementById('btnTutSendUsbText');
    const statusEl = document.getElementById('tutUsbPortalStatus');

    btn.disabled = true;
    btn.classList.remove('waiting');
    text.innerText = 'Opening portal on mobile...';
    statusEl.innerHTML = '<span style="color:var(--accent);">Setting up physical USB reverse tether...</span>';

    // Drop any previously staged key so only a key sent from the phone now counts as received
    try {
        await fetch('/api/phone/clear-received-key', { method: 'POST' });
    } catch (e) {}

    try {
        const resp = await fetch('/api/phone/open-key-portal', { method: 'POST' });
        const res = await resp.json();
        if (resp.ok && res.status === 'success') {
            btn.disabled = false;
            btn.classList.add('waiting');
            text.innerHTML = 'Waiting for Key from Phone... <span style="font-size:11px;opacity:0.8;">(Click to Re-open)</span>';
            statusEl.innerHTML = `
                        <div style="color:var(--accent);font-weight:600;display:flex;align-items:center;gap:6px;">
                            <span class="status-dot dot-ready" style="animation:pulseWarning 1s infinite;"></span>
                            Portal opened on phone! Tap "Paste &amp; Send to PC" on mobile screen...
                        </div>
                    `;
            // Start polling /api/key-status
            startTutKeyStatusPolling();
        } else {
            btn.disabled = false;
            btn.classList.remove('waiting');
            text.innerText = 'Send Key from Phone via USB';
            statusEl.innerHTML = `<span style="color:#ef4444;">Could not open portal: ${res.message || 'Check USB debugging connection.'}</span>`;
        }
    } catch (err) {
        btn.disabled = false;
        btn.classList.remove('waiting');
        text.innerText = 'Send Key from Phone via USB';
        statusEl.innerHTML = `<span style="color:#ef4444;">Network error: ${err.message}</span>`;
    }
}

function startTutKeyStatusPolling() {
    if (tutKeyStatusPollTimer) clearInterval(tutKeyStatusPollTimer);
    tutKeyStatusPollTimer = setInterval(async () => {
        const tutModal = document.getElementById('modalTutorial');
        if (!tutModal || !tutModal.classList.contains('open')) {
            clearInterval(tutKeyStatusPollTimer);
            tutKeyStatusPollTimer = null;
            return;
        }
        try {
            const resp = await fetch('/api/key-status');
            if (resp.ok) {
                const data = await resp.json();
                const btn = document.getElementById('btnTutSendUsb');
                const text = document.getElementById('btnTutSendUsbText');
                const statusEl = document.getElementById('tutUsbPortalStatus');

                if (data.device_connected === false) {
                    if (btn) {
                        btn.disabled = false;
                        btn.classList.remove('waiting');
                    }
                    if (text) text.innerText = 'Send Key from Phone via USB';
                    if (statusEl) {
                        statusEl.innerHTML = '<span style="color:#ef4444;">Phone disconnected. Please check USB cable connection.</span>';
                    }
                    return;
                }

                // hex_key_set alone would report success instantly when resending over an existing key
                if (data.received_key) {
                    clearInterval(tutKeyStatusPollTimer);
                    tutKeyStatusPollTimer = null;
                    onTutKeyReceivedSuccess(data.received_key);
                }
            }
        } catch (e) {}
    }, 1000);
}

function onTutKeyReceivedSuccess(key) {
    const statusEl = document.getElementById('tutUsbPortalStatus');
    const btn = document.getElementById('btnTutSendUsb');
    const text = document.getElementById('btnTutSendUsbText');
    if (btn) {
        btn.disabled = false;
        btn.classList.remove('waiting');
    }
    if (text) {
        text.innerText = 'Key Received! (Click to Resend)';
    }
    if (statusEl) {
        statusEl.innerHTML = `
                    <div style="background:rgba(16,185,129,0.15);border:1px solid rgba(16,185,129,0.3);border-radius:8px;padding:8px 12px;color:var(--accent);font-weight:600;display:flex;align-items:center;gap:8px;">
                        <svg viewBox="0 0 24 24" style="width:16px;height:16px;fill:currentColor;"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
                        <span>64-digit key received and saved!</span>
                    </div>
                `;
    }
    const manualInput = document.getElementById('tutManualKeyInput');
    if (manualInput && key) {
        manualInput.value = key;
    }
    if (key && key.length === 64 && isHttpServer) {
        fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ hex_key: key })
        }).then(() => checkConfigStatus()).catch(() => {});
    }
    showToast('64-digit WhatsApp key received and saved!', 'success');
    checkConfigStatus();
}

function onTutManualKeyChange(val) {
    const cleaned = val.replace(/[^0-9a-fA-F]/g, '').toLowerCase();
    const manualInput = document.getElementById('tutManualKeyInput');
    if (manualInput) manualInput.value = cleaned;

    if (cleaned.length === 64 && isHttpServer) {
        fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ hex_key: cleaned })
        }).then(r => r.json()).then(res => {
            if (res && res.status === 'success') {
                showToast('64-digit key verified and saved!', 'success');
                checkConfigStatus();
                const statusEl = document.getElementById('tutUsbPortalStatus');
                if (statusEl) {
                    statusEl.innerHTML = `
                                <div style="background:rgba(16,185,129,0.15);border:1px solid rgba(16,185,129,0.3);border-radius:8px;padding:8px 12px;color:var(--accent);font-weight:600;display:flex;align-items:center;gap:8px;">
                                    <svg viewBox="0 0 24 24" style="width:16px;height:16px;fill:currentColor;"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
                                    <span>64-digit key verified and saved!</span>
                                </div>
                            `;
                }
            }
        }).catch(() => {});
    }
}

async function finishTutorialOnboarding(autoStartSync = false) {
    let keyToSave = '';
    const manualInput = document.getElementById('tutManualKeyInput');
    if (manualInput && manualInput.value.trim().length === 64) {
        keyToSave = manualInput.value.trim();
    }

    let keyConfigured = false;
    if (isHttpServer) {
        try {
            const r = await fetch('/api/config');
            if (r.ok) {
                const cfg = await r.json();
                if (cfg && cfg.hex_key_set) {
                    keyConfigured = true;
                }
            }
        } catch (e) {}
    }

    if (!keyConfigured && !keyToSave) {
        showToast('Please transfer or paste your 64-digit WhatsApp key first before finishing.', 'error');
        if (manualInput) {
            manualInput.focus();
            manualInput.style.borderColor = '#ef4444';
            manualInput.style.boxShadow = '0 0 12px rgba(239, 68, 68, 0.4)';
            setTimeout(() => {
                manualInput.style.borderColor = '';
                manualInput.style.boxShadow = '';
            }, 2500);
        }
        return;
    }

    if (keyToSave && isHttpServer) {
        try {
            await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ hex_key: keyToSave })
            });
        } catch (e) {}
    }

    closeModal('modalTutorial');
    if (isHttpServer) {
        try {
            fetch('/api/onboarding/complete', { method: 'POST' }).catch(() => {});
        } catch (e) {}
    }
    showToast('Setup complete! Connecting to phone...', 'success');
    if (autoStartSync) {
        openSyncModal();
        showSyncView('progress');
        if (typeof updateSyncPreflightProgress === 'function') {
            updateSyncPreflightProgress('Checking phone connection...', 'Detecting Android device over ADB...', 15);
        }
        setTimeout(() => {
            startSyncFromSummary();
        }, 100);
    }
}
