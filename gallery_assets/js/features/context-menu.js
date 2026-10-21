/* Right-click context menu, clipboard and properties modal
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

// Context Menu & Properties Controller
let contextTargetItem = null;
let contextTargetIndex = -1;

// Media entries do not carry their chat: look it up (the open chat first)
function chatNameOfMedia(item) {
    if (item.chat_name) return item.chat_name;
    const owns = (chat) => chat && Array.isArray(chat.media) && chat.media.some(m => m.rel_path === item.rel_path);
    const chat = owns(activeChat) ? activeChat : getChatsArray().find(owns);
    return chat ? (chatNameForDisplay(chat.name) || chat.name) : 'Unknown chat';
}

function getMediaItemByRelPath(relPath) {
    if (!relPath) return null;
    if (contextTargetItem && contextTargetItem.rel_path === relPath) {
        return contextTargetItem;
    }
    if (Array.isArray(filteredMedia)) {
        const found = filteredMedia.find(m => m.rel_path === relPath);
        if (found) return found;
    }
    const allChats = getChatsArray();
    for (const chat of allChats) {
        if (Array.isArray(chat.media)) {
            const found = chat.media.find(m => m.rel_path === relPath);
            if (found) return found;
        }
    }
    return null;
}

function openMediaContextMenu(e, item, originalIndex) {
    if (!item) return;
    contextTargetItem = item;
    contextTargetIndex = originalIndex;

    const isCtrlHeld = !!(e.ctrlKey || e.metaKey);

    if (isCtrlHeld) {
        // Ctrl+RightClick adds or keeps this item in multi-selection
        if (!selectModeActive) {
            enterSelectionMode();
        }
        if (!selectedFiles.includes(item.rel_path)) {
            selectedFiles.push(item.rel_path);
            const card = document.querySelector(`.media-card[data-rel-path="${CSS.escape(item.rel_path)}"]`);
            if (card) card.classList.add('selected');
        }
        updateSelectionUI();
    } else if (!selectedFiles.includes(item.rel_path)) {
        // Right-clicking an unselected item without Ctrl selects only this single item
        if (!selectModeActive) {
            enterSelectionMode();
        }
        selectedFiles = [item.rel_path];
        document.querySelectorAll('.media-card').forEach(c => {
            if (c.dataset.relPath === item.rel_path) {
                c.classList.add('selected');
            } else {
                c.classList.remove('selected');
            }
        });
        updateSelectionUI();
    }
    // If right-clicking one of the already-selected items without Ctrl,
    // we PRESERVE all selected items so batch actions operate on all of them!

    const count = selectedFiles.length;
    const menu = document.getElementById('mediaContextMenu');
    if (!menu) return;

    const title = document.getElementById('ctxMenuTitle');
    const subtitle = document.getElementById('ctxMenuSubtitle');
    const backupLabel = document.getElementById('ctxActionBackupLabel');
    const toggleSelectLabel = document.getElementById('ctxActionToggleSelectLabel');
    const copyPathLabel = document.getElementById('ctxActionCopyPathLabel');
    const selectAllLabel = document.getElementById('ctxActionSelectAllLabel');
    const copyHashBtn = document.getElementById('ctxActionCopyHash');

    if (title) title.innerText = count === 1 ? '1 item selected' : `${count} items selected`;
    if (subtitle) {
        if (count === 1) {
            subtitle.innerText = item.filename || 'Media file';
        } else {
            subtitle.innerText = `${item.filename || 'Media'} (+${count - 1} more)`;
        }
    }
    if (backupLabel) backupLabel.innerText = count > 1 ? `Backup Selected (${count})` : 'Backup Selected (ZIP)';
    if (copyPathLabel) copyPathLabel.innerText = count > 1 ? `Copy ${count} File Paths` : 'Copy File Path';
    if (toggleSelectLabel) {
        toggleSelectLabel.innerText = selectedFiles.includes(item.rel_path) ? 'Deselect Item' : 'Select Item';
    }
    if (selectAllLabel && Array.isArray(filteredMedia) && filteredMedia.length > 0) {
        const isAll = (selectedFiles.length >= filteredMedia.length && filteredMedia.every(m => selectedFiles.includes(m.rel_path)));
        selectAllLabel.innerText = isAll ? 'Deselect All' : 'Select All';
    }
    if (copyHashBtn) {
        copyHashBtn.style.display = item.md5 ? 'flex' : 'none';
    }
    const recycleLabel = document.getElementById('ctxActionRecycleLabel');
    const deleteLabel = document.getElementById('ctxActionDeleteLabel');
    if (recycleLabel) recycleLabel.innerText = count > 1 ? `Move ${count} to Recycle Bin` : 'Move to Recycle Bin';
    if (deleteLabel) deleteLabel.innerText = count > 1 ? `Delete ${count} Permanently` : 'Delete Permanently';
    ['ctxDeleteDivider', 'ctxActionRecycle', 'ctxActionDelete'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = isHttpServer ? '' : 'none';
    });

    menu.style.display = 'block';
    menu.setAttribute('aria-hidden', 'false');

    const menuWidth = menu.offsetWidth || 230;
    const menuHeight = menu.offsetHeight || 260;
    const winWidth = window.innerWidth;
    const winHeight = window.innerHeight;

    let posX = e.clientX;
    let posY = e.clientY;

    if (posX + menuWidth > winWidth - 10) {
        posX = Math.max(10, winWidth - menuWidth - 10);
    }
    if (posY + menuHeight > winHeight - 10) {
        posY = Math.max(10, winHeight - menuHeight - 10);
    }

    menu.style.left = `${posX}px`;
    menu.style.top = `${posY}px`;
}

function closeMediaContextMenu() {
    const menu = document.getElementById('mediaContextMenu');
    if (menu && menu.style.display !== 'none') {
        menu.style.display = 'none';
        menu.setAttribute('aria-hidden', 'true');
    }
}

function handleCtxPreview() {
    closeMediaContextMenu();
    if (contextTargetIndex >= 0) {
        openLightbox(contextTargetIndex);
    }
}

function handleCtxBackup() {
    closeMediaContextMenu();
    if (typeof handleBackupSelected === 'function') {
        handleBackupSelected();
    }
}

function handleCtxReveal() {
    closeMediaContextMenu();
    if (contextTargetItem && contextTargetItem.rel_path) {
        revealInExplorer(contextTargetItem.rel_path);
    }
}

// ---------------------------------------------------------------- removing media from the gallery

function selectedOrTargetPaths() {
    if (Array.isArray(selectedFiles) && selectedFiles.length > 0) return [...selectedFiles];
    return contextTargetItem && contextTargetItem.rel_path ? [contextTargetItem.rel_path] : [];
}

// Drops removed media from the open chat without reloading it
function removeMediaFromView(relPaths) {
    const gone = new Set(relPaths);
    if (activeChat && Array.isArray(activeChat.media)) {
        let freed = 0;
        activeChat.media = activeChat.media.filter(m => {
            if (gone.has(m.rel_path)) { freed += (m.size_bytes || 0); return false; }
            return true;
        });
        activeChat.file_count = activeChat.media.length;
        activeChat.total_size = Math.max(0, (activeChat.total_size || 0) - freed);
        activeChat._dupCache = null;
        const metaEl = document.getElementById('currentChatMeta');
        if (metaEl) metaEl.innerText = `${activeChat.file_count} files • Total storage: ${formatBytes(activeChat.total_size)}`;
    }
    resetSelectionUI();
    renderSidebar();
    filterAndRenderMedia({ preserveScroll: true, keepItemsCount: true });
}

async function recycleMediaFromGallery(relPaths) {
    if (!isHttpServer || relPaths.length === 0) return;
    try {
        const resp = await fetch('/api/duplicates/recycle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rel_paths: relPaths })
        });
        const res = await resp.json();
        if (!resp.ok || res.status !== 'success') {
            showToast(res.message || 'Could not move to the Recycle Bin.', 'error');
            return;
        }
        const moved = (res.moved || []).map(m => m.rel_path);
        removeMediaFromView(moved);
        updateRecycleBinPill();
        showToast(`Moved ${moved.length} item(s) to the Recycle Bin.`, 'success', 'Undo',
            () => restoreRecycledItems({ rel_paths: moved }, 'Putting them back...'));
    } catch (e) {
        showToast(`Recycle error: ${e.message}`, 'error');
    }
}

async function deleteMediaFromGallery(relPaths) {
    if (!isHttpServer || relPaths.length === 0) return;
    if (!confirm(permanentDeleteWarning(relPaths.length))) return;
    try {
        const resp = await fetch('/api/media/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rel_paths: relPaths })
        });
        const res = await resp.json();
        if (!resp.ok || res.status !== 'success') {
            showToast(res.message || 'Delete failed.', 'error');
            return;
        }
        removeMediaFromView(res.deleted || []);
        showToast(`Permanently deleted ${res.deleted_count} file(s), freed ${formatBytes(res.freed_bytes || 0)}.`, 'success');
    } catch (e) {
        showToast(`Delete error: ${e.message}`, 'error');
    }
}

function handleCtxRecycle() {
    closeMediaContextMenu();
    recycleMediaFromGallery(selectedOrTargetPaths());
}

function handleCtxDeletePermanently() {
    closeMediaContextMenu();
    deleteMediaFromGallery(selectedOrTargetPaths());
}

function handleCtxProperties() {
    closeMediaContextMenu();
    openMediaPropertiesModal();
}

function handleCtxCopyPath() {
    closeMediaContextMenu();
    if (!selectedFiles || selectedFiles.length === 0) {
        if (contextTargetItem && contextTargetItem.rel_path) {
            copyTextToClipboard(contextTargetItem.rel_path, 'File path copied to clipboard');
        }
        return;
    }
    if (selectedFiles.length === 1) {
        copyTextToClipboard(selectedFiles[0], 'File path copied to clipboard');
    } else {
        copyTextToClipboard(selectedFiles.join('\n'), `${selectedFiles.length} file paths copied to clipboard`);
    }
}

function handleCtxCopyHash() {
    closeMediaContextMenu();
    if (contextTargetItem && contextTargetItem.md5) {
        copyTextToClipboard(contextTargetItem.md5, 'MD5 checksum copied to clipboard');
    }
}

function handleCtxToggleSelect() {
    closeMediaContextMenu();
    if (contextTargetItem) {
        const card = document.querySelector(`.media-card[data-rel-path="${CSS.escape(contextTargetItem.rel_path)}"]`);
        if (card) {
            toggleCardSelection(card, contextTargetItem.rel_path);
        } else {
            const idx = selectedFiles.indexOf(contextTargetItem.rel_path);
            if (idx !== -1) {
                selectedFiles.splice(idx, 1);
            } else {
                selectedFiles.push(contextTargetItem.rel_path);
            }
            updateSelectionUI();
        }
    }
}

function handleCtxClearSelection() {
    closeMediaContextMenu();
    resetSelectionUI();
}

function copyTextToClipboard(text, msg = 'Copied to clipboard!') {
    if (!text) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => {
            showToast(msg, 'success');
        }).catch(() => {
            fallbackCopyText(text, msg);
        });
    } else {
        fallbackCopyText(text, msg);
    }
}

function fallbackCopyText(text, msg) {
    try {
        const textArea = document.createElement('textarea');
        textArea.value = text;
        textArea.style.position = 'fixed';
        textArea.style.left = '-9999px';
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
        showToast(msg, 'success');
    } catch (err) {
        showToast('Failed to copy text', 'error');
    }
}

function openMediaPropertiesModal() {
    const body = document.getElementById('mediaPropertiesBody');
    const title = document.getElementById('mediaPropertiesTitle');
    const footerLeft = document.getElementById('mediaPropertiesFooterLeft');
    const footerRight = document.getElementById('mediaPropertiesFooterRight');
    if (!body) return;

    const targetPaths = (selectedFiles && selectedFiles.length > 0)
        ? selectedFiles
        : (contextTargetItem ? [contextTargetItem.rel_path] : []);

    if (targetPaths.length === 0) {
        showToast('No media item selected for properties', 'info');
        return;
    }

    const items = targetPaths.map(p => getMediaItemByRelPath(p)).filter(Boolean);
    if (items.length === 0) {
        showToast('Media metadata not found', 'warning');
        return;
    }

    if (items.length === 1) {
        const item = items[0];
        if (title) title.innerText = 'Media Properties';

        let thumbHtml = '';
        const mime = (item.mime_type || '').toLowerCase();
        const fn = (item.filename || '').toLowerCase();
        if (mime.startsWith('image/') || fn.endsWith('.jpg') || fn.endsWith('.png') || fn.endsWith('.webp')) {
            thumbHtml = `<img src="${escapeHtml(getMediaUrl(item.rel_path))}" alt="" style="width:68px; height:68px; object-fit:cover; border-radius:8px; border:1px solid rgba(255,255,255,0.1); background:#000;">`;
        } else if (mime.startsWith('video/') || fn.endsWith('.mp4')) {
            thumbHtml = `<div style="width:68px; height:68px; border-radius:8px; background:rgba(59,130,246,0.15); border:1px solid rgba(59,130,246,0.3); display:flex; align-items:center; justify-content:center; color:#93c5fd;"><svg viewBox="0 0 24 24" style="width:32px;height:32px;fill:currentColor;"><path d="M8 5v14l11-7z"/></svg></div>`;
        } else if (mime.startsWith('audio/') || fn.endsWith('.opus') || fn.endsWith('.mp3')) {
            thumbHtml = `<div style="width:68px; height:68px; border-radius:8px; background:rgba(168,85,247,0.15); border:1px solid rgba(168,85,247,0.3); display:flex; align-items:center; justify-content:center; color:#c084fc;"><svg viewBox="0 0 24 24" style="width:32px;height:32px;fill:currentColor;"><path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/></svg></div>`;
        } else {
            thumbHtml = `<div style="width:68px; height:68px; border-radius:8px; background:rgba(234,179,8,0.15); border:1px solid rgba(234,179,8,0.3); display:flex; align-items:center; justify-content:center; color:#fef08a;"><svg viewBox="0 0 24 24" style="width:32px;height:32px;fill:currentColor;"><path d="M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z"/></svg></div>`;
        }

        const bytesStr = `${(item.size_bytes || 0).toLocaleString()} bytes`;
        const humanSize = formatBytes(item.size_bytes);
        const starredTag = item.starred ? '<span style="color:#fbbf24; font-weight:600;">Starred (Favorite)</span>' : '<span style="color:var(--text-secondary);">No</span>';
        const fwdTag = (item.forward_score && item.forward_score > 0) ? `<span style="color:#93c5fd;">Forwarded (${item.forward_score}x)</span>` : '<span style="color:var(--text-secondary);">Original message</span>';
        const dupTag = item.is_duplicate ? `<span style="color:#f87171; font-weight:600;">Duplicate copy (${escapeHtml(item.duplicate_reason || 'quality')})</span>` : '<span style="color:#4ade80;">Unique primary copy</span>';
        const durationStr = item.media_duration && item.media_duration > 0 ? formatDuration(item.media_duration) : '';

        body.innerHTML = `
                    <div style="display:flex; align-items:center; gap:14px; padding-bottom:14px; border-bottom:1px solid rgba(255,255,255,0.08);">
                        ${thumbHtml}
                        <div style="flex:1; min-width:0;">
                            <div style="font-size:14px; font-weight:600; color:var(--text-primary); word-break:break-all; line-height:1.3;">${escapeHtml(item.filename || 'Unknown')}</div>
                            <div style="display:flex; gap:8px; align-items:center; margin-top:5px; flex-wrap:wrap;">
                                <span class="badge-pill" style="background:rgba(16,185,129,0.15); color:#4ade80; font-size:11px; padding:2px 7px;">${humanSize}</span>
                                <span class="badge-pill" style="background:rgba(255,255,255,0.08); color:var(--text-secondary); font-size:11px; padding:2px 7px;">${escapeHtml(item.mime_type || 'Unknown Type')}</span>
                                ${durationStr ? `<span class="badge-pill" style="background:rgba(59,130,246,0.15); color:#93c5fd; font-size:11px; padding:2px 7px;">${durationStr}</span>` : ''}
                            </div>
                        </div>
                    </div>

                    <div class="properties-grid">
                        <div class="prop-card prop-card-full">
                            <span class="prop-label">Relative Disk Location</span>
                            <div class="prop-value">
                                <span style="font-family:monospace; font-size:11px; color:#cbd5e1;">${escapeHtml(item.rel_path)}</span>
                                <button type="button" class="sidebar-chip" onclick="copyTextToClipboard('${escapeJsAttr(item.rel_path)}', 'Relative path copied')" style="padding:2px 8px; font-size:11px; height:22px; flex-shrink:0;">Copy</button>
                            </div>
                        </div>
                        <div class="prop-card">
                            <span class="prop-label">Exact File Size</span>
                            <div class="prop-value">${humanSize} <span style="font-size:11px; color:var(--text-muted);">(${bytesStr})</span></div>
                        </div>
                        <div class="prop-card">
                            <span class="prop-label">Date &amp; Time</span>
                            <div class="prop-value">${escapeHtml(item.received_at || 'Unknown')}</div>
                        </div>
                        <div class="prop-card">
                            <span class="prop-label">Chat Source</span>
                            <div class="prop-value" title="${escapeHtml(item.chat_jid || '')}">${escapeHtml(chatNameOfMedia(item))}</div>
                        </div>
                        <div class="prop-card">
                            <span class="prop-label">Sender</span>
                            <div class="prop-value" title="${escapeHtml(item.sender_jid || '')}">${escapeHtml(item.sender_name || (item.from_me ? 'You' : 'Participant'))}</div>
                        </div>
                        <div class="prop-card">
                            <span class="prop-label">Starred / Favorite</span>
                            <div class="prop-value">${starredTag}</div>
                        </div>
                        <div class="prop-card">
                            <span class="prop-label">Forwarding</span>
                            <div class="prop-value">${fwdTag}</div>
                        </div>
                        <div class="prop-card prop-card-full">
                            <span class="prop-label">Duplicate Status</span>
                            <div class="prop-value">${dupTag}</div>
                        </div>
                        ${item.md5 ? `
                        <div class="prop-card prop-card-full">
                            <span class="prop-label">MD5 Cryptographic Hash</span>
                            <div class="prop-value">
                                <span style="font-family:monospace; font-size:11px; color:#94a3b8;">${escapeHtml(item.md5)}</span>
                                <button type="button" class="sidebar-chip" onclick="copyTextToClipboard('${escapeJsAttr(item.md5)}', 'MD5 hash copied')" style="padding:2px 8px; font-size:11px; height:22px; flex-shrink:0;">Copy</button>
                            </div>
                        </div>` : ''}
                    </div>
                `;

        if (footerLeft) {
            footerLeft.innerHTML = `
                        <button type="button" class="action-btn action-btn-secondary" onclick="revealInExplorer('${escapeJsAttr(item.rel_path)}')" style="font-size:12px; display:inline-flex; align-items:center; gap:6px;">
                            <svg viewBox="0 0 24 24" style="width:14px;height:14px;fill:currentColor;"><path d="M20 6h-8l-2-2H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2zm0 12H4V8h16v10z"/></svg>
                            <span>Show in ${fileManagerName()}</span>
                        </button>
                    `;
        }

        if (footerRight) {
            footerRight.innerHTML = `
                        <button type="button" class="action-btn action-btn-primary" onclick="closeMediaPropertiesModal(); handleBackupSelected();" style="font-size:12px;">Download ZIP</button>
                        <button type="button" class="action-btn action-btn-secondary" onclick="closeMediaPropertiesModal()" style="font-size:12px;">Close</button>
                    `;
        }
    } else {
        // Multi-Item View
        const count = items.length;
        if (title) title.innerText = `Selected Properties (${count} items)`;

        let totalBytes = 0;
        let photosCount = 0;
        let videosCount = 0;
        let docsCount = 0;
        let audioCount = 0;
        let starredCount = 0;
        let dupsCount = 0;

        items.forEach(it => {
            const sz = it.size_bytes || 0;
            totalBytes += sz;
            const mime = (it.mime_type || '').toLowerCase();
            const fn = (it.filename || '').toLowerCase();
            if (mime.startsWith('image/') || fn.endsWith('.jpg') || fn.endsWith('.png') || fn.endsWith('.webp')) {
                photosCount++;
            } else if (mime.startsWith('video/') || fn.endsWith('.mp4') || fn.endsWith('.m4v')) {
                videosCount++;
            } else if (mime.startsWith('audio/') || fn.endsWith('.opus') || fn.endsWith('.mp3')) {
                audioCount++;
            } else {
                docsCount++;
            }
            if (it.starred) starredCount++;
            if (it.is_duplicate) dupsCount++;
        });

        let tableRowsHtml = '';
        items.forEach(it => {
            tableRowsHtml += `
                        <div style="display:flex; justify-content:space-between; align-items:center; padding:6px 8px; border-bottom:1px solid rgba(255,255,255,0.05); font-size:11.5px;">
                            <div style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap; flex:1; padding-right:10px;">
                                <span style="font-weight:500; color:var(--text-primary);">${escapeHtml(it.filename || 'Unknown')}</span>
                                <span style="color:var(--text-muted); font-size:10.5px; margin-left:6px;">(${escapeHtml(it.received_at || '')})</span>
                            </div>
                            <div style="display:flex; align-items:center; gap:8px; flex-shrink:0;">
                                <strong style="color:#4ade80;">${formatBytes(it.size_bytes)}</strong>
                                <button type="button" onclick="revealInExplorer('${escapeJsAttr(it.rel_path)}')" title="Show in ${fileManagerName()}" style="background:none; border:none; color:var(--text-muted); cursor:pointer; padding:2px;" onmouseover="this.style.color='var(--accent)'" onmouseout="this.style.color='var(--text-muted)'">
                                    <svg viewBox="0 0 24 24" style="width:13px;height:13px;fill:currentColor;"><path d="M20 6h-8l-2-2H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2zm0 12H4V8h16v10z"/></svg>
                                </button>
                                <button type="button" onclick="removeSelectedItemFromProperties('${escapeJsAttr(it.rel_path)}')" title="Remove from selection" style="background:none; border:none; color:#ef4444; cursor:pointer; padding:2px;">
                                    <svg viewBox="0 0 24 24" style="width:13px;height:13px;fill:currentColor;"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
                                </button>
                            </div>
                        </div>
                    `;
        });

        body.innerHTML = `
                    <div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); border-radius:10px; padding:12px 16px; margin-bottom:14px; display:flex; justify-content:space-between; align-items:center;">
                        <div>
                            <div style="font-size:18px; font-weight:700; color:var(--text-primary);">${count} Files Selected</div>
                            <div style="font-size:12px; color:var(--text-secondary); margin-top:2px;">Combined Total: <strong style="color:#4ade80;">${formatBytes(totalBytes)}</strong> (${totalBytes.toLocaleString()} bytes)</div>
                        </div>
                        <div style="display:flex; gap:6px; flex-wrap:wrap;">
                            ${photosCount > 0 ? `<span class="badge-pill" style="background:rgba(16,185,129,0.15); color:#4ade80; font-size:11px; padding:3px 8px;">${photosCount} Photos</span>` : ''}
                            ${videosCount > 0 ? `<span class="badge-pill" style="background:rgba(59,130,246,0.15); color:#93c5fd; font-size:11px; padding:3px 8px;">${videosCount} Videos</span>` : ''}
                            ${docsCount > 0 ? `<span class="badge-pill" style="background:rgba(234,179,8,0.15); color:#fef08a; font-size:11px; padding:3px 8px;">${docsCount} Documents</span>` : ''}
                            ${audioCount > 0 ? `<span class="badge-pill" style="background:rgba(168,85,247,0.15); color:#c084fc; font-size:11px; padding:3px 8px;">${audioCount} Audio</span>` : ''}
                        </div>
                    </div>

                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; font-size:11.5px; color:var(--text-muted);">
                        <span>Included Files Breakdown:</span>
                        <button type="button" class="sidebar-chip" onclick="handleCtxCopyPath()" style="padding:2px 8px; font-size:11px; height:22px;">Copy All Paths</button>
                    </div>

                    <div style="max-height:220px; overflow-y:auto; background:rgba(0,0,0,0.25); border:1px solid rgba(255,255,255,0.08); border-radius:8px; padding:4px;">
                        ${tableRowsHtml}
                    </div>
                `;

        if (footerLeft) {
            footerLeft.innerHTML = `
                        <button type="button" class="action-btn action-btn-secondary" onclick="resetSelectionUI(); closeMediaPropertiesModal();" style="font-size:12px;">Clear Selection</button>
                    `;
        }

        if (footerRight) {
            footerRight.innerHTML = `
                        <button type="button" class="action-btn action-btn-primary" onclick="closeMediaPropertiesModal(); handleBackupSelected();" style="font-size:12px;">Backup All Selected (${count})</button>
                        <button type="button" class="action-btn action-btn-secondary" onclick="closeMediaPropertiesModal()" style="font-size:12px;">Close</button>
                    `;
        }
    }

    openModal('modalMediaProperties');
}

function closeMediaPropertiesModal() {
    closeModal('modalMediaProperties');
}

function removeSelectedItemFromProperties(relPath) {
    const idx = selectedFiles.indexOf(relPath);
    if (idx !== -1) {
        selectedFiles.splice(idx, 1);
        const card = document.querySelector(`.media-card[data-rel-path="${CSS.escape(relPath)}"]`);
        if (card) card.classList.remove('selected');
        updateSelectionUI();
        if (selectedFiles.length === 0) {
            closeMediaPropertiesModal();
        } else {
            openMediaPropertiesModal();
        }
    }
}

// Global context menu dismiss listeners
document.addEventListener('pointerdown', (e) => {
    if (!e.target.closest('#mediaContextMenu')) {
        closeMediaContextMenu();
    }
});
document.addEventListener('click', (e) => {
    if (!e.target.closest('#mediaContextMenu')) {
        closeMediaContextMenu();
    }

    // Only primary left-click triggers background deselection
    if (e.button !== 0) return;

    // Clicking anywhere else in the main chat media window deselects active items
    if ((selectModeActive || (selectedFiles && selectedFiles.length > 0)) && currentViewMode === 'gallery') {
        const galleryView = document.getElementById('galleryViewContainer');
        if (galleryView && galleryView.contains(e.target)) {
            // Ignore clicks on media cards (handled by card click listener)
            if (e.target.closest('.media-card')) return;

            // Ignore clicks inside selection toolbar pill
            if (e.target.closest('#btnActionSelectedGroup')) return;

            // Ignore clicks inside context menu
            if (e.target.closest('#mediaContextMenu')) return;

            // Ignore clicks inside filter panel, action buttons, or interactive controls
            if (e.target.closest('#filterPanel') || e.target.closest('.action-btn') || e.target.closest('button') || e.target.closest('input') || e.target.closest('select')) {
                return;
            }

            // Ignore clicks directly on the scrollbar track of gallery content
            const galleryContent = document.getElementById('galleryContent');
            if (galleryContent) {
                const rect = galleryContent.getBoundingClientRect();
                if (e.clientX >= rect.left + galleryContent.clientWidth && e.clientX <= rect.right) {
                    return;
                }
            }

            // User clicked on empty background, grid spacing, or header whitespace in the main chat window!
            resetSelectionUI();
        }
    }
});
window.addEventListener('resize', closeMediaContextMenu);
// Close when the user scrolls, not on every scroll event: the app itself scrolls (restoring the
// position after a refresh, loading more cards), which used to close the menu as soon as it opened.
['wheel', 'touchmove'].forEach(evt => window.addEventListener(evt, (e) => {
    if (!e.target.closest || !e.target.closest('#mediaContextMenu')) closeMediaContextMenu();
}, { passive: true, capture: true }));
