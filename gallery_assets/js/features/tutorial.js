/* Interactive setup and onboarding tutorial
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */


/* ==========================================================================
   INTERACTIVE SETUP & ONBOARDING TUTORIAL CONTROLLER
   ========================================================================== */
let activeTutTab = 'phone';
let activeTutSlide = 0;
let activeTutOem = 'xiaomi';
let tutDevicePollInterval = null;
let tutKeyStatusPollTimer = null;
let tutOemDetected = false;
let tutUserManuallySelectedOem = false;
let tutHasAutoSwitchedToKey = false;
let tutUserManuallySelectedTab = false;

const TUTORIAL_SLIDES_DATA = [
    {
        badge: 'Step 1 of 12',
        title: 'Open WhatsApp Settings',
        desc: 'On your Android phone, open WhatsApp. Tap the <strong>3-dot menu</strong> (top right) or tap your <strong>Settings / Profile tab</strong> (bottom right) and select <strong>Settings</strong>.',
        alert: {
            type: 'tip',
            icon: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><path d="M12 16v-4"></path><path d="M12 8h.01"></path></svg>',
            title: 'Newer WhatsApp with Bottom Navigation Bar?',
            text: 'In newer WhatsApp versions, the 3-dot menu may not appear. Instead, tap the <strong>Settings</strong> (or <strong>"You" / Profile picture</strong>) tab located at the bottom right corner.'
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

const OEM_INSTRUCTIONS = {
    xiaomi: [
        { num: '1', title: 'Open About Phone', text: 'Go to <strong>Settings &gt; About phone</strong>.' },
        { num: '2', title: 'Tap OS / MIUI Version 7 Times', text: 'Rapidly tap <strong>OS Version</strong> (or <strong>MIUI Version</strong>) 7 times until you see "You are now a developer!".' },
        { num: '3', title: 'Open Developer Options', text: 'Return to <strong>Settings &gt; Additional settings &gt; Developer options</strong>.' },
        { num: '4', title: 'Enable USB Debugging', text: 'Turn ON <strong>USB Debugging</strong>.' },
        { num: '5', title: 'Xiaomi Special Permissions', text: 'Also enable <strong>"Install via USB"</strong> and <strong>"USB debugging (Security settings)"</strong> if available on your MIUI/HyperOS device.' },
        { num: '6', title: 'Allow PC Connection', text: 'Connect USB cable to PC. When the phone prompts "Allow USB debugging?", check <strong>"Always allow from this computer"</strong> and tap <strong>OK</strong>.' }
    ],
    samsung: [
        { num: '1', title: 'Open Software Information', text: 'Go to <strong>Settings &gt; About phone &gt; Software information</strong>.' },
        { num: '2', title: 'Tap Build Number 7 Times', text: 'Tap <strong>Build number</strong> 7 times (enter your lock screen PIN if requested).' },
        { num: '3', title: 'Open Developer Options', text: 'Return to main <strong>Settings</strong> and scroll to the very bottom to find <strong>Developer options</strong>.' },
        { num: '4', title: 'Enable USB Debugging', text: 'Toggle the switch for <strong>USB debugging</strong> to <strong>ON</strong>.' },
        { num: '5', title: 'Authorize USB on Phone', text: 'Plug in the USB cable. Check <strong>"Always allow from this computer"</strong> on the pop-up and tap <strong>Allow</strong>.' }
    ],
    oneplus: [
        { num: '1', title: 'Open Version Info', text: 'Go to <strong>Settings &gt; About device &gt; Version</strong>.' },
        { num: '2', title: 'Tap Build Number 7 Times', text: 'Tap <strong>Build number</strong> 7 times until Developer mode is unlocked.' },
        { num: '3', title: 'Open Developer Options', text: 'Go back to <strong>Settings &gt; Additional settings</strong> (or <strong>System settings</strong>) <strong>&gt; Developer options</strong>.' },
        { num: '4', title: 'Enable USB Debugging', text: 'Turn ON <strong>USB debugging</strong>.' },
        { num: '5', title: 'Authorize USB on Phone', text: 'Plug in USB cable. When prompted, check <strong>"Always allow from this computer"</strong> and tap <strong>Allow</strong>.' }
    ],
    vivo: [
        { num: '1', title: 'Open Software Information', text: 'Go to <strong>Settings &gt; About phone &gt; Software information</strong> (or <strong>More settings &gt; About phone</strong>).' },
        { num: '2', title: 'Tap Build Number 7 Times', text: 'Tap <strong>Build number</strong> (or <strong>Software version</strong>) 7 times rapidly until "You are now a developer" appears.' },
        { num: '3', title: 'Open Developer Options', text: 'Return to <strong>Settings &gt; System management</strong> (or <strong>System / More settings</strong>) <strong>&gt; Developer options</strong>.' },
        { num: '4', title: 'Enable USB Debugging', text: 'Turn ON <strong>USB debugging</strong>.' },
        { num: '5', title: 'Authorize USB on Phone', text: 'Connect USB cable to PC. When prompted "Allow USB debugging?", check <strong>"Always allow from this computer"</strong> and tap <strong>Allow</strong> (or <strong>OK</strong>).' }
    ],
    motorola: [
        { num: '1', title: 'Open About Phone', text: 'Go to <strong>Settings &gt; About phone</strong>.' },
        { num: '2', title: 'Tap Build Number 7 Times', text: 'Scroll to the very bottom and tap <strong>Build number</strong> 7 times (enter your PIN or pattern if prompted).' },
        { num: '3', title: 'Open Developer Options', text: 'Return to <strong>Settings &gt; System &gt; Developer options</strong> (or <strong>Advanced &gt; Developer options</strong>).' },
        { num: '4', title: 'Enable USB Debugging', text: 'Toggle <strong>USB debugging</strong> to <strong>ON</strong>.' },
        { num: '5', title: 'Authorize USB on Phone', text: 'Connect USB cable to PC. Check <strong>"Always allow from this computer"</strong> on the prompt and tap <strong>Allow</strong>.' }
    ],
    nothing: [
        { num: '1', title: 'Open Software Info', text: 'Go to <strong>Settings &gt; About phone &gt; Software info</strong>.' },
        { num: '2', title: 'Tap Build Number 7 Times', text: 'Tap <strong>Build number</strong> 7 times until you see "You are now in Developer mode!".' },
        { num: '3', title: 'Open Developer Options', text: 'Return to <strong>Settings &gt; System &gt; Developer options</strong>.' },
        { num: '4', title: 'Enable USB Debugging', text: 'Turn ON the <strong>USB debugging</strong> toggle.' },
        { num: '5', title: 'Authorize USB on Phone', text: 'Connect USB cable to PC. Check <strong>"Always allow from this computer"</strong> and tap <strong>Allow</strong>.' }
    ],
    pixel: [
        { num: '1', title: 'Open About Phone', text: 'Go to <strong>Settings &gt; About phone</strong>.' },
        { num: '2', title: 'Tap Build Number 7 Times', text: 'Scroll to the bottom and tap <strong>Build number</strong> 7 times until unlocked.' },
        { num: '3', title: 'Open Developer Options', text: 'Return to <strong>Settings &gt; System &gt; Developer options</strong>.' },
        { num: '4', title: 'Enable USB Debugging', text: 'Turn ON <strong>USB debugging</strong>.' },
        { num: '5', title: 'Authorize USB on Phone', text: 'Plug in USB cable. Check <strong>"Always allow from this computer"</strong> and tap <strong>Allow</strong>.' }
    ]
};

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
}

async function openTutorialModal(tab = null, slide = 0) {
    tutHasAutoSwitchedToKey = false;
    tutUserManuallySelectedTab = false;
    tutUserManuallySelectedOem = false;
    tutOemDetected = false;
    preloadTutorialImages();
    initTutStoryBars();
    renderTutOemContent(activeTutOem);

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
}

function switchTutOem(oemKey, isHardwareAuto = false, isUserManual = false) {
    if (isUserManual) {
        tutUserManuallySelectedOem = true;
    }
    activeTutOem = oemKey;
    ['xiaomi', 'samsung', 'oneplus', 'vivo', 'motorola', 'nothing', 'pixel'].forEach(k => {
        const btn = document.getElementById('btnOem' + k.charAt(0).toUpperCase() + k.slice(1));
        if (btn) {
            if (k === oemKey) btn.classList.add('active');
            else btn.classList.remove('active');
        }
    });

    const badge = document.getElementById('tutOemSuggestedBadge');
    if (badge) {
        badge.style.display = (isHardwareAuto && !tutUserManuallySelectedOem) ? 'inline-block' : 'none';
    }

    renderTutOemContent(oemKey);
}

function renderTutOemContent(oemKey) {
    const container = document.getElementById('tutOemContent');
    if (!container) return;
    const steps = OEM_INSTRUCTIONS[oemKey] || OEM_INSTRUCTIONS.xiaomi;
    container.innerHTML = steps.map(s => `
                <div class="tut-step-item">
                    <div class="tut-step-num">${s.num}</div>
                    <div>${s.text}</div>
                </div>
            `).join('');
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
        if (st.usb_debugging === false) {
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

    // Hardware suggested brand detection if plugged in and user hasn't manually selected
    if (isHttpServer && !tutUserManuallySelectedOem && !tutOemDetected && (st.connected || st.authorized)) {
        fetch('/api/phone/oem').then(r => r.json()).then(info => {
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
