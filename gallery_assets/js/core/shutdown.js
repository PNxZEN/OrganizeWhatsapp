/* Exit confirmation, cross-tab shutdown and history exit trap
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

let _exitModalOpen = false;

function confirmExitApp(pushHistory = true) {
    if (!isHttpServer) {
        window.close();
        return;
    }
    const warnEl = document.getElementById('exitSyncWarning');
    if (warnEl) {
        warnEl.style.display = _syncActive ? 'flex' : 'none';
    }
    _exitModalOpen = true;
    openModal('modalExit', false);
    if (pushHistory) {
        try {
            history.pushState({ app: 'wa_gallery', view: 'modal_exit' }, '');
        } catch (e) {}
    }
}

function cancelExitApp() {
    _exitModalOpen = false;
    closeModal('modalExit', false);
    try {
        if (history.state && history.state.view === 'modal_exit') {
            history.replaceState({ app: 'wa_gallery', view: 'gallery_main' }, '');
        }
    } catch (e) {}
}

// Cross-tab synchronization channel
let appBroadcastChannel = null;
try {
    if (typeof BroadcastChannel !== 'undefined') {
        appBroadcastChannel = new BroadcastChannel('wa_organizer_sync');
        appBroadcastChannel.onmessage = (event) => {
            if (event.data && event.data.type === 'SERVER_SHUTDOWN') {
                if (!isShutdownInitiator && !isServerShuttingDown) {
                    renderShutdownScreen(false);
                }
            }
        };
    }
} catch (e) {}

// Cross-tab localStorage event listener fallback
window.addEventListener('storage', (e) => {
    if (e.key === 'wa_server_shutdown_event') {
        if (!isShutdownInitiator && !isServerShuttingDown) {
            renderShutdownScreen(false);
        }
    }
});

// Stops every polling loop so a stopped server is not hammered by a dead tab
function stopAllBackgroundTimers() {
    [_heartbeatTimer, _devicePollTimer, modalDevicePollTimer, syncPollingTimer, storageReclaimPollTimer,
        tutDevicePollInterval, tutKeyStatusPollTimer, keyModalPollTimer, waitingTimerInterval]
        .forEach(t => { if (t) clearInterval(t); });
    _heartbeatTimer = _devicePollTimer = modalDevicePollTimer = syncPollingTimer = storageReclaimPollTimer = null;
    tutDevicePollInterval = tutKeyStatusPollTimer = keyModalPollTimer = waitingTimerInterval = null;
    stopSyncPolling();
    stopDeviceReconnectWatcher();
}

function renderShutdownScreen(isOriginator = true) {
    isServerShuttingDown = true;
    stopAllBackgroundTimers();
    closeModal('modalExit');
    const subtitle = isOriginator
        ? 'The local server has shut down. You can now close this browser tab.'
        : 'The local server was shut down from another tab. You can now close this browser tab.';
    
    document.body.innerHTML = `
                <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;background:var(--bg-main);color:var(--text-primary);font-family:var(--font-family);animation:fadeInScale 0.25s ease;">
                    <div style="width:48px;height:48px;border-radius:12px;background:rgba(239,68,68,0.15);border:1px solid rgba(239,68,68,0.3);display:flex;align-items:center;justify-content:center;margin-bottom:16px;">
                        <svg class="icon" viewBox="0 0 24 24" style="width:24px;height:24px;fill:#ef4444;"><path d="M13 3h-2v10h2V3zm4.83 2.17l-1.42 1.42C17.99 7.86 19 9.81 19 12c0 3.87-3.13 7-7 7s-7-3.13-7-7c0-2.19 1.01-4.14 2.58-5.42L6.17 5.17C4.23 6.82 3 9.26 3 12c0 4.97 4.03 9 9 9s9-4.03 9-9c0-2.74-1.23-5.18-3.17-6.83z"/></svg>
                    </div>
                    <h2 style="margin-bottom:8px;font-size:20px;font-weight:700;">WhatsApp Media Organizer Stopped</h2>
                    <p style="color:var(--text-secondary);font-size:14px;text-align:center;max-width:400px;line-height:1.5;">${subtitle}</p>
                </div>
            `;
}

function executeShutdown() {
    isShutdownInitiator = true;
    isServerShuttingDown = true;
    stopAllBackgroundTimers();

    try {
        if (appBroadcastChannel) {
            appBroadcastChannel.postMessage({ type: 'SERVER_SHUTDOWN' });
        }
        localStorage.setItem('wa_server_shutdown_event', Date.now().toString());
    } catch (e) {}

    fetch('/api/shutdown', { method: 'POST' }).catch(() => {});
    renderShutdownScreen(true);
}

window._historyTrapArmed = false;
function armHistoryTrap() {
    if (window._historyTrapArmed) return;
    try {
        if (!history.state || history.state.view === 'gallery_main' || !history.state.app) {
            history.replaceState({ app: 'wa_gallery', view: 'exit_trap' }, '');
            history.pushState({ app: 'wa_gallery', view: 'gallery_main' }, '');
        }
        window._historyTrapArmed = true;
    } catch (e) {}
}

// Arm the history trap on any user gesture (pointerdown, keydown, touchstart, wheel, click)
// This ensures the entry is created WITH user activation so Chromium never skips it!
['pointerdown', 'keydown', 'touchstart', 'wheel', 'click'].forEach(evt => {
    window.addEventListener(evt, armHistoryTrap, { capture: true, passive: true });
});
setTimeout(armHistoryTrap, 1000);
