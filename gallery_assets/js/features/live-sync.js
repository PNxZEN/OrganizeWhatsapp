/* Live-sync banner polling and gallery_data.js hot reload
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

// ── LIVE-SYNC POLLING ──────────────────────────────────────────────
// These functions are always present in the HTML so the file can be
// opened against any server invocation (--live, --serve, or file://).
// When the server is NOT in --live mode, /api/sync-status returns
// {"active":false} immediately and polling stops.

let _syncVersion = -1;
let _syncPollInterval = null;
let _notifiedDoneVersion = -1;

function startSyncPolling() {
    stopSyncPolling();
    checkSyncStatus();
    _syncPollInterval = setInterval(checkSyncStatus, 5000);
}

function stopSyncPolling() {
    if (_syncPollInterval !== null) {
        clearInterval(_syncPollInterval);
        _syncPollInterval = null;
    }
}

async function checkSyncStatus() {
    try {
        const res = await fetch('/api/sync-status', {
            // cache:'no-store' forces the browser to skip its HTTP cache
            cache: 'no-store',
        });
        if (!res.ok) {
            stopSyncPolling();
            return;
        }
        const status = await res.json();
        if (status.has_local_db !== undefined) {
            windowHasLocalDb = !!status.has_local_db;
        }
        updateSyncButtonUI(status);
        const banner = document.getElementById('syncBanner');
        if (!banner) return;

        if (status.active) {
            // Reset dismissal only when a new sync session begins
            if (_syncVersion === -1) {
                window._syncBannerDismissed = false;
            }

            const phaseLabels = {
                'pulling_db':     'Pulling database from phone...',
                'pulling_media':  'Pulling media from phone...',
                'organizing':     'Organizing new files...',
                'syncing':        'Transferring media files...',
                'done':           'Sync complete!',
            };
            const phaseText = status.phase_label || phaseLabels[status.phase] || (status.current_file ? `Transferring: ${status.current_file.split('/').pop()}` : 'Syncing from phone...');
            const countText = (status.synced_files !== undefined && status.total_files > 0)
                ? ` - <strong>${status.synced_files.toLocaleString()}</strong> / <strong>${status.total_files.toLocaleString()}</strong> files (${status.progress_percent || 0}%)`
                : '';
            document.getElementById('syncBannerText').innerHTML =
                `<strong>Syncing:</strong> ${phaseText}${countText}`;

            const spinner = document.getElementById('syncSpinner');
            if (spinner) spinner.style.display = 'block';

            const refreshBtn = document.getElementById('syncRefreshBtn');
            if (refreshBtn) {
                refreshBtn.dataset.action = 'view';
                refreshBtn.innerText = 'View Progress';
                refreshBtn.disabled = false;
                refreshBtn.style.display = 'inline-block';
            }

            if (!window._syncBannerDismissed) {
                banner.style.display = 'flex';
            }

            // When the version number changes, new files have been organized.
            // Update chats list incrementally (no full-file re-download needed in live mode).
            if (_syncVersion !== -1 && status.version !== _syncVersion) {
                if (isHttpServer) {
                    reloadChatsList();
                } else {
                    reloadGalleryData();
                }
            }
            _syncVersion = (status.version !== undefined) ? status.version : _syncVersion;

        } else {
            // Pipeline is NOT active.
            if (status.status === 'paused' || status.can_resume) {
                if (!window._syncBannerDismissed) {
                    const savedFiles = status.synced_files || 0;
                    const totalFiles = status.total_files || 0;
                    document.getElementById('syncBannerText').innerHTML =
                        `<strong>Sync Paused:</strong> Saved ${savedFiles.toLocaleString()} of ${totalFiles.toLocaleString()} files.`;
                    const spinner = document.getElementById('syncSpinner');
                    if (spinner) spinner.style.display = 'none';

                    const refreshBtn = document.getElementById('syncRefreshBtn');
                    if (refreshBtn) {
                        refreshBtn.dataset.action = 'resume';
                        refreshBtn.innerText = 'Resume Sync';
                        refreshBtn.disabled = false;
                        refreshBtn.style.display = 'inline-block';
                    }
                    banner.style.display = 'flex';
                }
                return;
            }

            // Stop polling immediately to avoid repeated invocation while executing completion actions
            stopSyncPolling();

            // Only show "Sync complete!" if:
            // 1) A sync was actively in progress in this session (_syncVersion > -1)
            // 2) We haven't already notified the user for this completion version
            // 3) The user hasn't explicitly dismissed the banner
            if (_syncVersion > -1 && (status.status === 'done' || status.phase === 'done') && status.version !== _notifiedDoneVersion) {
                _notifiedDoneVersion = status.version;
                _syncVersion = -1; // Reset immediately to prevent infinite re-triggering

                if (!window._syncBannerDismissed) {
                    document.getElementById('syncBannerText').innerHTML =
                        '<strong>Sync complete!</strong> Gallery is up to date.';
                    document.getElementById('syncSpinner').style.display = 'none';
                    document.getElementById('syncRefreshBtn').style.display = 'none';
                    banner.style.display = 'flex';

                    // Smoothly animate the banner out after 4 seconds
                    setTimeout(() => {
                        banner.classList.add('banner-hidden');
                        setTimeout(() => {
                            banner.style.display = 'none';
                            banner.classList.remove('banner-hidden');
                        }, 350);
                    }, 4000);
                }

                if (isHttpServer) {
                    reloadChatsList(true);
                } else {
                    reloadGalleryData();
                }
            } else {
                // Any other inactive state (idle, dismissed, or already notified)
                _syncVersion = -1;
                if (status.status !== 'done' || window._syncBannerDismissed || status.version === _notifiedDoneVersion) {
                    banner.style.display = 'none';
                }
            }
        }
    } catch (e) {
        // Network error (e.g. file:// protocol or server offline).
        // Stop quietly - don't spam the console during normal usage.
        stopSyncPolling();
    }
}

async function handleSyncBannerClick(e) {
    if (e) e.stopPropagation();
    const btn = document.getElementById('syncRefreshBtn');
    if (btn && btn.dataset.action === 'resume') {
        btn.disabled = true;
        btn.innerText = 'Resuming...';
        await handleSyncResume();
    } else {
        openSyncModal();
    }
}

function dismissSyncBanner(e) {
    if (e) e.stopPropagation();
    window._syncBannerDismissed = true;
    const banner = document.getElementById('syncBanner');
    if (banner) {
        banner.classList.add('banner-hidden');
        setTimeout(() => {
            banner.style.display = 'none';
            banner.classList.remove('banner-hidden');
        }, 280);
    }
}

/**
 * Hot-reloads gallery_data.js without a full page refresh.
 * Fetches the file with a cache-buster, parses the JSON,
 * pre-calculates monthGroup, then re-renders the sidebar.
 * If a chat is currently selected its view is also refreshed.
 */
async function reloadGalleryData() {
    try {
        const url = '/gallery_data.js?_v=' + Date.now();
        const res = await fetch(url, { cache: 'no-store' });
        if (!res.ok) return;

        const jsText = await res.text();
        // Accept every writer format: leading comments, then `const|let|var GALLERY_DATA =` or `window.GALLERY_DATA =`
        const body = jsText.replace(/^\uFEFF/, '').replace(/^(\s*(\/\/[^\n]*\n|\/\*[\s\S]*?\*\/))*\s*/, '');
        const match = body.match(/^(?:(?:const|let|var)\s+|window\.)?GALLERY_DATA\s*=\s*/);
        if (!match) return;

        // Strip the JS wrapper and parse as JSON
        const jsonStr = body.slice(match[0].length).replace(/;\s*$/, '');
        const newData = JSON.parse(jsonStr);
        if (!newData || !Array.isArray(newData.chats)) return;

        // Pre-calculate monthGroup for every item (same grouping as the gallery grid)
        newData.chats.forEach(chat => {
            (chat.media || []).forEach(item => {
                item.monthGroup = getMonthGroupForItem(item);
            });
        });

        // Replace the global
        window.GALLERY_DATA = newData;

        // Re-render the sidebar chat list while preserving scroll
        renderSidebar(true);

        // If a chat is open, refresh it from the new data
        if (activeChat) {
            const refreshed = newData.chats.find(c => c.jid === activeChat.jid);
            if (refreshed) {
                const prevMedia = activeChat.media || [];
                const refreshedMedia = refreshed.media || [];
                const countChanged = (refreshedMedia.length !== prevMedia.length);
                const sizeChanged = (refreshed.total_size !== activeChat.total_size);
                activeChat = refreshed;
                const namEl = document.getElementById('currentChatName');
                const metEl = document.getElementById('currentChatMeta');
                if (namEl) namEl.innerText = activeChat.name || activeChat.jid;
                if (metEl) metEl.innerText =
                    `${activeChat.file_count} files • Total storage: ${formatBytes(activeChat.total_size)}`;

                // Only re-render media if this specific chat received new files!
                if (countChanged || sizeChanged) {
                    const container = document.getElementById('galleryContent');
                    const isScrolledDown = container && container.scrollTop > 40;
                    const hasFiltersActive = isAnyFilterActive();
                    if (isScrolledDown || hasFiltersActive) {
                        // Keep the visible grid stable; the pill swaps in the new media on click
                        window._pendingNewMedia = refreshedMedia;
                        activeChat.media = prevMedia;
                        const diff = refreshedMedia.length - prevMedia.length;
                        showNewMediaPill(diff > 0 ? diff : refreshedMedia.length);
                    } else {
                        filterAndRenderMedia({ preserveScroll: true, keepItemsCount: true });
                    }
                }
            }
        }

        console.log(
            '[Live] Gallery reloaded: ',
            newData.chats.reduce((n, c) => n + c.file_count, 0),
            'files across',
            newData.chats.length,
            'chats.'
        );
    } catch (e) {
        console.warn('[Live] reloadGalleryData failed:', e);
    }
}
