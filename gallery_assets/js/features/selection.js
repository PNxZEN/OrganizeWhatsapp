/* Multi-select mode for media cards
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

function enterSelectionMode() {
    selectModeActive = true;
    document.querySelectorAll('.media-card').forEach(card => card.classList.add('select-mode'));
}

function resetSelectionUI() {
    if (window._isBackupRunning && typeof cancelActiveBackup === 'function') {
        cancelActiveBackup();
    }
    selectModeActive = false;
    selectedFiles = [];
    const group = document.getElementById('btnActionSelectedGroup');
    if (group && group.style.display !== 'none') {
        group.classList.add('hiding');
        setTimeout(() => {
            group.style.display = 'none';
            group.classList.remove('hiding');
        }, 190);
    }
    const txt = document.getElementById('btnActionSelectedText');
    if (txt) txt.innerText = 'Backup Selected (0)';
    const selectAllTxt = document.getElementById('btnToggleSelectAllText');
    if (selectAllTxt) selectAllTxt.innerText = 'Select All';

    document.querySelectorAll('.media-card').forEach(card => {
        card.classList.remove('select-mode');
        card.classList.remove('selected');
    });
}

function toggleCardSelection(card, relPath) {
    card.classList.toggle('selected');
    if (card.classList.contains('selected')) {
        if (!selectedFiles.includes(relPath)) {
            selectedFiles.push(relPath);
        }
    } else {
        selectedFiles = selectedFiles.filter(p => p !== relPath);
    }
    updateSelectionUI();
}

function toggleCardSelectionFromCheckbox(checkboxEl, relPath) {
    const card = checkboxEl.closest('.media-card');
    if (!card) return;
    if (!selectModeActive) {
        enterSelectionMode();
    }
    toggleCardSelection(card, relPath);
}

function updateSelectionUI() {
    const group = document.getElementById('btnActionSelectedGroup');
    const txt = document.getElementById('btnActionSelectedText');
    const selectAllTxt = document.getElementById('btnToggleSelectAllText');
    if (!group || !txt) return;

    if (selectedFiles.length > 0) {
        txt.innerText = `Backup Selected (${selectedFiles.length})`;
        if (group.style.display === 'none' || !group.style.display) {
            group.classList.remove('hiding');
            group.style.display = 'inline-flex';
        }
        if (selectAllTxt && Array.isArray(filteredMedia) && filteredMedia.length > 0) {
            const isAll = (selectedFiles.length >= filteredMedia.length && filteredMedia.every(m => selectedFiles.includes(m.rel_path)));
            selectAllTxt.innerText = isAll ? 'Deselect All' : 'Select All';
        }
    } else {
        resetSelectionUI();
    }

    // If context menu is open, dynamically sync its headers and count
    const ctxMenu = document.getElementById('mediaContextMenu');
    if (ctxMenu && ctxMenu.style.display !== 'none') {
        const title = document.getElementById('ctxMenuTitle');
        const subtitle = document.getElementById('ctxMenuSubtitle');
        const backupLabel = document.getElementById('ctxActionBackupLabel');
        const copyPathLabel = document.getElementById('ctxActionCopyPathLabel');
        const selectAllLabel = document.getElementById('ctxActionSelectAllLabel');
        const count = selectedFiles.length;
        if (title) title.innerText = count === 1 ? '1 item selected' : `${count} items selected`;
        if (subtitle && contextTargetItem) {
            subtitle.innerText = count === 1 ? (contextTargetItem.filename || 'Media file') : `${contextTargetItem.filename || 'Media'} (+${count - 1} more)`;
        }
        if (backupLabel) backupLabel.innerText = count > 1 ? `Backup Selected (${count})` : 'Backup Selected (ZIP)';
        if (copyPathLabel) copyPathLabel.innerText = count > 1 ? `Copy ${count} File Paths` : 'Copy File Path';
        if (selectAllLabel && Array.isArray(filteredMedia) && filteredMedia.length > 0) {
            const isAll = (selectedFiles.length >= filteredMedia.length && filteredMedia.every(m => selectedFiles.includes(m.rel_path)));
            selectAllLabel.innerText = isAll ? 'Deselect All' : 'Select All';
        }
    }
}

function handleToggleSelectAllMedia() {
    if (!activeChat || !Array.isArray(filteredMedia) || filteredMedia.length === 0) {
        showToast('No media in current view to select', 'info');
        return;
    }

    const allPaths = filteredMedia.map(m => m.rel_path).filter(Boolean);
    const isAllSelected = (selectedFiles.length >= allPaths.length && allPaths.every(p => selectedFiles.includes(p)));

    if (isAllSelected) {
        resetSelectionUI();
        showToast('Deselected all media', 'info');
    } else {
        if (!selectModeActive) {
            enterSelectionMode();
        }
        selectedFiles = [...allPaths];
        // Visually mark only the currently rendered DOM cards as selected.
        // NOTE: We do NOT force-render unrendered media cards here to keep virtual scroll smooth!
        // As the user scrolls, newly created cards will automatically check selectedFiles.includes(rel_path).
        document.querySelectorAll('.media-card').forEach(card => {
            card.classList.add('selected');
        });
        updateSelectionUI();
        showToast(`Selected all ${selectedFiles.length} files (Ctrl+C to copy, Esc to clear)`, 'success');
    }
}

function handleCopySelectedPaths() {
    if (!selectedFiles || selectedFiles.length === 0) {
        if (contextTargetItem && contextTargetItem.rel_path) {
            copyTextToClipboard(contextTargetItem.rel_path, 'File path copied to clipboard');
        } else {
            showToast('No files selected to copy', 'info');
        }
        return;
    }
    if (selectedFiles.length === 1) {
        copyTextToClipboard(selectedFiles[0], 'File path copied to clipboard');
    } else {
        copyTextToClipboard(selectedFiles.join('\n'), `${selectedFiles.length} file paths copied to clipboard`);
    }
}

function handleCtxSelectAll() {
    closeMediaContextMenu();
    handleToggleSelectAllMedia();
}
