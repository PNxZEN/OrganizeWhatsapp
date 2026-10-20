/* Duplicate review modal, kept-as-unique items and undo
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

// DUPLICATE REVIEW & RECYCLE BIN MANAGEMENT

function updateDuplicateCountBadgesUI() {
    const badge = document.getElementById('hiddenDupsCount');
    const filter = document.getElementById('hideDuplicatesFilter');
    const hideDuplicates = filter ? filter.checked : true;
    const count = (window._currentChatDupSet ? window._currentChatDupSet.size : 0);
    if (badge) {
        if (count === 0) {
            badge.innerText = '(No duplicates)';
            badge.style.color = 'var(--text-muted)';
            badge.style.display = 'inline';
        } else if (hideDuplicates) {
            badge.innerText = `(${count} hidden)`;
            badge.style.color = 'var(--accent)';
            badge.style.display = 'inline';
        } else {
            badge.innerText = `(${count} duplicates)`;
            badge.style.color = 'var(--text-muted)';
            badge.style.display = 'inline';
        }
    }
}

function updateDuplicateReviewButtonUI() {
    const btnReview = document.getElementById('btnReviewDuplicates');
    const pillCount = document.getElementById('dupCountReviewPill');
    const btnQuick = document.getElementById('btnQuickReviewDups');
    const count = (window._currentChatDupSet ? window._currentChatDupSet.size : 0);

    if (btnReview) {
        if (count > 0) {
            btnReview.style.display = 'inline-flex';
            if (pillCount) pillCount.innerText = count;
        } else {
            btnReview.style.display = 'none';
        }
    }
    if (btnQuick) {
        if (count > 0) {
            btnQuick.style.display = 'inline-flex';
            btnQuick.innerText = `Review & Clean (${count})`;
        } else {
            btnQuick.style.display = 'none';
        }
    }
    updateDuplicateCountBadgesUI();
}

function openDuplicateReviewModal(initialTab = 'review') {
    if (initialTab === 'review') {
        const pairs = getFlattenedDupPairs();
        if (pairs && pairs.length > 0) {
            openDuplicateCompareFullscreen(pairs[0].grpIdx, pairs[0].dupIdx);
            return;
        } else {
            showToast('No duplicate pairs to review in this chat.', 'info');
            return;
        }
    }
    openModal('modalDuplicateReview');
    switchDuplicateTab(initialTab);
}

function switchDuplicateTab(tabName) {
    const btnReview = document.getElementById('tabBtnReview');
    const btnRecycle = document.getElementById('tabBtnRecycleBin');
    const btnIgnored = document.getElementById('tabBtnIgnored');
    const viewReview = document.getElementById('dupViewReview');
    const viewRecycle = document.getElementById('dupViewRecycleBin');
    const viewIgnored = document.getElementById('dupViewIgnored');
    const btnFullscreen = document.getElementById('btnSwitchToCompareView');

    [btnReview, btnRecycle, btnIgnored].forEach(b => { if (b) b.classList.remove('active'); });
    [viewReview, viewRecycle, viewIgnored].forEach(v => { if (v) v.style.display = 'none'; });

    if (btnFullscreen) {
        btnFullscreen.style.display = (tabName === 'review') ? 'inline-flex' : 'none';
    }

    if (tabName === 'review') {
        if (btnReview) btnReview.classList.add('active');
        if (viewReview) viewReview.style.display = 'flex';
        renderDuplicateReviewContent();
    } else if (tabName === 'recycle-bin') {
        if (btnRecycle) btnRecycle.classList.add('active');
        if (viewRecycle) viewRecycle.style.display = 'flex';
        loadRecycleBinContent();
    } else if (tabName === 'ignored') {
        if (btnIgnored) btnIgnored.classList.add('active');
        if (viewIgnored) viewIgnored.style.display = 'flex';
        renderIgnoredPairsContent();
    }
    updateIgnoredTabCount();
}

function getIgnoredItemsForCurrentChat() {
    if (!activeChat || !activeChat.media || !window._ignoredDupKeys) return [];
    const seen = new Set();
    const items = [];
    activeChat.media.forEach(item => {
        const k = item.rel_path || item.filename;
        if ((window._ignoredDupKeys.has(k) || window._ignoredDupKeys.has(item.filename)) && !seen.has(item.filename)) {
            seen.add(item.filename);
            items.push(item);
        }
    });
    return items;
}

function updateIgnoredTabCount() {
    const countEl = document.getElementById('ignoredTabCount');
    const items = getIgnoredItemsForCurrentChat();
    if (countEl) countEl.innerText = items.length;
    const totalEl = document.getElementById('ignoredTotalCount');
    if (totalEl) totalEl.innerText = `${items.length} file(s) marked as not duplicates`;
    const btnResetAll = document.getElementById('btnResetAllIgnored');
    if (btnResetAll) {
        btnResetAll.style.display = items.length > 0 ? 'inline-block' : 'none';
    }
}

function renderIgnoredPairsContent() {
    const listEl = document.getElementById('ignoredList');
    if (!listEl) return;
    updateIgnoredTabCount();
    const items = getIgnoredItemsForCurrentChat();

    if (items.length === 0) {
        listEl.innerHTML = `
                    <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:240px;color:var(--text-muted);gap:12px;text-align:center;">
                        <svg viewBox="0 0 24 24" style="width:42px;height:42px;fill:currentColor;opacity:0.4;"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>
                        <div style="font-size:15px;font-weight:600;color:var(--text-primary);">No Files Kept as Non-Duplicates</div>
                        <div style="font-size:13px;max-width:380px;">When you click "Keep Both (Not Duplicate)" on any duplicate candidate, it will be listed here. You can return it to duplicate review anytime.</div>
                    </div>
                `;
        return;
    }

    let html = '';
    items.forEach(item => {
        const k = item.rel_path || item.filename;
        const thumbUrl = isHttpServer 
            ? ('/api/thumbnail?path=' + encodeURIComponent(item.rel_path)) 
            : encodePathForUrl(item.thumb_path || item.rel_path);
        const sizeStr = formatBytes(item.size_bytes || 0);
        const dateStr = formatDateTime(item.received_at, item.rel_path);

        html += `
                    <div style="display:flex;align-items:center;justify-content:space-between;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:8px;padding:10px 14px;gap:14px;">
                        <div style="display:flex;align-items:center;gap:12px;min-width:0;flex:1;">
                            <img src="${escapeHtml(thumbUrl)}" alt="" style="width:48px;height:48px;object-fit:cover;border-radius:6px;background:#0f172a;border:1px solid rgba(255,255,255,0.1);flex-shrink:0;">
                            <div style="min-width:0;display:flex;flex-direction:column;gap:3px;">
                                <div style="font-size:13px;font-weight:600;color:var(--text-primary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escapeHtml(item.filename)}">
                                    ${escapeHtml(item.filename)}
                                </div>
                                <div style="font-size:11px;color:var(--text-muted);display:flex;align-items:center;gap:8px;">
                                    <span>${sizeStr}</span>
                                    <span>•</span>
                                    <span>${dateStr}</span>
                                    <span style="display:inline-block;padding:1px 6px;border-radius:4px;background:rgba(96,165,250,0.15);color:#93c5fd;font-size:10px;font-weight:600;">Kept by User</span>
                                </div>
                            </div>
                        </div>
                        <button type="button" class="action-btn action-btn-secondary" style="font-size:12px;padding:6px 12px;flex-shrink:0;color:#60a5fa;border-color:rgba(96,165,250,0.3);" onclick="restoreIgnoredDupItem('${escapeJsAttr(k)}')">
                            Move Back to Duplicates
                        </button>
                    </div>
                `;
    });
    listEl.innerHTML = html;
}

function restoreIgnoredDupItem(key) {
    if (!key || !window._ignoredDupKeys) return;
    const item = activeChat && activeChat.media ? activeChat.media.find(m => (m.rel_path === key || m.filename === key)) : null;
    window._ignoredDupKeys.delete(key);
    if (item) {
        if (item.rel_path) window._ignoredDupKeys.delete(item.rel_path);
        if (item.filename) window._ignoredDupKeys.delete(item.filename);
        item.is_duplicate = true;
    }
    try {
        localStorage.setItem('wa_ignored_dups', JSON.stringify(Array.from(window._ignoredDupKeys)));
    } catch (e) {}

    if (activeChat) activeChat._dupCache = null;
    filterAndRenderMedia({ preserveScroll: true, keepItemsCount: true });
    updateDuplicateReviewButtonUI();
    updateIgnoredTabCount();
    renderIgnoredPairsContent();
    renderDuplicateReviewContent();
    showToast('Moved file back to duplicate review.', 'success');
}

function executeResetAllIgnored() {
    const items = getIgnoredItemsForCurrentChat();
    if (items.length === 0) return;
    items.forEach(item => {
        if (item.rel_path) window._ignoredDupKeys.delete(item.rel_path);
        if (item.filename) window._ignoredDupKeys.delete(item.filename);
        item.is_duplicate = true;
    });
    try {
        localStorage.setItem('wa_ignored_dups', JSON.stringify(Array.from(window._ignoredDupKeys)));
    } catch (e) {}

    if (activeChat) activeChat._dupCache = null;
    filterAndRenderMedia({ preserveScroll: true, keepItemsCount: true });
    updateDuplicateReviewButtonUI();
    updateIgnoredTabCount();
    renderIgnoredPairsContent();
    renderDuplicateReviewContent();
    showToast('All kept files moved back to duplicate review.', 'success');
}

window._dupUndoStack = window._dupUndoStack || [];

function updateDupUndoButtonUI() {
    const btn = document.getElementById('btnDupCmpUndo');
    if (!btn) return;
    if (window._dupUndoStack && window._dupUndoStack.length > 0) {
        btn.style.display = 'inline-flex';
    } else {
        btn.style.display = 'none';
    }
}

function undoDismissDuplicate() {
    if (!window._dupUndoStack || window._dupUndoStack.length === 0) {
        showToast('Nothing to undo.', 'info');
        return;
    }
    const last = window._dupUndoStack.pop();
    updateDupUndoButtonUI();

    if (last) {
        if (window._ignoredDupKeys) {
            if (last.dupKey) window._ignoredDupKeys.delete(last.dupKey);
            if (last.dupFilename) window._ignoredDupKeys.delete(last.dupFilename);
            if (last.dupRelPath) window._ignoredDupKeys.delete(last.dupRelPath);
        }
        try {
            localStorage.setItem('wa_ignored_dups', JSON.stringify(Array.from(window._ignoredDupKeys)));
        } catch (e) {}

        if (last.item) {
            last.item.is_duplicate = true;
            if (last.primaryFilename) {
                last.item.duplicate_primary = last.primaryFilename;
            }
        }

        // Re-filter and render gallery
        if (activeChat) activeChat._dupCache = null;
        filterAndRenderMedia({ preserveScroll: true, keepItemsCount: true });
        updateDuplicateReviewButtonUI();
        renderDuplicateReviewContent();
        updateIgnoredTabCount();

        // If lightbox is currently open, navigate to this restored pair
        const lightbox = document.getElementById('lightboxDupCompare');
        if (lightbox && lightbox.style.display !== 'none') {
            const pairs = getFlattenedDupPairs();
            let targetIdx = pairs.findIndex(p => 
                (p.dup && (p.dup.rel_path === last.dupRelPath || p.dup.filename === last.dupFilename)) ||
                (p.primary && (p.primary.rel_path === last.dupRelPath || p.primary.filename === last.dupFilename))
            );
            if (targetIdx !== -1) {
                window._dupCmpActiveGroupIdx = pairs[targetIdx].grpIdx;
                window._dupCmpActiveDupIdx = pairs[targetIdx].dupIdx;
            }
            renderDupCompareLightbox();
        }

        showToast(`Restored "${last.dupFilename || 'item'}" back to duplicate review.`, 'info');
    }
}

function applyFiltersAndRender(options = {}) {
    if (typeof filterAndRenderMedia === 'function') {
        filterAndRenderMedia(options);
    }
}

window._cachedImageDims = window._cachedImageDims || {};
window._ignoredDupKeys = window._ignoredDupKeys || new Set();
try {
    const rawIgnored = localStorage.getItem('wa_ignored_dups');
    if (rawIgnored) {
        JSON.parse(rawIgnored).forEach(k => window._ignoredDupKeys.add(k));
    }
} catch (e) {}
