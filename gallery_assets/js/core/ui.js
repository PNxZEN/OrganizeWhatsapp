/* Server detection, toasts, media URLs and modal stack
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

// ==========================================
// ZERO-TERMINAL CONTROL CENTER LOGIC
// ==========================================
const isHttpServer = window.location.protocol.startsWith('http');
let currentDeviceStatus = { connected: false, authorized: false, serial: null, model: null };
let syncPollingTimer = null;

function showToast(message, type = 'info', actionTextOrDuration = null, onAction = null) {
    const container = document.getElementById('toastContainer');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    let duration = 4000;
    if (typeof actionTextOrDuration === 'number') {
        duration = actionTextOrDuration;
        toast.innerText = message;
    } else if (actionTextOrDuration && typeof onAction === 'function') {
        duration = 7000;
        toast.style.display = 'flex';
        toast.style.alignItems = 'center';
        toast.style.justifyContent = 'space-between';
        toast.style.gap = '12px';

        const span = document.createElement('span');
        span.innerText = message;
        toast.appendChild(span);

        const btn = document.createElement('button');
        btn.className = 'btn btn-outline';
        btn.style.padding = '3px 10px';
        btn.style.fontSize = '0.78rem';
        btn.style.borderRadius = '5px';
        btn.style.borderColor = 'currentColor';
        btn.style.color = 'inherit';
        btn.style.background = 'rgba(255,255,255,0.15)';
        btn.style.cursor = 'pointer';
        btn.innerText = actionTextOrDuration;
        btn.onclick = (e) => {
            e.stopPropagation();
            toast.remove();
            onAction();
        };
        toast.appendChild(btn);
    } else {
        toast.innerText = message;
    }
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(10px)';
        toast.style.transition = 'all 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

function getMediaUrl(relPath) {
    if (!relPath) return '';
    if (isHttpServer) {
        return '/api/media?path=' + encodeURIComponent(relPath);
    }
    return encodePathForUrl(relPath);
}

// Returns the open modal overlay that is visually on top (highest z-index), or null.
function getTopOpenModal() {
    const open = Array.from(document.querySelectorAll('.modal-overlay.open'));
    if (open.length === 0) return null;
    return open.reduce((top, m) => ((parseInt(m.style.zIndex, 10) || 0) >= (parseInt(top.style.zIndex, 10) || 0) ? m : top));
}

let _modalZIndexCounter = 1050;
function openModal(id, pushHistory = true) {
    const m = document.getElementById(id);
    if (m) {
        m.style.zIndex = (++_modalZIndexCounter).toString();
        m.classList.add('open');
        if (pushHistory) {
            try {
                history.pushState({ app: 'wa_gallery', view: 'modal', modal: id, chat: activeChat ? activeChat.jid : null }, '');
            } catch (e) {}
        }
    }
}

function closeModal(id, triggerHistoryBack = true) {
    const m = document.getElementById(id);
    if (m) {
        m.classList.remove('open');
        m.style.zIndex = '';
    }
    if (triggerHistoryBack && history.state && history.state.view === 'modal' && history.state.modal === id) {
        try {
            window._closingModalViaBack = id;
            setTimeout(() => { if (window._closingModalViaBack === id) window._closingModalViaBack = null; }, 500);
            history.back();
        } catch (e) {}
    }
    if (id === 'modalDevice') {
        if (typeof stopDeviceWaiting === 'function') stopDeviceWaiting();
        if (modalDevicePollTimer) {
            clearInterval(modalDevicePollTimer);
            modalDevicePollTimer = null;
        }
    }
    if (id === 'modalKey') {
        if (keyModalPollTimer) {
            clearInterval(keyModalPollTimer);
            keyModalPollTimer = null;
        }
        if (isHttpServer) {
            fetch('/api/phone/clear-received-key', { method: 'POST' }).catch(() => {});
        }
    }
    if (id === 'modalSync') {
        if (typeof stopDeviceReconnectWatcher === 'function') stopDeviceReconnectWatcher();
    }
    if (id === 'modalAccountSelector') {
        window._pendingSyncAfterAccountSelect = false;
    }
}
