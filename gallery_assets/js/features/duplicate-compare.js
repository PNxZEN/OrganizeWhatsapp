/* Fullscreen duplicate comparison viewer
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

// FULLSCREEN DUPLICATE COMPARISON CONTROLLER
window._dupCmpActiveGroupIdx = 0;
window._dupCmpActiveDupIdx = 0;
window._dupCmpMode = 'split';
window._dupCmpBlinkState = 0;

function openDuplicateCompareFullscreen(grpIdx, dupIdx) {
    window._dupCmpActiveGroupIdx = parseInt(grpIdx, 10) || 0;
    window._dupCmpActiveDupIdx = parseInt(dupIdx, 10) || 0;
    window._dupCmpBlinkState = 0;
    updateDupUndoButtonUI();
    renderDupCompareLightbox();

    const lb = document.getElementById('lightboxDupCompare');
    if (lb) {
        lb.style.display = 'flex';
        lb.focus();
    }
    window.addEventListener('keydown', handleDupCompareKeydown);
}

function closeDuplicateCompareLightbox() {
    const lb = document.getElementById('lightboxDupCompare');
    if (lb) lb.style.display = 'none';
    closeDupPairDropdown();
    window.removeEventListener('keydown', handleDupCompareKeydown);
    renderDuplicateReviewContent();
    updateIgnoredTabCount();
}

function renderDupCompareLightbox() {
    const pairs = getFlattenedDupPairs();
    const total = pairs.length;
    if (total === 0) {
        closeDuplicateCompareLightbox();
        return;
    }

    let pairIndex = pairs.findIndex(p => p.grpIdx === window._dupCmpActiveGroupIdx && p.dupIdx === window._dupCmpActiveDupIdx);
    if (pairIndex === -1) {
        pairIndex = 0;
        window._dupCmpActiveGroupIdx = pairs[0].grpIdx;
        window._dupCmpActiveDupIdx = pairs[0].dupIdx;
    }

    const current = pairs[pairIndex];
    const primary = current.primary;
    const dup = current.dup;

    const curIdxEl = document.getElementById('dupCmpCurrentIdx');
    const totalCountEl = document.getElementById('dupCmpTotalCount');
    if (curIdxEl) curIdxEl.innerText = (pairIndex + 1);
    if (totalCountEl) totalCountEl.innerText = total;

    const dd = document.getElementById('dupCmpPairDropdown');
    if (dd && dd.style.display !== 'none') {
        renderDupPairDropdown();
    }

    const btnPrev = document.getElementById('btnDupCmpPrev');
    const btnNext = document.getElementById('btnDupCmpNext');
    if (btnPrev) btnPrev.disabled = (pairIndex === 0);
    if (btnNext) btnNext.disabled = (pairIndex === total - 1);

    const badgeEl = document.getElementById('dupCmpReasonBadge');
    let reasonLabel = 'SD Compression Copy';
    let badgeClass = 'badge-quality';
    const dupReason = (dup.duplicate_reason || (window._currentChatDupInfo && window._currentChatDupInfo[dup.rel_path || dup.filename]?.reason) || 'quality');
    const dupFn = (dup.filename || '').toLowerCase();
    if (dupFn.startsWith('stk-') || dup.mime_type === 'image/webp') {
        reasonLabel = 'Sticker Copy';
        badgeClass = 'badge-sticker';
    } else if (dupReason === 'exact') {
        reasonLabel = 'Exact Byte Copy';
        badgeClass = 'badge-exact';
    } else if (dupReason === 'perceptual') {
        reasonLabel = 'Visual Match';
        badgeClass = 'badge-perceptual';
    }
    if (badgeEl) {
        badgeEl.innerText = reasonLabel;
        badgeEl.className = `dup-reason-badge ${badgeClass}`;
    }

    const primaryDirect = (primary.rel_path || '').split('/').map(seg => encodeURIComponent(seg)).join('/');
    const dupDirect = (dup.rel_path || '').split('/').map(seg => encodeURIComponent(seg)).join('/');
    const primaryUrl = isHttpServer ? ('/api/media?path=' + encodeURIComponent(primary.rel_path)) : primaryDirect;
    const dupUrl = isHttpServer ? ('/api/media?path=' + encodeURIComponent(dup.rel_path)) : dupDirect;

    const wrapK = document.getElementById('dupWrapKeeper');
    const wrapD = document.getElementById('dupWrapDup');
    if (wrapK) wrapK.classList.remove('zoomed');
    if (wrapD) wrapD.classList.remove('zoomed');

    if (wrapK) {
        if (isImageItem(primary)) {
            wrapK.innerHTML = `<img id="dupImgKeeper" src="${escapeHtml(primaryUrl)}" alt="Keeper Image">`;
            const imgKeeper = document.getElementById('dupImgKeeper');
            if (imgKeeper) {
                imgKeeper.onerror = function() {
                    if (this.src !== primaryDirect && !this.dataset.fallbackTried) {
                        this.dataset.fallbackTried = '1';
                        this.src = primaryDirect;
                    }
                };
            }
        } else {
            const mime = primary.mime_type || 'video/mp4';
            const kVidSrc = primary.preview_path ? getMediaUrl(primary.preview_path) : primaryUrl;
            wrapK.innerHTML = `<video id="dupVidKeeper" controls preload="auto" style="max-width:100%;max-height:100%;object-fit:contain;border-radius:8px;"><source src="${escapeHtml(kVidSrc)}" type="${escapeHtml(mime)}"></video>`;
        }
    }

    if (wrapD) {
        if (isImageItem(dup)) {
            wrapD.innerHTML = `<img id="dupImgDup" src="${escapeHtml(dupUrl)}" alt="Duplicate Image">`;
            const imgDup = document.getElementById('dupImgDup');
            if (imgDup) {
                imgDup.onerror = function() {
                    if (this.src !== dupDirect && !this.dataset.fallbackTried) {
                        this.dataset.fallbackTried = '1';
                        this.src = dupDirect;
                    }
                };
            }
        } else {
            const mime = dup.mime_type || 'video/mp4';
            const dVidSrc = dup.preview_path ? getMediaUrl(dup.preview_path) : dupUrl;
            wrapD.innerHTML = `<video id="dupVidDup" controls preload="auto" style="max-width:100%;max-height:100%;object-fit:contain;border-radius:8px;"><source src="${escapeHtml(dVidSrc)}" type="${escapeHtml(mime)}"></video>`;
        }
    }

    // Side-by-side synchronized video playback for comparison
    const vidK = document.getElementById('dupVidKeeper');
    const vidD = document.getElementById('dupVidDup');
    if (vidK && vidD) {
        let syncing = false;
        vidK.onplay = () => { if (!syncing && vidD.paused) { syncing = true; vidD.play().catch(() => {}); syncing = false; } };
        vidK.onpause = () => { if (!syncing && !vidD.paused) { syncing = true; vidD.pause(); syncing = false; } };
        vidK.onseeked = () => { if (!syncing) { syncing = true; vidD.currentTime = vidK.currentTime; syncing = false; } };
        vidD.onplay = () => { if (!syncing && vidK.paused) { syncing = true; vidK.play().catch(() => {}); syncing = false; } };
        vidD.onpause = () => { if (!syncing && !vidK.paused) { syncing = true; vidK.pause(); syncing = false; } };
        vidD.onseeked = () => { if (!syncing) { syncing = true; vidK.currentTime = vidD.currentTime; syncing = false; } };
    }

    const metaKRes = document.getElementById('dupMetaKeeperRes');
    const metaKSize = document.getElementById('dupMetaKeeperSize');
    const metaKDate = document.getElementById('dupMetaKeeperDate');
    const metaKFn = document.getElementById('dupMetaKeeperFilename');

    if (metaKRes) resolveAndDisplayImageDims(primary, 'dupMetaKeeperRes');
    if (metaKSize) metaKSize.innerText = formatBytes(primary.size_bytes || 0);
    if (metaKDate) metaKDate.innerText = formatDateTime(primary.received_at, primary.rel_path);
    if (metaKFn) {
        metaKFn.innerText = primary.filename;
        metaKFn.title = primary.filename;
    }

    const metaDRes = document.getElementById('dupMetaDupRes');
    const metaDSize = document.getElementById('dupMetaDupSize');
    const metaDDate = document.getElementById('dupMetaDupDate');
    const metaDFn = document.getElementById('dupMetaDupFilename');
    const freesBadge = document.getElementById('dupCmpFreesBadge');

    if (metaDRes) resolveAndDisplayImageDims(dup, 'dupMetaDupRes');
    const szDiff = (primary.size_bytes && dup.size_bytes && primary.size_bytes > dup.size_bytes)
        ? ` (-${Math.round((1 - dup.size_bytes / primary.size_bytes) * 100)}%)`
        : '';
    if (metaDSize) metaDSize.innerText = `${formatBytes(dup.size_bytes || 0)}${szDiff}`;
    if (metaDDate) metaDDate.innerText = formatDateTime(dup.received_at, dup.rel_path);
    if (metaDFn) {
        metaDFn.innerText = dup.filename;
        metaDFn.title = dup.filename;
    }
    if (freesBadge) {
        freesBadge.innerText = `Frees ${formatBytes(dup.size_bytes || 0)}`;
    }

    updateBlinkDisplay(current);
}

function setDupCompareMode(mode) {
    window._dupCmpMode = mode;
    const splitCont = document.getElementById('dupCmpSplitContainer');
    const blinkCont = document.getElementById('dupCmpBlinkContainer');
    const btnSplit = document.getElementById('btnDupModeSplit');
    const btnBlink = document.getElementById('btnDupModeBlink');

    if (mode === 'split') {
        if (splitCont) splitCont.style.display = 'flex';
        if (blinkCont) blinkCont.style.display = 'none';
        if (btnSplit) btnSplit.classList.add('active');
        if (btnBlink) btnBlink.classList.remove('active');
    } else {
        if (splitCont) splitCont.style.display = 'none';
        if (blinkCont) blinkCont.style.display = 'flex';
        if (btnSplit) btnSplit.classList.remove('active');
        if (btnBlink) btnBlink.classList.add('active');
        updateBlinkDisplay();
    }
}

function updateBlinkDisplay(pair) {
    const badge = document.getElementById('dupBlinkBadge');
    const badgeText = document.getElementById('dupBlinkBadgeText');
    const dot = document.getElementById('dupBlinkIndicatorDot');
    const metaInfo = document.getElementById('dupBlinkMetaInfo');

    if (!pair) {
        const pairs = getFlattenedDupPairs();
        pair = pairs.find(p => p.grpIdx === window._dupCmpActiveGroupIdx && p.dupIdx === window._dupCmpActiveDupIdx) || pairs[0];
    }
    if (!pair) return;

    const primary = pair.primary;
    const dup = pair.dup;

    const targetItem = (window._dupCmpBlinkState === 0 ? primary : dup);
    const targetDirect = (targetItem.rel_path || '').split('/').map(seg => encodeURIComponent(seg)).join('/');
    const targetUrl = isHttpServer ? ('/api/media?path=' + encodeURIComponent(targetItem.rel_path)) : targetDirect;

    const blinkStage = document.querySelector('.dup-blink-stage');
    if (blinkStage) {
        if (isImageItem(targetItem)) {
            blinkStage.innerHTML = `<img id="dupImgBlink" src="${escapeHtml(targetUrl)}" alt="Blink comparison">`;
            const imgBlink = document.getElementById('dupImgBlink');
            if (imgBlink) {
                imgBlink.onerror = function() {
                    if (this.src !== targetDirect && !this.dataset.fallbackTried) {
                        this.dataset.fallbackTried = '1';
                        this.src = targetDirect;
                    }
                };
            }
        } else {
            const mime = targetItem.mime_type || 'video/mp4';
            blinkStage.innerHTML = `<video controls autoplay muted loop style="max-width:100%;max-height:100%;object-fit:contain;border-radius:8px;"><source src="${escapeHtml(targetUrl)}" type="${escapeHtml(mime)}"></video>`;
        }
    }

    if (window._dupCmpBlinkState === 0) {
        if (badge) {
            badge.style.background = 'rgba(34,197,94,0.2)';
            badge.style.color = '#4ade80';
            badge.style.borderColor = 'rgba(34,197,94,0.4)';
        }
        if (dot) dot.style.background = '#4ade80';
        if (badgeText) badgeText.innerText = 'Viewing: KEEPER (Original / HD)';
        if (metaInfo) metaInfo.innerText = `${primary.filename} (${formatBytes(primary.size_bytes || 0)})`;
    } else {
        if (badge) {
            badge.style.background = 'rgba(239,68,68,0.2)';
            badge.style.color = '#f87171';
            badge.style.borderColor = 'rgba(239,68,68,0.4)';
        }
        if (dot) dot.style.background = '#f87171';
        if (badgeText) badgeText.innerText = 'Viewing: DUPLICATE (SD / Candidate)';
        if (metaInfo) metaInfo.innerText = `${dup.filename} (${formatBytes(dup.size_bytes || 0)})`;
    }
}

function toggleDupBlinkState() {
    window._dupCmpBlinkState = 1 - window._dupCmpBlinkState;
    updateBlinkDisplay();
}

function toggleZoomDupSide(wrapId) {
    const wrap = document.getElementById(wrapId);
    if (wrap) wrap.classList.toggle('zoomed');
}

function navigateDupCompare(delta) {
    const pairs = getFlattenedDupPairs();
    if (pairs.length === 0) return;
    let pairIndex = pairs.findIndex(p => p.grpIdx === window._dupCmpActiveGroupIdx && p.dupIdx === window._dupCmpActiveDupIdx);
    if (pairIndex === -1) pairIndex = 0;
    const newIndex = pairIndex + delta;
    if (newIndex >= 0 && newIndex < pairs.length) {
        window._dupCmpActiveGroupIdx = pairs[newIndex].grpIdx;
        window._dupCmpActiveDupIdx = pairs[newIndex].dupIdx;
        renderDupCompareLightbox();
    }
}

function dismissCurrentDupPair() {
    const pairs = getFlattenedDupPairs();
    const pairIndex = pairs.findIndex(p => p.grpIdx === window._dupCmpActiveGroupIdx && p.dupIdx === window._dupCmpActiveDupIdx);
    if (pairIndex === -1) return;
    const pair = pairs[pairIndex];
    dismissDuplicatePair(pair.grpIdx, pair.dupIdx);
    const remaining = getFlattenedDupPairs();
    if (remaining.length === 0) {
        closeDuplicateCompareLightbox();
        closeModal('modalDuplicateReview');
        showToast('All duplicate pairs reviewed!', 'success');
    } else {
        const nextIdx = Math.min(pairIndex, remaining.length - 1);
        window._dupCmpActiveGroupIdx = remaining[nextIdx].grpIdx;
        window._dupCmpActiveDupIdx = remaining[nextIdx].dupIdx;
        renderDupCompareLightbox();
    }
}

function swapCurrentDupPair() {
    const pairs = getFlattenedDupPairs();
    const pairIndex = pairs.findIndex(p => p.grpIdx === window._dupCmpActiveGroupIdx && p.dupIdx === window._dupCmpActiveDupIdx);
    if (pairIndex === -1) return;
    const pair = pairs[pairIndex];
    const keeperBefore = pair.primary;
    const dupBefore = pair.dup;

    swapDuplicateKeeper(pair.grpIdx, pair.dupIdx);
    const updatedPairs = getFlattenedDupPairs();
    const newPairIdx = updatedPairs.findIndex(p =>
        p.primary && (p.primary.rel_path === dupBefore.rel_path || p.primary.filename === dupBefore.filename) &&
        p.dup && (p.dup.rel_path === keeperBefore.rel_path || p.dup.filename === keeperBefore.filename)
    );
    if (newPairIdx !== -1) {
        window._dupCmpActiveGroupIdx = updatedPairs[newPairIdx].grpIdx;
        window._dupCmpActiveDupIdx = updatedPairs[newPairIdx].dupIdx;
    } else if (updatedPairs[pairIndex]) {
        window._dupCmpActiveGroupIdx = updatedPairs[pairIndex].grpIdx;
        window._dupCmpActiveDupIdx = updatedPairs[pairIndex].dupIdx;
    }
    renderDupCompareLightbox();
}

async function recycleCurrentDupDirectly() {
    if (!isHttpServer) {
        showToast('Launch gallery via start_gallery.bat for Recycle Bin features.', 'info');
        return;
    }
    const pairs = getFlattenedDupPairs();
    const pairIndex = pairs.findIndex(p => p.grpIdx === window._dupCmpActiveGroupIdx && p.dupIdx === window._dupCmpActiveDupIdx);
    if (pairIndex === -1) return;
    const pair = pairs[pairIndex];

    const dup = pair.dup;
    const btn = document.getElementById('btnCmpRecycleThis');
    const btnText = document.getElementById('btnCmpRecycleThisText');
    if (btn) btn.disabled = true;
    if (btnText) btnText.innerText = 'Recycling...';

    try {
        const resp = await fetch('/api/duplicates/recycle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rel_paths: [dup.rel_path] })
        });
        const res = await resp.json();
        if (resp.ok && res.status === 'success') {
            showToast(`Moved ${dup.filename} to Recycle Bin (freed ${formatBytes(dup.size_bytes || 0)}).`, 'success');

            if (activeChat && activeChat.media) {
                activeChat.media = activeChat.media.filter(m => m.rel_path !== dup.rel_path);
                activeChat.file_count = activeChat.media.length;
                activeChat.total_size = Math.max(0, (activeChat.total_size || 0) - (dup.size_bytes || 0));
                const metaEl = document.getElementById('currentChatMeta');
                if (metaEl) metaEl.innerText = `${activeChat.file_count} files • Total storage: ${formatBytes(activeChat.total_size)}`;
            }

            const grp = pair.grp;
            grp.duplicates.splice(pair.dupIdx, 1);
            if (grp.duplicates.length === 0) {
                const groups = window._currentChatDuplicateGroups || [];
                groups.splice(pair.grpIdx, 1);
            }
            if (window._currentChatDupSet) {
                window._currentChatDupSet.delete(dup.rel_path);
                window._currentChatDupSet.delete(dup.filename);
            }

            if (activeChat) activeChat._dupCache = null;
            renderSidebar();
            filterAndRenderMedia({ preserveScroll: true, keepItemsCount: true });
            updateDuplicateReviewButtonUI();
            updateRecycleBinPill();
            updateRecycleModalStats();

            const remPairs = getFlattenedDupPairs();
            if (remPairs.length === 0) {
                closeDuplicateCompareLightbox();
                closeModal('modalDuplicateReview');
                showToast('All duplicate pairs reviewed!', 'success');
            } else {
                const nextIdx = Math.min(pairIndex, remPairs.length - 1);
                window._dupCmpActiveGroupIdx = remPairs[nextIdx].grpIdx;
                window._dupCmpActiveDupIdx = remPairs[nextIdx].dupIdx;
                renderDupCompareLightbox();
            }
        } else {
            showToast(res.message || 'Recycle failed.', 'error');
        }
    } catch (e) {
        showToast(`Recycle error: ${e.message}`, 'error');
    } finally {
        if (btn) btn.disabled = false;
        if (btnText) btnText.innerText = 'Move Duplicate to Recycle Bin';
    }
}

function toggleDupPairDropdown(e) {
    if (e) {
        e.stopPropagation();
        e.preventDefault();
    }
    const dd = document.getElementById('dupCmpPairDropdown');
    if (!dd) return;
    if (dd.style.display === 'none' || dd.style.display === '') {
        renderDupPairDropdown();
        dd.style.display = 'flex';
        setTimeout(() => {
            const activeItem = dd.querySelector('.dup-pair-dropdown-item.active');
            if (activeItem) {
                activeItem.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
            }
        }, 50);
    } else {
        closeDupPairDropdown();
    }
}

function closeDupPairDropdown(e) {
    if (e) {
        e.stopPropagation();
    }
    const dd = document.getElementById('dupCmpPairDropdown');
    if (dd) dd.style.display = 'none';
}

function renderDupPairDropdown() {
    const listEl = document.getElementById('dupCmpPairDropdownList');
    const countEl = document.getElementById('dupDropdownCount');
    if (!listEl) return;
    const pairs = getFlattenedDupPairs();
    if (countEl) countEl.innerText = pairs.length;
    if (pairs.length === 0) {
        listEl.innerHTML = '<div style="padding:16px;text-align:center;color:var(--text-muted);font-size:12px;">No duplicate pairs</div>';
        return;
    }

    let html = '';
    pairs.forEach((p, idx) => {
        const isActive = (p.grpIdx === window._dupCmpActiveGroupIdx && p.dupIdx === window._dupCmpActiveDupIdx);
        const primary = p.primary;
        const dup = p.dup;

        const primaryDirect = (primary.rel_path || '').split('/').map(seg => encodeURIComponent(seg)).join('/');
        const dupDirect = (dup.rel_path || '').split('/').map(seg => encodeURIComponent(seg)).join('/');
        const primaryUrl = isHttpServer ? ('/api/media?path=' + encodeURIComponent(primary.rel_path)) : primaryDirect;
        const dupUrl = isHttpServer ? ('/api/media?path=' + encodeURIComponent(dup.rel_path)) : dupDirect;

        const dupFn = (dup.filename || '').toLowerCase();
        let reasonTag = 'SD Copy';
        const dupReason = (dup.duplicate_reason || (window._currentChatDupInfo && window._currentChatDupInfo[dup.rel_path || dup.filename]?.reason) || 'quality');
        if (dupFn.startsWith('stk-') || dup.mime_type === 'image/webp') {
            reasonTag = 'Sticker';
        } else if (dupReason === 'exact') {
            reasonTag = 'Exact';
        } else if (dupReason === 'perceptual') {
            reasonTag = 'Visual';
        }

        const sizeDiff = (primary.size_bytes && dup.size_bytes && primary.size_bytes > dup.size_bytes)
            ? `-${Math.round((1 - dup.size_bytes / primary.size_bytes) * 100)}%`
            : formatBytes(dup.size_bytes || 0);

        html += `
                    <div class="dup-pair-dropdown-item ${isActive ? 'active' : ''}" onclick="jumpToDupPair(${idx})">
                        <span class="dup-pair-dropdown-num">#${idx + 1}</span>
                        <div class="dup-pair-dropdown-thumbs">
                            <img class="dup-pair-dropdown-thumb" src="${escapeHtml(primaryUrl)}" alt="Keeper" title="Keeper: ${escapeHtml(primary.filename)}" onerror="this.onerror=null; this.src='${escapeJsAttr(primaryDirect)}'">
                            <img class="dup-pair-dropdown-thumb" src="${escapeHtml(dupUrl)}" alt="Duplicate" title="Duplicate: ${escapeHtml(dup.filename)}" onerror="this.onerror=null; this.src='${escapeJsAttr(dupDirect)}'">
                        </div>
                        <div class="dup-pair-dropdown-info">
                            <div class="dup-pair-dropdown-title" title="${escapeHtml(dup.filename)}">${escapeHtml(dup.filename)}</div>
                            <div class="dup-pair-dropdown-sub">
                                <span style="color:#f87171;font-weight:600;">Frees ${sizeDiff}</span>
                                <span>:</span>
                                <span>${reasonTag}</span>
                            </div>
                        </div>
                    </div>
                `;
    });
    listEl.innerHTML = html;
}

function jumpToDupPair(pairIndex) {
    const pairs = getFlattenedDupPairs();
    if (pairIndex >= 0 && pairIndex < pairs.length) {
        window._dupCmpActiveGroupIdx = pairs[pairIndex].grpIdx;
        window._dupCmpActiveDupIdx = pairs[pairIndex].dupIdx;
        renderDupCompareLightbox();
    }
    closeDupPairDropdown();
}

document.addEventListener('click', function(e) {
    const wrapper = document.getElementById('dupCmpPairDropdownWrapper');
    if (wrapper && !wrapper.contains(e.target)) {
        closeDupPairDropdown();
    }
});

function handleDupCompareKeydown(e) {
    const lb = document.getElementById('lightboxDupCompare');
    if (!lb || lb.style.display === 'none') return;

    if (e.key === 'Escape') {
        e.preventDefault();
        const dd = document.getElementById('dupCmpPairDropdown');
        if (dd && dd.style.display !== 'none') {
            closeDupPairDropdown();
            return;
        }
        closeDuplicateCompareLightbox();
    } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        navigateDupCompare(-1);
    } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        navigateDupCompare(1);
    } else if (e.key === 'Tab' || e.key === 'b' || e.key === 'B' || e.key === '1') {
        e.preventDefault();
        setDupCompareMode(window._dupCmpMode === 'split' ? 'blink' : 'split');
    } else if (e.key === '2') {
        e.preventDefault();
        setDupCompareMode('blink');
    } else if (e.code === 'Space') {
        e.preventDefault();
        if (window._dupCmpMode !== 'blink') {
            setDupCompareMode('blink');
        } else {
            toggleDupBlinkState();
        }
    } else if (e.key === 'l' || e.key === 'L') {
        e.preventDefault();
        switchToListReviewView();
    } else if ((e.ctrlKey || e.metaKey) && (e.key === 'z' || e.key === 'Z')) {
        e.preventDefault();
        undoDismissDuplicate();
    } else if (e.key === 'k' || e.key === 'K') {
        e.preventDefault();
        dismissCurrentDupPair();
    } else if (e.key === 's' || e.key === 'S') {
        e.preventDefault();
        swapCurrentDupPair();
    } else if (e.key === 'r' || e.key === 'R' || e.key === 'Enter') {
        e.preventDefault();
        recycleCurrentDupDirectly();
    }
}

function switchToListReviewView() {
    closeDuplicateCompareLightbox();
    openModal('modalDuplicateReview');
    switchDuplicateTab('review');
}

function switchToCompareView() {
    closeModal('modalDuplicateReview');
    const pairs = getFlattenedDupPairs();
    if (pairs && pairs.length > 0) {
        openDuplicateCompareFullscreen(pairs[0].grpIdx, pairs[0].dupIdx);
    } else {
        showToast('No duplicates to compare in this chat.', 'info');
    }
}
