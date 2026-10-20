/* Live refresh of the chat list and active chat while syncing
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

function isAnyFilterActive() {
    const type = activeType;
    const sender = document.getElementById('senderFilter');
    const search = document.getElementById('searchFilter');
    const starred = document.getElementById('starredFilter');
    const fwd = document.getElementById('forwardedFilter');
    const freqFwd = document.getElementById('freqForwardedFilter');
    const dir = document.getElementById('directionFilter');
    const startDate = document.getElementById('startDateFilter');
    const endDate = document.getElementById('endDateFilter');

    if (type && type !== 'all') return true;
    if (sender && sender.value !== 'all') return true;
    if (search && search.value.trim() !== '') return true;
    if (starred && starred.checked) return true;
    if (fwd && fwd.checked) return true;
    if (freqFwd && freqFwd.checked) return true;
    if (dir && dir.value !== 'all') return true;
    if (startDate && startDate.value !== '') return true;
    if (endDate && endDate.value !== '') return true;
    return false;
}

function showNewMediaPill(count) {
    const pill = document.getElementById('newMediaPill');
    const pillText = document.getElementById('newMediaPillText');
    if (pill && pillText) {
        const countLabel = (count && count > 0) ? `${count} ` : '';
        pillText.innerText = `${countLabel}new media arrived - Click to view`;
        pill.style.display = 'inline-flex';
    }
}

function handleNewMediaPillClick() {
    const pill = document.getElementById('newMediaPill');
    if (pill) pill.style.display = 'none';
    const container = document.getElementById('galleryContent');
    if (container) {
        container.scrollTo({ top: 0, behavior: 'smooth' });
    }
    if (window._pendingNewMedia && activeChat) {
        activeChat.media = window._pendingNewMedia;
        activeChat.file_count = window._pendingNewMedia.length;
        window._pendingNewMedia = null;
        populateSenders(activeChat.media, true);
        setDateRangeLimits(activeChat.media);
        filterAndRenderMedia({ preserveScroll: false });
    }
}

let isRefreshingLiveChat = false;
let _lastAutoRenderTime = 0;
async function refreshActiveChatLive() {
    if (!activeChat || !isHttpServer || isRefreshingLiveChat) return;
    try {
        isRefreshingLiveChat = true;
        const requestedChat = activeChat;
        const resp = await fetch('/api/chats/' + encodeURIComponent(requestedChat.jid) + '/media');
        if (!resp.ok) return;
        const data = await resp.json();
        // The user may have switched chats while the request was in flight
        if (activeChat !== requestedChat) return;
        const newMedia = data.media || [];

        if (data.total_size !== undefined) {
            activeChat.total_size = data.total_size;
        }
        if (data.file_count !== undefined) {
            activeChat.file_count = data.file_count;
        }
        if (data.name && data.name !== activeChat.name) {
            activeChat.name = data.name;
            const displayName = chatNameForDisplay(data.name);
            const nameEl = document.getElementById('currentChatName');
            if (nameEl) nameEl.innerText = displayName;
        }

        const metaEl = document.getElementById('currentChatMeta');
        if (metaEl) {
            const subtitle = (activeChat.jid === '_unmatched')
                ? `${activeChat.file_count} files • Unindexed WhatsApp Media`
                : `${activeChat.file_count} files • Total storage: ${formatBytes(activeChat.total_size)}`;
            metaEl.innerText = subtitle;
        }

        // Compare length to guarantee zero jitter if no new files arrived for this chat
        if (activeChat.media && activeChat.media.length === newMedia.length) {
            return;
        }

        const container = document.getElementById('galleryContent');
        const isScrolledDown = container && container.scrollTop > 40;
        const hasFiltersActive = isAnyFilterActive();

        // If user has scrolled down OR has active filters: DO NOT destroy or reset the view!
        if (isScrolledDown || hasFiltersActive) {
            window._pendingNewMedia = newMedia;
            const diff = newMedia.length - (activeChat.media ? activeChat.media.length : 0);
            showNewMediaPill(diff > 0 ? diff : newMedia.length);
            return;
        }

        // If user is idle at the very top with no filters: throttle auto-updates
        const now = Date.now();
        if (now - _lastAutoRenderTime < 10000) {
            window._pendingNewMedia = newMedia;
            showNewMediaPill(newMedia.length - (activeChat.media ? activeChat.media.length : 0));
            return;
        }
        _lastAutoRenderTime = now;

        activeChat.media = newMedia;
        activeChat.file_count = newMedia.length;

        populateSenders(activeChat.media, true);
        setDateRangeLimits(activeChat.media);
        filterAndRenderMedia({ preserveScroll: true, keepItemsCount: true });
    } catch (e) {
        console.warn('Live chat refresh error:', e);
    } finally {
        isRefreshingLiveChat = false;
    }
}

let _lastChatsListReloadTime = 0;
async function reloadChatsList(force = false) {
    if (!isHttpServer) return;
    const now = Date.now();
    if (!force && (now - _lastChatsListReloadTime < 2500)) return;
    _lastChatsListReloadTime = now;
    try {
        const resp = await fetch('/api/chats');
        if (resp.ok) {
            const data = await resp.json();
            if (data.chats) {
                // Preserve cached media on active chat if present and update storage / count
                if (activeChat) {
                    const found = data.chats.find(c => c.jid === activeChat.jid);
                    if (found) {
                        if (activeChat.media) {
                            found.media = activeChat.media;
                        }
                        activeChat.total_size = found.total_size;
                        activeChat.file_count = found.file_count;
                        if (found.name) activeChat.name = found.name;

                        const metaEl = document.getElementById('currentChatMeta');
                        if (metaEl) {
                            const subtitle = (activeChat.jid === '_unmatched')
                                ? `${activeChat.file_count} files • Unindexed WhatsApp Media`
                                : `${activeChat.file_count} files • Total storage: ${formatBytes(activeChat.total_size)}`;
                            metaEl.innerText = subtitle;
                        }
                    }
                }
                window.GALLERY_DATA = { chats: data.chats };
                renderSidebar(true);

                // Smoothly refresh active chat media if active
                if (activeChat) {
                    await refreshActiveChatLive();
                }
            }
        }
    } catch (e) {}
}
