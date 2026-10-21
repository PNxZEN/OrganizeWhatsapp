/* Version badge and the "About & Updates" settings tab
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md).
 *
 * The app only talks to GitHub when the user presses "Check for updates". An update is
 * downloaded and verified first; installing it needs a second click and is refused by the
 * server while a sync, import or other long operation is running. While the app restarts a
 * blocking overlay covers every open tab, and the page reloads itself once the new version
 * answers. */

const UPDATE_RESTART_TIMEOUT_MS = 120000;
const UPDATE_RESTART_RECHECK_MS = 25000;

let _appVersion = '';
let _installInfo = null;
let _updateStatus = null;       // last answer of /api/update/status
let _updateCheck = null;        // last answer of /api/update/check
let _updateCheckError = '';
let _updateBusyRequest = false; // a button was pressed and its request is in flight
let _updatePollTimer = null;
let _notifiedReadyVersion = '';
let _restartWatch = null;
let _updateChannel = null;
let _autoCheckEnabled = false;

// ---------------------------------------------------------------- version info

async function loadVersionInfo() {
    if (!isHttpServer) return;
    try {
        const res = await fetch('/api/version?consume=1', { cache: 'no-store' });
        if (!res.ok) return;
        const data = await res.json();
        _appVersion = data.version || '';
        _installInfo = data.install || null;
        _autoCheckEnabled = !!data.auto_check_updates;
        const autoToggle = document.getElementById('settingAutoCheckUpdates');
        if (autoToggle) autoToggle.checked = _autoCheckEnabled;
        const badge = document.getElementById('appVersionBadge');
        if (badge && _appVersion) {
            badge.textContent = 'v' + _appVersion;
            badge.style.display = '';
        }
        const tab = document.getElementById('tabSettingsAbout');
        if (tab) tab.style.display = '';
        if (data.last_update) announceUpdateOutcome(data.last_update);
        renderUpdateUi();
        if (data.auto_check_due) runAutoUpdateCheck();
    } catch (e) { /* the version label is optional; the rest of the app works without it */ }
}

function announceUpdateOutcome(result) {
    if (!result || !result.status) return;
    if (result.status === 'updated') {
        showToast(`Updated to version ${result.to}. Enjoy!`, 'success', 8000);
    } else if (result.status === 'rolled_back') {
        showToast(`The update to ${result.to} could not be completed, so version ${result.from} was restored. ${result.error || ''}`.trim(), 'error', 15000);
    } else if (result.status === 'failed') {
        showToast(`The update failed. ${result.error || ''}`.trim(), 'error', 20000);
    }
}

// ---------------------------------------------------------------- privacy: opt-in automatic check

// The server refuses {auto: true} unless the user enabled this and a day has passed, so the page
// can never make the app go online on its own.
async function runAutoUpdateCheck() {
    try {
        const data = await updateApi('/api/update/check', { auto: true });
        if (data.status !== 'success') return;
        _updateCheck = data;
        setUpdateIndicators(!!data.update_available);
        renderUpdateUi();
    } catch (e) { /* silent: an automatic check must never bother the user */ }
}

async function onAutoUpdateToggle(enabled) {
    const box = document.getElementById('settingAutoCheckUpdates');
    try {
        await updateApi('/api/update/settings', { auto_check: !!enabled });
        _autoCheckEnabled = !!enabled;
        showToast(enabled ? 'The app will check for updates once a day when it opens.' : 'Automatic update checks are off. The app stays offline.', 'info', 4000);
    } catch (e) {
        if (box) box.checked = _autoCheckEnabled;
        showToast('Could not save the setting. ' + e.message, 'error', 6000);
    }
}

// ---------------------------------------------------------------- calling the server

async function updateApi(path, body) {
    const res = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {})
    });
    let data = {};
    try { data = await res.json(); } catch (e) { /* non-JSON error page */ }
    if (!res.ok) {
        const err = new Error(data.message || `The request failed (${res.status}).`);
        err.code = data.code;
        err.busy = data.busy;
        throw err;
    }
    return data;
}

async function refreshUpdateStatus() {
    try {
        const res = await fetch('/api/update/status', { cache: 'no-store' });
        if (res.ok) _updateStatus = await res.json();
    } catch (e) { /* server restarting: the restart watch takes over */ }
    renderUpdateUi();
    return _updateStatus;
}

function isAboutTabVisible() {
    const view = document.getElementById('settingsViewAbout');
    return !!view && view.style.display !== 'none' && view.offsetParent !== null;
}

function scheduleUpdatePoll() {
    clearTimeout(_updatePollTimer);
    _updatePollTimer = null;
    const state = _updateStatus && _updateStatus.state;
    const working = state === 'downloading' || state === 'verifying' || state === 'staging';
    if (!working && !(state === 'ready' && isAboutTabVisible())) return;
    _updatePollTimer = setTimeout(async () => {
        const before = state;
        await refreshUpdateStatus();
        if (before !== 'ready' && _updateStatus && _updateStatus.state === 'ready'
            && _notifiedReadyVersion !== _updateStatus.target_version && !isAboutTabVisible()) {
            _notifiedReadyVersion = _updateStatus.target_version;
            showToast(`Version ${_updateStatus.target_version} is ready to install (Settings → About & Updates).`, 'success', 8000);
        }
        scheduleUpdatePoll();
    }, working ? 500 : 2000);
}

// ---------------------------------------------------------------- actions

async function onAboutTabShown() {
    await refreshUpdateStatus();
    scheduleUpdatePoll();
}

async function checkForUpdates(force = true) {
    if (_updateBusyRequest) return;
    _updateBusyRequest = true;
    _updateCheckError = '';
    renderUpdateUi();
    try {
        _updateCheck = await updateApi('/api/update/check', { force });
    } catch (e) {
        _updateCheck = null;
        _updateCheckError = e.message;
    } finally {
        _updateBusyRequest = false;
    }
    setUpdateIndicators(!!(_updateCheck && _updateCheck.update_available));
    await refreshUpdateStatus();
}

async function startUpdateDownload() {
    if (_updateBusyRequest) return;
    _updateBusyRequest = true;
    _updateCheckError = '';
    renderUpdateUi();
    try {
        await updateApi('/api/update/download');
    } catch (e) {
        _updateCheckError = e.message;
    } finally {
        _updateBusyRequest = false;
    }
    await refreshUpdateStatus();
    scheduleUpdatePoll();
}

async function cancelUpdate() {
    if (_updateBusyRequest) return;
    _updateBusyRequest = true;
    try {
        await updateApi('/api/update/cancel');
    } catch (e) {
        _updateCheckError = e.message;
    } finally {
        _updateBusyRequest = false;
    }
    await refreshUpdateStatus();
    scheduleUpdatePoll();
}

async function installUpdate() {
    if (_updateBusyRequest || !_updateStatus || _updateStatus.state !== 'ready') return;
    const target = _updateStatus.target_version;
    if (!confirm(`Install version ${target} now?\n\nThe app will restart for a few seconds. Your settings, backup key and media are not touched. Make sure nothing else is using the app.`)) return;
    _updateBusyRequest = true;
    _updateCheckError = '';
    renderUpdateUi();
    try {
        await updateApi('/api/update/apply');
    } catch (e) {
        _updateBusyRequest = false;
        _updateCheckError = e.message;
        await refreshUpdateStatus();
        return;
    }
    _updateBusyRequest = false;
    beginRestartWatch(target, true);
}

// ---------------------------------------------------------------- restart handling

function openUpdateChannel() {
    if (_updateChannel || typeof BroadcastChannel === 'undefined') return;
    try {
        _updateChannel = new BroadcastChannel('wa-gallery-update');
        _updateChannel.onmessage = (ev) => {
            if (ev.data && ev.data.type === 'restart' && !_restartWatch) beginRestartWatch(ev.data.target, false);
        };
    } catch (e) { _updateChannel = null; }
}

function setUpdateOverlay(show, title, text, stalled) {
    const overlay = document.getElementById('updateOverlay');
    if (!overlay) return;
    overlay.classList.toggle('show', !!show);
    overlay.classList.toggle('stalled', !!stalled);
    if (title) document.getElementById('updateOverlayTitle').textContent = title;
    if (text) document.getElementById('updateOverlayText').textContent = text;
}

function beginRestartWatch(target, announce) {
    if (_restartWatch) return;
    // The server is about to disappear: stop prompting about leaving the page and stop pinging it
    isServerShuttingDown = true;
    if (announce && _updateChannel) {
        try { _updateChannel.postMessage({ type: 'restart', target }); } catch (e) { /* other tabs still notice via heartbeat */ }
    }
    setUpdateOverlay(true, 'Installing update…',
        'The app is restarting. This page will reload by itself. Please don’t close it.', false);
    _restartWatch = { target: target || null, startedAt: Date.now(), sawDown: false, timer: null };
    tickRestartWatch();
}

function resumeRestartWatch() {
    if (!_restartWatch) return;
    _restartWatch.startedAt = Date.now();
    setUpdateOverlay(true, 'Installing update…',
        'The app is restarting. This page will reload by itself. Please don’t close it.', false);
    tickRestartWatch();
}

async function tickRestartWatch() {
    const w = _restartWatch;
    if (!w) return;
    clearTimeout(w.timer);
    const elapsed = Date.now() - w.startedAt;
    let health = null;
    try {
        const ctl = new AbortController();
        const abort = setTimeout(() => ctl.abort(), 2000);
        const res = await fetch('/api/health?_=' + Date.now(), { cache: 'no-store', signal: ctl.signal });
        clearTimeout(abort);
        if (res.ok) health = await res.json();
    } catch (e) { /* down: expected while the files are being swapped */ }

    if (!health) {
        w.sawDown = true;
    } else if (w.sawDown || (w.target && health.version === w.target)) {
        setUpdateOverlay(true, 'Almost done…', 'Reloading the app.', false);
        setTimeout(() => location.reload(), 400);
        return;
    } else if (elapsed > UPDATE_RESTART_RECHECK_MS) {
        // The server never went down: find out whether the installation actually started
        try {
            const st = await (await fetch('/api/update/status', { cache: 'no-store' })).json();
            if (st.state !== 'applying') {
                _restartWatch = null;
                isServerShuttingDown = false;
                setUpdateOverlay(false);
                _updateStatus = st;
                _updateCheckError = (st.error && st.error.message) || 'The update could not be started.';
                renderUpdateUi();
                return;
            }
        } catch (e) { w.sawDown = true; }
    }

    if (elapsed > UPDATE_RESTART_TIMEOUT_MS) {
        setUpdateOverlay(true, 'This is taking longer than expected',
            'The app has not come back yet. You can keep waiting, or reload this page. If the app does not start, open it again from its shortcut. Your previous version is kept as a backup in the “.update” folder.', true);
        return;
    }
    w.timer = setTimeout(tickRestartWatch, 1000);
}

// A tab that missed the broadcast still learns about the restart from its heartbeat
function onHeartbeatInfo(data) {
    if (data && data.maintenance && !_restartWatch) beginRestartWatch(null, false);
}

// ---------------------------------------------------------------- rendering

function setUpdateIndicators(available) {
    const badge = document.getElementById('appVersionBadge');
    if (badge) {
        badge.classList.toggle('has-update', !!available);
        badge.title = available ? 'A new version is available, open About & Updates' : 'About & updates';
    }
    const dot = document.getElementById('aboutUpdateDot');
    if (dot) dot.classList.toggle('show', !!available);
}

function renderReleaseNotes(text) {
    // Release notes are GitHub markdown; show the useful subset and escape everything else
    const inline = (s) => escapeHtml(s)
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/`(.+?)`/g, '<code>$1</code>')
        .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1');
    const out = [];
    let inList = false;
    const closeList = () => { if (inList) { out.push('</ul>'); inList = false; } };
    for (const raw of String(text || '').split(/\r?\n/)) {
        const line = raw.trim();
        if (!line || /^[-=*_]{3,}$/.test(line) || /^(\||>)/.test(line)) { closeList(); continue; }
        const heading = line.match(/^#{1,4}\s+(.*)$/);
        const bullet = line.match(/^[-*]\s+(.*)$/);
        if (heading) { closeList(); out.push('<h4>' + inline(heading[1]) + '</h4>'); }
        else if (bullet) { if (!inList) { out.push('<ul>'); inList = true; } out.push('<li>' + inline(bullet[1]) + '</li>'); }
        else { closeList(); out.push('<div>' + inline(line) + '</div>'); }
    }
    closeList();
    return out.join('');
}

function formatInstallLine() {
    if (!_installInfo) return '';
    const kinds = { portable: 'Windows portable', source: 'Source install', git: 'Git checkout' };
    return kinds[_installInfo.kind] || 'Installed copy';
}

function renderUpdateUi() {
    const pill = document.getElementById('aboutVersionPill');
    if (!pill) return;
    if (_appVersion) pill.textContent = 'v' + _appVersion;
    const installLine = document.getElementById('aboutInstallLine');
    if (installLine) installLine.textContent = formatInstallLine();

    const st = _updateStatus || { state: 'idle', install: _installInfo || {}, busy: [] };
    const install = st.install || _installInfo || {};
    const state = st.state;
    const check = _updateCheck;
    const available = !!(check && check.update_available);
    const target = st.target_version || (check && check.latest_version) || '';

    const el = (id) => document.getElementById(id);
    const show = (id, on, display = '') => { const n = el(id); if (n) n.style.display = on ? display : 'none'; };
    const working = state === 'downloading' || state === 'verifying' || state === 'staging';

    let icon = 'check', iconClass = '', title = '', sub = '';
    if (working) {
        icon = 'download';
        title = `Downloading version ${target}…`;
        sub = state === 'downloading' ? 'Please keep the app open. Nothing is installed yet.'
            : state === 'verifying' ? 'Checking the download’s integrity…' : 'Preparing the files…';
    } else if (state === 'ready') {
        icon = 'download'; iconClass = 'is-available';
        title = `Version ${target} is ready to install`;
        sub = (st.busy && st.busy.length)
            ? `Waiting for: ${st.busy.join(', ')}. Finish or cancel it, then restart to install.`
            : 'The app will restart for a few seconds. Your settings, backup key and media are not touched.';
    } else if (state === 'applying') {
        icon = 'download'; iconClass = 'is-available';
        title = 'Installing…'; sub = 'The app is restarting.';
    } else if (available) {
        icon = 'download'; iconClass = 'is-available';
        title = `Version ${check.latest_version} is available`;
        const when = check.release && check.release.published_at ? new Date(check.release.published_at).toLocaleDateString() : '';
        const size = check.package_size ? formatBytes(check.package_size) : '';
        sub = [`You have ${_appVersion ? 'v' + _appVersion : 'an older version'}`, when && `Published ${when}`, size && `Download: ${size}`].filter(Boolean).join(' · ');
        if (!install.can_self_update) sub += '. ' + (install.reason || 'Updates are installed manually for this copy.');
        else if (!check.has_package) sub += '. This release has no automatic update package, use the release page.';
    } else if (check) {
        title = 'You’re up to date';
        sub = `Version ${check.current_version} is the latest release.`;
    } else {
        title = 'Software update';
        sub = install.can_self_update === false && install.reason ? install.reason
            : 'Check whether a newer version is available.';
    }
    if (state === 'error' && st.error) { icon = 'alert'; iconClass = 'is-error'; title = 'The update could not be completed'; sub = ''; }

    const icons = {
        check: '<svg viewBox="0 0 24 24"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>',
        download: '<svg viewBox="0 0 24 24"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>',
        alert: '<svg viewBox="0 0 24 24"><path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/></svg>'
    };
    const iconEl = el('updateStatusIcon');
    iconEl.className = 'update-status-icon ' + iconClass;
    iconEl.innerHTML = icons[icon];
    el('updateStatusTitle').textContent = title;
    el('updateStatusSub').textContent = sub;

    // release notes
    const notes = el('updateNotesBox');
    const showNotes = available && check.release && check.release.notes && !working && state !== 'applying';
    notes.style.display = showNotes ? '' : 'none';
    if (showNotes) notes.innerHTML = renderReleaseNotes(check.release.notes);

    // progress
    show('updateProgressWrap', working);
    if (working) {
        el('updateProgressBar').style.width = (st.percent || 0) + '%';
        el('updateProgressDetail').textContent = st.bytes_total
            ? `${formatBytes(st.bytes_done)} of ${formatBytes(st.bytes_total)} (${Math.floor(st.percent || 0)}%)`
            : (st.message || '');
    }

    // errors: the server's explanation first, then request errors
    const errMsg = (state === 'error' && st.error && st.error.message) || _updateCheckError;
    const errEl = el('updateError');
    errEl.style.display = errMsg ? '' : 'none';
    errEl.textContent = errMsg || '';

    // buttons
    const canSelfUpdate = install.can_self_update !== false;
    const idleLike = state === 'idle' || state === 'error';
    const busyReq = _updateBusyRequest;
    const btnCheck = el('btnUpdateCheck');
    btnCheck.style.display = (idleLike || state === 'ready') ? '' : 'none';
    btnCheck.disabled = busyReq;
    btnCheck.textContent = busyReq && !working && state !== 'ready' ? 'Checking…' : 'Check for updates';
    const canDownload = idleLike && available && canSelfUpdate && check.has_package;
    show('btnUpdateDownload', canDownload);
    el('btnUpdateDownload').disabled = busyReq;
    el('btnUpdateDownload').textContent = state === 'error' ? 'Try again' : 'Download update';
    show('btnUpdateInstall', state === 'ready');
    const installBusy = st.busy && st.busy.length > 0;
    el('btnUpdateInstall').disabled = busyReq || installBusy;
    el('btnUpdateInstall').title = installBusy ? `Waiting for: ${st.busy.join(', ')}` : '';
    show('btnUpdateCancel', working || state === 'ready');
    el('btnUpdateCancel').disabled = busyReq;
    el('btnUpdateCancel').textContent = working ? 'Cancel' : 'Discard download';

    const link = el('updateReleaseLink');
    const url = check && check.release && check.release.html_url;
    const linkable = !!url && /^https:\/\/github\.com\//.test(url);
    link.style.display = linkable && (available || state === 'error') ? '' : 'none';
    if (linkable) link.href = url;
}

openUpdateChannel();
