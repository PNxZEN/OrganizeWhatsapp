/* Phone sync modal, pre-flight checks, pause/resume/cancel and progress polling
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

function hasCompletedPriorSync(st) {
    const chats = getChatsArray();
    const totalFiles = chats.reduce((acc, c) => acc + (c.file_count || 0), 0);
    if (totalFiles > 0) return true;
    if (st && st.has_completed_sync) return true;
    return false;
}

function updateSyncButtonUI(st) {
    const btn = document.getElementById('btnControlSync');
    if (!btn) return;
    const span = btn.querySelector('span');
    _syncActive = !!(st && st.active);
    if (st && st.active) {
        btn.classList.add('control-btn-syncing');
        if (span) span.innerText = 'Syncing...';
    } else {
        btn.classList.remove('control-btn-syncing');
        if (span) {
            span.innerText = hasCompletedPriorSync(st) ? 'Refresh Sync' : 'Sync Phone';
        }
    }
}

function showSyncView(view) {
    const viewSummary = document.getElementById('syncViewSummary');
    const viewProgress = document.getElementById('syncViewProgress');
    const footerSummary = document.getElementById('syncFooterSummary');
    const footerProgress = document.getElementById('syncFooterProgress');

    if (view === 'summary') {
        if (viewSummary) viewSummary.style.display = 'block';
        if (viewProgress) viewProgress.style.display = 'none';
        if (footerSummary) footerSummary.style.display = 'flex';
        if (footerProgress) footerProgress.style.display = 'none';
    } else {
        if (viewSummary) viewSummary.style.display = 'none';
        if (viewProgress) viewProgress.style.display = 'block';
        if (footerSummary) footerSummary.style.display = 'none';
        if (footerProgress) footerProgress.style.display = 'flex';
    }
}

function renderSyncModalSummary(st) {
    const title = document.getElementById('syncModalTitle');
    const btnStart = document.getElementById('btnStartSyncNow');
    const priorSync = hasCompletedPriorSync(st);

    const chats = getChatsArray();
    const totalChats = chats.length;
    const totalFiles = chats.reduce((acc, c) => acc + (c.file_count || 0), 0);

    if (title) {
        title.innerText = (priorSync || totalFiles > 0) ? 'Sync Newer Media' : 'WhatsApp Synchronization';
    }
    if (btnStart) {
        btnStart.innerText = (priorSync || totalFiles > 0) ? 'Sync Newer Media' : 'Start Sync';
    }

    // Populate organized library statistics
    const statsText = document.getElementById('syncSummaryStatsText');
    if (statsText) {
        if (totalFiles > 0) {
            statsText.innerHTML = `<strong>${totalFiles.toLocaleString()}</strong> media files organized across <strong>${totalChats}</strong> chats. Ready to check for newest updates.`;
        } else if (priorSync) {
            statsText.innerHTML = '<strong>Archive initialized.</strong> Ready to refresh synchronization with latest phone backups.';
        } else {
            statsText.innerHTML = '<strong>No media files organized yet.</strong> Ready for initial sync.';
        }
    }

    // Conditionally show Skip DB checkbox ONLY if an existing local database is present
    const skipContainer = document.getElementById('syncSummarySkipDbContainer');
    const chkSkip = document.getElementById('syncSummaryChkSkipDb');
    const hasDb = !!(windowHasLocalDb || (st && st.has_local_db));
    if (skipContainer) {
        skipContainer.style.display = hasDb ? 'block' : 'none';
    }
    if (chkSkip) {
        chkSkip.checked = false; // Always default to fresh sync unless user specifically opts in
    }
}

function updateSyncModalNotices(cfg) {
    const box = document.getElementById('syncModalNoticeBox');
    if (!box) return;

    if (!currentDeviceStatus || !currentDeviceStatus.connected) {
        box.style.display = 'block';
        box.innerHTML = `
                    <div style="background:rgba(245,158,11,0.12);border:1px solid rgba(245,158,11,0.3);color:#fbbf24;padding:10px 14px;border-radius:8px;font-size:12px;display:flex;align-items:center;justify-content:space-between;gap:12px;line-height:1.4;">
                        <div><strong>Phone Not Connected:</strong> Connect your phone via USB cable to sync messages or reclaim storage.</div>
                        <button type="button" class="action-btn action-btn-secondary" onclick="closeModal('modalSync'); openDeviceModal();" style="font-size:11px;padding:4px 10px;white-space:nowrap;border-color:rgba(245,158,11,0.4);color:#fbbf24;">Device Guide</button>
                    </div>
                `;
    } else if (!currentDeviceStatus.authorized) {
        box.style.display = 'block';
        box.innerHTML = `
                    <div style="background:rgba(245,158,11,0.12);border:1px solid rgba(245,158,11,0.3);color:#fbbf24;padding:10px 14px;border-radius:8px;font-size:12px;display:flex;align-items:center;justify-content:space-between;gap:12px;line-height:1.4;">
                        <div><strong>Authorization Required:</strong> Tap 'Allow USB debugging' on your phone screen to start sync.</div>
                        <button type="button" class="action-btn action-btn-secondary" onclick="closeModal('modalSync'); openDeviceModal();" style="font-size:11px;padding:4px 10px;white-space:nowrap;border-color:rgba(245,158,11,0.4);color:#fbbf24;">Authorize</button>
                    </div>
                `;
    } else if (cfg && !cfg.hex_key_set) {
        box.style.display = 'block';
        box.innerHTML = `
                    <div style="background:rgba(59,130,246,0.12);border:1px solid rgba(59,130,246,0.3);color:#93c5fd;padding:10px 14px;border-radius:8px;font-size:12px;display:flex;align-items:center;justify-content:space-between;gap:12px;line-height:1.4;">
                        <div><strong>Decryption Key Needed for PC Sync:</strong> A 64-digit WhatsApp key is required to sync new messages to PC. (Reclaim Phone Space does not need a key).</div>
                        <button type="button" class="action-btn action-btn-secondary" onclick="closeModal('modalSync'); openKeyModal();" style="font-size:11px;padding:4px 10px;white-space:nowrap;border-color:rgba(59,130,246,0.4);color:#93c5fd;">Enter Key</button>
                    </div>
                `;
    } else if (cfg && cfg.hex_key_set) {
        const chats = getChatsArray();
        const totalFiles = chats.reduce((acc, c) => acc + (c.file_count || 0), 0);
        const isIncremental = (totalFiles > 0);
        box.style.display = 'block';
        box.innerHTML = `
                    <div style="background:rgba(16,185,129,0.08);border:1px solid rgba(16,185,129,0.25);color:var(--text-primary);padding:10px 14px;border-radius:8px;font-size:12px;line-height:1.5;">
                        <div style="display:flex;align-items:center;gap:8px;margin-bottom:3px;">
                            <div style="width:7px;height:7px;border-radius:50%;background:var(--accent);"></div>
                            <strong style="color:var(--accent);">${isIncremental ? 'Ready for Incremental Sync' : 'Ready to Sync'}</strong>
                            <span style="color:var(--text-muted);font-size:11px;">(Backup key saved: ...${cfg.masked_key ? cfg.masked_key.slice(-8) : ''})</span>
                        </div>
                        <div style="color:var(--text-secondary);font-size:11px;">
                            ${isIncremental
                        ? 'Your 64-digit key is saved permanently and never expires. All previously organized and imported media are skipped automatically -- only newly received media will be downloaded.'
                        : 'Your backup decryption key is saved. Connect your phone and click Start Sync to begin.'}
                        </div>
                        <div style="color:var(--text-muted);font-size:11px;margin-top:4px;">
                            Tip: In WhatsApp on your phone (Settings &gt; Chats &gt; Chat backup), tap <strong>'Back up'</strong> right before syncing to include messages up to this exact minute.
                        </div>
                    </div>
                `;
    } else {
        box.style.display = 'none';
        box.innerHTML = '';
    }
    updateSyncModalBackupAge();
}

async function recheckPhoneBackupAge(btn) {
    if (btn) {
        btn.disabled = true;
        btn.innerText = 'Checking...';
    }
    try {
        // Force a fresh scan of the phone's WhatsApp folders and wait for its result
        await checkDeviceStatus({ refresh: true, wait: 20 });
        updateSyncModalBackupAge();
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerText = 'Check Freshness';
        }
    }
}

function updateSyncModalBackupAge() {
    const badge = document.getElementById('syncPhoneBackupAgeBadge');
    const btnRefresh = document.getElementById('btnRefreshBackupCheck');
    if (!badge) return;

    if (!currentDeviceStatus || !currentDeviceStatus.connected || !currentDeviceStatus.authorized) {
        badge.innerHTML = '<span style="color:var(--text-muted);">(Phone not connected)</span>';
        if (btnRefresh) btnRefresh.style.display = 'none';
        return;
    }

    const acc = currentDeviceStatus.selected_account;
    // Account records from /api/device-status expose latest_db_mtime / latest_backup_str
    const dbMtime = acc ? Number(acc.latest_db_mtime || acc.db_mtime || 0) : 0;
    const backupStr = acc ? (acc.latest_backup_str || acc.last_backup_str || '') : '';
    const scanState = getAccountScanState();
    if (!acc && scanState === 'scanning') {
        // Still reading the phone: never report "no backup" before the scan has finished
        const elapsed = currentDeviceStatus.accounts_scan && currentDeviceStatus.accounts_scan.elapsed_seconds;
        badge.innerHTML = `<span style="color:#93c5fd;display:inline-flex;align-items:center;gap:6px;"><span class="sync-spinner" style="width:10px;height:10px;border-width:2px;"></span>Scanning phone for WhatsApp backups...${elapsed ? ` (${Math.round(elapsed)}s)` : ''}</span>`;
        if (btnRefresh) btnRefresh.style.display = 'none';
        return;
    }
    if (!acc && scanState === 'error') {
        badge.innerHTML = '<span style="color:#fbbf24;">(Could not read WhatsApp folders on phone)</span>';
        if (btnRefresh) btnRefresh.style.display = 'inline-block';
        return;
    }
    if (!acc || !dbMtime) {
        badge.innerHTML = '<span style="color:#fbbf24;">(No backup file found on phone)</span>';
        if (btnRefresh) btnRefresh.style.display = 'inline-block';
        return;
    }

    if (btnRefresh) btnRefresh.style.display = 'inline-block';

    const nowSec = Math.floor(Date.now() / 1000);
    const ageSec = Math.max(0, nowSec - dbMtime);

    if (ageSec < 180) {
        badge.innerHTML = `<span style="background:rgba(16,185,129,0.15);color:var(--accent);padding:2px 8px;border-radius:6px;font-weight:600;">✓ Fresh backup (just now)</span>`;
    } else if (ageSec < 3600) {
        const mins = Math.floor(ageSec / 60);
        badge.innerHTML = `<span style="background:rgba(59,130,246,0.15);color:#93c5fd;padding:2px 8px;border-radius:6px;">Last backup: ${mins}m ago</span>`;
    } else if (ageSec < 86400) {
        const hours = Math.floor(ageSec / 3600);
        badge.innerHTML = `<span style="background:rgba(245,158,11,0.15);color:#fbbf24;padding:2px 8px;border-radius:6px;">Last backup: ${hours}h ago${backupStr ? ` (${escapeHtml(backupStr)})` : ''}</span>`;
    } else {
        const days = Math.floor(ageSec / 86400);
        badge.innerHTML = `<span style="background:rgba(239,68,68,0.15);color:#fca5a5;padding:2px 8px;border-radius:6px;font-weight:500;">Last backup: ${days} days ago -- Tap Back up now!</span>`;
    }
}

function updateSyncPreflightProgress(label, sub, percent) {
    const lbl = document.getElementById('syncPhaseLabel');
    const sb = document.getElementById('syncPhaseSub');
    const bar = document.getElementById('syncProgressBar');
    const stat = document.getElementById('syncStatsStatus');
    if (lbl) lbl.innerText = label;
    if (sb) sb.innerText = sub;
    if (bar) bar.style.width = percent + '%';
    if (stat) stat.innerText = 'Phase: Verification';
}

// ---- Sync pre-flight checklist ---------------------------------------------------------------
// Every check the sync needs is shown as a step, so a slow phone never looks like a frozen app.
const SYNC_PREFLIGHT_STEPS = [
    { id: 'device', label: 'Phone connected over USB' },
    { id: 'auth', label: 'USB debugging authorized' },
    { id: 'key', label: '64-digit backup key saved' },
    { id: 'backups', label: 'WhatsApp backups found on phone' },
    { id: 'account', label: 'WhatsApp account chosen' },
];
let _syncPreflightRunning = false;

function createSyncPreflightChecklist() {
    const steps = {};
    SYNC_PREFLIGHT_STEPS.forEach(s => { steps[s.id] = { state: 'pending', detail: '', startedAt: 0 }; });
    const list = document.getElementById('syncPreflightSteps');
    const render = () => {
        if (!list) return;
        list.style.display = 'flex';
        list.innerHTML = SYNC_PREFLIGHT_STEPS.map(s => {
            const st = steps[s.id];
            const secs = (st.state === 'running' && st.startedAt) ? Math.floor((Date.now() - st.startedAt) / 1000) : 0;
            const icon = st.state === 'running'
                ? '<span class="sync-spinner preflight-spinner"></span>'
                : ({ done: '✓', failed: '✕', warn: '!' }[st.state] || '');
            return `
                <li class="preflight-step is-${st.state}">
                    <span class="preflight-icon">${icon}</span>
                    <span class="preflight-text">
                        <span class="preflight-label">${escapeHtml(s.label)}</span>
                        ${st.detail ? `<span class="preflight-detail">${escapeHtml(st.detail)}</span>` : ''}
                    </span>
                    ${secs >= 2 ? `<span class="preflight-elapsed">${secs}s</span>` : ''}
                </li>`;
        }).join('');
    };
    const ticker = setInterval(render, 1000);
    render();
    return {
        set(id, state, detail = '') {
            const st = steps[id];
            if (state === 'running' && st.state !== 'running') st.startedAt = Date.now();
            st.state = state;
            st.detail = detail;
            render();
        },
        stop() { clearInterval(ticker); },
        hide() {
            clearInterval(ticker);
            if (list) list.style.display = 'none';
        },
    };
}

function describeBackupAge(mtimeSec) {
    if (!mtimeSec) return 'no backup file yet';
    const age = Math.max(0, Math.floor(Date.now() / 1000) - mtimeSec);
    if (age < 180) return 'backed up just now';
    if (age < 3600) return `backed up ${Math.floor(age / 60)} min ago`;
    if (age < 86400) return `backed up ${Math.floor(age / 3600)} h ago`;
    return `backed up ${Math.floor(age / 86400)} days ago`;
}

async function startSyncFromSummary() {
    if (_syncPreflightRunning) {
        showToast('Already checking your phone, please wait a moment...', 'info');
        return;
    }
    _syncPreflightRunning = true;

    const btnStart = document.getElementById('btnStartSyncNow');
    const originalHtml = btnStart ? btnStart.innerHTML : '';
    if (btnStart) {
        btnStart.disabled = true;
    }

    showSyncView('progress');
    const spinner = document.getElementById('syncModalSpinner');
    if (spinner) spinner.style.display = 'block';
    const checklist = createSyncPreflightChecklist();
    // Leaves the checklist and returns to the summary with a toast explaining what is missing
    const backToSummary = (message, level = 'warning') => {
        checklist.hide();
        showSyncView('summary');
        if (message) showToast(message, level);
    };

    try {
        // Steps 1 & 2: device connected & authorized (fast: plain `adb devices`)
        updateSyncPreflightProgress('Checking phone connection...', 'Detecting Android device over ADB...', 10);
        checklist.set('device', 'running');
        const dev = (await checkDeviceStatus()) || currentDeviceStatus;
        if (!dev || !dev.connected) {
            checklist.set('device', 'failed', 'No phone detected');
            backToSummary('Please connect your Android phone via USB cable.');
            openDeviceModal();
            return;
        }
        checklist.set('device', 'done', dev.model || dev.serial || '');
        checklist.set('auth', 'running');
        if (!dev.authorized) {
            checklist.set('auth', 'failed', 'Waiting for permission on the phone');
            backToSummary(dev.usb_debugging === false
                ? 'Phone detected, but USB Debugging is OFF. Please enable it in Developer Options.'
                : "Please tap 'Allow' on your phone screen to authorize USB debugging.");
            openDeviceModal();
            return;
        }
        checklist.set('auth', 'done');

        // Step 3: decryption key configured
        updateSyncPreflightProgress('Verifying backup key...', 'Checking 64-character WhatsApp decryption key...', 25);
        checklist.set('key', 'running');
        let cfg = null;
        try {
            const cfgResp = await fetch('/api/config');
            if (cfgResp.ok) cfg = await cfgResp.json();
        } catch (e) {
            console.warn('Pre-flight key check failed:', e);
        }
        if (cfg) {
            windowHasLocalDb = !!cfg.has_local_db;
            if (!cfg.hex_key_set) {
                checklist.set('key', 'failed', 'No key saved yet');
                backToSummary('A 64-character WhatsApp backup key is required before syncing.');
                await openKeyModal();
                const feedback = document.getElementById('keyValidationFeedback');
                if (feedback) {
                    feedback.innerHTML = `
                        <div style="background:rgba(245,158,11,0.12);border:1px solid rgba(245,158,11,0.3);color:#fbbf24;padding:10px 12px;border-radius:6px;font-size:12px;margin-top:8px;line-height:1.5;">
                            <strong>Key Required:</strong> A 64-character hex backup key is required to decrypt your WhatsApp database (<code>msgstore.db.crypt14</code>). Please enter and save your key to start syncing.
                        </div>
                    `;
                }
                return;
            }
            checklist.set('key', 'done', cfg.masked_key ? `Key ending ...${cfg.masked_key.slice(-4)}` : '');
        } else {
            checklist.set('key', 'warn', 'Could not verify, continuing');
        }

        // Step 4: WhatsApp folders / backups on the phone. The server scans in the background;
        // wait for that scan here instead of racing it (this used to look like a frozen
        // "Checking phone connection..." and then a false "No backup file found").
        updateSyncPreflightProgress('Scanning phone for WhatsApp backups...', 'Reading WhatsApp folders and backup files over ADB. The first scan after connecting can take a few seconds.', 40);
        checklist.set('backups', 'running', 'Reading WhatsApp folders over ADB');
        let st = dev;
        if (getAccountScanState(st) !== 'ready') {
            st = (await checkDeviceStatus({ wait: 25 })) || currentDeviceStatus;
        }
        if (!st || !st.connected || !st.authorized) {
            checklist.set('backups', 'failed', 'Phone disconnected during the scan');
            backToSummary('The phone disconnected while it was being scanned. Reconnect it and try again.');
            return;
        }
        const accounts = st.accounts || [];
        const scanState = getAccountScanState(st);
        if (accounts.length === 0) {
            // Never block here: the sync pipeline runs its own discovery and default-path fallback
            checklist.set('backups', 'warn', scanState === 'scanning'
                ? 'Phone is slow to answer; the sync will keep looking'
                : 'No backup listed yet; the sync will search the default WhatsApp folder');
        } else {
            const acc = st.selected_account || accounts[0];
            const countLabel = accounts.length > 1 ? `${accounts.length} accounts found, ` : '';
            checklist.set('backups', 'done', countLabel + describeBackupAge(Number(acc.latest_db_mtime || 0)));
        }

        // Step 5: pick an account when the phone has several
        updateSyncPreflightProgress('Checking WhatsApp accounts...', 'Confirming which WhatsApp account to sync...', 55);
        checklist.set('account', 'running');
        if (st.has_multiple_accounts) {
            let hasSelectedAccount = Boolean(st.has_selected_account || st.selected_account_path);
            if (!hasSelectedAccount && cfg && cfg.selected_account_path) {
                hasSelectedAccount = true;
                st.selected_account_path = cfg.selected_account_path;
                st.has_selected_account = true;
            }
            if (!hasSelectedAccount) {
                checklist.set('account', 'failed', 'Choose which account to sync');
                backToSummary('Multiple WhatsApp accounts detected. Please select an account to sync.', 'info');
                window._pendingSyncAfterAccountSelect = true;
                openAccountSelectorModal();
                return;
            }
        }
        const chosen = st.selected_account || accounts[0];
        checklist.set('account', 'done', chosen ? (chosen.label || chosen.path || '') : 'Default WhatsApp folder');

        updateSyncPreflightProgress('Launching sync pipeline...', 'Connecting background streaming engine...', 65);
        checklist.hide();
        const chkSkip = document.getElementById('syncSummaryChkSkipDb');
        const skipDb = (!!windowHasLocalDb && chkSkip && chkSkip.checked);
        startSyncFlow(skipDb);
    } catch (err) {
        backToSummary('Pre-flight verification failed: ' + (err.message || err), 'error');
    } finally {
        checklist.stop();
        _syncPreflightRunning = false;
        if (btnStart) {
            btnStart.disabled = false;
            btnStart.innerHTML = originalHtml || '<svg class="icon" viewBox="0 0 24 24" style="width:14px;height:14px;fill:currentColor;"><path d="M12 4V1L8 5l4 4V6c3.31 0 6 2.69 6 6 0 1.01-.25 1.97-.7 2.8l1.46 1.46C19.54 15.03 20 13.57 20 12c0-4.42-3.58-8-8-8zm0 14c-3.31 0-6-2.69-6-6 0-1.01.25-1.97.7-2.8L5.24 7.74C4.46 8.97 4 10.43 4 12c0 4.42 3.58 8 8 8v3l4-4-4-4v3z"/></svg> <span>' + (hasCompletedPriorSync() ? 'Refresh Sync' : 'Start Sync') + '</span>';
        }
    }
}

async function openSyncModal() {
    if (!isHttpServer) {
        showSyncView('progress');
        openModal('modalSync');
        const label = document.getElementById('syncPhaseLabel');
        const sub = document.getElementById('syncPhaseSub');
        const spinner = document.getElementById('syncModalSpinner');
        const btnDismiss = document.getElementById('btnDismissSync');
        if (label) label.innerText = 'Server Not Running';
        if (sub) sub.innerText = 'Please launch start_gallery.bat to enable background synchronization.';
        if (spinner) spinner.style.display = 'none';
        if (btnDismiss) {
            btnDismiss.style.display = 'inline-block';
            btnDismiss.innerText = 'Close';
        }
        return;
    }

    // Zero lag: open modal immediately!
    showSyncView('summary');
    openModal('modalSync');

    // Quick check for active or paused sync in background
    let st = null;
    try {
        const resp = await fetch('/api/sync-status');
        if (resp.ok) {
            st = await resp.json();
            if (st.has_local_db !== undefined) {
                windowHasLocalDb = !!st.has_local_db;
            }
        }
    } catch (e) {
        console.warn('Initial sync-status check failed:', e);
    }

    if (st && st.active) {
        showSyncView('progress');
        pollSyncModalStatus();
        return;
    }

    if (st && (st.status === 'paused' || st.can_resume)) {
        showSyncView('progress');
        renderSyncModalPaused(st);
        pollSyncModalStatus();
        return;
    }

    // Render summary view immediately
    renderSyncModalSummary(st);

    // In background, refresh device status and config to update summary notices without blocking UI
    checkDeviceStatus().then(() => {
        fetch('/api/config').then(r => r.json()).then(cfg => {
            if (cfg) {
                windowHasLocalDb = !!cfg.has_local_db;
                updateSyncModalNotices(cfg);
            }
        }).catch(() => {});
    }).catch(() => {});
}

function renderSyncModalPaused(st) {
    const title = document.getElementById('syncModalTitle');
    const label = document.getElementById('syncPhaseLabel');
    const sub = document.getElementById('syncPhaseSub');
    const bar = document.getElementById('syncProgressBar');
    const statsOrg = document.getElementById('syncStatsOrganized');
    const statsSt = document.getElementById('syncStatsStatus');
    const btnDismiss = document.getElementById('btnDismissSync');
    const spinner = document.getElementById('syncModalSpinner');
    const btnPause = document.getElementById('btnSyncPause');
    const btnResume = document.getElementById('btnSyncResume');
    const btnCancel = document.getElementById('btnSyncCancel');
    const skipBox = document.getElementById('syncInFlightSkipContainer');
    const bgTip = document.getElementById('syncBackgroundTip');

    if (skipBox) skipBox.style.display = 'none';
    if (bgTip) bgTip.style.display = 'none';
    if (spinner) spinner.style.display = 'none';
    if (btnDismiss) {
        btnDismiss.style.display = 'inline-block';
        btnDismiss.innerText = 'Close';
        btnDismiss.classList.remove('btn-highlight-pulse');
    }
    if (btnPause) btnPause.style.display = 'none';
    if (btnResume) {
        btnResume.style.display = 'inline-block';
        btnResume.disabled = false;
        btnResume.innerText = 'Resume Sync';
    }
    if (btnCancel) btnCancel.style.display = 'inline-block';

    if (title) title.innerText = 'Sync Paused';
    if (label) label.innerText = st.phase_label || 'Sync Paused';
    if (st.interrupted_by_device) {
        if (sub) sub.innerText = 'Phone disconnected. Sync will resume automatically as soon as the phone is plugged back in!';
        startDeviceReconnectWatcher();
    } else {
        if (sub) sub.innerText = st.error || 'Progress safely saved to checkpoint. Ready to resume.';
        stopDeviceReconnectWatcher();
    }
    const pct = st.progress_percent || 0;
    if (bar) {
        bar.style.width = `${pct}%`;
        bar.style.background = '#fbbf24';
    }
    if (statsOrg) statsOrg.innerText = `Saved: ${st.synced_files || 0} / ${st.total_files || 0} files`;
    if (statsSt) statsSt.innerText = 'Status: Paused';
}

let _deviceReconnectWatcherTimer = null;
function startDeviceReconnectWatcher() {
    if (_deviceReconnectWatcherTimer) return;
    _deviceReconnectWatcherTimer = setInterval(async () => {
        try {
            const r = await fetch('/api/phone/status');
            if (r.ok) {
                const dev = await r.json();
                if (dev && dev.connected && dev.authorized) {
                    stopDeviceReconnectWatcher();
                    showToast('Phone reconnected! Resuming sync automatically...', 'info');
                    await handleSyncResume();
                }
            }
        } catch (e) {}
    }, 1500);
}

function stopDeviceReconnectWatcher() {
    if (_deviceReconnectWatcherTimer) {
        clearInterval(_deviceReconnectWatcherTimer);
        _deviceReconnectWatcherTimer = null;
    }
}

async function handleSyncPause() {
    const btnPause = document.getElementById('btnSyncPause');
    if (btnPause) {
        btnPause.disabled = true;
        btnPause.innerText = 'Pausing safely...';
    }
    const restorePauseButton = () => {
        if (btnPause) {
            btnPause.disabled = false;
            btnPause.innerText = 'Pause Sync';
        }
    };
    try {
        const resp = await fetch('/api/sync/pause', { method: 'POST' });
        if (resp.ok) {
            showToast('Pausing sync after current file completes...', 'info');
        } else {
            const data = await resp.json().catch(() => ({}));
            showToast(data.message || 'Cannot pause sync', 'warning');
            restorePauseButton();
        }
    } catch (e) {
        showToast('Failed to pause sync: ' + e.message, 'error');
        restorePauseButton();
    }
}

// Skips the in-flight Phase 1 database download and continues with the existing local database
async function handleInFlightSkipDb(btn) {
    if (!isHttpServer) return;
    const label = btn ? btn.querySelector('span') : null;
    if (btn) btn.disabled = true;
    if (label) label.innerText = 'Skipping...';
    try {
        const resp = await fetch('/api/sync/skip-db', { method: 'POST' });
        const data = await resp.json().catch(() => ({}));
        if (resp.ok) {
            showToast(data.message || 'Database download skipped. Using existing local database.', 'info');
            const skipBox = document.getElementById('syncInFlightSkipContainer');
            if (skipBox) skipBox.style.display = 'none';
        } else {
            showToast(data.message || 'Database download can no longer be skipped.', 'warning');
        }
    } catch (e) {
        showToast('Failed to skip database download: ' + e.message, 'error');
    } finally {
        if (btn) btn.disabled = false;
        if (label) label.innerText = 'Skip DB Download';
    }
}

async function handleSyncResume() {
    stopDeviceReconnectWatcher();
    const btnResume = document.getElementById('btnSyncResume');
    if (btnResume) {
        btnResume.disabled = true;
        btnResume.innerText = 'Resuming...';
    }
    const bannerBtn = document.getElementById('syncRefreshBtn');
    if (bannerBtn && bannerBtn.innerText.includes('Resume')) {
        bannerBtn.disabled = true;
        bannerBtn.innerText = 'Resuming...';
    }
    try {
        const resp = await fetch('/api/sync/resume', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });
        const data = await resp.json();
        if (resp.ok) {
            showToast('Resuming synchronization from checkpoint...', 'success');
            pollSyncModalStatus();
            startSyncPolling();
            if (typeof checkSyncStatus === 'function') {
                checkSyncStatus();
            }
        } else {
            showToast(data.message || 'Cannot resume sync', 'error');
            if (btnResume) {
                btnResume.disabled = false;
                btnResume.innerText = 'Resume Sync';
            }
            if (bannerBtn) {
                bannerBtn.disabled = false;
                bannerBtn.innerText = 'Resume Sync';
            }
        }
    } catch (e) {
        showToast('Failed to resume sync: ' + e.message, 'error');
        if (btnResume) {
            btnResume.disabled = false;
            btnResume.innerText = 'Resume Sync';
        }
        if (bannerBtn) {
            bannerBtn.disabled = false;
            bannerBtn.innerText = 'Resume Sync';
        }
    }
}

async function handleSyncCancel() {
    // Confirm first: declining must keep the auto-resume reconnect watcher alive
    if (!confirm('Are you sure you want to cancel the synchronization? Incomplete files will be cleaned up.')) return;
    stopDeviceReconnectWatcher();
    if (syncPollingTimer) {
        clearInterval(syncPollingTimer);
        syncPollingTimer = null;
    }
    try {
        const resp = await fetch('/api/sync/cancel', { method: 'POST' });
        if (resp.ok) {
            showToast('Synchronization cancelled.', 'info');
            closeModal('modalSync');
            updateSyncButtonUI({ active: false });
        }
    } catch (e) {
        showToast('Failed to cancel sync: ' + e.message, 'error');
    }
}

async function startSyncFlow(skipDb = false) {
    const title = document.getElementById('syncModalTitle');
    const label = document.getElementById('syncPhaseLabel');
    const sub = document.getElementById('syncPhaseSub');
    const bar = document.getElementById('syncProgressBar');
    const statsOrg = document.getElementById('syncStatsOrganized');
    const statsSt = document.getElementById('syncStatsStatus');
    const btnDismiss = document.getElementById('btnDismissSync');
    const spinner = document.getElementById('syncModalSpinner');
    const btnPause = document.getElementById('btnSyncPause');
    const btnResume = document.getElementById('btnSyncResume');
    const btnCancel = document.getElementById('btnSyncCancel');
    const skipBox = document.getElementById('syncInFlightSkipContainer');
    const bgTip = document.getElementById('syncBackgroundTip');

    if (skipBox) skipBox.style.display = 'none';
    if (bgTip) bgTip.style.display = 'none';
    if (title) title.innerText = 'WhatsApp Synchronization';
    if (label) label.innerText = 'Starting synchronization pipeline...';
    if (sub) sub.innerText = 'Connecting to phone over ADB...';
    if (bar) {
        bar.style.width = '5%';
        bar.style.background = 'var(--accent)';
    }
    if (statsOrg) statsOrg.innerText = 'Organized: In Progress';
    if (statsSt) statsSt.innerText = 'Phase: Initializing';
    if (spinner) spinner.style.display = 'block';
    if (btnDismiss) {
        btnDismiss.style.display = 'inline-block';
        btnDismiss.innerText = 'Run in Background';
        btnDismiss.classList.remove('btn-highlight-pulse');
    }
    if (btnPause) {
        btnPause.style.display = 'inline-block';
        btnPause.disabled = false;
        btnPause.innerText = 'Pause Sync';
    }
    if (btnResume) btnResume.style.display = 'none';
    if (btnCancel) {
        btnCancel.style.display = 'inline-block';
        btnCancel.disabled = false;
        btnCancel.innerText = 'Cancel Sync';
    }

    const btnSyncDev = document.getElementById('btnSyncCompleteDisableDev');
    if (btnSyncDev) {
        btnSyncDev.style.display = 'none';
        btnSyncDev.disabled = false;
        btnSyncDev.innerHTML = 'Disable Developer Options &amp; Disconnect';
        btnSyncDev.style.background = 'rgba(245,158,11,0.15)';
        btnSyncDev.style.borderColor = 'rgba(245,158,11,0.3)';
        btnSyncDev.style.color = '#fbbf24';
    }
    const syncFeedback = document.getElementById('syncDevOptionsFeedback');
    if (syncFeedback) syncFeedback.innerText = '';

    updateSyncButtonUI({ active: true });

    try {
        const resp = await fetch('/api/sync', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ skip_db_pull: skipDb })
        });
        const res = await resp.json();
        if (resp.ok || resp.status === 409) {
            pollSyncModalStatus();
        } else {
            if (label) label.innerText = 'Sync Failed to Start';
            if (sub) sub.innerText = res.message || 'Unknown error';
            if (spinner) spinner.style.display = 'none';
            if (btnDismiss) {
                btnDismiss.style.display = 'inline-block';
                btnDismiss.innerText = 'Close';
            }
            if (btnPause) btnPause.style.display = 'none';
            updateSyncButtonUI({ active: false });
        }
    } catch (e) {
        if (label) label.innerText = 'Connection Error';
        if (sub) sub.innerText = e.message;
        if (spinner) spinner.style.display = 'none';
        if (btnDismiss) {
            btnDismiss.style.display = 'inline-block';
            btnDismiss.innerText = 'Close';
        }
        if (btnPause) btnPause.style.display = 'none';
        updateSyncButtonUI({ active: false });
    }
}

let _lastSyncVersion = 0;

function pollSyncModalStatus() {
    if (syncPollingTimer) clearInterval(syncPollingTimer);
    syncPollingTimer = setInterval(async () => {
        try {
            const resp = await fetch('/api/sync-status');
            if (!resp.ok) return;
            const st = await resp.json();

            if (st.has_local_db !== undefined) {
                windowHasLocalDb = !!st.has_local_db;
            }

            // Always update header sync button live state
            updateSyncButtonUI(st);

            // Incrementally refresh sidebar when server signals new data batch
            if (st.version && st.version !== _lastSyncVersion) {
                _lastSyncVersion = st.version;
                reloadChatsList();
            }

            const title = document.getElementById('syncModalTitle');
            const label = document.getElementById('syncPhaseLabel');
            const sub = document.getElementById('syncPhaseSub');
            const bar = document.getElementById('syncProgressBar');
            const statsOrg = document.getElementById('syncStatsOrganized');
            const statsSt = document.getElementById('syncStatsStatus');
            const btnDismiss = document.getElementById('btnDismissSync');
            const spinner = document.getElementById('syncModalSpinner');
            const btnPause = document.getElementById('btnSyncPause');
            const btnResume = document.getElementById('btnSyncResume');
            const btnCancel = document.getElementById('btnSyncCancel');
            const skipBox = document.getElementById('syncInFlightSkipContainer');
            const bgTip = document.getElementById('syncBackgroundTip');

            if (st.active) {
                if (spinner) spinner.style.display = 'block';
                if (btnDismiss) {
                    btnDismiss.style.display = 'inline-block';
                    btnDismiss.innerText = 'Run in Background';
                }

                // Background tip & close button pulse during media streaming
                if (st.phase === 'syncing') {
                    if (bgTip) bgTip.style.display = 'flex';
                    if (btnDismiss) btnDismiss.classList.add('btn-highlight-pulse');
                } else {
                    if (bgTip) bgTip.style.display = 'none';
                    if (btnDismiss) btnDismiss.classList.remove('btn-highlight-pulse');
                }

                // In-Flight Skip DB: ONLY show if actively in Phase 1 database download and local db exists
                if (st.phase === 'database' && windowHasLocalDb) {
                    if (skipBox) skipBox.style.display = 'flex';
                } else {
                    if (skipBox) skipBox.style.display = 'none';
                }

                if (st.status === 'pausing') {
                    if (title) title.innerText = 'Pausing Sync...';
                    if (bar) bar.style.background = '#fbbf24';
                    if (btnPause) {
                        btnPause.style.display = 'inline-block';
                        btnPause.disabled = true;
                        btnPause.innerText = 'Pausing safely...';
                    }
                } else {
                    if (title) {
                        if (st.phase === 'database') {
                            title.innerText = 'Syncing WhatsApp (Database)';
                        } else if (st.phase === 'decrypting') {
                            title.innerText = 'Syncing WhatsApp (Decrypting)';
                        } else if (st.phase === 'syncing' || st.phase === 'organizing') {
                            title.innerText = 'Syncing WhatsApp (Media)';
                        } else {
                            title.innerText = 'WhatsApp Synchronization';
                        }
                    }
                    if (bar) bar.style.background = 'var(--accent)';
                    if (btnPause) {
                        btnPause.style.display = 'inline-block';
                        btnPause.disabled = false;
                        btnPause.innerText = 'Pause Sync';
                    }
                }
                if (btnResume) btnResume.style.display = 'none';
                if (btnCancel) {
                    btnCancel.style.display = 'inline-block';
                    btnCancel.disabled = false;
                    btnCancel.innerText = 'Cancel Sync';
                }

                if (label) label.innerText = st.phase_label || 'Processing...';

                if (sub) {
                    if (st.current_file) {
                        sub.innerText = st.current_file;
                    } else if (st.phase_detail) {
                        sub.innerText = st.phase_detail;
                    } else if (st.phase === 'database') {
                        sub.innerText = 'Retrieving chat database from phone...';
                    } else if (st.phase === 'decrypting') {
                        sub.innerText = 'Decrypting chat database with backup key...';
                    } else if (st.phase === 'indexing') {
                        sub.innerText = 'Scanning phone for WhatsApp files...';
                    } else if (st.phase === 'syncing') {
                        sub.innerText = 'Transferring media files...';
                    } else {
                        sub.innerText = 'Processing WhatsApp data...';
                    }
                }

                const pct = (typeof st.progress_percent === 'number' && st.total_files > 0)
                    ? st.progress_percent
                    : (st.phase === 'indexing' ? 3 : st.phase === 'database' ? 10 : st.phase === 'decrypting' ? 25 : st.phase === 'parsing' ? 40 : st.phase === 'organizing' ? 75 : 5);
                if (bar) bar.style.width = `${Math.min(pct, 99)}%`;

                if (statsOrg) {
                    if (st.phase === 'database') {
                        statsOrg.innerText = `Database: ${st.synced_files || 0} / ${st.total_files || 0} files`;
                    } else if (st.phase === 'decrypting') {
                        statsOrg.innerText = `Decrypting chat database...`;
                    } else if (st.phase === 'indexing') {
                        statsOrg.innerText = `Scanning device inventory...`;
                    } else {
                        statsOrg.innerText = `Synced: ${st.synced_files || 0} / ${st.total_files || 0} files`;
                    }
                }

                const phaseDisplayMap = {
                    'database': 'Storage & Database',
                    'decrypting': 'Decryption & Contacts',
                    'indexing': 'Scanning Phone',
                    'syncing': 'Media Streaming',
                    'organizing': 'Organizing Media',
                    'building_gallery': 'Finalizing Gallery',
                    'paused': 'Paused',
                    'done': 'Complete',
                    'error': 'Interrupted'
                };
                if (statsSt) statsSt.innerText = `Phase: ${phaseDisplayMap[st.phase] || st.phase || 'Active'}`;
            } else {
                if (spinner) spinner.style.display = 'none';
                if (btnDismiss) {
                    btnDismiss.style.display = 'inline-block';
                    btnDismiss.innerText = 'Close';
                    btnDismiss.classList.remove('btn-highlight-pulse');
                }
                if (skipBox) skipBox.style.display = 'none';
                if (bgTip) bgTip.style.display = 'none';
                if (btnPause) btnPause.style.display = 'none';

                if (st.status === 'paused' || st.can_resume) {
                    renderSyncModalPaused(st);
                } else if (st.phase === 'done' || st.status === 'done') {
                    if (btnResume) btnResume.style.display = 'none';
                    if (btnCancel) btnCancel.style.display = 'none';
                    if (bar) {
                        bar.style.width = '100%';
                        bar.style.background = 'var(--accent)';
                    }
                    if (title) title.innerText = 'Sync Complete';
                    if (label) label.innerText = 'Synchronization Complete';
                    if (sub) sub.innerText = st.phase_detail || 'All databases decrypted and media files organized.';
                    try { localStorage.setItem('wa_sync_completed_once', 'true'); } catch (e) {}
                    updateSyncButtonUI(st);
                    clearInterval(syncPollingTimer);
                    syncPollingTimer = null;
                    showToast('Synchronization complete!', 'success');
                    reloadChatsList(true);
                    const btnSyncDev = document.getElementById('btnSyncCompleteDisableDev');
                    if (btnSyncDev) {
                        checkDeviceStatus().then(() => {
                            if (currentDeviceStatus && currentDeviceStatus.connected) {
                                btnSyncDev.style.display = 'inline-block';
                                if (currentDeviceStatus.usb_debugging === false) {
                                    btnSyncDev.innerHTML = 'Developer Options Disabled';
                                    btnSyncDev.style.background = 'rgba(16,185,129,0.15)';
                                    btnSyncDev.style.borderColor = 'rgba(16,185,129,0.3)';
                                    btnSyncDev.style.color = 'var(--accent)';
                                    btnSyncDev.disabled = true;
                                } else {
                                    btnSyncDev.innerHTML = 'Disable Developer Options &amp; Disconnect';
                                    btnSyncDev.style.background = 'rgba(245,158,11,0.15)';
                                    btnSyncDev.style.borderColor = 'rgba(245,158,11,0.3)';
                                    btnSyncDev.style.color = '#fbbf24';
                                    btnSyncDev.disabled = false;
                                }
                            }
                        });
                    }
                } else if (st.phase === 'error') {
                    if (title) title.innerText = 'Sync Interrupted';
                    if (st.can_resume && btnResume) {
                        btnResume.style.display = 'inline-block';
                        btnResume.disabled = false;
                        btnResume.innerText = 'Resume Sync';
                    }
                    if (btnCancel) btnCancel.style.display = 'inline-block';
                    if (bar) bar.style.background = 'var(--danger)';
                    if (label) label.innerText = st.phase_label || 'Synchronization Interrupted';
                    if (sub) sub.innerText = st.error || 'Check connection and tap Resume.';
                } else {
                    if (title) title.innerText = 'WhatsApp Synchronization';
                    if (btnResume) btnResume.style.display = 'none';
                    if (btnCancel) btnCancel.style.display = 'none';
                    if (label) label.innerText = 'Ready';
                    if (sub) sub.innerText = 'Pipeline idle.';
                    clearInterval(syncPollingTimer);
                    syncPollingTimer = null;
                }
            }
        } catch (e) {
            console.warn('Sync status poll failed:', e);
        }
    }, 1000);
}
