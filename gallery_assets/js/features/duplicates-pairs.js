/* Duplicate pair list rendering, dismiss and swap
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

function renderDuplicateReviewContent() {
    const container = document.getElementById('dupCompareList');
    if (!container) return;

    updateIgnoredTabCount();

    const groups = window._currentChatDuplicateGroups || [];
    const dupSet = window._currentChatDupSet || new Set();

    const tabCountEl = document.getElementById('dupTabCount');
    if (tabCountEl) tabCountEl.innerText = dupSet.size;

    if (groups.length === 0 || dupSet.size === 0) {
        container.innerHTML = `
                    <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:240px;color:var(--text-muted);gap:12px;text-align:center;">
                        <svg viewBox="0 0 24 24" style="width:42px;height:42px;fill:currentColor;opacity:0.4;"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>
                        <div style="font-size:15px;font-weight:600;color:var(--text-primary);">No Duplicates in This Chat</div>
                        <div style="font-size:13px;max-width:360px;">All media files in this conversation are unique. No redundant copies were detected.</div>
                    </div>
                `;
        document.getElementById('dupMetricCount').innerText = '0';
        document.getElementById('dupMetricSavings').innerText = '0 B';
        document.getElementById('dupMetricPreserved').innerText = '0';
        document.getElementById('btnExecuteRecycle').disabled = true;
        document.getElementById('btnExecuteRecycleText').innerText = 'Move Selected to Recycle Bin (0 B)';
        return;
    }

    let totalSavings = 0;
    let totalDups = 0;
    let html = '';
    const dimMeasurements = [];

    groups.forEach((grp, grpIdx) => {
        const primary = grp.primary;
        const dups = grp.duplicates;
        totalDups += dups.length;

        const primaryThumb = isHttpServer 
            ? ('/api/thumbnail?path=' + encodeURIComponent(primary.rel_path)) 
            : encodePathForUrl(primary.thumb_path || primary.rel_path);

        dups.forEach((dup, dupIdx) => {
            totalSavings += (dup.size_bytes || 0);
            const dupThumb = isHttpServer 
                ? ('/api/thumbnail?path=' + encodeURIComponent(dup.rel_path)) 
                : encodePathForUrl(dup.thumb_path || dup.rel_path);

            let reasonLabel = 'SD Compression Pair';
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
            } else if (dupReason === 'collision') {
                reasonLabel = 'Filename Collision';
                badgeClass = 'badge-quality';
            }

            const savingsText = formatBytes(dup.size_bytes || 0);
            const ratioText = (primary.size_bytes && dup.size_bytes && dup.size_bytes > 0 && (primary.size_bytes / dup.size_bytes) >= 1.2)
                ? ` (${(primary.size_bytes / dup.size_bytes).toFixed(1)}x larger)`
                : '';

            const pSpanId = `pDim_${grpIdx}_${dupIdx}`;
            const dSpanId = `dDim_${grpIdx}_${dupIdx}`;
            dimMeasurements.push({ item: primary, spanId: pSpanId });
            dimMeasurements.push({ item: dup, spanId: dSpanId });

            html += `
                        <div class="dup-compare-card" id="dupCard_${escapeHtml(dup.rel_path)}">
                            <div class="dup-card-header">
                                <div style="display:flex;align-items:center;gap:8px;">
                                    <span class="dup-reason-badge ${badgeClass}">
                                        ${reasonLabel}
                                    </span>
                                    <span class="dup-savings-badge">Frees ${savingsText}</span>
                                </div>
                                <div style="display:flex;align-items:center;gap:6px;margin-left:auto;">
                                    <button type="button" class="card-action-btn btn-compare-fs" onclick="openDuplicateCompareFullscreen(${grpIdx}, ${dupIdx})" title="Compare full-resolution images side-by-side in fullscreen">
                                        <svg viewBox="0 0 24 24" style="width:12px;height:12px;fill:currentColor;"><path d="M15 3l2.3 2.3-2.89 2.87 1.42 1.42L18.7 6.7 21 9V3h-6zM3 9l2.3-2.3 2.87 2.89 1.42-1.42L6.7 5.3 9 3H3v6zm6 12l-2.3-2.3 2.89-2.87-1.42-1.42L5.3 17.3 3 15v6h6zm12-6l-2.3 2.3-2.87-2.89-1.42 1.42 2.89 2.87L15 21h6v-6z"/></svg>
                                        <span>Compare Fullscreen</span>
                                    </button>
                                    <button type="button" class="card-action-btn" onclick="swapDuplicateKeeper(${grpIdx}, ${dupIdx})" title="Swap: keep this duplicate copy instead">
                                        <svg viewBox="0 0 24 24" style="width:12px;height:12px;fill:currentColor;"><path d="M6.99 11L3 15l3.99 4v-3H14v-2H6.99v-3zM21 9l-3.99-4v3H10v2h7.01v3L21 9z"/></svg>
                                        <span>Swap</span>
                                    </button>
                                    <button type="button" class="card-action-btn" onclick="dismissDuplicatePair(${grpIdx}, ${dupIdx})" title="Not a duplicate: keep both copies">
                                        <svg viewBox="0 0 24 24" style="width:12px;height:12px;fill:currentColor;"><path d="M9 16.2L4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4L9 16.2z"/></svg>
                                        <span>Keep Both</span>
                                    </button>
                                </div>
                            </div>

                            <div class="dup-card-grid">
                                <!-- LEFT: Primary Keeper -->
                                <div class="dup-col dup-col-primary">
                                    <div style="display:flex;justify-content:space-between;align-items:center;">
                                        <div class="dup-col-tag tag-primary">
                                            <svg viewBox="0 0 24 24" style="width:12px;height:12px;fill:currentColor;"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
                                            Keep: Original / HD
                                        </div>
                                        <span style="font-size:11px;color:#4ade80;font-weight:700;">Preserved</span>
                                    </div>
                                    <div class="dup-preview-box" onclick="openDuplicateCompareFullscreen(${grpIdx}, ${dupIdx})" title="Click to compare in full screen">
                                        <img src="${escapeHtml(primaryThumb)}" alt="${escapeHtml(primary.filename)}" loading="lazy">
                                        <div class="dup-preview-overlay-hint">Fullscreen</div>
                                    </div>
                                    <div class="dup-meta-chips-row">
                                        <span class="dup-meta-chip chip-res" id="${pSpanId}">Measuring...</span>
                                        <span class="dup-meta-chip chip-size-primary">${formatBytes(primary.size_bytes || 0)}${ratioText}</span>
                                        <span class="dup-meta-chip">${formatDateTime(primary.received_at, primary.rel_path)}</span>
                                    </div>
                                    <div class="dup-meta-filename" title="${escapeHtml(primary.filename)}">${escapeHtml(primary.filename)}</div>
                                </div>

                                <!-- RIGHT: Duplicate to Recycle -->
                                <div class="dup-col dup-col-duplicate">
                                    <div style="display:flex;justify-content:space-between;align-items:center;">
                                        <div class="dup-col-tag tag-duplicate">
                                            <svg viewBox="0 0 24 24" style="width:12px;height:12px;fill:currentColor;"><path d="M16 9v10H8V9h8m-1.5-6h-5l-1 1H5v2h14V4h-3.5l-1-1zM18 7H6v12c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7z"/></svg>
                                            Duplicate Copy
                                        </div>
                                        <span style="font-size:11px;color:#f87171;font-weight:700;">To Recycle</span>
                                    </div>
                                    <div class="dup-preview-box" onclick="openDuplicateCompareFullscreen(${grpIdx}, ${dupIdx})" title="Click to compare in full screen">
                                        <img src="${escapeHtml(dupThumb)}" alt="${escapeHtml(dup.filename)}" loading="lazy">
                                        <div class="dup-preview-overlay-hint">Fullscreen</div>
                                    </div>
                                    <div class="dup-meta-chips-row">
                                        <span class="dup-meta-chip chip-res" id="${dSpanId}">Measuring...</span>
                                        <span class="dup-meta-chip chip-size-dup">${formatBytes(dup.size_bytes || 0)}</span>
                                        <span class="dup-meta-chip">${formatDateTime(dup.received_at, dup.rel_path)}</span>
                                    </div>
                                    <div class="dup-meta-filename" title="${escapeHtml(dup.filename)}">${escapeHtml(dup.filename)}</div>
                                    <label class="dup-checkbox-wrap">
                                        <input type="checkbox" class="dup-recycle-item-cb" checked data-rel-path="${escapeHtml(dup.rel_path)}" data-size="${dup.size_bytes || 0}" onchange="updateRecycleModalStats()">
                                        <span>Move this duplicate copy to Recycle Bin</span>
                                    </label>
                                </div>
                            </div>
                        </div>
                    `;
        });
    });

    container.innerHTML = html;

    document.getElementById('dupMetricCount').innerText = totalDups;
    document.getElementById('dupMetricSavings').innerText = formatBytes(totalSavings);
    document.getElementById('dupMetricPreserved').innerText = groups.length;

    updateRecycleModalStats();

    // Measure true image dimensions asynchronously
    dimMeasurements.forEach(m => resolveAndDisplayImageDims(m.item, m.spanId));
}

function getFlattenedDupPairs() {
    const groups = window._currentChatDuplicateGroups || [];
    const pairs = [];
    groups.forEach((grp, gIdx) => {
        grp.duplicates.forEach((dup, dIdx) => {
            pairs.push({
                grpIdx: gIdx,
                dupIdx: dIdx,
                primary: grp.primary,
                dup: dup,
                grp: grp
            });
        });
    });
    return pairs;
}

function dismissDuplicatePair(grpIdx, dupIdx) {
    const groups = window._currentChatDuplicateGroups || [];
    if (!groups[grpIdx]) return;
    const grp = groups[grpIdx];
    const dup = grp.duplicates[dupIdx];
    if (!dup) return;

    const dupKey = dup.rel_path || dup.filename;
    window._ignoredDupKeys.add(dupKey);
    window._ignoredDupKeys.add(dup.filename);
    try {
        localStorage.setItem('wa_ignored_dups', JSON.stringify(Array.from(window._ignoredDupKeys)));
    } catch (e) {}

    window._dupUndoStack = window._dupUndoStack || [];
    window._dupUndoStack.push({
        dupKey: dupKey,
        dupRelPath: dup.rel_path,
        dupFilename: dup.filename,
        primaryRelPath: grp.primary ? grp.primary.rel_path : null,
        primaryFilename: grp.primary ? grp.primary.filename : null,
        item: dup,
        primaryItem: grp.primary
    });
    updateDupUndoButtonUI();

    dup.is_duplicate = false;
    dup.duplicate_primary = null;
    if (window._currentChatDupSet) {
        window._currentChatDupSet.delete(dupKey);
        window._currentChatDupSet.delete(dup.filename);
    }

    grp.duplicates.splice(dupIdx, 1);
    if (grp.duplicates.length === 0) {
        groups.splice(grpIdx, 1);
    }

    updateDuplicateReviewButtonUI();
    updateRecycleBinPill();
    if (activeChat) activeChat._dupCache = null;
    filterAndRenderMedia({ preserveScroll: true, keepItemsCount: true });
    renderDuplicateReviewContent();
    updateIgnoredTabCount();
    showToast('Marked as not duplicate: keeping both files.', 'success', 'Undo', () => {
        undoDismissDuplicate();
    });
}

function swapDuplicateKeeper(grpIdx, dupIdx) {
    const groups = window._currentChatDuplicateGroups || [];
    if (!groups[grpIdx]) return;
    const grp = groups[grpIdx];
    const oldPrimary = grp.primary;
    const newPrimary = grp.duplicates[dupIdx];
    if (!newPrimary) return;

    window._manualSwappedPrimaries = window._manualSwappedPrimaries || new Set();
    if (newPrimary.rel_path) window._manualSwappedPrimaries.add(newPrimary.rel_path);
    if (newPrimary.filename) window._manualSwappedPrimaries.add(newPrimary.filename);
    if (oldPrimary.rel_path) window._manualSwappedPrimaries.delete(oldPrimary.rel_path);
    if (oldPrimary.filename) window._manualSwappedPrimaries.delete(oldPrimary.filename);

    grp.primary = newPrimary;
    grp.duplicates[dupIdx] = oldPrimary;

    newPrimary.is_duplicate = false;
    newPrimary.duplicate_primary = null;
    oldPrimary.is_duplicate = true;
    oldPrimary.duplicate_primary = newPrimary.filename;

    if (window._currentChatDupSet) {
        window._currentChatDupSet.delete(newPrimary.rel_path || newPrimary.filename);
        window._currentChatDupSet.delete(newPrimary.filename);
        window._currentChatDupSet.add(oldPrimary.rel_path || oldPrimary.filename);
    }

    updateDuplicateReviewButtonUI();
    if (activeChat) activeChat._dupCache = null;
    filterAndRenderMedia({ preserveScroll: true, keepItemsCount: true });
    renderDuplicateReviewContent();
    renderDupCompareLightbox();
    showToast(`Swapped keeper: now keeping ${newPrimary.filename}`, 'info');
}
