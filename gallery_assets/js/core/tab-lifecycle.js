/* Browser tab id, heartbeat and tab-close notification
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

// Tab lifecycle tracking and clean shutdown on tab close
const BROWSER_TAB_ID = 'tab_' + Math.random().toString(36).substring(2, 10) + '_' + Date.now();
let _heartbeatTimer = null;
let _devicePollTimer = null;
let windowHasLocalDb = false;
let isShutdownInitiator = false;
let isServerShuttingDown = false;
let _syncActive = false;
// Long operations started from this tab (ZIP backup, phone cleanup, restore, import), so closing
// the tab asks for confirmation. The server also keeps running until they finish.
const _busyOps = new Set();

function setBusyOperation(label, busy) {
    if (busy) _busyOps.add(label); else _busyOps.delete(label);
}

async function trackedFetch(label, url, options) {
    setBusyOperation(label, true);
    try {
        return await fetch(url, options);
    } finally {
        setBusyOperation(label, false);
    }
}

let _knownLibraryVersion = null;

async function sendHeartbeat() {
    if (isServerShuttingDown || !isHttpServer) return;
    try {
        const res = await fetch('/api/heartbeat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tab_id: BROWSER_TAB_ID })
        });
        if (!res.ok) return;
        const data = await res.json();
        // The server reports when it is installing an update, so every open tab can show the restart overlay
        if (typeof onHeartbeatInfo === 'function') onHeartbeatInfo(data);
        // Media recycled, restored or imported (or settings changed) in another tab: refresh this one
        if (typeof data.data_version === 'number') {
            if (_knownLibraryVersion !== null && data.data_version !== _knownLibraryVersion
                && typeof applyExternalLibraryChange === 'function') {
                applyExternalLibraryChange();
            }
            _knownLibraryVersion = data.data_version;
        }
    } catch (e) {}
}

function startHeartbeat() {
    if (_heartbeatTimer) clearInterval(_heartbeatTimer);
    sendHeartbeat();
    _heartbeatTimer = setInterval(sendHeartbeat, 10000);
}

// Switching back to this tab picks up changes made elsewhere straight away
document.addEventListener('visibilitychange', () => {
    if (!document.hidden) sendHeartbeat();
});

// Warn user before closing if sync is active or exit modal is pending
window.addEventListener('beforeunload', (e) => {
    if ((_syncActive || _busyOps.size > 0 || (typeof _exitModalOpen !== 'undefined' && _exitModalOpen)) && !isServerShuttingDown) {
        e.preventDefault();
        e.returnValue = '';
        return '';
    }
});

// Notify server when tab unloads / closes (supports Ctrl+W, tab close, window close)
function notifyTabClosed() {
    if (isServerShuttingDown || !isHttpServer) return;
    const payload = JSON.stringify({ tab_id: BROWSER_TAB_ID });
    if (navigator.sendBeacon) {
        navigator.sendBeacon('/api/tab-closed', payload);
    } else {
        fetch('/api/tab-closed', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: payload,
            keepalive: true
        }).catch(() => {});
    }
}
window.addEventListener('pagehide', notifyTabClosed);
