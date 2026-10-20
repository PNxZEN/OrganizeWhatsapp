/* Recycle Bin: recycle, restore and empty
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

function updateRecycleModalStats() {
    const checkboxes = document.querySelectorAll('.dup-recycle-item-cb:checked');
    let selectedBytes = 0;
    checkboxes.forEach(cb => {
        selectedBytes += parseInt(cb.getAttribute('data-size') || '0', 10);
    });
    const btnText = document.getElementById('btnExecuteRecycleText');
    const btn = document.getElementById('btnExecuteRecycle');
    if (btnText) {
        btnText.innerText = `Move Selected to Recycle Bin (${checkboxes.length} files, ${formatBytes(selectedBytes)})`;
    }
    if (btn) {
        btn.disabled = (checkboxes.length === 0);
    }
}

function setAllDuplicateCheckboxes(val) {
    const checkboxes = document.querySelectorAll('.dup-recycle-item-cb');
    checkboxes.forEach(cb => { cb.checked = val; });
    updateRecycleModalStats();
}

async function executeRecycleDuplicates() {
    if (!isHttpServer) {
        showToast('Launch gallery via start_gallery.bat for Recycle Bin features.', 'info');
        return;
    }
    const checkboxes = document.querySelectorAll('.dup-recycle-item-cb:checked');
    if (checkboxes.length === 0) return;

    const relPaths = Array.from(checkboxes).map(cb => cb.getAttribute('data-rel-path'));
    const btn = document.getElementById('btnExecuteRecycle');
    const btnText = document.getElementById('btnExecuteRecycleText');
    const origText = btnText ? btnText.innerText : 'Move Selected to Recycle Bin';

    if (btn) btn.disabled = true;
    if (btnText) btnText.innerText = 'Recycling files...';

    try {
        const resp = await fetch('/api/duplicates/recycle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rel_paths: relPaths })
        });
        const res = await resp.json();
        if (resp.ok && res.status === 'success') {
            showToast(`Moved ${res.recycled_count} duplicate(s) to Recycle Bin (freed ${formatBytes(res.reclaimed_bytes)}).`, 'success');

            // Remove recycled items from activeChat.media in memory
            if (activeChat && activeChat.media) {
                const recycledSet = new Set(relPaths);
                let freed = 0;
                activeChat.media = activeChat.media.filter(m => {
                    if (recycledSet.has(m.rel_path)) {
                        freed += (m.size_bytes || 0);
                        return false;
                    }
                    return true;
                });
                activeChat.file_count = activeChat.media.length;
                activeChat.total_size = Math.max(0, (activeChat.total_size || 0) - freed);

                // Update currentChatMeta
                const metaEl = document.getElementById('currentChatMeta');
                if (metaEl) {
                    metaEl.innerText = `${activeChat.file_count} files • Total storage: ${formatBytes(activeChat.total_size)}`;
                }
            }

            // Update sidebar and gallery
            if (activeChat) activeChat._dupCache = null;
            renderSidebar();
            filterAndRenderMedia({ preserveScroll: true, keepItemsCount: true });

            // Update Recycle Bin badge pill
            updateRecycleBinPill();

            // Re-render duplicate review or close if finished
            renderDuplicateReviewContent();
            if ((window._currentChatDupSet ? window._currentChatDupSet.size : 0) === 0) {
                setTimeout(() => closeModal('modalDuplicateReview'), 800);
            }
        } else {
            showToast(res.message || 'Recycle operation failed.', 'error');
        }
    } catch (e) {
        showToast(`Recycle error: ${e.message}`, 'error');
    } finally {
        if (btn) btn.disabled = false;
        if (btnText) btnText.innerText = origText;
    }
}

async function loadRecycleBinContent() {
    const listEl = document.getElementById('recycleBinList');
    const totalSizeEl = document.getElementById('recycleBinTotalSize');
    if (!listEl) return;

    if (!isHttpServer) {
        listEl.innerHTML = `
                    <div style="text-align:center;padding:40px;color:var(--text-muted);">
                        Recycle Bin inspection is available in server mode. Run start_gallery.bat to view and restore items.
                    </div>
                `;
        return;
    }

    listEl.innerHTML = `
                <div style="display:flex;align-items:center;justify-content:center;height:160px;gap:10px;color:var(--text-muted);">
                    <div class="sync-spinner" style="width:20px;height:20px;border-width:2px;"></div>
                    <span>Loading Recycle Bin items...</span>
                </div>
            `;

    try {
        const resp = await fetch('/api/duplicates/recycle-bin');
        const data = await resp.json();
        if (resp.ok && (data.success || data.status === 'success')) {
            const items = data.items || [];
            const tabCountEl = document.getElementById('recycleBinTabCount');
            if (tabCountEl) tabCountEl.innerText = items.length;
            const pillCount = document.getElementById('recycleBinCountPill');
            const btnOpen = document.getElementById('btnOpenRecycleBin');
            if (pillCount) {
                pillCount.innerText = items.length;
                pillCount.style.display = items.length > 0 ? 'inline-flex' : 'none';
            }
            if (btnOpen) {
                btnOpen.classList.toggle('has-items', items.length > 0);
            }

            if (totalSizeEl) {
                totalSizeEl.innerText = `${items.length} file(s) quarantined (${formatBytes(data.total_bytes || 0)})`;
            }

            // Drop selections for items that are no longer in the bin
            const presentPaths = new Set(items.map(it => it.rel_path));
            Array.from(_recycleSelectedPaths).forEach(p => { if (!presentPaths.has(p)) _recycleSelectedPaths.delete(p); });
            const selectAllWrap = document.getElementById('recycleSelectAllWrap');
            if (selectAllWrap) selectAllWrap.style.display = items.length > 0 ? 'inline-flex' : 'none';

            if (items.length === 0) {
                updateRecycleSelectionUI();
                listEl.innerHTML = `
                            <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:220px;color:var(--text-muted);gap:12px;text-align:center;">
                                <svg viewBox="0 0 24 24" style="width:40px;height:40px;fill:currentColor;opacity:0.35;"><path d="M19 4h-3.5l-1-1h-5l-1 1H5v2h14M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12z"/></svg>
                                <div style="font-size:15px;font-weight:600;color:var(--text-primary);">Recycle Bin is Empty</div>
                                <div style="font-size:13px;max-width:320px;">No quarantined duplicates found. Any duplicate you move here will appear and can be restored.</div>
                            </div>
                        `;
                const btnRestoreAll = document.getElementById('btnRestoreAll');
                if (btnRestoreAll) btnRestoreAll.style.display = 'none';
                const btnEmpty = document.getElementById('btnEmptyRecycleBin');
                if (btnEmpty) btnEmpty.style.display = 'none';
                return;
            }

            const btnRestoreAll = document.getElementById('btnRestoreAll');
            if (btnRestoreAll) {
                btnRestoreAll.style.display = 'inline-flex';
                btnRestoreAll.innerText = `Restore All (${items.length} files)`;
            }
            const btnEmpty = document.getElementById('btnEmptyRecycleBin');
            if (btnEmpty) {
                btnEmpty.style.display = 'inline-flex';
            }

            let html = '';
            items.forEach(item => {
                const thumbSrc = '/api/thumbnail?path=' + encodeURIComponent(item.recycled_path || ('.duplicates_recycle_bin/' + item.rel_path));
                const chatFolder = item.original_chat || '';
                html += `
                            <div class="recycle-bin-item">
                                <input type="checkbox" class="recycle-bin-item-cb" data-rel-path="${escapeHtml(item.rel_path)}" ${_recycleSelectedPaths.has(item.rel_path) ? 'checked' : ''} onchange="toggleRecycleItemSelection(this)" title="Select for restore" aria-label="Select ${escapeHtml(item.filename)}">
                                <img src="${escapeHtml(thumbSrc)}" class="recycle-thumb" alt="${escapeHtml(item.filename)}" onerror="this.style.display='none'">
                                <div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:3px;">
                                    <div style="font-size:13px;font-weight:600;color:var(--text-primary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                                        ${escapeHtml(item.filename)}
                                    </div>
                                    <div style="font-size:11px;color:var(--text-muted);display:flex;gap:10px;flex-wrap:wrap;">
                                        <span>Chat: ${escapeHtml(chatFolder)}</span>
                                        <span>Size: <b style="color:var(--text-primary);">${formatBytes(item.size_bytes || 0)}</b></span>
                                        <span>Reason: ${escapeHtml(item.reason || 'quality')}</span>
                                    </div>
                                </div>
                                <button type="button" class="action-btn action-btn-secondary" style="font-size:11px;padding:5px 12px;color:#4ade80;border-color:rgba(34,197,94,0.3);background:rgba(34,197,94,0.08);" onclick="executeRestoreItem('${escapeJsAttr(item.rel_path)}')">
                                    Restore
                                </button>
                            </div>
                        `;
            });
            listEl.innerHTML = html;
            updateRecycleSelectionUI();
        } else {
            listEl.innerHTML = `<div style="color:#f87171;padding:20px;">Failed to load Recycle Bin: ${escapeHtml(data.error || 'Server error')}</div>`;
        }
    } catch (e) {
        listEl.innerHTML = `<div style="color:#f87171;padding:20px;">Error loading Recycle Bin: ${escapeHtml(e.message)}</div>`;
    }
}

// rel_paths currently checked in the Recycle Bin list (survives list reloads)
const _recycleSelectedPaths = new Set();

function updateRecycleSelectionUI() {
    const btn = document.getElementById('btnRestoreSelected');
    const countEl = document.getElementById('restoreSelectedCount');
    const selectAll = document.getElementById('recycleSelectAll');
    const boxes = Array.from(document.querySelectorAll('.recycle-bin-item-cb'));
    const count = _recycleSelectedPaths.size;
    if (countEl) countEl.innerText = count;
    if (btn) btn.style.display = count > 0 ? 'inline-flex' : 'none';
    if (selectAll) {
        selectAll.checked = boxes.length > 0 && count === boxes.length;
        selectAll.indeterminate = count > 0 && count < boxes.length;
    }
    boxes.forEach(cb => {
        const row = cb.closest('.recycle-bin-item');
        if (row) row.classList.toggle('selected', cb.checked);
    });
}

function toggleRecycleItemSelection(checkbox) {
    const relPath = checkbox.getAttribute('data-rel-path');
    if (!relPath) return;
    if (checkbox.checked) {
        _recycleSelectedPaths.add(relPath);
    } else {
        _recycleSelectedPaths.delete(relPath);
    }
    updateRecycleSelectionUI();
}

function toggleSelectAllRecycleItems(checked) {
    document.querySelectorAll('.recycle-bin-item-cb').forEach(cb => {
        cb.checked = checked;
        const relPath = cb.getAttribute('data-rel-path');
        if (!relPath) return;
        if (checked) _recycleSelectedPaths.add(relPath);
        else _recycleSelectedPaths.delete(relPath);
    });
    updateRecycleSelectionUI();
}

// Restores items from the Recycle Bin. payload is { rel_paths: [...] } or { all: true }.
async function restoreRecycledItems(payload, pendingMessage) {
    if (!isHttpServer) return;
    showToast(pendingMessage);
    try {
        const resp = await fetch('/api/duplicates/restore', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const res = await resp.json();
        if (resp.ok && res.status === 'success') {
            const restoredCount = res.restored_count || 0;
            showToast(`Restored ${restoredCount} item(s) to original chats.`, 'success');
            (payload.rel_paths || []).forEach(p => _recycleSelectedPaths.delete(p));
            if (payload.all) _recycleSelectedPaths.clear();
            loadRecycleBinContent();
            updateRecycleBinPill();
            if (activeChat) {
                const refreshedChat = activeChat;
                try {
                    const cRes = await fetch('/api/chats/' + encodeURIComponent(refreshedChat.jid) + '/media');
                    if (cRes.ok && activeChat === refreshedChat) {
                        const cData = await cRes.json();
                        refreshedChat.media = cData.media || [];
                        refreshedChat.file_count = cData.file_count || refreshedChat.media.length;
                        refreshedChat.total_size = cData.total_size || refreshedChat.total_size;
                        refreshedChat._dupCache = null;
                        renderSidebar();
                        filterAndRenderMedia({ preserveScroll: true, keepItemsCount: true });
                    }
                } catch (err) {}
            }
        } else {
            showToast(res.message || 'Restore failed.', 'error');
        }
    } catch (e) {
        showToast(`Restore error: ${e.message}`, 'error');
    }
}

async function executeRestoreItem(relPath) {
    await restoreRecycledItems({ rel_paths: [relPath] }, 'Restoring item to chat folder...');
}

async function executeRestoreSelected() {
    const relPaths = Array.from(_recycleSelectedPaths);
    if (relPaths.length === 0) {
        showToast('Select one or more items to restore.', 'info');
        return;
    }
    await restoreRecycledItems({ rel_paths: relPaths }, `Restoring ${relPaths.length} selected item(s)...`);
}

async function executeRestoreAll() {
    if (!isHttpServer) return;
    if (!confirm('Restore all items from the Recycle Bin back to their original chat folders?')) return;
    await restoreRecycledItems({ all: true }, 'Restoring all items to original folders...');
}

async function executeEmptyRecycleBin() {
    if (!isHttpServer) return;
    if (!confirm('Permanently delete and empty all items in the Recycle Bin? This action cannot be undone.')) return;
    showToast('Emptying Recycle Bin...');
    try {
        const resp = await fetch('/api/duplicates/empty-recycle-bin', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const res = await resp.json();
        if (resp.ok && (res.status === 'success' || res.success)) {
            showToast(`Recycle Bin emptied: ${res.deleted_count || 0} file(s) permanently deleted.`, 'success');
            loadRecycleBinContent();
            updateRecycleBinPill();
        } else {
            showToast(res.message || 'Failed to empty Recycle Bin.', 'error');
        }
    } catch (e) {
        showToast(`Empty Recycle Bin error: ${e.message}`, 'error');
    }
}

async function updateRecycleBinPill() {
    if (!isHttpServer) return;
    try {
        const resp = await fetch('/api/duplicates/recycle-bin');
        const data = await resp.json();
        if (resp.ok && (data.success || data.status === 'success')) {
            const count = data.count || (data.items ? data.items.length : 0);
            const totalBytes = data.total_bytes || 0;
            const pill = document.getElementById('recycleBinCountPill');
            const tabCount = document.getElementById('recycleBinTabCount');
            const btnOpen = document.getElementById('btnOpenRecycleBin');
            const totalText = document.getElementById('settingsRecycleTotalText');
            const btnEmpty = document.getElementById('btnSettingsEmptyBin');
            const shortcutBox = document.getElementById('settingsKeyRecycleShortcut');
            const shortcutText = document.getElementById('settingsKeyRecycleShortcutText');

            if (pill) {
                pill.innerText = count;
                pill.style.display = count > 0 ? 'inline-flex' : 'none';
            }
            if (btnOpen) {
                btnOpen.classList.toggle('has-items', count > 0);
            }
            if (tabCount) {
                tabCount.innerText = count;
            }
            if (totalText) {
                totalText.innerText = `${count} file(s) quarantined (${formatBytes(totalBytes)})`;
            }
            if (btnEmpty) {
                btnEmpty.style.display = count > 0 ? 'inline-flex' : 'none';
            }
            if (shortcutBox) {
                shortcutBox.style.display = count > 0 ? 'flex' : 'none';
                if (shortcutText) {
                    shortcutText.innerText = `${count} file(s) in Recycle Bin (${formatBytes(totalBytes)})`;
                }
            }
        }
    } catch (e) {}
}
