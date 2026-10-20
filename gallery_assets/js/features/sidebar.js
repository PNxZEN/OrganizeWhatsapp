/* Sidebar chat filtering, sorting and rendering
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

let sidebarChatFilter = 'all'; // 'all', 'groups', 'direct', 'archived', 'inactive'
let sidebarChatSort = 'size'; // 'size', 'inactive', 'active', 'name'
let sidebarChatSortDirection = 'desc'; // 'desc' (default) | 'asc'

function setSidebarChatFilter(filter, el) {
    sidebarChatFilter = filter;
    document.querySelectorAll('#sidebarFilterChips .sidebar-chip').forEach(c => c.classList.remove('active'));
    if (el) el.classList.add('active');
    chatsToShow = 10;
    renderSidebar(false);
}

function setSidebarChatSort(sortVal) {
    sidebarChatSort = sortVal;
    chatsToShow = 10;
    renderSidebar(false);
}

function toggleSidebarSortDirection() {
    sidebarChatSortDirection = (sidebarChatSortDirection === 'desc') ? 'asc' : 'desc';
    const btn = document.getElementById('sidebarSortOrderBtn');
    const icon = document.getElementById('sidebarSortOrderIcon');
    if (btn) {
        btn.title = `Sort Order: ${sidebarChatSortDirection === 'desc' ? 'Descending' : 'Ascending'} (Click to toggle)`;
    }
    if (icon) {
        if (sidebarChatSortDirection === 'desc') {
            // Inverted pyramid: wide bar at top, tapering down to narrow bar
            icon.innerHTML = '<path d="M3 6h18v2.2H3zm3 5h12v2.2H6zm3 5h6v2.2H9z"/>';
        } else {
            // Pyramid: narrow bar at top, tapering down to wide bar
            icon.innerHTML = '<path d="M9 6h6v2.2H9zm-3 5h12v2.2H6zm-3 5h18v2.2H3z"/>';
        }
    }
    chatsToShow = 10;
    renderSidebar(false);
}

function updateSidebarActiveChat(activeJid) {
    const chatList = document.getElementById('chatList');
    if (!chatList) return;
    const items = chatList.querySelectorAll('.chat-item');
    if (items.length === 0) {
        renderSidebar();
        return;
    }
    items.forEach(el => {
        if (el.dataset.jid === activeJid) {
            el.classList.add('active');
        } else {
            el.classList.remove('active');
        }
    });
}

// Render sidebar chats
function renderSidebar(preserveScroll = true) {
    const chatList = document.getElementById('chatList');
    const prevScroll = (preserveScroll && chatList) ? chatList.scrollTop : 0;
    chatList.innerHTML = '';

    const rawChats = getChatsArray();
    const query = sidebarSearchQuery.toLowerCase().trim();
    const nowMs = Date.now();
    
    // Filter chats by search query and category
    const filteredChats = rawChats.filter(chat => {
        const displayName = chatNameForDisplay(chat.name);
        const chatJid = chat.jid || '';
        const matchQuery = displayName.toLowerCase().includes(query) || chatJid.toLowerCase().includes(query);
        if (!matchQuery) return false;

        const isArchived = Boolean(chat.archived || chat.chat_archived);
        const isGroup = Boolean(chat.is_group || (chat.jid && chat.jid.endsWith('@g.us')));
        const lastTs = Number(chat.last_message_ts || chat.chat_last_active_ts || 0);

        if (sidebarChatFilter === 'groups') {
            return isGroup;
        }
        if (sidebarChatFilter === 'direct') {
            return !isGroup;
        }
        if (sidebarChatFilter === 'archived') {
            return isArchived;
        }
        if (sidebarChatFilter === 'inactive') {
            if (!isGroup || !lastTs || lastTs <= 0) return false;
            const diffDays = (nowMs - lastTs) / 86400000;
            return diffDays >= 90;
        }
        return true;
    });

    // Sort chats
    const mult = (sidebarChatSortDirection === 'asc') ? -1 : 1;
    filteredChats.sort((a, b) => {
        if (sidebarChatSort === 'size') {
            return mult * ((b.total_size || 0) - (a.total_size || 0));
        }
        if (sidebarChatSort === 'inactive') {
            const tsA = Number(a.last_message_ts || a.chat_last_active_ts || 0);
            const tsB = Number(b.last_message_ts || b.chat_last_active_ts || 0);
            if (tsA === 0) return 1;
            if (tsB === 0) return -1;
            return mult * (tsA - tsB);
        }
        if (sidebarChatSort === 'active') {
            const tsA = Number(a.last_message_ts || a.chat_last_active_ts || 0);
            const tsB = Number(b.last_message_ts || b.chat_last_active_ts || 0);
            return mult * (tsB - tsA);
        }
        if (sidebarChatSort === 'name') {
            return mult * (a.name || '').localeCompare(b.name || '');
        }
        return 0;
    });

    const countToDisplay = Math.min(filteredChats.length, chatsToShow);
    const isReclaimMode = (typeof currentViewMode !== 'undefined' && currentViewMode === 'reclaim');

    for (let i = 0; i < countToDisplay; i++) {
        const chat = filteredChats[i];
        const activeClass = (activeChat && activeChat.jid === chat.jid) ? 'active' : '';

        const displayName = chatNameForDisplay(chat.name);
        const isArchived = Boolean(chat.archived || chat.chat_archived);
        const isGroup = Boolean(chat.is_group || (chat.jid && chat.jid.endsWith('@g.us')));
        const lastTs = Number(chat.last_message_ts || chat.chat_last_active_ts || 0);

        let badgesHtml = '';
        if (isArchived) {
            badgesHtml += '<span class="badge-pill" style="background: rgba(234, 179, 8, 0.2); color: #fef08a; font-size: 10px; padding: 1px 5px; border-radius: 4px; font-weight: 500;">Archived</span>';
        }
        if (isGroup && lastTs > 0) {
            const diffDays = Math.floor((nowMs - lastTs) / 86400000);
            if (diffDays >= 90) {
                const lbl = diffDays >= 365 ? `${(diffDays/365).toFixed(1)}y inactive` : `${Math.floor(diffDays/30)}mo inactive`;
                badgesHtml += `<span class="badge-pill" style="background: rgba(148, 163, 184, 0.15); color: #cbd5e1; font-size: 10px; padding: 1px 5px; border-radius: 4px; font-weight: 500;">${lbl}</span>`;
            }
        }

        const isTargetSelected = isReclaimMode ? customCleanTargetJids.has(chat.jid) : false;
        const item = document.createElement('div');
        item.className = `chat-item glass ${activeClass} ${isTargetSelected ? 'reclaim-selected' : ''}`;
        item.dataset.jid = chat.jid;

        let cbHtml = '';
        if (isReclaimMode) {
            cbHtml = `<input type="checkbox" class="chat-item-reclaim-cb" ${isTargetSelected ? 'checked' : ''} onclick="event.stopPropagation(); toggleCustomTargetChat('${escapeJsAttr(chat.jid)}');" title="Toggle chat in cleanup scope" />`;
        }

        const isDirectNumberShown = !isGroup && (formatJIDName(chat.jid) !== displayName);
        const numberSubtextHtml = isDirectNumberShown ? `<span style="font-size:0.72rem; color:var(--text-muted); text-overflow:ellipsis; overflow:hidden; white-space:nowrap; flex-shrink:0; max-width:130px;" title="${escapeHtml(chat.jid)}">${escapeHtml(formatJIDName(chat.jid))}</span>` : '';

        item.innerHTML = `
                    <div style="display: flex; align-items: center; gap: 8px; width: 100%;">
                        ${cbHtml}
                        <div style="flex: 1; min-width: 0;">
                            <div class="chat-meta">
                                <span class="chat-name" title="${escapeHtml(chat.jid)}">${escapeHtml(displayName || formatJIDName(chat.jid))}</span>
                                <span class="chat-size">${formatBytes(chat.total_size)}</span>
                            </div>
                            <div class="chat-details">
                                <div style="display: flex; align-items: center; gap: 6px; overflow: hidden; min-width: 0;">
                                    <span style="white-space: nowrap; flex-shrink: 0;">${chat.file_count} files</span>
                                    ${badgesHtml}
                                </div>
                                ${numberSubtextHtml}
                            </div>
                        </div>
                    </div>
                `;

        item.addEventListener('click', () => {
            if (isReclaimMode) {
                toggleCustomTargetChat(chat.jid);
            } else {
                selectChat(chat);
            }
        });
        chatList.appendChild(item);
    }

    // "See More" Button (Incremental pagination)
    if (filteredChats.length > countToDisplay) {
        const remaining = filteredChats.length - countToDisplay;
        const btn = document.createElement('button');
        btn.className = 'see-more-btn';
        btn.innerText = `See More (${remaining} more chats)`;
        btn.addEventListener('click', () => {
            chatsToShow += 10;
            renderSidebar(true);
        });
        chatList.appendChild(btn);
    }

    if (preserveScroll && chatList && prevScroll > 0) {
        chatList.scrollTop = prevScroll;
    }
}

function debounce(func, wait) {
    let timeout;
    return function(...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
}
