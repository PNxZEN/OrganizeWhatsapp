/* Push chat media back to the phone
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

async function cancelActiveRestore() {
    const btnCancel = document.getElementById('btnCancelRestoreChat');
    if (btnCancel) {
        btnCancel.disabled = true;
        btnCancel.innerHTML = '<svg class="icon" viewBox="0 0 24 24" style="width:12px;height:12px;fill:currentColor;"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg> Cancelling...';
    }
    try {
        showToast('Cancelling phone restore push...', 'info');
        await fetch('/api/restore/cancel', { method: 'POST' });
    } catch (e) {
        showToast('Error requesting restore cancellation: ' + e.message, 'error');
    }
}

let _isRestoreRunning = false;

function switchSyncTab(tab) {
    const btnSync = document.getElementById('tabBtnSyncPhone');
    const btnReclaim = document.getElementById('tabBtnReclaimSpace');
    if (tab === 'reclaim') {
        closeModal('modalSync');
        openStorageReclaimModal();
    } else {
        if (btnSync) btnSync.classList.add('active');
        if (btnReclaim) btnReclaim.classList.remove('active');
    }
}

async function openRestoreChatModal() {
    if (!activeChat || !activeChat.jid) {
        showToast('Please select a chat first.', 'info');
        return;
    }
    if (_isRestoreRunning) {
        showToast('A media push to phone is already running. Please wait or cancel it first.', 'warning');
        return;
    }

    const modal = document.getElementById('modalRestoreChat');
    if (!modal) return;

    const chatName = activeChat.name || activeChat.jid;
    const mediaList = activeChat.media || [];
    const fileCount = mediaList.length;
    const totalSize = activeChat.total_size || 0;

    const subtitle = document.getElementById('restoreChatSubtitle');
    if (subtitle) subtitle.innerText = `Chat: ${chatName} (${(activeChat.jid && activeChat.jid.endsWith('@g.us')) ? 'Group' : 'Direct'})`;

    const statFiles = document.getElementById('restoreStatFiles');
    if (statFiles) statFiles.innerText = fileCount.toLocaleString();

    const statSize = document.getElementById('restoreStatSize');
    if (statSize) statSize.innerText = formatBytes(totalSize);

    const btnConfirm = document.getElementById('btnConfirmStartRestore');
    function setRestoreConfirmState(enabled, label, tooltip) {
        if (!btnConfirm) return;
        btnConfirm.disabled = !enabled;
        if (!enabled) {
            btnConfirm.style.background = '#374151';
            btnConfirm.style.borderColor = '#4b5563';
            btnConfirm.style.color = '#9ca3af';
            btnConfirm.style.boxShadow = 'none';
            btnConfirm.style.cursor = 'not-allowed';
            btnConfirm.style.opacity = '0.6';
            btnConfirm.title = tooltip || 'Phone not connected over USB';
            btnConfirm.innerHTML = `<svg viewBox="0 0 24 24" style="width:14px;height:14px;fill:currentColor;"><path d="M16 1H8C6.34 1 5 2.34 5 4v16c0 1.66 1.34 3 3 3h8c1.66 0 3-1.34 3-3V4c0-1.66-1.34-3-3-3zm-2 20h-4v-1h4v1zm3-3H7V4h10v14zm-4-7l-3-3-3 3h2v4h2v-4h2z"/></svg> <span>${label || 'Phone Disconnected'}</span>`;
        } else {
            btnConfirm.style.background = '#2563eb';
            btnConfirm.style.borderColor = '#3b82f6';
            btnConfirm.style.color = '#ffffff';
            btnConfirm.style.boxShadow = '0 2px 10px rgba(37,99,235,0.35)';
            btnConfirm.style.cursor = 'pointer';
            btnConfirm.style.opacity = '1';
            btnConfirm.title = tooltip || 'Push chat media to phone';
            btnConfirm.innerHTML = `<svg viewBox="0 0 24 24" style="width:14px;height:14px;fill:currentColor;"><path d="M16 1H8C6.34 1 5 2.34 5 4v16c0 1.66 1.34 3 3 3h8c1.66 0 3-1.34 3-3V4c0-1.66-1.34-3-3-3zm-2 20h-4v-1h4v1zm3-3H7V4h10v14zm-4-7l-3-3-3 3h2v4h2v-4h2z"/></svg> <span>Confirm Push to Phone</span>`;
        }
    }

    setRestoreConfirmState(false, 'Checking Phone...', 'Checking USB device connection...');

    const statPhone = document.getElementById('restoreStatPhoneFree');
    if (statPhone) {
        statPhone.innerText = 'Checking phone...';
        statPhone.style.color = '#94a3b8';
    }

    if (!isHttpServer) {
        if (statPhone) {
            statPhone.innerText = 'Offline Gallery';
            statPhone.style.color = '#f59e0b';
        }
        setRestoreConfirmState(false, 'Phone Disconnected', 'Start local server to enable phone restore');
        return;
    }

    // Check phone storage live
    fetch('/api/phone/storage')
        .then(r => r.json())
        .then(data => {
            const isConnected = !!(data && (data.connected === true || (data.storage && data.storage.connected === true)));
            const isAuthorized = !!(data && (data.authorized === true || (data.storage && data.storage.authorized === true)));
            const freeBytes = (data && data.free_bytes !== undefined) ? data.free_bytes : (data && data.storage && data.storage.free_bytes !== undefined ? data.storage.free_bytes : null);

            if (!isConnected) {
                if (statPhone) {
                    statPhone.innerText = 'No Phone Connected';
                    statPhone.style.color = '#f59e0b';
                    statPhone.title = 'Please connect your Android phone via USB cable';
                }
                setRestoreConfirmState(false, 'Phone Disconnected', 'Phone not connected over USB');
                return;
            }

            if (!isAuthorized) {
                if (statPhone) {
                    statPhone.innerText = 'Phone Unauthorized';
                    statPhone.style.color = '#f59e0b';
                    statPhone.title = 'Please tap Allow USB debugging on your phone screen';
                }
                setRestoreConfirmState(false, 'Device Unauthorized', 'Device unauthorized. Tap Allow USB debugging on phone.');
                return;
            }

            // Connected and authorized!
            if (freeBytes !== null && freeBytes !== undefined) {
                const freeStr = formatBytes(freeBytes);
                if (statPhone) {
                    statPhone.innerText = `${freeStr} Free`;
                    if (freeBytes < totalSize) {
                        statPhone.style.color = '#ef4444';
                        statPhone.title = 'Warning: Phone free space might be lower than required space!';
                    } else {
                        statPhone.style.color = '#4ade80';
                        statPhone.title = 'Phone storage sufficient for this transfer.';
                    }
                }
            } else {
                if (statPhone) {
                    statPhone.innerText = 'Phone Ready';
                    statPhone.style.color = '#4ade80';
                }
            }

            if (fileCount === 0) {
                setRestoreConfirmState(false, 'No Files to Push', 'No media files in this chat to push');
            } else {
                setRestoreConfirmState(true, 'Confirm Push to Phone', 'Push chat media to phone');
            }
        })
        .catch(() => {
            if (statPhone) {
                statPhone.innerText = 'Phone Disconnected';
                statPhone.style.color = '#f59e0b';
            }
            setRestoreConfirmState(false, 'Phone Disconnected', 'Could not detect USB phone connection');
        });

    // Media breakdown pills
    const breakdownContainer = document.getElementById('restoreMediaBreakdownPills');
    if (breakdownContainer) {
        let imgCount = 0, imgBytes = 0;
        let vidCount = 0, vidBytes = 0;
        let audCount = 0, audBytes = 0;
        let docCount = 0, docBytes = 0;

        mediaList.forEach(m => {
            const mime = (m.mime_type || '').toLowerCase();
            const sz = m.size_bytes || 0;
            if (m.is_doc || (!mime.startsWith('image/') && !mime.startsWith('video/') && !mime.startsWith('audio/'))) {
                docCount++; docBytes += sz;
            } else if (mime.startsWith('image/')) {
                imgCount++; imgBytes += sz;
            } else if (mime.startsWith('video/')) {
                vidCount++; vidBytes += sz;
            } else if (mime.startsWith('audio/')) {
                audCount++; audBytes += sz;
            }
        });

        let pillsHtml = '';
        if (imgCount > 0) pillsHtml += `<span class="badge-pill" style="background:rgba(34,197,94,0.15);color:#4ade80;font-size:11px;padding:3px 8px;">Photos: ${imgCount} (${formatBytes(imgBytes)})</span>`;
        if (vidCount > 0) pillsHtml += `<span class="badge-pill" style="background:rgba(59,130,246,0.15);color:#93c5fd;font-size:11px;padding:3px 8px;">Videos: ${vidCount} (${formatBytes(vidBytes)})</span>`;
        if (audCount > 0) pillsHtml += `<span class="badge-pill" style="background:rgba(168,85,247,0.15);color:#c084fc;font-size:11px;padding:3px 8px;">Audio: ${audCount} (${formatBytes(audBytes)})</span>`;
        if (docCount > 0) pillsHtml += `<span class="badge-pill" style="background:rgba(234,179,8,0.15);color:#fef08a;font-size:11px;padding:3px 8px;">Docs: ${docCount} (${formatBytes(docBytes)})</span>`;
        breakdownContainer.innerHTML = pillsHtml || '<span style="color:var(--text-muted);font-size:12px;">No media files.</span>';
    }

    // Preview file list
    const previewList = document.getElementById('restoreFilesPreviewList');
    if (previewList) {
        const sample = mediaList.slice(0, 20);
        let listHtml = sample.map(m => `
                    <div style="display:flex; justify-content:space-between; align-items:center; padding:3px 0; border-bottom:1px solid rgba(255,255,255,0.04);">
                        <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:70%; color:var(--text-primary); font-family:monospace; font-size:11px;">${escapeHtml(m.filename)}</span>
                        <span style="color:var(--text-muted); font-size:11px;">${formatBytes(m.size_bytes || 0)}</span>
                    </div>
                `).join('');
        if (mediaList.length > 20) {
            listHtml += `<div style="text-align:center; padding-top:6px; font-size:11px; color:var(--text-muted);">+ ${mediaList.length - 20} more files will be copied</div>`;
        }
        previewList.innerHTML = listHtml;
    }

    // Reset views
    const preView = document.getElementById('restoreChatPreView');
    const preFooter = document.getElementById('restoreChatPreFooter');
    const progView = document.getElementById('restoreChatProgressView');
    const doneView = document.getElementById('restoreChatDoneView');
    if (preView) preView.style.display = 'block';
    if (preFooter) preFooter.style.display = 'flex';
    if (progView) progView.style.display = 'none';
    if (doneView) doneView.style.display = 'none';

    modal.classList.add('open');
}

function closeRestoreChatModal() {
    const modal = document.getElementById('modalRestoreChat');
    if (modal) modal.classList.remove('open');
}

async function executeRestoreChatTransfer() {
    if (!activeChat || !activeChat.jid) return;
    if (_isRestoreRunning) return;

    const chatName = activeChat.name || activeChat.jid;
    const fileCount = activeChat.file_count || 0;
    const sizeStr = formatBytes(activeChat.total_size || 0);

    _isRestoreRunning = true;
    window._isRestoreRunning = true;

    const preView = document.getElementById('restoreChatPreView');
    const preFooter = document.getElementById('restoreChatPreFooter');
    const progView = document.getElementById('restoreChatProgressView');
    const doneView = document.getElementById('restoreChatDoneView');

    if (preView) preView.style.display = 'none';
    if (preFooter) preFooter.style.display = 'none';
    if (progView) progView.style.display = 'block';
    if (doneView) doneView.style.display = 'none';

    const statusText = document.getElementById('restoreProgressStatusText');
    if (statusText) statusText.innerText = `Pushing ${fileCount} files (${sizeStr}) to phone...`;

    const barFill = document.getElementById('restoreProgressBarFill');
    if (barFill) {
        barFill.style.width = '35%';
        barFill.style.background = 'linear-gradient(90deg, #3b82f6, #60a5fa)';
    }

    const btn = document.getElementById('btnRestoreChat');
    const btnCancel = document.getElementById('btnCancelRestoreChat');
    if (btn) btn.style.display = 'none';
    if (btnCancel) {
        btnCancel.style.display = 'inline-flex';
        btnCancel.disabled = false;
    }

    try {
        const res = await fetch('/api/restore/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ chat_jid: activeChat.jid })
        });
        const result = await res.json().catch(() => ({}));

        if (res.ok && result.success) {
            if (barFill) barFill.style.width = '100%';
            if (progView) progView.style.display = 'none';
            if (doneView) doneView.style.display = 'block';
            const doneSub = document.getElementById('restoreDoneSubtitle');
            if (doneSub) {
                if (result.skipped_count && result.skipped_count > 0 && (!result.restored_count || result.restored_count === 0)) {
                    doneSub.innerText = `All ${result.skipped_count} media files already exist on your phone with identical size. No files needed transferring. Media scanner has refreshed your gallery.`;
                } else if (result.skipped_count && result.skipped_count > 0) {
                    doneSub.innerText = `Transferred ${result.restored_count} new files (${formatBytes(result.restored_bytes || 0)}). ${result.skipped_count} files already existed on phone with matching size and were kept intact.`;
                } else {
                    doneSub.innerText = `Successfully transferred ${result.restored_count || fileCount} files to phone. Native Android Gallery has been refreshed.`;
                }
            }
            if (result.skipped_count && result.skipped_count > 0 && (!result.restored_count || result.restored_count === 0)) {
                showToast(`All ${result.skipped_count} files already exist on phone!`, 'info');
            } else if (result.skipped_count && result.skipped_count > 0) {
                showToast(`Pushed ${result.restored_count} files (${result.skipped_count} already existed)!`, 'success');
            } else {
                showToast(`Restored ${result.restored_count || fileCount} files to phone!`, 'success');
            }
            if (typeof loadPhoneStorageInfo === 'function') loadPhoneStorageInfo();
        } else if (result.cancelled) {
            closeRestoreChatModal();
            showToast(`Push cancelled by user. ${result.restored_count || 0} completed files were indexed on phone.`, 'info');
        } else if (result.disconnected) {
            closeRestoreChatModal();
            showToast(`Phone disconnected: USB cable was disconnected during transfer. Restored ${result.restored_count || 0} files.`, 'error');
            if (typeof checkDeviceStatus === 'function') checkDeviceStatus();
        } else {
            closeRestoreChatModal();
            const err = result.error || result.message || '';
            if (err.includes('Insufficient phone storage')) {
                showToast(err + ' - Use "Reclaim Phone Space" to free up storage first!', 'warning');
            } else if (err.includes('WhatsApp is not installed') || err.includes('folder not found')) {
                showToast(err, 'error');
            } else if (err.includes('unauthorized')) {
                showToast(err, 'warning');
                if (typeof openDeviceModal === 'function') openDeviceModal();
            } else if (err.includes('not connected')) {
                showToast(err, 'error');
                if (typeof openDeviceModal === 'function') openDeviceModal();
            } else if (err) {
                showToast(err, 'error');
            } else {
                showToast('Restore failed. Check phone connection and storage.', 'error');
            }
        }
    } catch (err) {
        closeRestoreChatModal();
        showToast('Error pushing chat to phone: ' + err.message, 'error');
    } finally {
        _isRestoreRunning = false;
        window._isRestoreRunning = false;
        if (btn) btn.style.display = (isHttpServer && activeChat && activeChat.jid !== '_unmatched') ? 'inline-flex' : 'none';
        if (btnCancel) btnCancel.style.display = 'none';
    }
}

async function restoreCurrentChatToPhone() {
    openRestoreChatModal();
}
