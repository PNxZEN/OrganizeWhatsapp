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

function startHeartbeat() {
    if (_heartbeatTimer) clearInterval(_heartbeatTimer);
    const sendPing = async () => {
        if (isServerShuttingDown || !isHttpServer) return;
        try {
            const res = await fetch('/api/heartbeat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tab_id: BROWSER_TAB_ID })
            });
            // The server reports when it is installing an update, so every open tab can show the restart overlay
            if (res.ok && typeof onHeartbeatInfo === 'function') onHeartbeatInfo(await res.json());
        } catch (e) {}
    };
    sendPing();
    _heartbeatTimer = setInterval(sendPing, 10000);
}

// Warn user before closing if sync is active or exit modal is pending
window.addEventListener('beforeunload', (e) => {
    if ((_syncActive || (typeof _exitModalOpen !== 'undefined' && _exitModalOpen)) && !isServerShuttingDown) {
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
