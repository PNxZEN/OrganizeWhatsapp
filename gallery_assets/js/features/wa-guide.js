/* Guided WhatsApp backup setup in the setup guide's key tab (backend: core/wa_guide.py)
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md).
 *
 * With the phone connected, the app reads which WhatsApp screen is showing and either taps the
 * next step itself ("Do it for me") or says what to tap ("Guide me"). It reads the 64-digit key
 * off the screen. The manual slides below stay available, and are shown automatically when the
 * phone is not connected or shows a screen the guide does not know. */

let waGuideStatus = null;
let waGuidePollTimer = null;
let waGuideShowManual = false;
let waGuideHaveKeyOpen = false;
let waGuideKeyInfo = { set: false, masked: '' };

function waGuideDeviceReady() {
    const st = (typeof currentDeviceStatus !== 'undefined' && currentDeviceStatus) || {};
    return !!(st.connected && st.authorized);
}

// Pure: what the panel shows. Exposed for tests.
function buildWaGuideView(ctx) {
    const g = ctx.guide || {};
    const esc = (s) => escapeHtml(String(s == null ? '' : s));
    const running = !!g.active || ['needs_choice', 'needs_user', 'have_key', 'low_storage'].includes(g.phase);
    const view = { html: '', showManual: !!ctx.showManual, showFinish: !!ctx.keySet, state: '' };

    const haveKeyPanel = () => `
        <div class="wag-havekey">
            <div class="wag-havekey-title">Give this app your 64-digit key</div>
            <div class="wag-havekey-row">
                <button type="button" class="action-btn action-btn-primary wag-btn" onclick="waGuidePasteKey()">Paste key</button>
                <input type="text" id="wagKeyInput" class="key-input wag-key-input" placeholder="or paste the 64 characters here" spellcheck="false" autocomplete="off" oninput="waGuideKeyTyped(this.value)">
            </div>
            <button type="button" class="wag-link" onclick="waGuideImportOlderKey()">Use the key from an older version of this app&hellip;</button>
            <div id="wagKeyMsg" class="wag-key-msg"></div>
        </div>`;

    const stepsList = (steps) => `
        <ol class="wag-steps">${(steps || []).map(s => `
            <li class="wag-step wag-step-${esc(s.state)}"><span class="wag-step-mark">${s.state === 'done' ? '&#10003;' : ''}</span>${esc(s.title)}</li>`).join('')}
        </ol>`;

    if (!ctx.deviceReady && !running && g.phase !== 'done') {
        view.state = 'no_phone';
        view.showManual = true;
        view.html = `
            <div class="wag-card wag-muted">
                <div><strong>Connect your phone first</strong> (Phone Connection tab) and this app can do these steps for you,
                or at least show you where to tap. Without the phone, follow the steps below.</div>
            </div>`;
        return view;
    }

    if (g.phase === 'done') {
        view.state = 'done';
        view.showFinish = false;  // the card has its own Finish button
        view.html = `
            <div class="wag-card wag-success">
                <div class="wag-title">&#10003; Key saved${g.masked_key ? ` <span class="wag-masked">(${esc(g.masked_key)})</span>` : ''}</div>
                <div class="wag-text">${esc(g.message || 'Your 64-digit key is saved on this computer.')}</div>
                <button type="button" class="action-btn action-btn-primary wag-btn" onclick="finishTutorialOnboarding(true)">Finish &amp; Sync Phone &rarr;</button>
            </div>`;
        return view;
    }

    if (g.phase === 'needs_choice' || (g.phase === 'have_key')) {
        view.state = g.phase;
        view.html = `
            <div class="wag-card">
                <div class="wag-title">Your WhatsApp backup is already end-to-end encrypted</div>
                <div class="wag-text">This app can read it with the 64-digit key that was made when it was turned on.</div>
                <div class="wag-choices">
                    <button type="button" class="wag-choice ${g.choice === 'have_key' ? 'selected' : ''}" onclick="waGuideChoose('have_key')">
                        <strong>I have my 64-digit key</strong><span>Paste it, or use the one saved by an older version of this app. Nothing changes on your phone.</span>
                    </button>
                    <button type="button" class="wag-choice" onclick="waGuideChoose('reset')">
                        <strong>Make a new key</strong><span>Turns off the old encrypted backup and creates a new one. Your phone will ask for its screen lock.</span>
                    </button>
                </div>
                ${g.choice === 'have_key' ? haveKeyPanel() : ''}
            </div>`;
        return view;
    }

    if (running) {
        view.state = 'running';
        view.showFinish = false;  // finishing now would close the guide before WhatsApp's "Create"
        const auto = g.mode === 'auto';
        const lowStorage = g.phase === 'low_storage';
        view.showManual = !!ctx.showManual || !!g.fallback;
        view.html = `
            <div class="wag-card">
                <div class="wag-head">
                    <div class="wag-live"><span class="wag-dot ${g.phase === 'needs_user' || lowStorage ? 'action' : 'ready'}"></span>
                        ${auto && g.input_allowed !== false ? 'Doing it for you on your phone' : 'Follow along on your phone'}</div>
                    <div class="wag-head-actions">
                        ${g.input_allowed !== false ? `<button type="button" class="wag-link" onclick="waGuideSetMode('${auto ? 'guide' : 'auto'}')">${auto ? 'Let me tap myself' : 'Do it for me'}</button>` : ''}
                        <button type="button" class="wag-link" onclick="waGuideStop()">Stop</button>
                    </div>
                </div>
                <div class="wag-now">${g.phase === 'needs_user' ? '<span class="wag-you">Your turn:</span> ' : ''}${esc(g.instruction || 'Reading your phone’s screen…')}</div>
                ${g.warning ? `<div class="wag-warn">${esc(g.warning)}</div>` : ''}
                ${g.notice ? `<div class="wag-warn">${esc(g.notice)}</div>` : ''}
                ${lowStorage ? `<div class="wag-row"><button type="button" class="action-btn action-btn-secondary wag-btn" onclick="waGuideAllowLowStorage()">Continue anyway</button></div>` : ''}
                ${g.key_captured ? `<div class="wag-key-ok">&#10003; Key read from your phone and saved (${esc(g.masked_key)})</div>` : ''}
                ${g.fallback ? `<div class="wag-warn">${esc(g.fallback_reason)} Follow the steps below; this app still watches for your key.</div>` : ''}
                ${stepsList(g.steps)}
            </div>`;
        return view;
    }

    // Not started yet (or stopped / failed)
    view.state = g.phase === 'error' ? 'error' : 'start';
    const keyNote = ctx.keySet ? `
        <div class="wag-key-ok">&#10003; A key is already saved${ctx.maskedKey ? ` (${esc(ctx.maskedKey)})` : ''}. You only need a new one if WhatsApp's key changed.</div>` : '';
    view.html = `
        <div class="wag-card">
            <div class="wag-title">Let this app set up the key on your phone</div>
            <div class="wag-text">It opens WhatsApp, goes to the backup settings and reads the 64-digit key off the screen. No copying, no typing.</div>
            ${g.phase === 'error' ? `<div class="wag-warn">${esc(g.message)}</div>` : ''}
            ${g.phase === 'stopped' && g.message ? `<div class="wag-warn">${esc(g.message)}</div>` : ''}
            ${keyNote}
            <div class="wag-row">
                <button type="button" class="action-btn action-btn-primary wag-btn" onclick="waGuideStart('auto')">Do it for me</button>
                <button type="button" class="action-btn action-btn-secondary wag-btn" onclick="waGuideStart('guide')">Guide me step by step</button>
            </div>
            <div class="wag-row wag-links">
                <button type="button" class="wag-link" onclick="waGuideToggleHaveKey()">I already have my key</button>
                <button type="button" class="wag-link" onclick="waGuideToggleManual()">${ctx.showManual ? 'Hide the manual steps' : 'Show all steps instead'}</button>
            </div>
            ${ctx.haveKeyOpen ? haveKeyPanel() : ''}
        </div>`;
    return view;
}

function renderWaGuide() {
    const box = document.getElementById('tutWaGuide');
    if (!box) return;
    const view = buildWaGuideView({
        guide: waGuideStatus,
        deviceReady: waGuideDeviceReady(),
        keySet: waGuideKeyInfo.set,
        maskedKey: waGuideKeyInfo.masked,
        showManual: waGuideShowManual,
        haveKeyOpen: waGuideHaveKeyOpen,
    });
    // Do not replace the panel while the user types or pastes a key into it
    const typing = document.activeElement && document.activeElement.id === 'wagKeyInput';
    if (!typing && box._html !== view.html) {
        box._html = view.html;
        box.innerHTML = view.html;
    }
    box.setAttribute('data-state', view.state);
    const manual = document.getElementById('tutManualSteps');
    if (manual) manual.style.display = view.showManual ? 'flex' : 'none';
    const manualAppeared = view.showManual && !(waGuideFooterView && waGuideFooterView.showManual);
    waGuideFooterView = view;
    if (manualAppeared) {
        // Give the slides their Previous / Next controls back
        waGuideRestoreFooter();
        if (typeof setTutSlide === 'function') setTutSlide(activeTutSlide || 0);
    }
    waGuideSyncFooter();
}

let waGuideFooterView = null;

// The key tab footer drives the manual slides; while they are hidden only Finish makes sense.
function waGuideSyncFooter() {
    const v = waGuideFooterView;
    if (!v || v.showManual) return;
    const prev = document.getElementById('btnTutPrevFooter');
    const next = document.getElementById('btnTutNextFooter');
    const finish = document.getElementById('btnTutFinishFooter');
    const counter = document.getElementById('tutSlideCounterFooter');
    if (prev) prev.style.visibility = 'hidden';
    if (counter) counter.style.visibility = 'hidden';
    if (next) next.style.display = 'none';
    if (finish) finish.style.display = v.showFinish ? 'inline-flex' : 'none';
}

function waGuideRestoreFooter() {
    ['btnTutPrevFooter', 'tutSlideCounterFooter'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.visibility = '';
    });
}

async function waGuideRefreshKeyInfo() {
    if (!isHttpServer) return;
    try {
        const r = await fetch('/api/config');
        if (r.ok) {
            const cfg = await r.json();
            waGuideKeyInfo = { set: !!cfg.hex_key_set, masked: cfg.masked_key || '' };
        }
    } catch (e) {}
}

async function waGuidePoll() {
    const modal = document.getElementById('modalTutorial');
    if (!modal || !modal.classList.contains('open') || activeTutTab !== 'key') {
        waGuideStopPolling();
        // Closing the guide stops the phone automation too
        if (waGuideStatus && waGuideStatus.active && (!modal || !modal.classList.contains('open'))) {
            waGuidePost('stop');
        }
        return;
    }
    try {
        const r = await fetch('/api/wa-guide/status');
        if (r.ok) {
            const before = waGuideStatus;
            waGuideStatus = await r.json();
            if (waGuideStatus.key_captured && !(before && before.key_captured)) {
                showToast('64-digit key read from your phone and saved!', 'success');
                await waGuideRefreshKeyInfo();
                if (typeof checkConfigStatus === 'function') checkConfigStatus();
            }
        }
    } catch (e) {}
    renderWaGuide();
}

function waGuideStartPolling() {
    if (waGuidePollTimer) return;
    waGuidePollTimer = setInterval(waGuidePoll, 1000);
}

function waGuideStopPolling() {
    if (waGuidePollTimer) clearInterval(waGuidePollTimer);
    waGuidePollTimer = null;
}

// Called by switchTutTab
async function waGuideOnTabShown(tab) {
    if (tab !== 'key') {
        waGuideRestoreFooter();
        return;
    }
    await waGuideRefreshKeyInfo();
    await waGuidePoll();
    waGuideStartPolling();
}

async function waGuidePost(action, body) {
    try {
        const r = await fetch('/api/wa-guide/' + action, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body || {})
        });
        const data = await r.json();
        if (r.ok) waGuideStatus = data;
        else showToast(data.message || 'The phone guide could not do that.', 'error');
    } catch (e) {
        showToast('Could not reach the app. Is it still running?', 'error');
    }
    renderWaGuide();
}

function waGuideStart(mode) {
    waGuideHaveKeyOpen = false;
    waGuideShowManual = false;
    waGuidePost('start', { mode });
    waGuideStartPolling();
}

function waGuideStop() { waGuidePost('stop'); }
function waGuideSetMode(mode) { waGuidePost('mode', { mode }); }
function waGuideChoose(choice) { waGuidePost('choose', { choice }); }
function waGuideAllowLowStorage() { waGuidePost('allow-low-storage'); }

function waGuideToggleManual() {
    waGuideShowManual = !waGuideShowManual;
    if (waGuideShowManual) waGuideRestoreFooter();
    renderWaGuide();
    if (waGuideShowManual && typeof setTutSlide === 'function') setTutSlide(activeTutSlide || 0);
}

function waGuideToggleHaveKey() {
    waGuideHaveKeyOpen = !waGuideHaveKeyOpen;
    renderWaGuide();
}

function waGuideKeyMessage(html) {
    const el = document.getElementById('wagKeyMsg');
    if (el) el.innerHTML = html;
}

async function waGuideSaveKey(raw) {
    const key = String(raw || '').replace(/[^0-9a-fA-F]/g, '').toLowerCase();
    if (key.length !== 64) {
        waGuideKeyMessage(`<span class="wag-err">That is ${key.length} of 64 characters. Copy the whole key and try again.</span>`);
        return false;
    }
    try {
        const r = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ hex_key: key })
        });
        const res = await r.json();
        if (!r.ok || (res && res.status === 'error')) throw new Error((res && res.message) || 'not saved');
    } catch (e) {
        waGuideKeyMessage(`<span class="wag-err">The key could not be saved: ${escapeHtml(e.message)}</span>`);
        return false;
    }
    await waGuideKeyProvided();
    return true;
}

async function waGuideKeyProvided() {
    await waGuideRefreshKeyInfo();
    if (typeof checkConfigStatus === 'function') checkConfigStatus();
    showToast('64-digit key saved!', 'success');
    const input = document.getElementById('wagKeyInput');
    if (input) input.blur();
    // The server records it too (and stops any phone automation), so every poll agrees it is done
    await waGuidePost('key-provided');
}

async function waGuidePasteKey() {
    let text = '';
    try {
        text = await navigator.clipboard.readText();
    } catch (e) {
        const input = document.getElementById('wagKeyInput');
        if (input) input.focus();
        waGuideKeyMessage('Your browser did not allow reading the clipboard. Paste into the box instead (Ctrl+V / Cmd+V).');
        return;
    }
    const input = document.getElementById('wagKeyInput');
    if (input) input.value = text.trim();
    await waGuideSaveKey(text);
}

function waGuideKeyTyped(value) {
    const key = String(value || '').replace(/[^0-9a-fA-F]/g, '');
    if (key.length >= 64) waGuideSaveKey(key.slice(0, 64));
    else if (key.length) waGuideKeyMessage(`${key.length} of 64 characters`);
}

async function waGuideImportOlderKey() {
    waGuideKeyMessage('Choose the folder of the older version (or its output folder)&hellip;');
    try {
        const r = await fetch('/api/key/import-previous', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });
        const res = await r.json();
        if (res.status === 'success') {
            await waGuideKeyProvided();
        } else if (res.status === 'canceled') {
            waGuideKeyMessage('');
        } else {
            waGuideKeyMessage(`<span class="wag-err">${escapeHtml(res.message || 'No key was found there.')}</span>`);
        }
    } catch (e) {
        waGuideKeyMessage('<span class="wag-err">Could not open the folder picker.</span>');
    }
}
