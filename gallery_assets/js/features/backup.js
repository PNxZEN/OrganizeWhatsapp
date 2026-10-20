/* ZIP backups of selected files / whole chat and chat action buttons
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

// Setup Chat Action Handlers and Cancellation
window._activeBackupAbortController = null;
window._isBackupRunning = false;

async function cancelActiveBackup() {
    if (!window._isBackupRunning && !window._activeBackupAbortController) {
        const btnCancelBackupChat = document.getElementById('btnCancelBackupChat');
        if (btnCancelBackupChat) btnCancelBackupChat.style.display = 'none';
        return;
    }
    showToast('Cancelling backup...');
    if (window._activeBackupAbortController) {
        try {
            window._activeBackupAbortController.abort();
        } catch (e) {}
        window._activeBackupAbortController = null;
    }
    try {
        await fetch('/api/backup/cancel', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
    } catch (e) {}
    window._isBackupRunning = false;

    const zipBtn = document.getElementById('btnZipBackup');
    const zipBtnText = document.getElementById('btnZipBackupText');
    if (zipBtn) {
        zipBtn.disabled = false;
        if (zipBtnText) zipBtnText.innerText = 'Backup Chat';
    }
    const actionSelectedBtn = document.getElementById('btnActionSelected');
    const label = document.getElementById('btnActionSelectedText');
    const cancelSelectedBtn = document.getElementById('btnCancelSelected');
    if (actionSelectedBtn) actionSelectedBtn.disabled = false;
    if (label) label.innerText = `Backup Selected (${selectedFiles.length})`;
    if (cancelSelectedBtn) cancelSelectedBtn.title = 'Clear selection';
    const btnCancelBackupChat = document.getElementById('btnCancelBackupChat');
    if (btnCancelBackupChat) btnCancelBackupChat.style.display = 'none';
    showToast('Backup cancelled.', 'info');
}

function handleCancelSelectedClick(e) {
    if (e) e.stopPropagation();
    if (window._isBackupRunning) {
        cancelActiveBackup();
    } else {
        resetSelectionUI();
    }
}

async function handleBackupSelected() {
    if (window._isBackupRunning) return;
    if (!selectedFiles || selectedFiles.length === 0) return;
    
    const fileContent = selectedFiles.join('\n');
    
    if (!isHttpServer) {
        const blob = new Blob([fileContent], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'backup_list.txt';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        resetSelectionUI();
        showToast('Saved backup_list.txt. Run organizer in server mode for direct downloads.', 'info');
        return;
    }

    window._isBackupRunning = true;
    window._activeBackupAbortController = new AbortController();

    const actionSelectedBtn = document.getElementById('btnActionSelected');
    const label = document.getElementById('btnActionSelectedText');
    const cancelSelectedBtn = document.getElementById('btnCancelSelected');
    const btnCancelBackupChat = document.getElementById('btnCancelBackupChat');

    if (actionSelectedBtn) actionSelectedBtn.disabled = true;
    if (label) {
        label.innerHTML = '<span class="sync-spinner" style="width:12px;height:12px;border-width:2px;display:inline-block;margin-right:6px;vertical-align:middle;"></span>Zipping...';
    }
    if (cancelSelectedBtn) cancelSelectedBtn.title = 'Cancel backup';
    if (btnCancelBackupChat) btnCancelBackupChat.style.display = 'inline-flex';
    showToast(`Creating ZIP for ${selectedFiles.length} selected files...`);

    try {
        const resp = await fetch('/api/backup-files', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ files: selectedFiles }),
            signal: window._activeBackupAbortController.signal
        });
        const res = await resp.json();
        if (resp.ok && res.status === 'success') {
            showToast(`Archive ready! Downloading ${res.zip_name}...`, 'success');
            const a = document.createElement('a');
            a.href = res.download_url;
            a.download = res.zip_name || 'selected_backup.zip';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            resetSelectionUI();
        } else if (res.status === 'cancelled') {
            showToast('Backup cancelled.', 'info');
        } else {
            showToast(res.message || 'Backup failed.', 'error');
        }
    } catch (e) {
        if (e.name === 'AbortError') {
            showToast('Backup cancelled.', 'info');
        } else {
            showToast(`Backup error: ${e.message}`, 'error');
        }
    } finally {
        window._isBackupRunning = false;
        window._activeBackupAbortController = null;
        if (actionSelectedBtn) actionSelectedBtn.disabled = false;
        if (label) label.innerText = `Backup Selected (${selectedFiles.length})`;
        if (cancelSelectedBtn) cancelSelectedBtn.title = 'Clear selection';
        if (btnCancelBackupChat) btnCancelBackupChat.style.display = 'none';
    }
}

async function handleBackupChat() {
    if (window._isBackupRunning) return;
    if (!activeChat) return;
    if (!isHttpServer) {
        showToast('Launch local server via start_gallery.bat for in-browser ZIP downloads.', 'info');
        return;
    }

    window._isBackupRunning = true;
    window._activeBackupAbortController = new AbortController();

    const zipBtn = document.getElementById('btnZipBackup');
    const zipBtnText = document.getElementById('btnZipBackupText');
    const btnCancelBackupChat = document.getElementById('btnCancelBackupChat');

    if (zipBtn) {
        zipBtn.disabled = true;
        if (zipBtnText) {
            zipBtnText.innerText = 'Zipping Archive...';
        }
    }
    if (btnCancelBackupChat) {
        btnCancelBackupChat.style.display = 'inline-flex';
    }

    const chatName = activeChat.name || activeChat.jid;
    showToast(`Creating ZIP for ${chatName}... Please wait.`);

    try {
        const resp = await fetch('/api/backup-chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ chat_name: chatName }),
            signal: window._activeBackupAbortController.signal
        });
        const res = await resp.json();
        if (resp.ok && res.status === 'success') {
            showToast(`Archive ready! Downloading ${res.zip_name} (${res.file_count} files)...`, 'success');
            const a = document.createElement('a');
            a.href = res.download_url;
            a.download = res.zip_name || `${chatName}_backup.zip`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        } else if (res.status === 'cancelled') {
            showToast('Backup cancelled.', 'info');
        } else {
            showToast(res.message || 'Backup failed.', 'error');
        }
    } catch (e) {
        if (e.name === 'AbortError') {
            showToast('Backup cancelled.', 'info');
        } else {
            showToast(`Backup error: ${e.message}`, 'error');
        }
    } finally {
        window._isBackupRunning = false;
        window._activeBackupAbortController = null;
        if (zipBtn) {
            zipBtn.disabled = false;
            if (zipBtnText) zipBtnText.innerText = 'Backup Chat';
        }
        if (btnCancelBackupChat) {
            btnCancelBackupChat.style.display = 'none';
        }
    }
}

function setupChatActionButtons() {
    const actionSelectedBtn = document.getElementById('btnActionSelected');
    if (actionSelectedBtn) {
        actionSelectedBtn.onclick = handleBackupSelected;
    }
    const cancelBtn = document.getElementById('btnCancelSelected');
    if (cancelBtn) {
        cancelBtn.onclick = handleCancelSelectedClick;
    }
    const zipBtn = document.getElementById('btnZipBackup');
    if (zipBtn) {
        zipBtn.style.display = 'inline-flex';
        zipBtn.onclick = handleBackupChat;
    }
    const cancelBackupBtn = document.getElementById('btnCancelBackupChat');
    if (cancelBackupBtn) {
        cancelBackupBtn.onclick = cancelActiveBackup;
    }
    const reviewBtn = document.getElementById('btnReviewDuplicates');
    if (reviewBtn) {
        reviewBtn.onclick = () => openDuplicateReviewModal('review');
    }
    const recycleBinBtn = document.getElementById('btnOpenRecycleBin');
    if (recycleBinBtn) {
        recycleBinBtn.style.display = isHttpServer ? 'inline-flex' : 'none';
        recycleBinBtn.onclick = () => openDuplicateReviewModal('recycle-bin');
    }
    const restoreBtn = document.getElementById('btnRestoreChat');
    const cancelRestoreBtn = document.getElementById('btnCancelRestoreChat');
    if (restoreBtn) {
        if (window._isRestoreRunning) {
            restoreBtn.style.display = 'none';
            if (cancelRestoreBtn) cancelRestoreBtn.style.display = 'inline-flex';
        } else {
            restoreBtn.style.display = (isHttpServer && activeChat && activeChat.jid !== '_unmatched') ? 'inline-flex' : 'none';
            if (cancelRestoreBtn) cancelRestoreBtn.style.display = 'none';
        }
        restoreBtn.onclick = restoreCurrentChatToPhone;
    }
    updateDuplicateReviewButtonUI();
    updateRecycleBinPill();
}
