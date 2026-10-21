/* Phone Storage Reclaim Studio
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

// ==========================================
// PHONE STORAGE RECLAIM & RESTORE MODULE
// ==========================================
let activeCleanPlan = null;
let selectedCleanProfile = 'smart_reclaim';
let storageReclaimPollTimer = null;
window._isPhoneConnectedForClean = false;
let _reclaimLastStorageRefreshTime = 0;

function switchViewMode(mode) {
    currentViewMode = mode;
    const galleryContainer = document.getElementById('galleryViewContainer');
    const reclaimStudio = document.getElementById('reclaimStudioView');
    const btnControlReclaim = document.getElementById('btnControlReclaim');
    const banner = document.getElementById('sidebarReclaimBanner');

    if (mode === 'reclaim') {
        if (galleryContainer) galleryContainer.style.display = 'none';
        if (reclaimStudio) {
            reclaimStudio.style.display = 'flex';
            reclaimStudio.style.flexDirection = 'column';
        }
        if (btnControlReclaim) btnControlReclaim.classList.add('active');
        if (banner) banner.style.display = 'block';

        // Pre-select all chats by default across all 3 reclaim strategies
        if (customCleanTargetJids.size === 0) {
            const allChats = getChatsArray();
            allChats.forEach(c => {
                if (c.jid) customCleanTargetJids.add(c.jid);
            });
        }

        updateSidebarReclaimBanner();
        renderSidebar();
        loadPhoneStorageInfo();
        if (storageReclaimPollTimer) clearInterval(storageReclaimPollTimer);
        // Real-time USB debugging device watcher:
        // Fast 2s checkDeviceStatus detects cable plug/unplug instantly without heavy storage calculation.
        // When connected, periodic storage refresh runs gently every 30s.
        _reclaimLastStorageRefreshTime = Date.now();
        storageReclaimPollTimer = setInterval(async () => {
            if (currentViewMode !== 'reclaim' || document.hidden) return;
            await checkDeviceStatus();
            const now = Date.now();
            if (currentDeviceStatus && currentDeviceStatus.connected && currentDeviceStatus.authorized) {
                if (now - _reclaimLastStorageRefreshTime >= 30000) {
                    _reclaimLastStorageRefreshTime = now;
                    loadPhoneStorageInfo();
                }
            }
        }, 2000);
    } else {
        if (reclaimStudio) reclaimStudio.style.display = 'none';
        if (galleryContainer) galleryContainer.style.display = 'flex';
        if (btnControlReclaim) btnControlReclaim.classList.remove('active');
        if (banner) banner.style.display = 'none';
        renderSidebar();
        if (storageReclaimPollTimer) {
            clearInterval(storageReclaimPollTimer);
            storageReclaimPollTimer = null;
        }
    }
}

async function openStorageReclaimModal() {
    if (currentViewMode === 'reclaim') {
        closeStorageReclaimStudio();
        return;
    }
    switchViewMode('reclaim');
    showReclaimStep('profiles');
    selectCleanProfile(selectedCleanProfile || 'smart_reclaim');
}

function closeStorageReclaimStudio() {
    switchViewMode('gallery');
    activeCleanPlan = null;
}

function closeStorageReclaimModal() {
    closeStorageReclaimStudio();
}

function handleMinAgePresetChange() {
    const sel = document.getElementById('customMinAgeSelect');
    const wrap = document.getElementById('customMinAgeDaysWrap');
    if (sel && wrap) {
        wrap.style.display = (sel.value === 'custom') ? 'inline-flex' : 'none';
    }
}

async function loadPhoneStorageInfo(isManualClick = false) {
    _reclaimLastStorageRefreshTime = Date.now();
    const dot = document.getElementById('reclaimPhoneStatusDot');
    const text = document.getElementById('reclaimPhoneStatusText');
    const numbers = document.getElementById('reclaimStorageNumbers');
    const bar = document.getElementById('reclaimStorageBarFill');
    const icon = document.getElementById('reclaimPhoneRefreshIcon');

    if (isManualClick && icon) {
        icon.classList.add('refresh-spinning');
    }
    const startTime = Date.now();

    if (!isHttpServer) {
        window._isPhoneConnectedForClean = false;
        if (dot) dot.style.background = '#94a3b8';
        if (text) text.innerText = 'Offline Gallery (Start local server for USB device clean)';
        if (numbers) numbers.innerText = '';
        if (isManualClick && icon) {
            setTimeout(() => icon.classList.remove('refresh-spinning'), 600);
        }
        return;
    }

    try {
        const res = await fetch('/api/phone/storage');
        const data = await res.json().catch(() => ({}));
        const isConn = Boolean(data.connected);
        const isAuth = Boolean(data.authorized);
        const hasStorage = res.ok && data.total_bytes > 0;

        if (hasStorage) {
            window._isPhoneConnectedForClean = true;
            const freeGb = data.free_gb || 0;
            const totalGb = data.total_gb || 0;
            const pctUsed = Math.min(100, Math.round(((data.used_bytes || 0) / data.total_bytes) * 100));

            if (dot) dot.style.background = '#10b981';
            if (text) text.innerText = 'Phone Connected via USB';
            if (numbers) numbers.innerText = `${freeGb} GB free of ${totalGb} GB (${pctUsed}% used)`;
            if (bar) bar.style.width = `${pctUsed}%`;
        } else if (!isConn) {
            window._isPhoneConnectedForClean = false;
            if (dot) dot.style.background = '#ef4444';
            if (text) text.innerHTML = '<span style="color:#f87171;font-weight:600;">Phone Not Connected</span> - Connect your phone via USB cable';
            if (numbers) numbers.innerText = 'Device Offline';
            if (bar) bar.style.width = '0%';
        } else if (!isAuth) {
            window._isPhoneConnectedForClean = false;
            if (dot) dot.style.background = '#f59e0b';
            if (text) text.innerHTML = '<span style="color:#fbbf24;font-weight:600;">Authorization Required</span> - Tap "Allow USB debugging" on phone screen';
            if (numbers) numbers.innerText = 'Unauthorized';
            if (bar) bar.style.width = '0%';
        } else {
            window._isPhoneConnectedForClean = false;
            if (dot) dot.style.background = '#f59e0b';
            const errMsg = data.error || 'Failed to read device storage';
            if (text) text.innerText = 'Storage Status: ' + errMsg;
            if (numbers) numbers.innerText = 'Storage Busy';
            if (bar) bar.style.width = '0%';
        }

        // Dynamically update Step 2 offline notice and button if preview is currently open
        const warnBanner = document.getElementById('reclaimDisconnectedWarningBanner');
        if (warnBanner && document.getElementById('reclaimStepPreview')?.style.display !== 'none') {
            warnBanner.style.display = window._isPhoneConnectedForClean ? 'none' : 'flex';
        }
        if (activeCleanPlan && document.getElementById('reclaimStepPreview')?.style.display !== 'none') {
            recalculatePreviewMetrics();
        }
    } catch (e) {
        window._isPhoneConnectedForClean = false;
        if (dot) dot.style.background = '#ef4444';
        if (text) text.innerText = 'Failed to fetch device storage: ' + e.message;
    } finally {
        if (isManualClick && icon) {
            const elapsed = Date.now() - startTime;
            const minDuration = 600;
            setTimeout(() => {
                icon.classList.remove('refresh-spinning');
            }, Math.max(0, minDuration - elapsed));
        }
    }
}

function selectCleanProfile(profile) {
    selectedCleanProfile = profile;
    document.querySelectorAll('.reclaim-card').forEach(c => c.classList.remove('selected'));
    const cardMap = {
        'smart_reclaim': 'cardSmartReclaim',
        'video_offload': 'cardVideoOffload',
        'custom': 'cardCustomProfile'
    };
    const activeCard = document.getElementById(cardMap[profile]);
    if (activeCard) activeCard.classList.add('selected');

    const drawer = document.getElementById('customProfileDrawer');
    if (drawer) {
        drawer.style.display = 'block';
    }
    const dSmart = document.getElementById('drawerSmartReclaim');
    const dVideo = document.getElementById('drawerVideoOffload');
    const dCustom = document.getElementById('drawerCustomClean');
    if (dSmart) dSmart.style.display = (profile === 'smart_reclaim') ? 'block' : 'none';
    if (dVideo) dVideo.style.display = (profile === 'video_offload') ? 'block' : 'none';
    if (dCustom) dCustom.style.display = (profile === 'custom') ? 'block' : 'none';

    updateSidebarReclaimBanner();
    renderSidebar();
}

function updateSidebarReclaimBanner() {
    const banner = document.getElementById('sidebarReclaimBanner');
    if (!banner || currentViewMode !== 'reclaim') return;
    const title = document.getElementById('sidebarReclaimModeTitle');
    const desc = document.getElementById('sidebarReclaimModeDesc');
    const toggleIcon = document.getElementById('sidebarReclaimToggleAllIcon');
    const toggleText = document.getElementById('sidebarReclaimToggleAllText');

    const allChats = getChatsArray();
    const totalCount = allChats.length;
    const selectedCount = customCleanTargetJids.size;

    const isAllSelected = (selectedCount === totalCount && totalCount > 0);

    if (title) title.innerText = 'Cleanup Scope';

    if (toggleIcon) toggleIcon.innerText = isAllSelected ? '✕' : '✓';
    if (toggleText) toggleText.innerText = isAllSelected ? 'Deselect All' : 'Select All';

    if (desc) {
        if (selectedCount === totalCount) {
            desc.innerText = `All ${totalCount} chats selected for cleanup. Uncheck any chat to protect it.`;
        } else if (selectedCount === 0) {
            desc.innerText = `0 chats selected. Check chats below to include in cleanup.`;
        } else {
            const excludedCount = totalCount - selectedCount;
            desc.innerText = `${selectedCount} of ${totalCount} chats selected • ${excludedCount} chat${excludedCount === 1 ? '' : 's'} protected.`;
        }
    }
}

function toggleSelectAllSidebarChats() {
    const allChats = getChatsArray();
    const previewStep = document.getElementById('reclaimStepPreview');
    const isPreviewOpen = previewStep && previewStep.style.display !== 'none' && activeCleanPlan;

    if (customCleanTargetJids.size === allChats.length) {
        // If all selected, deselect all
        customCleanTargetJids.clear();
        if (isPreviewOpen) {
            toggleAllPreviewChats(false, false);
        }
    } else {
        // If not all selected, select all
        allChats.forEach(c => {
            if (c.jid) customCleanTargetJids.add(c.jid);
        });
        if (isPreviewOpen) {
            toggleAllPreviewChats(true, false);
        }
    }
    updateSidebarReclaimBanner();
    renderSidebar();
}

function selectAllSidebarChatsForReclaim() {
    toggleSelectAllSidebarChats();
}

function clearSidebarChatsForReclaim() {
    customCleanTargetJids.clear();
    const previewStep = document.getElementById('reclaimStepPreview');
    if (previewStep && previewStep.style.display !== 'none' && activeCleanPlan) {
        toggleAllPreviewChats(false, false);
    }
    updateSidebarReclaimBanner();
    renderSidebar();
}

function toggleCustomTargetChat(jid) {
    const willBeChecked = !customCleanTargetJids.has(jid);
    if (customCleanTargetJids.has(jid)) {
        customCleanTargetJids.delete(jid);
    } else {
        customCleanTargetJids.add(jid);
    }
    updateSidebarReclaimBanner();
    renderSidebar();

    // If Step 2 (Plan Preview) is currently active, sync preview metrics and row
    const previewStep = document.getElementById('reclaimStepPreview');
    if (previewStep && previewStep.style.display !== 'none' && activeCleanPlan) {
        togglePreviewChat(jid, willBeChecked, false);
    }
}

function handleStorageReclaimBack() {
    const previewStep = document.getElementById('reclaimStepPreview');
    const progressStep = document.getElementById('reclaimStepProgress');
    if ((previewStep && previewStep.style.display !== 'none') || (progressStep && progressStep.style.display !== 'none')) {
        showReclaimStep('profiles');
    } else {
        closeStorageReclaimStudio();
    }
}

function handleDuplicateReviewBack() {
    const lightbox = document.getElementById('lightboxDupCompare');
    if (lightbox && lightbox.style.display !== 'none') {
        closeDuplicateCompareLightbox();
        return;
    }
    if (typeof currentDupTab !== 'undefined' && currentDupTab !== 'review') {
        switchDuplicateTab('review');
        return;
    }
    closeModal('modalDuplicateReview');
}

let customCleanTargetJids = new Set();

function showReclaimStep(step) {
    const s1 = document.getElementById('reclaimStepProfiles');
    const s2 = document.getElementById('reclaimStepPreview');
    const s3 = document.getElementById('reclaimStepProgress');
    if (s1) s1.style.display = (step === 'profiles') ? 'block' : 'none';
    if (s2) s2.style.display = (step === 'preview') ? 'block' : 'none';
    if (s3) s3.style.display = (step === 'progress') ? 'block' : 'none';
}

let _analyzeProgressTimer = null;

function startAnalyzeButtonProgress() {
    const bar = document.getElementById('btnAnalyzeProgressBar');
    if (bar) {
        bar.style.transition = 'width 0.25s cubic-bezier(0.4, 0, 0.2, 1)';
        bar.style.width = '10%';
    }
    if (_analyzeProgressTimer) clearInterval(_analyzeProgressTimer);
    let pct = 10;
    _analyzeProgressTimer = setInterval(() => {
        if (pct < 55) {
            pct += Math.random() * 8 + 4;
        } else if (pct < 84) {
            pct += Math.random() * 4 + 2;
        } else if (pct < 94) {
            pct += 0.8;
        }
        if (pct > 94) pct = 94;
        if (bar) bar.style.width = `${pct}%`;
    }, 120);
}

function finishAnalyzeButtonProgress(callback) {
    if (_analyzeProgressTimer) {
        clearInterval(_analyzeProgressTimer);
        _analyzeProgressTimer = null;
    }
    const bar = document.getElementById('btnAnalyzeProgressBar');
    if (bar) {
        bar.style.transition = 'width 0.2s cubic-bezier(0, 0, 0.2, 1)';
        bar.style.width = '100%';
        setTimeout(() => {
            if (callback) callback();
            setTimeout(() => {
                bar.style.transition = 'none';
                bar.style.width = '0%';
                resetAnalyzeButtonText();
            }, 350);
        }, 220);
    } else {
        if (callback) callback();
        resetAnalyzeButtonText();
    }
}

function resetAnalyzeButtonProgress() {
    if (_analyzeProgressTimer) {
        clearInterval(_analyzeProgressTimer);
        _analyzeProgressTimer = null;
    }
    const bar = document.getElementById('btnAnalyzeProgressBar');
    if (bar) {
        bar.style.transition = 'none';
        bar.style.width = '0%';
    }
    resetAnalyzeButtonText();
}

function resetAnalyzeButtonText() {
    const btn = document.getElementById('btnAnalyzeReclaim');
    const txt = document.getElementById('btnAnalyzeReclaimText');
    if (btn) btn.disabled = false;
    if (txt) txt.innerText = 'Analyze & Preview Reclaim';
}

async function generateCleanPlanPreview() {
    const customCfg = {};
    let effectiveMinAge = 30;

    if (selectedCleanProfile === 'smart_reclaim') {
        const vidMb = parseInt(document.getElementById('smartVideoSize')?.value || '15', 10);
        const vidAge = parseInt(document.getElementById('smartVideoAge')?.value || '90', 10);
        const archAge = parseInt(document.getElementById('smartArchivedAge')?.value || '60', 10);
        const inactGrp = parseInt(document.getElementById('smartGroupInactivity')?.value || '180', 10);
        const protFloor = parseInt(document.getElementById('smartProtectionFloor')?.value || '30', 10);

        customCfg.large_video_min_bytes = vidMb * 1024 * 1024;
        customCfg.large_video_min_age = vidAge;
        customCfg.archived_min_age = archAge;
        customCfg.inactive_group_threshold_days = inactGrp;
        customCfg.min_age_days = protFloor;
        effectiveMinAge = Math.min(vidAge, archAge, protFloor);
    } else if (selectedCleanProfile === 'video_offload') {
        const offloadAge = parseInt(document.getElementById('videoOffloadAge')?.value || '30', 10);
        customCfg.large_video_min_age = offloadAge;
        customCfg.min_age_days = offloadAge;
        effectiveMinAge = offloadAge;
    } else if (selectedCleanProfile === 'custom') {
        const types = [];
        if (document.getElementById('customTypeVideos')?.checked) types.push('videos');
        if (document.getElementById('customTypePhotos')?.checked) types.push('photos');
        if (document.getElementById('customTypeAudio')?.checked) types.push('audio');
        if (document.getElementById('customTypeDocs')?.checked) types.push('documents');
        if (document.getElementById('customTypeStickers')?.checked) types.push('stickers');
        if (types.length === 0) {
            showToast('Please select at least one media type to clean (e.g. Videos or Photos).', 'warning');
            return;
        }
        customCfg.media_types = types;

        const presetVal = document.getElementById('customMinAgeSelect')?.value;
        if (presetVal === 'custom') {
            effectiveMinAge = Math.max(0, parseInt(document.getElementById('customMinAgeInput')?.value || '0', 10));
        } else {
            effectiveMinAge = Math.max(0, parseInt(presetVal || '30', 10));
        }
        customCfg.min_age_days = effectiveMinAge;
        customCfg.keep_starred = Boolean(document.getElementById('customKeepStarred')?.checked !== false);
    }

    // Apply sidebar chat inclusion / exclusion across all 3 reclaim profiles
    if (customCleanTargetJids.size === 0) {
        showToast('Please select at least one chat in the left sidebar to clean.', 'warning');
        return;
    }

    const allChats = getChatsArray();
    const selectedJids = Array.from(customCleanTargetJids);
    const excludedJids = allChats.filter(c => !customCleanTargetJids.has(c.jid)).map(c => c.jid);

    customCfg.include_jids = selectedJids;
    customCfg.exclude_jids = excludedJids;
    customCfg.chat_scope = (selectedJids.length === allChats.length) ? 'all' : 'selected_only';

    // Safety Warning for < 30 days selection
    if (effectiveMinAge < 30) {
        const proceed = confirm(
            `[Safety Notice]: You selected media newer than 30 days (${effectiveMinAge} days).\n\n` +
            `Media received recently will be queued for removal from your phone storage. (Your PC archive keeps 100% of all files safe).\n\n` +
            `Do you want to proceed with this cleanup preview?`
        );
        if (!proceed) {
            return;
        }
    }

    const btn = document.getElementById('btnAnalyzeReclaim');
    const txt = document.getElementById('btnAnalyzeReclaimText');
    if (btn) btn.disabled = true;
    if (txt) txt.innerText = 'Analyzing Storage...';
    startAnalyzeButtonProgress();

    try {
        const res = await fetch('/api/clean/plan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                profile: selectedCleanProfile,
                custom_config: customCfg
            })
        });
        if (!res.ok) {
            resetAnalyzeButtonProgress();
            const errData = await res.json().catch(() => ({}));
            showToast(errData.message || 'Failed to generate clean plan', 'error');
            return;
        }
        const data = await res.json();
        activeCleanPlan = data.plan;
        finishAnalyzeButtonProgress(() => {
            renderCleanPlanPreview(activeCleanPlan);
            showReclaimStep('preview');
        });
    } catch (err) {
        resetAnalyzeButtonProgress();
        showToast('Network error analyzing clean plan: ' + err.message, 'error');
    }
}

let previewExcludedChatJids = new Set();

function resetPreviewChatExclusions() {
    previewExcludedChatJids.clear();
}

function togglePreviewChat(jid, isChecked, syncSidebar = true) {
    if (isChecked) {
        previewExcludedChatJids.delete(jid);
        if (syncSidebar) customCleanTargetJids.add(jid);
    } else {
        previewExcludedChatJids.add(jid);
        if (syncSidebar) customCleanTargetJids.delete(jid);
    }
    recalculatePreviewMetrics();
    const row = document.getElementById('reclaimChatRow_' + jid);
    if (row) {
        row.style.opacity = isChecked ? '1' : '0.5';
        const tagEl = row.querySelector('.reclaim-row-excl-tag');
        if (tagEl) tagEl.style.display = isChecked ? 'none' : 'inline';
        const sizeEl = row.querySelector('.reclaim-row-size');
        if (sizeEl) sizeEl.style.color = isChecked ? '#4ade80' : 'var(--text-muted)';
        const cb = row.querySelector('.reclaim-chat-cb');
        if (cb) cb.checked = isChecked;
    }
    if (syncSidebar) {
        updateSidebarReclaimBanner();
        renderSidebar();
    }
}

function toggleAllPreviewChats(selectAll, syncSidebar = true) {
    if (!activeCleanPlan || !activeCleanPlan.breakdown || !activeCleanPlan.breakdown.by_chat) return;
    const chats = activeCleanPlan.breakdown.by_chat;
    if (selectAll) {
        previewExcludedChatJids.clear();
        if (syncSidebar) {
            chats.forEach(c => { if (c.jid) customCleanTargetJids.add(c.jid); });
        }
    } else {
        chats.forEach(c => {
            previewExcludedChatJids.add(c.jid);
            if (syncSidebar) customCleanTargetJids.delete(c.jid);
        });
    }
    document.querySelectorAll('.reclaim-chat-cb').forEach(cb => {
        cb.checked = selectAll;
    });
    chats.forEach(c => {
        const row = document.getElementById('reclaimChatRow_' + c.jid);
        if (row) {
            row.style.opacity = selectAll ? '1' : '0.5';
            const tagEl = row.querySelector('.reclaim-row-excl-tag');
            if (tagEl) tagEl.style.display = selectAll ? 'none' : 'inline';
            const sizeEl = row.querySelector('.reclaim-row-size');
            if (sizeEl) sizeEl.style.color = selectAll ? '#4ade80' : 'var(--text-muted)';
        }
    });
    recalculatePreviewMetrics();
    if (syncSidebar) {
        updateSidebarReclaimBanner();
        renderSidebar();
    }
}

function recalculatePreviewMetrics() {
    if (!activeCleanPlan || !activeCleanPlan.breakdown || !activeCleanPlan.breakdown.by_chat) return;
    const chats = activeCleanPlan.breakdown.by_chat;
    let includedBytes = 0;
    let includedFiles = 0;
    let includedChats = 0;

    chats.forEach(c => {
        if (!previewExcludedChatJids.has(c.jid)) {
            includedBytes += (c.bytes || 0);
            includedFiles += (c.count || 0);
            includedChats += 1;
        }
    });

    const savingsEl = document.getElementById('reclaimMetricSavings');
    const filesEl = document.getElementById('reclaimMetricFiles');
    const countText = document.getElementById('reclaimSelectedCountText');
    if (savingsEl) savingsEl.innerText = formatBytes(includedBytes);
    if (filesEl) filesEl.innerText = includedFiles.toLocaleString();
    if (countText) {
        countText.innerText = `${includedChats} of ${chats.length} chats included`;
    }

    const execBtn = document.getElementById('btnExecuteCleanPlan');
    if (execBtn) {
        const isPhoneReady = Boolean(window._isPhoneConnectedForClean);
        if (includedFiles === 0) {
            execBtn.disabled = true;
            execBtn.style.background = '#374151';
            execBtn.style.borderColor = '#4b5563';
            execBtn.style.color = '#9ca3af';
            execBtn.style.boxShadow = 'none';
            execBtn.style.cursor = 'not-allowed';
            execBtn.innerHTML = `<span>No Chats Selected to Clean</span>`;
        } else if (!isPhoneReady) {
            execBtn.disabled = true;
            execBtn.style.background = '#4b5563';
            execBtn.style.borderColor = '#6b7280';
            execBtn.style.color = '#d1d5db';
            execBtn.style.boxShadow = 'none';
            execBtn.style.cursor = 'not-allowed';
            execBtn.innerHTML = `<svg class="icon" viewBox="0 0 24 24" style="width: 16px; height: 16px; fill: currentColor;"><path d="M16 1H8C6.34 1 5 2.34 5 4v16c0 1.66 1.34 3 3 3h8c1.66 0 3-1.34 3-3V4c0-1.66-1.34-3-3-3zm-2 20h-4v-1h4v1zm3-3H7V4h10v14z"/></svg> <span>Connect Phone to Clean Storage</span>`;
        } else {
            execBtn.disabled = false;
            execBtn.style.background = '#10b981';
            execBtn.style.borderColor = '#059669';
            execBtn.style.color = '#ffffff';
            execBtn.style.boxShadow = '0 2px 14px rgba(16,185,129,0.35)';
            execBtn.style.cursor = 'pointer';
            execBtn.innerHTML = `<svg class="icon" viewBox="0 0 24 24" style="width: 16px; height: 16px; fill: currentColor;"><path d="M16 1H8C6.34 1 5 2.34 5 4v16c0 1.66 1.34 3 3 3h8c1.66 0 3-1.34 3-3V4c0-1.66-1.34-3-3-3zm-2 20h-4v-1h4v1zm3-3H7V4h10v14z"/></svg> <span>Confirm &amp; Clean Phone Storage (${formatBytes(includedBytes)})</span>`;
        }
    }
}

let reclaimChatFilter = 'all'; // 'all', 'archived', 'inactive', 'direct'
let reclaimChatSort = 'size';   // 'size', 'inactive', 'active', 'name', 'count'

function setReclaimChatFilter(filter, el) {
    reclaimChatFilter = filter;
    document.querySelectorAll('#reclaimChatFilterChips .sidebar-chip').forEach(c => c.classList.remove('active'));
    if (el) el.classList.add('active');
    renderReclaimChatList();
}

function setReclaimChatSort(sortVal) {
    reclaimChatSort = sortVal;
    renderReclaimChatList();
}

function renderReclaimChatList() {
    const chatListCont = document.getElementById('reclaimChatListContainer');
    const badge = document.getElementById('reclaimChatCountBadge');
    if (!chatListCont) return;

    if (!activeCleanPlan || !activeCleanPlan.breakdown || !activeCleanPlan.breakdown.by_chat) {
        if (badge) badge.innerText = '0 chats';
        chatListCont.innerHTML = '<div style="padding: 16px; font-size: 13px; color: var(--text-muted); text-align: center;">No candidate files matched your cleanup criteria.</div>';
        return;
    }

    const rawChats = activeCleanPlan.breakdown.by_chat;
    if (rawChats.length === 0) {
        if (badge) badge.innerText = '0 chats';
        chatListCont.innerHTML = '<div style="padding: 16px; font-size: 13px; color: var(--text-muted); text-align: center;">No candidate files matched your cleanup criteria. Your phone storage is already optimal for this profile.</div>';
        return;
    }

    const searchInput = document.getElementById('reclaimChatSearch');
    const query = (searchInput ? searchInput.value : '').toLowerCase().trim();

    // Filter chats by search query and category
    const filteredChats = rawChats.filter(chat => {
        const displayName = chatNameForDisplay(chat.name);
        const chatJid = chat.jid || '';
        const matchQuery = displayName.toLowerCase().includes(query) || chatJid.toLowerCase().includes(query);
        if (!matchQuery) return false;

        const isArchived = Boolean(chat.archived);
        const isGroup = Boolean(chat.is_group || chatJid.endsWith('@g.us'));
        const inactDays = Number(chat.inactivity_days || 0);

        if (reclaimChatFilter === 'archived') {
            return isArchived;
        }
        if (reclaimChatFilter === 'inactive') {
            return isGroup && inactDays >= 90;
        }
        if (reclaimChatFilter === 'direct') {
            return !isGroup;
        }
        return true;
    });

    // Sort chats
    filteredChats.sort((a, b) => {
        if (reclaimChatSort === 'size') {
            return (b.bytes || 0) - (a.bytes || 0);
        }
        if (reclaimChatSort === 'count') {
            return (b.count || 0) - (a.count || 0);
        }
        if (reclaimChatSort === 'inactive') {
            const tsA = Number(a.last_active_ts || 0);
            const tsB = Number(b.last_active_ts || 0);
            if (tsA === 0) return 1;
            if (tsB === 0) return -1;
            return tsA - tsB;
        }
        if (reclaimChatSort === 'active') {
            const tsA = Number(a.last_active_ts || 0);
            const tsB = Number(b.last_active_ts || 0);
            return tsB - tsA;
        }
        if (reclaimChatSort === 'name') {
            const nameA = chatNameForDisplay(a.name);
            const nameB = chatNameForDisplay(b.name);
            return nameA.localeCompare(nameB);
        }
        return 0;
    });

    if (badge) {
        badge.innerText = `${filteredChats.length} chat${filteredChats.length === 1 ? '' : 's'}`;
    }

    if (filteredChats.length === 0) {
        chatListCont.innerHTML = '<div style="padding: 16px; font-size: 12px; color: var(--text-muted); text-align: center;">No affected chats match this filter or search.</div>';
        return;
    }

    let itemsHtml = '';
    filteredChats.forEach(c => {
        let tags = '';
        if (c.archived) tags += ' <span style="font-size:10px;background:rgba(234,179,8,0.2);color:#fef08a;padding:1px 5px;border-radius:3px;">Archived</span>';
        if (c.inactivity_days >= 90) tags += ` <span style="font-size:10px;background:rgba(148,163,184,0.15);color:#cbd5e1;padding:1px 5px;border-radius:3px;">${Math.round(c.inactivity_days/30)}mo inactive</span>`;
        const isGroup = Boolean(c.is_group || (c.jid && c.jid.endsWith('@g.us')));
        if (!isGroup) tags += ' <span style="font-size:10px;background:rgba(59,130,246,0.15);color:#93c5fd;padding:1px 5px;border-radius:3px;">Direct</span>';

        const displayName = chatNameForDisplay(c.name);
        const isChecked = !previewExcludedChatJids.has(c.jid);
        itemsHtml += `
                    <div id="reclaimChatRow_${escapeHtml(c.jid)}" style="display: flex; justify-content: space-between; align-items: center; padding: 6px 8px; border-bottom: 1px solid rgba(255,255,255,0.05); font-size: 12px; transition: opacity 0.15s ease; opacity: ${isChecked ? '1' : '0.5'};">
                        <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; flex: 1; overflow: hidden; margin: 0;">
                            <input type="checkbox" class="reclaim-chat-cb" data-jid="${escapeHtml(c.jid)}" ${isChecked ? 'checked' : ''} onchange="togglePreviewChat('${escapeJsAttr(c.jid)}', this.checked)" style="width: 15px; height: 15px; cursor: pointer; accent-color: var(--accent); flex-shrink: 0;">
                            <div style="display: flex; align-items: center; gap: 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                                <span style="font-weight: 500; color: var(--text-primary);">${escapeHtml(displayName)}</span>
                                ${tags}
                                <span class="reclaim-row-excl-tag" style="font-size:10px;background:rgba(239,68,68,0.15);color:#fca5a5;padding:1px 5px;border-radius:3px;display:${isChecked ? 'none' : 'inline'};">Excluded</span>
                            </div>
                        </label>
                        <div style="text-align: right; color: var(--text-muted); font-size: 11px; white-space: nowrap; margin-left: 8px;">
                            <strong class="reclaim-row-size" style="color: ${isChecked ? '#4ade80' : 'var(--text-muted)'};">${formatBytes(c.bytes)}</strong> (${c.count} file${c.count === 1 ? '' : 's'})
                        </div>
                    </div>
                `;
    });
    chatListCont.innerHTML = itemsHtml;
}

function renderCleanPlanPreview(plan) {
    if (!plan) return;
    resetPreviewChatExclusions();
    const savingsEl = document.getElementById('reclaimMetricSavings');
    const filesEl = document.getElementById('reclaimMetricFiles');
    const protEl = document.getElementById('reclaimMetricProtected');
    if (savingsEl) savingsEl.innerText = formatBytes(plan.reclaimable_bytes);
    if (filesEl) filesEl.innerText = (plan.reclaimable_files_count || 0).toLocaleString();
    if (protEl) protEl.innerText = (plan.protected_files_count || 0).toLocaleString();

    // Disconnected phone banner
    const warnBanner = document.getElementById('reclaimDisconnectedWarningBanner');
    if (warnBanner) {
        warnBanner.style.display = window._isPhoneConnectedForClean ? 'none' : 'flex';
    }

    const pillsContainer = document.getElementById('reclaimReasonPills');
    if (pillsContainer && plan.breakdown && plan.breakdown.by_reason) {
        let pillsHtml = '';
        const reasons = plan.breakdown.by_reason;
        if (reasons.archived_chats && reasons.archived_chats.count > 0) {
            pillsHtml += `<span class="badge-pill" style="background: rgba(234,179,8,0.15); color: #fef08a; padding: 4px 10px; font-size: 11px;">Archived Chats: ${formatBytes(reasons.archived_chats.bytes)} (${reasons.archived_chats.count} files)</span>`;
        }
        if (reasons.inactive_groups && reasons.inactive_groups.count > 0) {
            pillsHtml += `<span class="badge-pill" style="background: rgba(148,163,184,0.15); color: #cbd5e1; padding: 4px 10px; font-size: 11px;">Inactive Groups: ${formatBytes(reasons.inactive_groups.bytes)} (${reasons.inactive_groups.count} files)</span>`;
        }
        if (reasons.large_videos && reasons.large_videos.count > 0) {
            pillsHtml += `<span class="badge-pill" style="background: rgba(59,130,246,0.15); color: #93c5fd; padding: 4px 10px; font-size: 11px;">Large Videos: ${formatBytes(reasons.large_videos.bytes)} (${reasons.large_videos.count} files)</span>`;
        }
        if (reasons.aged_videos && reasons.aged_videos.count > 0) {
            pillsHtml += `<span class="badge-pill" style="background: rgba(59,130,246,0.15); color: #93c5fd; padding: 4px 10px; font-size: 11px;">Aged Videos: ${formatBytes(reasons.aged_videos.bytes)} (${reasons.aged_videos.count} files)</span>`;
        }
        if (reasons.custom_selection && reasons.custom_selection.count > 0) {
            pillsHtml += `<span class="badge-pill" style="background: rgba(168,85,247,0.15); color: #d8b4fe; padding: 4px 10px; font-size: 11px;">Target Chats: ${formatBytes(reasons.custom_selection.bytes)} (${reasons.custom_selection.count} files)</span>`;
        }
        pillsContainer.innerHTML = pillsHtml || '<span style="font-size:12px;color:var(--text-muted);">No candidates matched the selected filters.</span>';
    }

    renderReclaimChatList();
    recalculatePreviewMetrics();
}

async function cancelCleanPlanExecution() {
    const btn = document.getElementById('btnCancelCleanPurge');
    if (btn) {
        btn.disabled = true;
        btn.innerText = 'Cancelling...';
    }
    try {
        showToast('Cancelling phone storage cleanup...', 'info');
        await fetch('/api/clean/cancel', { method: 'POST' });
    } catch (e) {
        showToast('Error requesting cleanup cancellation: ' + e.message, 'error');
    }
}

async function confirmAndExecuteCleanPlan() {
    if (!activeCleanPlan || !activeCleanPlan.plan_id) return;
    const allChats = (activeCleanPlan.breakdown && activeCleanPlan.breakdown.by_chat) || [];
    let activeFilesCount = 0;
    let activeBytes = 0;
    let includedChatsCount = 0;
    allChats.forEach(c => {
        if (!previewExcludedChatJids.has(c.jid)) {
            activeFilesCount += (c.count || 0);
            activeBytes += (c.bytes || 0);
            includedChatsCount += 1;
        }
    });

    if (activeFilesCount === 0) {
        showToast('No files selected to clean. Please select at least one chat.', 'info');
        return;
    }

    if (!window._isPhoneConnectedForClean) {
        showToast('Please connect your Android phone via USB cable to execute cleanup.', 'warning');
        openDeviceModal();
        return;
    }

    const bytesStr = formatBytes(activeBytes);
    const excludedCount = previewExcludedChatJids.size;
    const excludedNote = excludedCount > 0 ? ` (${excludedCount} chat${excludedCount === 1 ? '' : 's'} excluded)` : '';

    if (!confirm(`Are you sure you want to clean ${activeFilesCount} verified files (${bytesStr}) across ${includedChatsCount} chat(s) from your phone storage?${excludedNote}\n\nReminder: Your local PC backup will remain 100% intact.`)) {
        return;
    }

    showReclaimStep('progress');
    const spinner = document.getElementById('reclaimExecutionSpinner');
    const title = document.getElementById('reclaimProgressTitle');
    const subtitle = document.getElementById('reclaimProgressSubtitle');
    const bar = document.getElementById('reclaimExecutionProgressBar');
    const txt = document.getElementById('reclaimExecutionProgressText');
    const runningActions = document.getElementById('reclaimProgressRunningActions');
    const doneActions = document.getElementById('reclaimProgressDoneActions');
    const btnReconnect = document.getElementById('btnReclaimReconnect');
    const cancelPurgeBtn = document.getElementById('btnCancelCleanPurge');

    if (spinner) spinner.style.display = 'block';
    if (title) title.innerText = 'Purging Files from Phone...';
    if (subtitle) subtitle.innerText = `Safely deleting ${activeFilesCount} files from phone over USB...`;
    if (bar) {
        bar.style.width = '60%';
        bar.style.background = 'linear-gradient(90deg, #00a884, #10b981)';
    }
    if (txt) txt.innerText = 'Executing batch deletion commands...';
    if (runningActions) runningActions.style.display = 'block';
    if (cancelPurgeBtn) {
        cancelPurgeBtn.disabled = false;
        cancelPurgeBtn.innerText = 'Cancel Cleanup';
    }
    if (doneActions) doneActions.style.display = 'none';
    if (btnReconnect) btnReconnect.style.display = 'none';

    try {
        const res = await trackedFetch('phone-cleanup', '/api/clean/execute', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                plan_id: activeCleanPlan.plan_id,
                exclude_jids: Array.from(previewExcludedChatJids)
            })
        });
        const result = await res.json().catch(() => ({}));
        if (spinner) spinner.style.display = 'none';
        if (runningActions) runningActions.style.display = 'none';

        if (res.ok && result.success) {
            if (title) title.innerText = 'Phone Storage Successfully Cleaned!';
            if (subtitle) subtitle.innerText = `Freed ${result.freed_mb || 0} MB across ${result.deleted_count || activeFilesCount} files on your phone.`;
            if (bar) bar.style.width = '100%';
            if (txt) txt.innerText = 'All targeted files removed from device. PC backup is 100% safe.';
            if (doneActions) doneActions.style.display = 'flex';
            loadPhoneStorageInfo();
            showToast(`Successfully reclaimed ${result.freed_mb || 0} MB on phone!`, 'success');
        } else {
            const errMsg = result.message || (result.errors && result.errors[0]) || 'An error occurred during deletion.';
            const isDisconnect = errMsg.toLowerCase().includes('disconnected') || errMsg.toLowerCase().includes('not connected');
            const isCancelled = errMsg.toLowerCase().includes('cancel');
            if (isCancelled) {
                if (title) title.innerText = 'Cleanup Cancelled by User';
                if (subtitle) subtitle.innerText = `Safely stopped deletion after ${result.deleted_count || 0} files. PC backup is 100% safe.`;
                if (bar) {
                    bar.style.width = '100%';
                    bar.style.background = '#eab308';
                }
                if (txt) txt.innerText = `Deleted ${result.deleted_count || 0} of ${activeFilesCount} files before cancellation.`;
                if (doneActions) doneActions.style.display = 'flex';
                showToast(`Cleanup cancelled: ${result.deleted_count || 0} files deleted.`, 'info');
            } else {
                if (title) title.innerText = isDisconnect ? 'Phone Disconnected During Cleanup' : 'Deletion Incomplete or Interrupted';
                if (subtitle) subtitle.innerText = errMsg;
                if (bar) {
                    bar.style.width = '100%';
                    bar.style.background = '#ef4444';
                }
                if (txt) txt.innerText = `Deleted ${result.deleted_count || 0} of ${activeFilesCount} files before interruption.`;
                if (doneActions) doneActions.style.display = 'flex';
                if (btnReconnect && isDisconnect) btnReconnect.style.display = 'inline-flex';
                showToast('Cleanup interrupted: ' + errMsg, 'error');
            }
        }
    } catch (err) {
        if (spinner) spinner.style.display = 'none';
        if (runningActions) runningActions.style.display = 'none';
        if (title) title.innerText = 'Network / Connection Error';
        if (subtitle) subtitle.innerText = err.message;
        if (doneActions) doneActions.style.display = 'flex';
        showToast('Network error during cleanup: ' + err.message, 'error');
    }
}
