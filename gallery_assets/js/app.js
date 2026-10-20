/* Application bootstrap (runs after every module has loaded)
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

// Initialize App (Fast Hybrid Loader)
window.addEventListener('DOMContentLoaded', async () => {
    checkDeviceStatus();
    _devicePollTimer = setInterval(checkDeviceStatus, 5000);
    checkConfigStatus();

    startHeartbeat();
    startSyncPolling();

    // Set up sidebar search listener
    const sidebarSearch = document.getElementById('sidebarSearch');
    if (sidebarSearch) {
        let sidebarDebounceTimer = null;
        sidebarSearch.addEventListener('input', (e) => {
            sidebarSearchQuery = e.target.value;
            chatsToShow = 10;
            clearTimeout(sidebarDebounceTimer);
            sidebarDebounceTimer = setTimeout(() => {
                renderSidebar(false);
            }, 100);
        });
    }

    setupFilterListeners();
    setupLightbox();
    setupInfiniteScroll();
    setupCollapsibleFilterPanel();
    applyDuplicateDetectionSetting();

    // Initialize History Baseline (do not pushState on load to avoid Chromium History Manipulation Intervention)
    try {
        if (!history.state || !history.state.app) {
            history.replaceState({ app: 'wa_gallery', view: 'gallery_main' }, '');
        }
    } catch (e) {}

    // Check URL onboarding flag or first-time launch
    const urlParams = new URLSearchParams(window.location.search);
    if (!_tutAutoOpened && urlParams.get('onboarding') === '1') {
        _tutAutoOpened = true;
        setTimeout(() => openTutorialModal(), 400);
    }

    // Fast lazy load over HTTP
    if (isHttpServer) {
        try {
            const resp = await fetch('/api/chats');
            if (resp.ok) {
                const data = await resp.json();
                window.GALLERY_DATA = { chats: data.chats || [] };
                renderSidebar();
                restoreAppState();
                return;
            }
        } catch (e) {
            console.warn('Fast chats API failed, falling back to static data:', e);
        }
    }

    // Static fallback for file:// protocol
    if (getChatsArray().length === 0 && typeof GALLERY_DATA === 'undefined') {
        console.error("GALLERY_DATA is missing. Run the media organizer first to generate gallery_data.js");
        return;
    }

    renderSidebar();
    restoreAppState();
});

window.addEventListener('unhandledrejection', (event) => {
    console.error('[Gallery] Unhandled Promise Rejection:', event.reason);
});
