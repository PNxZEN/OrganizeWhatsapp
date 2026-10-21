/* Lightbox viewer, transcoding and keyboard shortcuts
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

// Lightbox state & controls
let activeIndex = -1;

async function triggerTranscode() {
    const item = filteredMedia[activeIndex];
    if (!item || item.preview_path) return;
    
    const container = document.getElementById('lbMediaContainer');
    
    // Create a dedicated container for the transcode loader
    const loaderContainer = document.createElement('div');
    loaderContainer.id = 'transcodeLoaderContainer';
    loaderContainer.className = 'transcode-loader-container';

    const spinner = document.createElement('div');
    spinner.className = 'transcode-spinner';
    
    const text = document.createElement('div');
    text.className = 'transcode-text';
    text.innerText = 'Transcoding...';
    
    loaderContainer.appendChild(spinner);
    loaderContainer.appendChild(text);
    // Clear existing content (e.g. the unsupported-format panel) so the container
    // fills the full viewport and absolute centering lands dead center.
    container.innerHTML = '';
    container.appendChild(loaderContainer);
    
    try {
        const response = await fetch(`/api/transcode?rel_path=${encodeURIComponent(item.rel_path)}`);
        if (!response.ok) {
            throw new Error('Server returned error status');
        }
        const result = await response.json();
        if (result.status === 'success' && result.preview_path) {
            item.preview_path = result.preview_path;
            renderLightboxContent();
        } else {
            throw new Error('Invalid server response');
        }
    } catch (err) {
        loaderContainer.remove();
        
        const offlinePanel = document.createElement('div');
        offlinePanel.className = 'lightbox-audio-player';
        offlinePanel.style.maxWidth = '420px';
        offlinePanel.innerHTML = `
                    <svg viewBox="0 0 24 24" style="width:48px;height:48px;fill:var(--text-secondary);margin-bottom:4px;"><path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/></svg>
                    <div style="font-weight:600;font-size:1rem;color:var(--text-primary);margin-bottom:4px;">Local Server Offline</div>
                    <div style="font-size:0.85rem;color:var(--text-secondary);text-align:center;line-height:1.5;margin-bottom:12px;">
                        Start the local server to transcode and play this video in the browser.
                    </div>
                    <div style="background:rgba(0,0,0,0.3);border:1px solid var(--border-color);border-radius:8px;padding:10px 14px;font-family:monospace;font-size:0.8rem;color:var(--accent);margin-bottom:14px;display:flex;align-items:center;justify-content:space-between;width:100%;">
                        <span id="serverCmdText">python wa_media_organizer.py --serve --auto-open</span>
                        <button id="copyServerCmd" style="background:rgba(255,255,255,0.08);border:1px solid var(--border-color);border-radius:6px;padding:4px 10px;color:var(--text-primary);cursor:pointer;font-size:0.75rem;font-family:var(--font-family);">Copy</button>
                    </div>
                    <div style="display:flex;gap:10px;width:100%;">
                        <button id="retryTranscode" class="action-btn action-btn-primary" style="flex:1;justify-content:center;">Retry</button>
                        <button class="action-btn action-btn-secondary" style="flex:1;justify-content:center;" onclick="this.closest('.lightbox-audio-player').remove();">Dismiss</button>
                    </div>
                    <div id="serverStatusLine" style="font-size:0.8rem;color:var(--text-muted);margin-top:8px;"></div>
                `;
        container.appendChild(offlinePanel);
        
        document.getElementById('copyServerCmd').addEventListener('click', () => {
            navigator.clipboard.writeText('python wa_media_organizer.py --serve --auto-open').then(() => {
                document.getElementById('copyServerCmd').innerText = 'Copied!';
                setTimeout(() => { document.getElementById('copyServerCmd').innerText = 'Copy'; }, 1500);
            });
        });
        
        document.getElementById('retryTranscode').addEventListener('click', async () => {
            const statusLine = document.getElementById('serverStatusLine');
            statusLine.innerText = 'Checking server...';
            statusLine.style.color = 'var(--text-muted)';
            try {
                const healthResp = await fetch('/api/health');
                if (healthResp.ok) {
                    statusLine.innerText = 'Server is online! Retrying transcode...';
                    statusLine.style.color = 'var(--accent)';
                    setTimeout(() => { offlinePanel.remove(); triggerTranscode(); }, 800);
                    return;
                }
            } catch (e) {}
            statusLine.innerText = 'Server still offline. Start it in your terminal.';
            statusLine.style.color = 'var(--danger)';
        });
    }
}

function setupLightbox() {
    const lightbox = document.getElementById('lightbox');
    const closeBtn = document.getElementById('lbClose');
    const closeBtnSecondary = document.getElementById('lbCloseSecondary');
    const prevBtn = document.getElementById('lbPrev');
    const nextBtn = document.getElementById('lbNext');
    const videoHelpBtn = document.getElementById('lbVideoHelp');

    videoHelpBtn.addEventListener('click', triggerTranscode);

    const close = (triggerHistoryBack = true) => {
        document.body.classList.remove('lightbox-open');
        lightbox.classList.remove('active');
        const container = document.getElementById('lbMediaContainer');
        if (container) container.innerHTML = ''; // Stop video/audio
        if (triggerHistoryBack && history.state && history.state.view === 'lightbox') {
            try {
                window._closingModalViaBack = 'lightbox';
                setTimeout(() => { if (window._closingModalViaBack === 'lightbox') window._closingModalViaBack = null; }, 500);
                history.back();
            } catch (e) {}
        }
    };
    window.closeLightbox = close;

    closeBtn.addEventListener('click', () => close(true));
    closeBtnSecondary.addEventListener('click', () => close(true));

    prevBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        navigateLightbox(-1);
    });

    nextBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        navigateLightbox(1);
    });

    // Close the lightbox when clicking outside the player controls/media.
    lightbox.addEventListener('click', (e) => {
        // If they click on header, footer, or navigation, do not close.
        if (e.target.closest('.lightbox-header') || e.target.closest('.lightbox-footer') || e.target.closest('.lightbox-nav-btn')) {
            return;
        }
        // If they click on the actual media element or its active panel, do not close.
        if (e.target.closest('.lightbox-main-media') || e.target.closest('.lightbox-audio-player')) {
            return;
        }
        // Otherwise, any click on the overlay or empty space around the player closes the lightbox.
        close(true);
    });

    // Global keyboard shortcuts and lightbox navigation
    document.addEventListener('keydown', (e) => {
        // Context menu close on Escape
        const ctxMenu = document.getElementById('mediaContextMenu');
        if (ctxMenu && ctxMenu.style.display !== 'none' && e.key === 'Escape') {
            closeMediaContextMenu();
            return;
        }

        // Alt+Enter for Media Properties
        if (e.altKey && e.key === 'Enter') {
            e.preventDefault();
            if ((selectedFiles && selectedFiles.length > 0) || contextTargetItem) {
                closeMediaContextMenu();
                openMediaPropertiesModal();
                return;
            }
        }

        const tutModal = document.getElementById('modalTutorial');
        if (tutModal && tutModal.classList.contains('open')) {
            if (activeTutTab === 'phone') {
                if (e.key === 'ArrowRight') {
                    const isAdbReady = currentDeviceStatus && currentDeviceStatus.connected && currentDeviceStatus.authorized;
                    if (isAdbReady) {
                        e.preventDefault();
                        switchTutTab('key');
                        return;
                    }
                }
            } else if (activeTutTab === 'key') {
                if (e.key === 'ArrowLeft') { prevTutSlide(); return; }
                if (e.key === 'ArrowRight') { nextTutSlide(); return; }
            }
        }
        // 1. Escape key closes open modals or active lightbox
        if (e.key === 'Escape') {
            // Check if duplicate compare lightbox is open
            const dupLightbox = document.getElementById('lightboxDupCompare');
            if (dupLightbox && dupLightbox.style.display !== 'none') {
                handleDuplicateReviewBack();
                return;
            }

            // Check if standard image/video lightbox is open
            if (lightbox && lightbox.classList.contains('active')) {
                close();
                return;
            }

            // Check if Reclaim Studio is active in main view
            if (typeof currentViewMode !== 'undefined' && currentViewMode === 'reclaim') {
                handleStorageReclaimBack();
                return;
            }

            // Check if any modal is open
            const topModal = getTopOpenModal();
            if (topModal) {
                if (topModal.id === 'modalStorageReclaim') {
                    handleStorageReclaimBack();
                } else if (topModal.id === 'modalDuplicateReview') {
                    handleDuplicateReviewBack();
                } else if (topModal.id === 'modalRestoreChat') {
                    closeRestoreChatModal();
                } else {
                    closeModal(topModal.id);
                }
                return;
            }

            // If no modals or lightboxes open, Escape clears active gallery media selection
            if (selectedFiles && selectedFiles.length > 0) {
                resetSelectionUI();
                return;
            }
        }

        // 2. Focus sidebar search on '/' or Ctrl+F / Cmd+F when not actively typing
        if ((e.key === '/' && !isUserTyping()) || ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === 'f' || e.code === 'KeyF'))) {
            if (!isModalOrLightboxOpen()) {
                const searchInput = document.getElementById('sidebarSearch');
                if (searchInput) {
                    e.preventDefault();
                    searchInput.focus();
                    searchInput.select();
                    return;
                }
            }
        }

        // 3. Select All Media (Ctrl+A / Cmd+A)
        const isCtrlA = (e.ctrlKey || e.metaKey) && (e.key === 'a' || e.key === 'A' || e.code === 'KeyA');
        if (isCtrlA && !isUserTyping() && !isModalOrLightboxOpen()) {
            if (currentViewMode === 'gallery') {
                e.preventDefault();
                e.stopPropagation();
                if (!activeChat) {
                    const firstChat = getChatsArray()[0];
                    if (firstChat) {
                        selectChat(firstChat).then(() => {
                            handleToggleSelectAllMedia();
                        });
                        return;
                    }
                }
                handleToggleSelectAllMedia();
                return;
            }
        }

        // 4. Delete moves the selection to the Recycle Bin; Shift+Delete deletes it for good
        if (e.key === 'Delete' && !isUserTyping() && !isModalOrLightboxOpen() && currentViewMode === 'gallery'
            && selectedFiles && selectedFiles.length > 0) {
            e.preventDefault();
            if (e.shiftKey) deleteMediaFromGallery([...selectedFiles]);
            else recycleMediaFromGallery([...selectedFiles]);
            return;
        }

        // 5. Copy Selected Media Paths (Ctrl+C / Cmd+C)
        const isCtrlC = (e.ctrlKey || e.metaKey) && (e.key === 'c' || e.key === 'C' || e.code === 'KeyC');
        if (isCtrlC && !isUserTyping() && !isModalOrLightboxOpen()) {
            if (currentViewMode === 'gallery') {
                if (selectedFiles && selectedFiles.length > 0) {
                    e.preventDefault();
                    e.stopPropagation();
                    handleCopySelectedPaths();
                    return;
                } else if (contextTargetItem && contextTargetItem.rel_path) {
                    e.preventDefault();
                    e.stopPropagation();
                    copyTextToClipboard(contextTargetItem.rel_path, 'File path copied to clipboard');
                    return;
                }
            }
        }

        if (!lightbox.classList.contains('active')) return;

        // Prevent space from scrolling the background gallery,
        // and explicitly toggle play/pause of the active video/audio element.
        if (e.key === ' ') {
            e.preventDefault();
            const activeVideo = lightbox.querySelector('video');
            const activeAudio = lightbox.querySelector('audio');
            const mediaEl = activeVideo || activeAudio;
            if (mediaEl) {
                if (mediaEl.paused) {
                    mediaEl.play();
                } else {
                    mediaEl.pause();
                }
            }
            return;
        }

        // Prevent arrow-up/down from scrolling the background
        if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
            e.preventDefault();
            return;
        }

        // Seek video/audio with Left/Right Arrows, or navigate media card if image/Shift key held
        if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
            const activeVideo = lightbox.querySelector('video');
            const activeAudio = lightbox.querySelector('audio');
            const mediaEl = activeVideo || activeAudio;
            if (mediaEl && e.shiftKey) {
                e.preventDefault();
                const seekAmount = 5; // seek by 5 seconds when Shift is held
                if (e.key === 'ArrowLeft') {
                    mediaEl.currentTime = Math.max(0, mediaEl.currentTime - seekAmount);
                } else {
                    mediaEl.currentTime = Math.min(mediaEl.duration || mediaEl.currentTime, mediaEl.currentTime + seekAmount);
                }
            } else {
                e.preventDefault();
                if (e.key === 'ArrowLeft') {
                    navigateLightbox(-1);
                } else {
                    navigateLightbox(1);
                }
            }
        }
    });
}

function openLightbox(index, pushHistory = true) {
    activeIndex = index;
    document.body.classList.add('lightbox-open');
    const lightbox = document.getElementById('lightbox');
    lightbox.classList.add('active');
    if (pushHistory) {
        try {
            history.pushState({ app: 'wa_gallery', view: 'lightbox', index: index, chat: activeChat ? activeChat.jid : null }, '');
        } catch (e) {}
    }
    renderLightboxContent();
}

function navigateLightbox(dir) {
    activeIndex += dir;
    if (activeIndex < 0) activeIndex = filteredMedia.length - 1;
    if (activeIndex >= filteredMedia.length) activeIndex = 0;
    renderLightboxContent();
}

function renderLightboxContent() {
    const item = filteredMedia[activeIndex];
    if (!item) return;

    // Filename and meta
    document.getElementById('lbFilename').innerText = item.filename;
    
    const senderDisplay = item.sender_name || (item.sender_jid ? formatJIDName(item.sender_jid) : '');
    let metaText = `${formatDateTime(item.received_at, item.rel_path)} • ${formatBytes(item.size_bytes)}`;
    if (senderDisplay) {
        metaText += ` • From: ${senderDisplay}`;
    }
    if (item.starred) {
        metaText += ` • ★ Starred`;
    }
    if (item.forward_score >= 1) {
        if (item.forward_score >= 5 || item.forward_score === 127) {
            metaText += ` • ⤻ Frequently Forwarded`;
        } else {
            metaText += ` • ↪ Forwarded`;
        }
    }
    const lbItemKey = item.rel_path || item.filename;
    const isLbDup = (item.is_duplicate && item.duplicate_primary) || (window._currentChatDupSet && window._currentChatDupSet.has(lbItemKey));
    if (isLbDup) {
        const dupInfo = (window._currentChatDupInfo && window._currentChatDupInfo[lbItemKey]) || {};
        const primaryName = item.duplicate_primary || dupInfo.primaryFilename || '';
        const reason = item.duplicate_reason || dupInfo.reason || 'quality';
        metaText += ` • [DUPLICATE: ${reason}]`;
        if (primaryName) {
            metaText += ` (Copy of ${primaryName})`;
        }
    }
    document.getElementById('lbMeta').innerText = metaText;

    // Setup download button
    const dlBtn = document.getElementById('lbDownload');
    dlBtn.href = getMediaUrl(item.rel_path);
    dlBtn.setAttribute('download', item.filename);

    // Conditionally show/hide 'Show in File Explorer' based on HTTP protocol (localhost access)
    const explorerBtn = document.getElementById('lbOpenFolder');
    if (explorerBtn) {
        if (window.location.protocol.startsWith('http')) {
            explorerBtn.style.display = 'inline-flex';
        } else {
            explorerBtn.style.display = 'none';
        }
    }

    const container = document.getElementById('lbMediaContainer');
    container.innerHTML = '';
    document.getElementById('lbVideoHelp').style.display = 'none';

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

    if (isImage) {
        const img = document.createElement('img');
        img.className = 'lightbox-main-media';
        img.src = getMediaUrl(item.rel_path || item.thumb_path);
        container.appendChild(img);
    } else if (isVideo) {
        const hasPlayablePreview = !!item.preview_path;
        
        if (isUnsupportedVideo && !hasPlayablePreview) {
            let formatName = 'unsupported format';
            if (filename.endsWith('.mov')) formatName = 'QuickTime MOV';
            else if (filename.endsWith('.avi')) formatName = 'AVI';
            else if (filename.endsWith('.mkv')) formatName = 'Matroska MKV';
            else if (filename.endsWith('.3gp')) formatName = '3GP Mobile';
            else if (filename.endsWith('.flv')) formatName = 'Flash FLV';

            const movWrapper = document.createElement('div');
            movWrapper.className = 'lightbox-audio-player'; // Reuse glassmorphic styling
            movWrapper.style.flexDirection = 'column';
            movWrapper.style.gap = '16px';
            movWrapper.style.padding = '24px';
            
            const movIcon = document.createElement('div');
            movIcon.innerHTML = `<svg viewBox="0 0 24 24" style="width:64px;height:64px;fill:var(--text-secondary);"><path d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"/></svg>`;
            
            const movText = document.createElement('div');
            movText.style.color = 'var(--text-secondary)';
            movText.style.fontSize = '0.95rem';
            movText.style.textAlign = 'center';
            movText.innerHTML = `
                        <div style="font-weight:600;margin-bottom:8px;color:var(--text-primary);">${escapeHtml(item.filename)}</div>
                        <div>${formatName} videos are not natively supported by Windows browsers.</div>
                        <div style="font-size:0.85rem;margin-top:4px;color:var(--accent);margin-bottom:12px;">Click the Download button below to play locally.</div>
                    `;
            
            const transcodeBtn = document.createElement('button');
            transcodeBtn.className = 'action-btn action-btn-primary';
            transcodeBtn.style.background = 'var(--accent)';
            transcodeBtn.style.borderColor = 'var(--accent)';
            transcodeBtn.innerText = 'Transcode Video';
            transcodeBtn.onclick = triggerTranscode;
            
            movWrapper.appendChild(movIcon);
            movWrapper.appendChild(movText);
            movWrapper.appendChild(transcodeBtn);
            container.appendChild(movWrapper);
        } else {
            const vid = document.createElement('video');
            vid.className = 'lightbox-main-media';
            const targetVidRel = item.preview_path || item.rel_path;
            vid.src = getMediaUrl(targetVidRel);
            vid.controls = true;
            vid.autoplay = true;
            
            // Create animated loading spinner element
            const spinner = document.createElement('div');
            spinner.className = 'lightbox-loader';
            container.appendChild(spinner);
            
            // Hide loading spinner once the video starts playing or is ready to play
            const hideSpinner = () => {
                spinner.style.opacity = 0;
                setTimeout(() => spinner.remove(), 300);
            };
            vid.addEventListener('canplay', hideSpinner);
            vid.addEventListener('playing', hideSpinner);

            // If the preview_path file no longer exists on disk (e.g. .cache was cleared),
            // fall back to the original file and re-enable the transcode button.
            vid.addEventListener('error', () => {
                if (item.preview_path) {
                    console.warn(`[Gallery] Preview missing on disk: ${item.preview_path} - falling back to original.`);
                    item.preview_path = null; // clear so triggerTranscode works again
                    vid.src = getMediaUrl(item.rel_path);
                    vid.load();
                    document.getElementById('lbVideoHelp').style.display = 'inline-block';
                } else {
                    hideSpinner();
                }
            });
            
            container.appendChild(vid);

            // Show the "Fix Black Screen?" help button in the footer for playable video files if not fixed yet
            if (item.preview_path) {
                document.getElementById('lbVideoHelp').style.display = 'none';
            } else {
                document.getElementById('lbVideoHelp').style.display = 'inline-block';
            }
        }
    } else if (mime.startsWith('audio/')) {
        // Audio custom interface
        const audioPlayerWrapper = document.createElement('div');
        audioPlayerWrapper.className = 'lightbox-audio-player';
        
        const wave = document.createElement('div');
        wave.className = 'audio-wave-visual';
        for (let i = 0; i < 40; i++) {
            const bar = document.createElement('div');
            bar.className = 'audio-bar';
            bar.style.animationDelay = `${i * 0.05}s`;
            wave.appendChild(bar);
        }

        const aud = document.createElement('audio');
        aud.src = getMediaUrl(item.rel_path);
        aud.controls = true;
        aud.style.width = '100%';

        aud.onplay = () => {
            wave.querySelectorAll('.audio-bar').forEach(bar => bar.classList.add('active'));
        };
        aud.onpause = () => {
            wave.querySelectorAll('.audio-bar').forEach(bar => bar.classList.remove('active'));
        };

        audioPlayerWrapper.appendChild(wave);
        audioPlayerWrapper.appendChild(aud);
        container.appendChild(audioPlayerWrapper);
    } else {
        // Document / Unviewable offline
        const fallback = document.createElement('div');
        fallback.className = 'doc-icon-container';
        fallback.style.color = '#ffffff';
        fallback.innerHTML = `
                    <svg viewBox="0 0 24 24" style="width:96px;height:96px;"><path d="M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z"/></svg>
                    <p style="font-size:1.1rem; margin-top:20px; font-weight:500;">${escapeHtml(item.filename)}</p>
                    <p style="font-size:0.9rem; color:var(--text-secondary); margin-top:8px;">This document format cannot be previewed in-browser.</p>
                `;
        container.appendChild(fallback);
    }
}
