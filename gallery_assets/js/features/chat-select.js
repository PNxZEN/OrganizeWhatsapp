/* Chat selection, lazy media loading and sender filter
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

function openLightboxForRelPath(relPath) {
    if (!activeChat || !activeChat.media) return;
    const idx = filteredMedia.findIndex(m => m.rel_path === relPath || m.filename === relPath);
    if (idx !== -1) {
        openLightbox(idx);
        return;
    }
    const item = activeChat.media.find(m => m.rel_path === relPath || m.filename === relPath);
    if (item) {
        const tempIdx = filteredMedia.length;
        filteredMedia.push(item);
        openLightbox(tempIdx);
    }
}

let _activeChatRequestId = 0;
let _activeChatAbortCtrl = null;

// Select a Chat
// On narrow windows the chat list is a drawer over the gallery
function toggleSidebarDrawer(open) {
    const want = typeof open === 'boolean' ? open : !document.body.classList.contains('sidebar-open');
    document.body.classList.toggle('sidebar-open', want);
}

async function selectChat(chat, pushHistory = true) {
    _activeChatRequestId++;
    const thisRequestId = _activeChatRequestId;

    if (_activeChatAbortCtrl) {
        try {
            _activeChatAbortCtrl.abort();
        } catch (e) {}
        _activeChatAbortCtrl = null;
    }

    // Immediately clear background video candidate queue from prior chat
    window._videoHashQueue = [];

    if (!chat) {
        activeChat = null;
        updateSidebarActiveChat(null);
        const titleEl = document.getElementById('currentChatName');
        const metaEl = document.getElementById('currentChatMeta');
        if (titleEl) titleEl.innerText = 'All WhatsApp Media';
        if (metaEl) metaEl.innerText = 'Select a chat from the sidebar or browse recent files';
        filterAndRenderMedia();
        return;
    }

    if (pushHistory) {
        try {
            history.pushState({ app: 'wa_gallery', view: 'chat', chat: chat.jid }, '');
        } catch (e) {}
    }
    activeChat = chat;
    window._pendingNewMedia = null;
    const pill = document.getElementById('newMediaPill');
    if (pill) pill.style.display = 'none';
    
    // Fast active class toggle in sidebar without rebuilding all DOM nodes
    updateSidebarActiveChat(chat.jid);

    // Update main header
    const displayName = chatNameForDisplay(chat.name) || formatJIDName(chat.jid);
    const nameEl = document.getElementById('currentChatName');
    nameEl.innerText = displayName;
    nameEl.title = displayName;  // long names are shortened to two lines
    toggleSidebarDrawer(false);
    const subtitle = (chat.jid === '_unmatched') 
        ? `${chat.file_count} files • Unindexed WhatsApp Media` 
        : `${chat.file_count} files • Total storage: ${formatBytes(chat.total_size)}`;
    document.getElementById('currentChatMeta').innerText = subtitle;
    
    // Reset selection state and wire buttons
    resetSelectionUI();
    setupChatActionButtons();

    // Show and reset filter panel
    const filterPanelEl = document.getElementById('filterPanel');
    filterPanelEl.style.display = 'flex';
    filterPanelEl.classList.remove('collapsed');
    isFilterCollapsed = false;
    lastFilterScrollTop = 0;

    const btnToggleFilters = document.getElementById('btnToggleFilters');
    if (btnToggleFilters) {
        btnToggleFilters.style.display = 'inline-flex';
        updateFilterToggleBtnState(false);
    }

    // If media is already cached in memory, render immediately!
    if (chat.media && chat.media.length > 0) {
        if (!chat._relPathDeduped) {
            const seenRel = new Set();
            const uniqueList = [];
            for (const item of chat.media) {
                const r = item.rel_path;
                if (r) {
                    if (seenRel.has(r)) continue;
                    seenRel.add(r);
                }
                uniqueList.push(item);
            }
            chat.media = uniqueList;
            chat._relPathDeduped = true;
        }
        populateSenders(chat.media);
        setDateRangeLimits(chat.media);
        document.getElementById('searchFilter').value = '';
        document.getElementById('senderFilter').value = 'all';
        document.getElementById('hideDuplicatesFilter').checked = true;
        document.getElementById('directionFilter').value = 'all';
        document.getElementById('starredFilter').checked = false;
        document.getElementById('forwardedFilter').checked = false;
        document.getElementById('freqForwardedFilter').checked = false;
        activeTypes = new Set(['all']);
        updateTypeFilterButtonsUI();
        filterAndRenderMedia();
        queueVideoCandidateHashing(chat, true);
        return;
    }

    // If running over HTTP server and media not yet loaded in memory:
    if (isHttpServer) {
        if (chat.file_count > 0) {
            const container = document.getElementById('galleryContent');
            if (container) {
                container.innerHTML = `
                            <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:350px;gap:16px;color:var(--text-secondary);animation:fadeIn 0.2s ease;">
                                <div class="sync-spinner" style="width:36px;height:36px;border-width:3px;"></div>
                                <div style="font-size:14px;font-weight:500;color:var(--text-primary);">Loading media for ${escapeHtml(displayName)}...</div>
                            </div>
                        `;
            }
            const abortCtrl = new AbortController();
            _activeChatAbortCtrl = abortCtrl;
            try {
                const res = await fetch('/api/chats/' + encodeURIComponent(chat.jid) + '/media', { signal: abortCtrl.signal });
                if (thisRequestId !== _activeChatRequestId) return;
                if (res.ok) {
                    const data = await res.json();
                    if (thisRequestId !== _activeChatRequestId) return;
                    const rawMedia = data.media || [];
                    const seenRel = new Set();
                    const uniqueList = [];
                    for (const item of rawMedia) {
                        const r = item.rel_path;
                        if (r) {
                            if (seenRel.has(r)) continue;
                            seenRel.add(r);
                        }
                        uniqueList.push(item);
                    }
                    chat.media = uniqueList;
                    chat._relPathDeduped = true;
                    chat.media.forEach(item => {
                        if (!item.monthGroup) {
                            item.monthGroup = getMonthGroupForItem(item);
                        }
                    });
                    if (data.total_size !== undefined) {
                        chat.total_size = data.total_size;
                    }
                    if (data.file_count !== undefined) {
                        chat.file_count = data.file_count;
                    }
                    const metaEl = document.getElementById('currentChatMeta');
                    if (metaEl && activeChat && activeChat.jid === chat.jid) {
                        const sub = (chat.jid === '_unmatched') 
                            ? `${chat.file_count} files • Unindexed WhatsApp Media` 
                            : `${chat.file_count} files • Total storage: ${formatBytes(chat.total_size)}`;
                        metaEl.innerText = sub;
                    }
                } else {
                    chat.media = [];
                }
            } catch (e) {
                if (e.name === 'AbortError') return;
                console.error('Failed to load chat media:', e);
                chat.media = [];
            } finally {
                if (_activeChatAbortCtrl === abortCtrl) {
                    _activeChatAbortCtrl = null;
                }
            }
        } else {
            chat.media = [];
        }
    } else if (!chat.media) {
        chat.media = [];
    }

    if (thisRequestId !== _activeChatRequestId) return;
    if (activeChat && activeChat.jid !== chat.jid) return;

    // Populate sender filter safely
    populateSenders(chat.media);

    // Set date limits safely
    setDateRangeLimits(chat.media);

    // Clear inputs
    document.getElementById('searchFilter').value = '';
    document.getElementById('senderFilter').value = 'all';
    document.getElementById('hideDuplicatesFilter').checked = true;
    document.getElementById('directionFilter').value = 'all';
    document.getElementById('starredFilter').checked = false;
    document.getElementById('forwardedFilter').checked = false;
    document.getElementById('freqForwardedFilter').checked = false;
    activeTypes = new Set(['all']);
    updateTypeFilterButtonsUI();
    filterAndRenderMedia();
    queueVideoCandidateHashing(chat, true);
}

// Populate sender dropdown
function populateSenders(media, preserveSelection = false) {
    const senderSelect = document.getElementById('senderFilter');
    if (!senderSelect) return;
    const prevVal = preserveSelection ? senderSelect.value : 'all';
    senderSelect.innerHTML = '<option value="all">All Senders</option>';

    const nameToJids = {};
    (media || []).forEach(m => {
        if (m.sender_jid) {
            const name = m.sender_name || formatJIDName(m.sender_jid);
            if (!nameToJids[name]) {
                nameToJids[name] = [];
            }
            if (!nameToJids[name].includes(m.sender_jid)) {
                nameToJids[name].push(m.sender_jid);
            }
        }
    });

    const sortedNames = Object.keys(nameToJids);
    sortedNames.sort((a, b) => a.localeCompare(b, undefined, {sensitivity: 'base'}));

    sortedNames.forEach(name => {
        const opt = document.createElement('option');
        opt.value = JSON.stringify(nameToJids[name]);
        opt.innerText = name;
        senderSelect.appendChild(opt);
    });

    if (preserveSelection && prevVal) {
        senderSelect.value = prevVal;
    }
}
