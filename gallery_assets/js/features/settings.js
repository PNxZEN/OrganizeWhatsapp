/* Settings modal: duplicate setting, import, backup key
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

let _tutAutoOpened = false;

async function checkConfigStatus() {
    if (!isHttpServer) return;
    try {
        const resp = await fetch('/api/config');
        if (resp.ok) {
            const cfg = await resp.json();
            windowHasLocalDb = !!cfg.has_local_db;
            if (!_tutAutoOpened && cfg.onboarding_completed === false) {
                const params = new URLSearchParams(window.location.search);
                if (!params.has('no_auto_tutorial')) {
                    _tutAutoOpened = true;
                    setTimeout(() => openTutorialModal(), 500);
                }
            }
            const ind = document.getElementById('keyIndicator');
            if (ind) {
                if (cfg.hex_key_set) {
                    ind.className = 'key-status-indicator configured';
                    ind.title = 'Backup key is configured';
                } else {
                    ind.className = 'key-status-indicator';
                    ind.title = 'Key not configured';
                }
            }
        }
    } catch (e) {}
}

let keyModalPollTimer = null;
let _lastAnalyzedImportPath = '';

function isDuplicateDetectionEnabled() {
    try {
        const val = localStorage.getItem('wa_setting_duplicate_detection');
        if (val === 'false') return false;
    } catch (e) {}
    return true;
}

function setDuplicateDetectionEnabled(enabled) {
    try {
        localStorage.setItem('wa_setting_duplicate_detection', enabled ? 'true' : 'false');
    } catch (e) {}
    applyDuplicateDetectionSetting();
}

function applyDuplicateDetectionSetting() {
    const enabled = isDuplicateDetectionEnabled();
    const filterControls = document.getElementById('duplicateFilterControls');
    const reviewBtn = document.getElementById('btnReviewDuplicates');
    const quickBtn = document.getElementById('btnQuickReviewDups');
    const chk = document.getElementById('settingEnableDuplicates');
    if (chk) {
        chk.checked = enabled;
        updateDuplicateSwitchLabel(enabled);
    }

    if (!enabled) {
        if (filterControls) filterControls.style.display = 'none';
        if (reviewBtn) reviewBtn.style.display = 'none';
        if (quickBtn) quickBtn.style.display = 'none';
        window._videoHashQueue = [];
        window._isVideoHashingRunning = false;
        window._currentChatDupSet = new Set();
        window._currentChatDupInfo = {};
        window._currentChatDuplicateGroups = [];
    } else {
        if (filterControls) filterControls.style.display = 'flex';
    }

    if (typeof activeChat !== 'undefined' && activeChat) {
        activeChat._dupCache = null;
    }
    if (typeof filterAndRenderMedia === 'function') {
        filterAndRenderMedia();
    }
}

function updateDuplicateSwitchLabel(enabled) {
    const lbl = document.getElementById('settingDuplicatesSwitchLabel');
    if (lbl) {
        lbl.innerText = enabled ? 'Enabled' : 'Disabled';
        lbl.style.color = enabled ? 'var(--accent)' : 'var(--text-muted)';
    }
}

function onToggleDuplicateDetectionSetting(checked) {
    setDuplicateDetectionEnabled(checked);
    updateDuplicateSwitchLabel(checked);
    showToast(checked ? 'Duplicate detection enabled' : 'Duplicate detection disabled', 'info');
}

function switchSettingsTab(tab) {
    const tabGeneral = document.getElementById('tabSettingsGeneral');
    const tabKey = document.getElementById('tabSettingsKey');
    const tabImport = document.getElementById('tabSettingsImport');
    const tabRecycle = document.getElementById('tabSettingsRecycle');
    const tabAbout = document.getElementById('tabSettingsAbout');
    const viewAbout = document.getElementById('settingsViewAbout');
    const viewGeneral = document.getElementById('settingsViewGeneral');
    const viewKey = document.getElementById('settingsViewKey');
    const viewImport = document.getElementById('settingsViewImport');
    const viewRecycle = document.getElementById('settingsViewRecycle');

    [tabGeneral, tabKey, tabImport, tabRecycle, tabAbout].forEach(t => t && t.classList.remove('active'));
    if (viewAbout) viewAbout.style.display = 'none';
    if (viewGeneral) viewGeneral.style.display = 'none';
    if (viewKey) viewKey.style.display = 'none';
    if (viewImport) viewImport.style.display = 'none';
    if (viewRecycle) viewRecycle.style.display = 'none';

    if (tab === 'about') {
        if (tabAbout) tabAbout.classList.add('active');
        if (viewAbout) viewAbout.style.display = 'flex';
        onAboutTabShown();
    } else if (tab === 'recycle') {
        if (tabRecycle) tabRecycle.classList.add('active');
        if (viewRecycle) viewRecycle.style.display = 'flex';
    } else if (tab === 'import') {
        if (tabImport) tabImport.classList.add('active');
        if (viewImport) viewImport.style.display = 'flex';
        onImportPathChanged();
        resumeImportJobView();
    } else if (tab === 'key') {
        if (tabKey) tabKey.classList.add('active');
        if (viewKey) viewKey.style.display = 'flex';
    } else {
        if (tabGeneral) tabGeneral.classList.add('active');
        if (viewGeneral) viewGeneral.style.display = 'flex';
        const chk = document.getElementById('settingEnableDuplicates');
        if (chk) {
            const isEnabled = isDuplicateDetectionEnabled();
            chk.checked = isEnabled;
            updateDuplicateSwitchLabel(isEnabled);
        }
    }
    updateRecycleBinPill();
}

function onImportPathChanged() {
    const input = document.getElementById('importFolderPathInput');
    const btnAnalyze = document.getElementById('btnAnalyzeImportFolder');
    const val = (input ? input.value : '').trim();
    if (btnAnalyze) {
        btnAnalyze.disabled = !val;
    }
    if (val !== _lastAnalyzedImportPath) {
        const box = document.getElementById('importAnalysisBox');
        if (box) box.style.display = 'none';
        const btnStart = document.getElementById('btnStartImport');
        if (btnStart) btnStart.style.display = 'none';
        const errEl = document.getElementById('importPathError');
        if (errEl) errEl.style.display = 'none';
    }
}

async function browseImportFolder() {
    const btn = document.getElementById('btnBrowseImportFolder');
    const btnText = document.getElementById('btnBrowseImportFolderText');
    const input = document.getElementById('importFolderPathInput');
    const errEl = document.getElementById('importPathError');
    if (errEl) errEl.style.display = 'none';

    if (!isHttpServer) {
        if (errEl) {
            errEl.innerText = 'Start the local server (start_gallery.bat) to use the native folder picker, or type/paste the path directly.';
            errEl.style.display = 'block';
        }
        return;
    }

    if (btnText) btnText.innerText = 'Waiting for folder...';
    if (btn) btn.disabled = true;

    try {
        const res = await fetch('/api/import/browse', { method: 'POST' });
        if (!res.ok) {
            throw new Error('Server returned HTTP ' + res.status);
        }
        const data = await res.json();
        if (data.status === 'success' && data.folder) {
            if (input) {
                input.value = data.folder;
                onImportPathChanged();
                await triggerAnalyzeImportFolder();
            }
        } else if (data.status === 'unavailable' || data.status === 'error') {
            if (errEl) {
                errEl.innerText = data.message || 'The folder picker could not be opened. Paste the folder path into the field instead.';
                errEl.style.display = 'block';
            }
            if (input) input.focus();
        }
        // status 'canceled': the user closed the dialog, nothing to do
    } catch (e) {
        console.error('[Import] Failed to open folder picker:', e);
        if (errEl) {
            errEl.innerText = 'Could not open folder picker window. Please paste or type your older folder path directly in the field.';
            errEl.style.display = 'block';
        }
    } finally {
        if (btnText) btnText.innerText = 'Browse...';
        if (btn) btn.disabled = false;
    }
}

let _lastImportAnalysis = null;
let _importPollTimer = null;

function getSelectedImportMode() {
    const checked = document.querySelector('input[name="importMode"]:checked');
    return checked ? checked.value : 'copy';
}

function onImportModeChanged() {
    const btnStart = document.getElementById('btnStartImport');
    const d = _lastImportAnalysis;
    if (!btnStart || !d) return;
    const verb = getSelectedImportMode() === 'move' ? 'Move' : 'Import';
    const files = d.files_to_import !== undefined ? d.files_to_import : d.new_files_count;
    btnStart.innerText = files > 0 ? `${verb} ${files.toLocaleString()} Files (${formatBytes(d.bytes_to_import || 0)})` : 'Merge Databases & Media';
}

async function triggerAnalyzeImportFolder() {
    const input = document.getElementById('importFolderPathInput');
    const path = (input ? input.value : '').trim();
    if (!path) return;

    const btnAnalyze = document.getElementById('btnAnalyzeImportFolder');
    const errEl = document.getElementById('importPathError');
    const box = document.getElementById('importAnalysisBox');
    const btnStart = document.getElementById('btnStartImport');
    if (errEl) errEl.style.display = 'none';
    if (btnAnalyze) {
        btnAnalyze.disabled = true;
        btnAnalyze.innerText = 'Scanning...';
    }

    try {
        const res = await fetch('/api/import/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source_path: path })
        });
        const body = await res.json();
        if (!res.ok || body.status !== 'success') {
            if (errEl) {
                errEl.innerText = body.message || 'Selected folder is invalid or contains no WhatsApp media.';
                errEl.style.display = 'block';
            }
            if (box) box.style.display = 'none';
            if (btnStart) btnStart.style.display = 'none';
            return;
        }

        const d = body.data;
        _lastAnalyzedImportPath = path;
        _lastImportAnalysis = d;
        const filesToImport = d.files_to_import !== undefined ? d.files_to_import : d.new_files_count;

        document.getElementById('importStatTotalMedia').innerText = `${d.media_count.toLocaleString()} files`;
        document.getElementById('importStatTotalSize').innerText = formatBytes(d.total_bytes);
        document.getElementById('importStatNewMedia').innerText = `${filesToImport.toLocaleString()} files`;
        document.getElementById('importStatSkippedMedia').innerText = `${d.already_exists_count.toLocaleString()} files`;

        const badgesEl = document.getElementById('importDbBadges');
        if (badgesEl) {
            let badgesHTML = '';
            if (d.has_gallery_data) {
                badgesHTML += `<span class="badge-tag" style="background:rgba(16,185,129,0.15);color:var(--accent);">✓ Gallery Data</span>`;
            }
            if (d.has_hashes_db) {
                badgesHTML += `<span class="badge-tag" style="background:rgba(59,130,246,0.15);color:#93c5fd;">✓ Hash Index SQLite</span>`;
            }
            if (d.has_sync_db) {
                badgesHTML += `<span class="badge-tag" style="background:rgba(168,85,247,0.15);color:#d8b4fe;">✓ Sync Manifest</span>`;
            }
            badgesEl.innerHTML = badgesHTML;
        }

        const moveDesc = document.getElementById('importMoveDesc');
        if (moveDesc) {
            moveDesc.innerText = d.same_volume
                ? 'Instant on this drive: files are moved, not copied. The older folder is emptied of imported media.'
                : 'The older folder is on another drive: each file is copied, verified, then deleted from it. Needs no extra space.';
        }

        if (box) box.style.display = 'block';
        if (btnStart) {
            btnStart.style.display = 'inline-flex';
            btnStart.disabled = (d.media_count === 0 && !d.has_gallery_data);
        }
        onImportModeChanged();
    } catch (e) {
        if (errEl) {
            errEl.innerText = 'Failed to analyze folder: ' + e.message;
            errEl.style.display = 'block';
        }
    } finally {
        if (btnAnalyze) {
            btnAnalyze.disabled = false;
            btnAnalyze.innerText = 'Analyze';
        }
    }
}

function formatDurationShort(totalSeconds) {
    if (totalSeconds === null || totalSeconds === undefined) return '';
    const s = Math.max(0, Math.round(totalSeconds));
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m} min ${s % 60}s`;
    return `${Math.floor(m / 60)} h ${m % 60} min`;
}

function renderImportProgress(job) {
    const pBox = document.getElementById('importProgressBox');
    const pBar = document.getElementById('importProgressBar');
    const pMsg = document.getElementById('importProgressMessage');
    const pDetail = document.getElementById('importProgressDetail');
    const pFile = document.getElementById('importProgressFile');
    const btnCancel = document.getElementById('btnCancelImport');
    const p = job.progress || {};
    if (pBox && pBox.style.display !== 'block') {
        // Collapse the analysis while importing so the progress is in view
        const aBox = document.getElementById('importAnalysisBox');
        const btnStart = document.getElementById('btnStartImport');
        if (aBox) aBox.style.display = 'none';
        if (btnStart) btnStart.style.display = 'none';
        pBox.style.display = 'block';
        pBox.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
    if (pBar) pBar.style.width = `${Math.min(100, p.percent || 0)}%`;

    const verb = job.mode === 'move' ? 'Moving' : 'Copying';
    let message = p.message || 'Preparing import...';
    let detail = '';
    if (p.phase === 'transferring') {
        message = `${verb} older media...`;
        const parts = [`${(p.files_done || 0).toLocaleString()} of ${(p.files_total || 0).toLocaleString()} files`];
        if (p.bytes_total) parts.push(`${formatBytes(p.bytes_done || 0)} of ${formatBytes(p.bytes_total)}`);
        if (p.speed_bps) parts.push(`${formatBytes(p.speed_bps)}/s`);
        if (p.eta_seconds) parts.push(`about ${formatDurationShort(p.eta_seconds)} left`);
        detail = parts.join(' • ');
    } else if (p.phase === 'scanning' || p.phase === 'starting') {
        message = 'Scanning older folder...';
    }
    if (job.cancel_requested) message = 'Cancelling after the current file...';
    if (pMsg) pMsg.innerText = message;
    if (pDetail) pDetail.innerText = detail;
    if (pFile) pFile.innerText = (p.phase === 'transferring' && p.current_file) ? p.current_file : '';
    if (btnCancel) {
        btnCancel.style.display = job.state === 'running' ? 'inline-flex' : 'none';
        btnCancel.disabled = !!job.cancel_requested;
    }
}

function showImportResult(job) {
    const pBox = document.getElementById('importProgressBox');
    const rBox = document.getElementById('importResultBox');
    const rTitle = document.getElementById('importResultTitle');
    const rDetails = document.getElementById('importResultDetails');
    const aBox = document.getElementById('importAnalysisBox');
    const btnStart = document.getElementById('btnStartImport');
    const d = job.result || {};
    if (pBox) pBox.style.display = 'none';

    if (job.state === 'error') {
        if (aBox) aBox.style.display = 'block';
        if (btnStart) {
            btnStart.style.display = 'inline-flex';
            btnStart.disabled = false;
        }
        showToast('Import failed: ' + (job.error || 'Unknown error'), 'error');
        return;
    }

    if (aBox) aBox.style.display = 'none';
    if (btnStart) btnStart.style.display = 'none';
    if (rBox) rBox.style.display = 'block';
    const moved = d.mode === 'move';
    if (rTitle) {
        rTitle.innerText = job.state === 'cancelled'
            ? 'Import Cancelled'
            : (d.failed_count ? 'Import Finished With Some Errors' : 'Migration Finished Successfully!');
    }
    if (rDetails) {
        const lines = [
            `<strong>${(d.copied_count || 0).toLocaleString()}</strong> media files ${moved ? 'moved' : 'copied'} (${formatBytes(d.copied_bytes || 0)}) in ${formatDurationShort(d.elapsed_seconds || 0)}.`,
            `<strong>${(d.skipped_count || 0).toLocaleString()}</strong> files were already present and skipped${moved && d.left_in_source_count ? ' (left in the older folder)' : ''}.`,
            `<strong>${(d.merged_hashes || 0).toLocaleString()}</strong> hash cache records merged into the duplicate index.`,
            `<strong>${(d.merged_manifest_items || 0).toLocaleString()}</strong> sync manifest items registered to prevent re-pulling.`,
        ];
        if (d.failed_count) {
            const first = (d.failed || [])[0];
            lines.push(`<span style="color:#fca5a5;"><strong>${d.failed_count}</strong> file(s) could not be ${moved ? 'moved' : 'copied'}${first ? ` (e.g. ${escapeHtml(first.file)}: ${escapeHtml(first.error)})` : ''}. Run the import again to retry them.</span>`);
        }
        if (job.state === 'cancelled') {
            lines.push('Files transferred before cancelling are already in your gallery. Run the import again to finish the rest.');
        }
        rDetails.innerHTML = lines.join('<br>');
    }
    // Trigger live gallery reload
    if (isHttpServer) {
        reloadChatsList(true);
    } else {
        reloadGalleryData();
    }
}

function pollImportJob() {
    if (_importPollTimer) clearTimeout(_importPollTimer);
    const tick = async () => {
        _importPollTimer = null;
        let job = null;
        try {
            const res = await fetch('/api/import/status');
            if (res.ok) job = await res.json();
        } catch (e) {}
        if (!job) {
            _importPollTimer = setTimeout(tick, 2000);
            return;
        }
        if (job.state === 'running') {
            renderImportProgress(job);
            _importPollTimer = setTimeout(tick, 500);
        } else if (job.state !== 'idle') {
            renderImportProgress(job);
            showImportResult(job);
        }
    };
    tick();
}

// Re-attaches the progress view when the Import tab is reopened during a running import
async function resumeImportJobView() {
    if (!isHttpServer) return;
    try {
        const res = await fetch('/api/import/status');
        if (!res.ok) return;
        const job = await res.json();
        if (job.state === 'running') {
            const input = document.getElementById('importFolderPathInput');
            if (input && job.source_dir) input.value = job.source_dir;
            const aBox = document.getElementById('importAnalysisBox');
            const btnStart = document.getElementById('btnStartImport');
            if (aBox) aBox.style.display = 'none';
            if (btnStart) btnStart.style.display = 'none';
            renderImportProgress(job);
            pollImportJob();
        }
    } catch (e) {}
}

async function startFolderImport() {
    const input = document.getElementById('importFolderPathInput');
    const path = (input ? input.value : '').trim();
    if (!path) return;
    const mode = getSelectedImportMode();
    if (mode === 'move' && !confirm('Move the media files out of the older folder into your current gallery?\n\nThe older folder will no longer contain the imported photos and videos.')) {
        return;
    }

    const btnStart = document.getElementById('btnStartImport');
    const rBox = document.getElementById('importResultBox');
    if (btnStart) btnStart.disabled = true;
    if (rBox) rBox.style.display = 'none';
    renderImportProgress({ state: 'running', mode, progress: { phase: 'starting', percent: 0 } });

    try {
        const res = await fetch('/api/import/execute', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source_path: path, mode })
        });
        const body = await res.json().catch(() => ({}));
        if (!res.ok || body.status !== 'started') {
            const pBox = document.getElementById('importProgressBox');
            const aBox = document.getElementById('importAnalysisBox');
            if (pBox) pBox.style.display = 'none';
            if (aBox) aBox.style.display = 'block';
            if (btnStart) {
                btnStart.style.display = 'inline-flex';
                btnStart.disabled = false;
            }
            showToast('Import could not start: ' + (body.message || `HTTP ${res.status}`), 'error');
            return;
        }
        pollImportJob();
    } catch (e) {
        const pBox = document.getElementById('importProgressBox');
        const aBox = document.getElementById('importAnalysisBox');
        if (pBox) pBox.style.display = 'none';
        if (aBox) aBox.style.display = 'block';
        if (btnStart) {
            btnStart.style.display = 'inline-flex';
            btnStart.disabled = false;
        }
        showToast('Import request failed: ' + e.message, 'error');
    }
}

async function cancelFolderImport() {
    const btnCancel = document.getElementById('btnCancelImport');
    if (btnCancel) btnCancel.disabled = true;
    try {
        await fetch('/api/import/cancel', { method: 'POST' });
    } catch (e) {
        if (btnCancel) btnCancel.disabled = false;
    }
}

async function openKeyModal(initialTab = 'general') {
    openModal('modalKey');
    switchSettingsTab(initialTab);
    const statusDiv = document.getElementById('keyCurrentStatus');
    const input = document.getElementById('hexKeyInput');
    const count = document.getElementById('keyCharCount');
    const btnSave = document.getElementById('btnSaveKey');
    const feedback = document.getElementById('keyValidationFeedback');
    const btnFetchPhone = document.getElementById('btnKeyFetchPhone');
    const fetchStatus = document.getElementById('keyFetchStatus');

    input.value = '';
    count.innerText = '0 / 64 hex characters';
    count.style.color = 'var(--text-muted)';
    btnSave.disabled = true;
    feedback.innerHTML = '';
    if (fetchStatus) fetchStatus.innerHTML = '';
    if (btnFetchPhone) {
        btnFetchPhone.style.display = 'none';
        btnFetchPhone.disabled = false;
        const txt = document.getElementById('btnKeyFetchPhoneText');
        if (txt) txt.innerText = 'Fetch from Phone';
    }

    let keyConfigured = false;

    if (isHttpServer) {
        // Clear any unstaged received key from memory
        fetch('/api/phone/clear-received-key', { method: 'POST' }).catch(() => {});

        try {
            const resp = await fetch('/api/config');
            if (resp.ok) {
                const cfg = await resp.json();
                windowHasLocalDb = !!cfg.has_local_db;
                keyConfigured = !!cfg.hex_key_set;
                if (cfg.hex_key_set) {
                    statusDiv.innerHTML = `
                                <div style="display:flex;align-items:center;justify-content:space-between;background:rgba(16,185,129,0.08);border:1px solid rgba(16,185,129,0.22);border-radius:8px;padding:8px 12px;gap:8px;">
                                    <div style="display:flex;align-items:center;gap:6px;font-size:12px;overflow:hidden;text-overflow:ellipsis;">
                                        <span style="color:var(--accent);font-weight:600;white-space:nowrap;">Active Key:</span> <code style="word-break:break-all;">${cfg.masked_key}</code>
                                    </div>
                                    <button type="button" id="btnDeleteKey" onclick="deleteActiveKey(event)" title="Delete Key (removes from config.json and deletes encrypted_backup.key)" aria-label="Delete WhatsApp Backup Key" style="background:transparent;border:none;color:#ef4444;cursor:pointer;padding:6px;border-radius:6px;display:flex;align-items:center;justify-content:center;transition:all 0.15s;flex-shrink:0;" onmouseover="this.style.background='rgba(239,68,68,0.15)'" onmouseout="this.style.background='transparent'">
                                        <svg viewBox="0 0 24 24" style="width:16px;height:16px;fill:currentColor;pointer-events:none;"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>
                                    </button>
                                </div>
                            `;
                    btnSave.disabled = false;
                    btnSave.innerText = 'Save Settings';
                } else {
                    statusDiv.innerHTML = `
                                <span style="color:#f59e0b;">No Key Configured:</span> Database decryption will require entering your key.
                            `;
                    btnSave.innerText = 'Save Key';
                }
            }
        } catch (e) {
            statusDiv.innerText = '';
        }

        // Check ADB device readiness: only show Fetch from Phone if key isn't present AND device is ready
        try {
            const devResp = await fetch('/api/device-status');
            if (devResp.ok) {
                currentDeviceStatus = await devResp.json();
            }
        } catch (e) {}

        const isDeviceReady = currentDeviceStatus && currentDeviceStatus.connected && currentDeviceStatus.authorized;
        if (btnFetchPhone && !keyConfigured && isDeviceReady) {
            btnFetchPhone.style.display = 'inline-flex';
        }
    }
}

async function deleteActiveKey(e) {
    if (e) {
        e.preventDefault();
        e.stopPropagation();
    }
    const confirmed = window.confirm('Are you sure you want to delete this backup key? It will be permanently removed from config.json and encrypted_backup.key.');
    if (!confirmed) {
        return;
    }
    try {
        const resp = await fetch('/api/delete-key', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });
        let res = {};
        try { res = await resp.json(); } catch(err) { res = {}; }
        if (resp.ok && (res.status === 'success' || !res.status)) {
            showToast('Backup key permanently deleted.', 'success');
            const input = document.getElementById('hexKeyInput');
            if (input) input.value = '';
            const count = document.getElementById('keyCharCount');
            if (count) {
                count.innerText = '0 / 64 hex characters';
                count.style.color = 'var(--text-muted)';
            }
            const feedback = document.getElementById('keyValidationFeedback');
            if (feedback) feedback.innerHTML = '';
            const fetchStatus = document.getElementById('keyFetchStatus');
            if (fetchStatus) fetchStatus.innerHTML = '';

            await checkConfigStatus();
            await openKeyModal();
        } else {
            showToast(res.message || 'Failed to delete key.', 'error');
        }
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
    }
}

async function fetchKeyFromPhone() {
    const btn = document.getElementById('btnKeyFetchPhone');
    const text = document.getElementById('btnKeyFetchPhoneText');
    const fetchStatus = document.getElementById('keyFetchStatus');

    btn.disabled = true;
    text.innerText = 'Opening portal...';
    if (fetchStatus) {
        fetchStatus.innerHTML = '<span style="color:var(--accent);">Setting up physical USB reverse tether...</span>';
    }

    try {
        const resp = await fetch('/api/phone/open-key-portal', { method: 'POST' });
        const res = await resp.json();
        if (resp.ok && res.status === 'success') {
            btn.disabled = false;
            text.innerText = 'Waiting for key...';
            if (fetchStatus) {
                fetchStatus.innerHTML = `
                            <div style="color:var(--accent);font-weight:600;display:flex;align-items:center;gap:6px;">
                                <span class="status-dot dot-ready" style="animation:pulseWarning 1s infinite;"></span>
                                Portal opened on phone! Tap "Paste &amp; Send to PC" on mobile screen...
                            </div>
                        `;
            }
            if (keyModalPollTimer) clearInterval(keyModalPollTimer);
            keyModalPollTimer = setInterval(async () => {
                try {
                    const kResp = await fetch('/api/key-status');
                    if (kResp.ok) {
                        const kData = await kResp.json();
                        if (kData.received_key) {
                            clearInterval(keyModalPollTimer);
                            keyModalPollTimer = null;
                            const key = kData.received_key;
                            onKeyInput(key);
                            text.innerText = 'Key Received!';
                            if (fetchStatus) {
                                fetchStatus.innerHTML = `
                                            <span style="color:var(--accent);font-weight:600;">64-digit key received from phone! Click "Save Settings" below to apply.</span>
                                        `;
                            }
                            showToast('64-digit key received from phone! Click Save Settings to save.', 'success');
                        }
                    }
                } catch (e) {}
            }, 1000);
        } else {
            btn.disabled = false;
            text.innerText = 'Fetch from Phone';
            if (fetchStatus) {
                fetchStatus.innerHTML = `<span style="color:#ef4444;">Could not open portal: ${res.message || 'Check USB debugging connection.'}</span>`;
            }
        }
    } catch (err) {
        btn.disabled = false;
        text.innerText = 'Fetch from Phone';
        if (fetchStatus) {
            fetchStatus.innerHTML = `<span style="color:#ef4444;">Network error: ${err.message}</span>`;
        }
    }
}

function onKeyInput(val) {
    const cleaned = val.replace(/[^0-9a-fA-F]/g, '').toLowerCase();
    const input = document.getElementById('hexKeyInput');
    const count = document.getElementById('keyCharCount');
    const btnSave = document.getElementById('btnSaveKey');
    const feedback = document.getElementById('keyValidationFeedback');

    input.value = cleaned;
    const len = cleaned.length;
    count.innerText = `${len} / 64 hex characters`;

    if (len === 64) {
        count.style.color = 'var(--accent)';
        btnSave.disabled = false;
        feedback.innerHTML = '<span style="color:var(--accent);">Valid 64-character hexadecimal key format.</span>';
    } else if (len === 0) {
        btnSave.disabled = false;
        count.style.color = 'var(--text-muted)';
        feedback.innerHTML = '';
    } else {
        count.style.color = len > 64 ? 'var(--danger)' : 'var(--text-muted)';
        btnSave.disabled = true;
        feedback.innerHTML = `<span style="color:var(--text-muted);">Need ${64 - len} more hex characters.</span>`;
    }
}

async function pasteKeyFromClipboard() {
    try {
        const text = await navigator.clipboard.readText();
        if (text) {
            onKeyInput(text.trim());
        }
    } catch (e) {
        showToast('Unable to read clipboard. Please paste manually.', 'error');
    }
}

async function saveKeyConfig() {
    const input = document.getElementById('hexKeyInput');
    const btnSave = document.getElementById('btnSaveKey');
    const key = input.value.trim();

    const payload = {};
    if (key.length > 0) {
        if (key.length !== 64) {
            showToast('Key must be exactly 64 hexadecimal characters.', 'error');
            return;
        }
        payload.hex_key = key;
    }

    btnSave.disabled = true;
    btnSave.innerText = 'Saving...';
    try {
        const resp = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const res = await resp.json();
        if (resp.ok && res.status === 'success') {
            showToast('Settings saved successfully.', 'success');
            await checkConfigStatus();
            closeModal('modalKey');
        } else {
            showToast(res.message || 'Failed to save configuration.', 'error');
        }
    } catch (e) {
        showToast(`Error: ${e.message}`, 'error');
    } finally {
        btnSave.disabled = false;
        btnSave.innerText = 'Save Settings';
    }
}
