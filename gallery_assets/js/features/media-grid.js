/* Media cards, video thumbnails and grid rendering
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

const _videoThumbCanvas = document.createElement('canvas');
const _videoThumbCtx = _videoThumbCanvas.getContext('2d');
const _videoThumbQueue = [];
let _videoThumbProcessing = false;
const _videoThumbCache = new Map();

function captureVideoFrame(src, callback) {
    if (_videoThumbCache.has(src)) {
        callback(_videoThumbCache.get(src));
        return;
    }
    _videoThumbQueue.push({ src, callback });
    _processNextVideoThumb();
}

function _processNextVideoThumb() {
    if (_videoThumbProcessing || _videoThumbQueue.length === 0) return;
    _videoThumbProcessing = true;
    const item = _videoThumbQueue.shift();
    const src = item.src;
    const callback = item.callback;

    const video = document.createElement('video');
    video.crossOrigin = 'anonymous';
    video.preload = 'auto'; // Preload auto guarantees onloadeddata fires reliably for thumbnail extraction
    video.muted = true;
    video.playsInline = true;

    let timeoutId = setTimeout(() => {
        cleanup();
        callback(null);
        _videoThumbProcessing = false;
        _processNextVideoThumb();
    }, 4000);

    function cleanup() {
        clearTimeout(timeoutId);
        video.onloadeddata = null;
        video.onseeked = null;
        video.onerror = null;
        video.removeAttribute('src');
        try { video.load(); } catch (e) {}
    }

    video.onloadeddata = () => {
        try {
            video.currentTime = Math.min(0.5, (video.duration || 1) / 2);
        } catch (e) {
            cleanup();
            callback(null);
            _videoThumbProcessing = false;
            _processNextVideoThumb();
        }
    };

    video.onseeked = () => {
        try {
            const w = 280;
            const h = Math.round((video.videoHeight / Math.max(1, video.videoWidth)) * 280) || 280;
            _videoThumbCanvas.width = w;
            _videoThumbCanvas.height = h;
            _videoThumbCtx.drawImage(video, 0, 0, w, h);
            const dataUrl = _videoThumbCanvas.toDataURL('image/jpeg', 0.8);
            _videoThumbCache.set(src, dataUrl);
            cleanup();
            callback(dataUrl);
        } catch (e) {
            cleanup();
            callback(null);
        }
        _videoThumbProcessing = false;
        _processNextVideoThumb();
    };

    video.onerror = () => {
        cleanup();
        callback(null);
        _videoThumbProcessing = false;
        _processNextVideoThumb();
    };

    video.src = src;
}

function handleVideoThumbFallback(img, encRelPath) {
    img.onerror = null;
    const videoUrl = isHttpServer ? ('/api/media?path=' + encRelPath) : encodePathForUrl(decodeURIComponent(encRelPath));
    captureVideoFrame(videoUrl, (dataUrl) => {
        if (dataUrl) {
            img.src = dataUrl;
            img.style.display = 'block';
        } else {
            img.style.display = 'none';
            let placeholder = img.nextElementSibling;
            while (placeholder && !placeholder.classList.contains('video-placeholder-container')) {
                placeholder = placeholder.nextElementSibling;
            }
            if (placeholder) {
                placeholder.style.display = 'flex';
            }
        }
    });
}

function createMediaCard(item, originalIndex) {
    const card = document.createElement('div');
    card.dataset.relPath = item.rel_path;
    
    // Set selection classes
    let cardClasses = 'media-card';
    if (selectModeActive) {
        cardClasses += ' select-mode';
        if (selectedFiles.includes(item.rel_path)) {
            cardClasses += ' selected';
        }
    }
    card.className = cardClasses;
    
    card.addEventListener('click', (e) => {
        if (e.ctrlKey || e.metaKey || selectModeActive) {
            if (!selectModeActive) {
                enterSelectionMode();
            }
            toggleCardSelection(card, item.rel_path);
        } else {
            openLightbox(originalIndex);
        }
    });

    card.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        e.stopPropagation();
        openMediaContextMenu(e, item, originalIndex);
    });

    const filename = (item.filename || '').toLowerCase();
    const mime = (item.mime_type || '').toLowerCase();
    
    const isImage = mime.startsWith('image/') || 
                    filename.endsWith('.jpg') || 
                    filename.endsWith('.jpeg') || 
                    filename.endsWith('.png') || 
                    filename.endsWith('.gif') || 
                    filename.endsWith('.webp') || 
                    filename.endsWith('.heic') || 
                    filename.endsWith('.heif');
                    
    const isPlayableVideo = mime.startsWith('video/mp4') || 
                            mime.startsWith('video/webm') || 
                            mime.startsWith('video/ogg') || 
                            filename.endsWith('.mp4') || 
                            filename.endsWith('.m4v') || 
                            filename.endsWith('.webm');
                            
    const isUnsupportedVideo = (mime.startsWith('video/') && !isPlayableVideo) ||
                               filename.endsWith('.mov') || 
                               filename.endsWith('.avi') || 
                               filename.endsWith('.mkv') || 
                               filename.endsWith('.3gp') ||
                               filename.endsWith('.flv');
                               
    const isVideo = isPlayableVideo || isUnsupportedVideo;
                    
    const isAudio = mime.startsWith('audio/') || 
                    filename.endsWith('.mp3') || 
                    filename.endsWith('.ogg') || 
                    filename.endsWith('.wav') || 
                    filename.endsWith('.m4a') || 
                    filename.endsWith('.opus') || 
                    filename.endsWith('.amr');

    let contentHTML = '';
    // File, sender and chat names come from WhatsApp data and must never be parsed as HTML
    const safeName = escapeHtml(item.filename);
    const localThumbUrl = (p) => (/^(data:|blob:|https?:|\/)/i.test(p) ? p : encodePathForUrl(p));

    if (isImage) {
        const src = isHttpServer 
            ? ('/api/thumbnail?path=' + encodeURIComponent(item.rel_path)) 
            : localThumbUrl(item.thumb_path || item.rel_path);
        contentHTML = `<img src="${escapeHtml(src)}" loading="lazy" decoding="async" alt="${safeName}">`;
        if (item.is_doc) {
            contentHTML += `<div class="badge badge-doc">DOC</div>`;
        }
    } else if (isVideo) {
        const durStr = formatDuration(item.media_duration);
        const thumbSrc = item.thumb_path ? localThumbUrl(item.thumb_path) : (isHttpServer ? ('/api/thumbnail?path=' + encodeURIComponent(item.rel_path)) : null);
        
        if (thumbSrc) {
            contentHTML = `
                        <img src="${escapeHtml(thumbSrc)}" loading="lazy" decoding="async" alt="${safeName}"
                             onerror="handleVideoThumbFallback(this, '${escapeJsAttr(encodeURIComponent(item.rel_path))}')">
                        <div class="video-placeholder-container" style="display:none;">
                            <svg viewBox="0 0 24 24"><path d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"/></svg>
                            <span class="doc-name">${safeName}</span>
                        </div>
                        <div class="badge badge-video">
                            <svg class="icon" viewBox="0 0 24 24" style="width:12px;height:12px;"><path d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"/></svg>
                            ${durStr ? durStr : 'VIDEO'}
                        </div>
                    `;
        } else if (isUnsupportedVideo) {
            let formatName = 'Unsupported Video';
            if (filename.endsWith('.mov')) formatName = 'QuickTime MOV Video';
            else if (filename.endsWith('.avi')) formatName = 'AVI Video';
            else if (filename.endsWith('.mkv')) formatName = 'Matroska MKV Video';
            else if (filename.endsWith('.3gp')) formatName = '3GP Mobile Video';
            else if (filename.endsWith('.flv')) formatName = 'Flash FLV Video';
            
            contentHTML = `
                        <div class="video-placeholder-container">
                            <svg viewBox="0 0 24 24"><path d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"/></svg>
                            <span class="doc-name">${safeName}</span>
                        </div>
                        <div class="badge badge-video">${formatName}</div>
                    `;
        } else {
            contentHTML = `
                        <div class="video-placeholder-container">
                            <svg viewBox="0 0 24 24"><path d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"/></svg>
                            <span class="doc-name">${safeName}</span>
                        </div>
                        <div class="badge badge-video">
                            <svg class="icon" viewBox="0 0 24 24" style="width:12px;height:12px;"><path d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"/></svg>
                            ${durStr ? durStr : 'VIDEO'}
                        </div>
                    `;
        }
    } else if (isAudio) {
        const durStr = formatDuration(item.media_duration);
        contentHTML = `
                    <div class="audio-icon-container">
                        <svg viewBox="0 0 24 24"><path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/></svg>
                        <span class="doc-name">${safeName}</span>
                    </div>
                    <div class="badge badge-audio">${durStr ? durStr : 'AUDIO'}</div>
                `;
    } else {
        // Document / Other
        contentHTML = `
                    <div class="doc-icon-container">
                        <svg viewBox="0 0 24 24"><path d="M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z"/></svg>
                        <span class="doc-name">${safeName}</span>
                    </div>
                    <div class="badge badge-doc">DOC</div>
                `;
    }

    // Left-hand stacked badges
    let leftBadgesHTML = '<div class="card-badges-left">';
    const itemKey = item.rel_path || item.filename;
    const isDupItem = (item.is_duplicate && item.duplicate_primary) || (window._currentChatDupSet && window._currentChatDupSet.has(itemKey));
    if (isDupItem) {
        const dupInfo = (window._currentChatDupInfo && window._currentChatDupInfo[itemKey]) || {};
        const primaryName = item.duplicate_primary || dupInfo.primaryFilename || '';
        const dupTitle = primaryName ? `Duplicate (Copy of ${primaryName})` : 'Duplicate';
        leftBadgesHTML += `<div class="badge-tag badge-tag-dup" title="${escapeHtml(dupTitle)}">DUPLICATE</div>`;
    }
    if (item.starred) {
        leftBadgesHTML += `<div class="badge-tag badge-tag-star" title="Starred">★ Starred</div>`;
    }
    if (item.forward_score >= 1) {
        if (item.forward_score >= 5 || item.forward_score === 127) {
            leftBadgesHTML += `<div class="badge-tag badge-tag-forward-many" title="Forwarded many times">⤻ Freq. Forwarded</div>`;
        } else {
            leftBadgesHTML += `<div class="badge-tag badge-tag-forward" title="Forwarded">↪ Forwarded</div>`;
        }
    }
    leftBadgesHTML += '</div>';
    contentHTML += leftBadgesHTML;

    // Hover overlay info
    const senderStr = item.sender_name ? ` • From: ${item.sender_name}` : (item.sender_jid ? ` • From: ${formatJIDName(item.sender_jid)}` : '');
    contentHTML += `
                <div class="card-overlay">
                    <span class="card-title">${safeName}</span>
                    <span class="card-time">${escapeHtml(formatDateTime(item.received_at, item.rel_path))} • ${formatBytes(item.size_bytes)}${escapeHtml(senderStr)}</span>
                </div>
            `;

    // Checkbox and preview overlay for select mode
    const showFolderClass = window.location.protocol.startsWith('http') ? 'card-folder-btn http-enabled' : 'card-folder-btn';
    contentHTML += `
                <div class="card-checkbox" title="Select item">
                    <svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"></polyline></svg>
                </div>
                <div class="card-preview-btn" title="Preview file" onclick="event.stopPropagation(); openLightbox(${originalIndex});">
                    <svg viewBox="0 0 24 24" style="width: 14px; height: 14px; fill: white;"><path d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z"/></svg>
                </div>
                <div class="${showFolderClass}" title="Show in File Explorer" onclick="event.stopPropagation(); revealInExplorer('${escapeJsAttr(item.rel_path)}');">
                    <svg viewBox="0 0 24 24" style="width: 14px; height: 14px; fill: none; stroke: white; stroke-width: 2.5;"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
                </div>
            `;

    card.innerHTML = contentHTML;

    const chk = card.querySelector('.card-checkbox');
    if (chk) {
        chk.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleCardSelectionFromCheckbox(chk, item.rel_path);
        });
    }

    return card;
}

// Render files grouped by date or flat list based on sorting
function renderGallery(options = {}) {
    const container = document.getElementById('galleryContent');
    const preserveScroll = !!(options && options.preserveScroll);
    const targetScrollTop = (options && options.targetScrollTop !== null && options.targetScrollTop !== undefined)
        ? options.targetScrollTop
        : (preserveScroll && container ? container.scrollTop : null);

    const prevFilterCollapsed = isFilterCollapsed;

    const pill = document.getElementById('newMediaPill');
    container.innerHTML = '';
    if (pill) {
        container.appendChild(pill);
    }
    renderedCount = 0;

    if (filteredMedia.length === 0) {
        const currentChats = getChatsArray();
        if (!currentChats || currentChats.length === 0) {
            container.innerHTML = `
                        <div class="empty-state" style="max-width:540px;margin:40px auto;padding:32px 24px;border:1px dashed var(--border-color);border-radius:16px;background:rgba(255,255,255,0.02);text-align:center;">
                            <div style="width:56px;height:56px;border-radius:50%;background:rgba(37,211,102,0.12);color:var(--accent-whatsapp);display:flex;align-items:center;justify-content:center;margin:0 auto 16px;">
                                <svg viewBox="0 0 24 24" style="width:28px;height:28px;fill:currentColor;"><path d="M12 4V1L8 5l4 4V6c3.31 0 6 2.69 6 6 0 1.01-.25 1.97-.7 2.8l1.46 1.46C19.54 15.03 20 13.57 20 12c0-4.42-3.58-8-8-8zm0 14c-3.31 0-6-2.69-6-6 0-1.01.25-1.97.7-2.8L5.24 7.74C4.46 8.97 4 10.43 4 12c0 4.42 3.58 8 8 8v3l4-4-4-4v3z"/></svg>
                            </div>
                            <h3 style="font-size:18px;font-weight:600;margin-bottom:8px;color:var(--text-primary);">Welcome to WhatsApp Media Organizer</h3>
                            <p style="font-size:13px;color:var(--text-secondary);line-height:1.6;margin-bottom:18px;">
                                No synced media found yet. Choose how you would like to get started:
                            </p>
                            <div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin-bottom:14px;">
                                <button type="button" class="action-btn action-btn-primary" onclick="openSyncModal();" style="padding:10px 18px;font-size:13px;font-weight:600;">
                                    Start Phone Sync
                                </button>
                                <button type="button" class="action-btn action-btn-secondary" onclick="openKeyModal('import');" style="padding:10px 18px;font-size:13px;display:inline-flex;align-items:center;gap:6px;">
                                    <svg class="icon" viewBox="0 0 24 24" style="width:14px;height:14px;fill:none;stroke:currentColor;stroke-width:2;"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
                                    <span>Import Older Backup</span>
                                </button>
                                <button type="button" class="action-btn action-btn-secondary" onclick="openTutorialModal();" style="padding:10px 18px;font-size:13px;">
                                    View Setup Guide
                                </button>
                            </div>
                            <div style="font-size:11px;color:var(--text-muted);line-height:1.4;">
                                Upgrading? Importing an older output folder first catalogs existing media -- subsequent phone syncs will download only the newer media files.
                            </div>
                        </div>
                    `;
            return;
        }
        container.innerHTML = `
                    <div class="empty-state">
                        <svg viewBox="0 0 24 24"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
                        <h3>No matching files</h3>
                        <p>Try adjusting your search criteria or filters.</p>
                    </div>
                `;
        return;
    }

    const sortBy = document.getElementById('sortFilter').value;
    const limit = Math.min(itemsToShow, filteredMedia.length);

    if (sortBy === 'largest' || sortBy === 'smallest') {
        const groupDiv = document.createElement('div');
        groupDiv.className = 'date-group';
        groupDiv.setAttribute('data-flat-group', 'true');
        
        const header = document.createElement('div');
        header.className = 'date-header';
        header.innerText = sortBy === 'largest' ? 'Sorted by: Largest Files First' : 'Sorted by: Smallest Files First';
        groupDiv.appendChild(header);

        const grid = document.createElement('div');
        grid.className = 'media-grid';

        const frag = document.createDocumentFragment();
        for (let i = 0; i < limit; i++) {
            frag.appendChild(createMediaCard(filteredMedia[i], i));
        }
        grid.appendChild(frag);
        groupDiv.appendChild(grid);
        container.appendChild(groupDiv);
        renderedCount = limit;
    } else {
        const groups = {};
        const monthOrder = [];
        filteredMedia.forEach((item, index) => {
            const monthGroup = getMonthGroupForItem(item);
            item.monthGroup = monthGroup;
            if (!groups[monthGroup]) {
                groups[monthGroup] = [];
                monthOrder.push(monthGroup);
            }
            groups[monthGroup].push({ item, index });
        });

        for (let i = 0; i < monthOrder.length && renderedCount < limit; i++) {
            const month = monthOrder[i];
            const groupDiv = document.createElement('div');
            groupDiv.className = 'date-group';
            groupDiv.setAttribute('data-month', month);
            
            const header = document.createElement('div');
            header.className = 'date-header';
            header.innerText = month;
            groupDiv.appendChild(header);

            const grid = document.createElement('div');
            grid.className = 'media-grid';

            const frag = document.createDocumentFragment();
            const groupItems = groups[month];
            for (let j = 0; j < groupItems.length && renderedCount < limit; j++) {
                const { item, index } = groupItems[j];
                frag.appendChild(createMediaCard(item, index));
                renderedCount++;
            }
            grid.appendChild(frag);
            groupDiv.appendChild(grid);
            container.appendChild(groupDiv);
        }
    }

    if (preserveScroll && targetScrollTop !== null && targetScrollTop > 0 && container) {
        container.scrollTop = targetScrollTop;
        lastFilterScrollTop = targetScrollTop;
        requestAnimationFrame(() => {
            if (container) {
                container.scrollTop = targetScrollTop;
                lastFilterScrollTop = targetScrollTop;
            }
            if (prevFilterCollapsed) {
                const fp = document.getElementById('filterPanel');
                if (fp && !fp.classList.contains('collapsed')) {
                    fp.classList.add('collapsed');
                    isFilterCollapsed = true;
                    updateFilterToggleBtnState(true);
                }
            }
        });
    } else {
        if (container) lastFilterScrollTop = container.scrollTop;
    }
}

function appendMoreCards() {
    if (renderedCount >= filteredMedia.length) return;
    const container = document.getElementById('galleryContent');
    const sortBy = document.getElementById('sortFilter').value;
    
    // Increment itemsToShow by 100 on every load
    itemsToShow += 100;
    const limit = Math.min(itemsToShow, filteredMedia.length);

    if (sortBy === 'largest' || sortBy === 'smallest') {
        const grid = container.querySelector('[data-flat-group] .media-grid');
        if (!grid) return;
        const frag = document.createDocumentFragment();
        for (let i = renderedCount; i < limit; i++) {
            frag.appendChild(createMediaCard(filteredMedia[i], i));
        }
        grid.appendChild(frag);
        renderedCount = limit;
    } else {
        // Optimized progressive appending: append only the next slice (O(K))
        // instead of rebuilding groups for all items (O(N))
        let currentGrid = null;
        let currentMonth = null;
        
        for (let i = renderedCount; i < limit; i++) {
            const item = filteredMedia[i];
            if (!item.monthGroup) {
                item.monthGroup = getMonthGroupForItem(item);
            }
            const month = item.monthGroup;
            
            if (month !== currentMonth) {
                currentMonth = month;
                let existingGroup = container.querySelector(`[data-month="${CSS.escape(month)}"]`);
                if (!existingGroup) {
                    existingGroup = document.createElement('div');
                    existingGroup.className = 'date-group';
                    existingGroup.setAttribute('data-month', month);
                    
                    const header = document.createElement('div');
                    header.className = 'date-header';
                    header.innerText = month;
                    existingGroup.appendChild(header);
                    
                    currentGrid = document.createElement('div');
                    currentGrid.className = 'media-grid';
                    existingGroup.appendChild(currentGrid);
                    
                    container.appendChild(existingGroup);
                } else {
                    currentGrid = existingGroup.querySelector('.media-grid');
                }
            }
            
            currentGrid.appendChild(createMediaCard(item, i));
            renderedCount++;
        }
    }
}
