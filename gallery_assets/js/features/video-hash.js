/* Background video 3-frame hashing queue
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

// VIDEO 3-FRAME SAMPLING & DUPLICATE DETECTION ENGINE
window._cachedVideo3FrameHashes = window._cachedVideo3FrameHashes || {};
window._video3FrameHashPending = window._video3FrameHashPending || new Set();

function computeVideo3FrameHash(item) {
    if (!item) return Promise.resolve(null);
    const key = item.rel_path || item.filename;
    if (window._cachedVideo3FrameHashes[key]) {
        return Promise.resolve(window._cachedVideo3FrameHashes[key]);
    }
    if (window._video3FrameHashPending.has(key)) {
        return Promise.resolve(null);
    }
    window._video3FrameHashPending.add(key);

    return new Promise((resolve) => {
        const vid = document.createElement('video');
        vid.crossOrigin = 'anonymous';
        vid.preload = 'auto'; // Preload auto ensures reliable frame seeking across all browsers and offline file mode
        vid.muted = true;
        vid.playsInline = true;

        const directUrl = (item.rel_path || '').split('/').map(seg => encodeURIComponent(seg)).join('/');
        const srcUrl = isHttpServer ? ('/api/media?path=' + encodeURIComponent(item.rel_path)) : directUrl;

        let duration = item.media_duration || 0;
        const pts = [];
        const hashes = [];
        let curPtIdx = 0;
        let canvas = document.createElement('canvas');
        canvas.width = 8;
        canvas.height = 8;
        let ctx = canvas.getContext('2d', { willReadFrequently: true });

        const cleanup = () => {
            window._video3FrameHashPending.delete(key);
            vid.onloadedmetadata = null;
            vid.onseeked = null;
            vid.onerror = null;
            vid.removeAttribute('src');
            try { vid.load(); } catch (e) {}
            if (canvas) {
                canvas.width = 1;
                canvas.height = 1;
                canvas = null;
                ctx = null;
            }
        };

        const timeoutId = setTimeout(() => {
            cleanup();
            resolve(null);
        }, 4000);

        vid.onerror = () => {
            clearTimeout(timeoutId);
            cleanup();
            resolve(null);
        };

        vid.onloadedmetadata = () => {
            duration = vid.duration || duration || 3;
            if (vid.videoWidth && vid.videoHeight) {
                window._cachedImageDims[key] = { w: vid.videoWidth, h: vid.videoHeight, dur: vid.duration };
                item.width = vid.videoWidth;
                item.height = vid.videoHeight;
            }
            pts.push(duration * 0.25, duration * 0.50, duration * 0.75);
            seekNext();
        };

        function seekNext() {
            if (curPtIdx >= pts.length) {
                clearTimeout(timeoutId);
                cleanup();
                if (hashes.length === 3) {
                    window._cachedVideo3FrameHashes[key] = hashes;
                    resolve(hashes);
                } else {
                    resolve(null);
                }
                return;
            }
            vid.currentTime = pts[curPtIdx];
        }

        vid.onseeked = () => {
            try {
                if (ctx) {
                    ctx.drawImage(vid, 0, 0, 8, 8);
                    const imgData = ctx.getImageData(0, 0, 8, 8).data;
                    let sum = 0;
                    const lum = [];
                    for (let i = 0; i < 64; i++) {
                        const r = imgData[i * 4];
                        const g = imgData[i * 4 + 1];
                        const b = imgData[i * 4 + 2];
                        const l = (r * 299 + g * 587 + b * 114) / 1000;
                        lum.push(l);
                        sum += l;
                    }
                    const avg = sum / 64;
                    let bitstr = '';
                    for (let i = 0; i < 64; i++) {
                        bitstr += (lum[i] >= avg ? '1' : '0');
                    }
                    hashes.push(bitstr);
                }
            } catch (e) {
                // Canvas read errors fallback safely
            }
            curPtIdx++;
            seekNext();
        };

        vid.src = srcUrl;
    });
}

function compareVideo3FrameHashes(h1, h2) {
    if (!h1 || !h2 || h1.length !== 3 || h2.length !== 3) return false;
    let totalDist = 0;
    for (let f = 0; f < 3; f++) {
        let dist = 0;
        const a = h1[f];
        const b = h2[f];
        for (let i = 0; i < 64; i++) {
            if (a[i] !== b[i]) dist++;
        }
        totalDist += dist;
    }
    return (totalDist / 3.0) <= 8.0;
}

window._videoHashQueue = [];
window._isVideoHashingRunning = false;

// User activity detection to prevent any UI lag or frame drops during background processing
let _lastUserInteractionTimestamp = 0;
['scroll', 'wheel', 'touchmove', 'pointerdown', 'keydown'].forEach(evt => {
    window.addEventListener(evt, () => {
        _lastUserInteractionTimestamp = Date.now();
    }, { passive: true, capture: true });
});

function queueVideoCandidateHashing(chat, isHighPriority = false) {
    if (typeof isDuplicateDetectionEnabled === 'function' && !isDuplicateDetectionEnabled()) return;
    if (!chat || !chat.media) return;
    const waVidPattern = /^VID-(\d{8})-WA(\d{4})(?:_dup\d+)?(?:\.[^.]+)?$/i;

    const dateGroups = new Map();
    const collisionCandidates = [];

    chat.media.forEach(it => {
        if (!isVideoItem(it)) return;
        const fn = it.filename || '';
        const key = it.rel_path || it.filename;
        if (window._cachedVideo3FrameHashes[key] || window._video3FrameHashPending.has(key)) return;

        if (/_dup\d+/i.test(fn)) {
            collisionCandidates.push({ item: it, chatJid: chat.jid });
            return;
        }

        const m = fn.match(waVidPattern);
        if (m) {
            const datePart = m[1];
            const counter = parseInt(m[2], 10);
            if (!dateGroups.has(datePart)) dateGroups.set(datePart, []);
            dateGroups.get(datePart).push({ item: it, counter, dur: it.media_duration });
        }
    });

    const candidates = [];
    // Only queue videos from date groups where at least one potential pair exists!
    dateGroups.forEach((vids, datePart) => {
        if (vids.length > 1) {
            const eligible = new Set();
            for (let a = 0; a < vids.length; a++) {
                for (let b = a + 1; b < vids.length; b++) {
                    const cDiff = Math.abs(vids[a].counter - vids[b].counter);
                    const durA = vids[a].dur;
                    const durB = vids[b].dur;
                    let durMatch = false;
                    if (durA !== undefined && durB !== undefined && durA !== null && durB !== null) {
                        durMatch = Math.abs(Number(durA) - Number(durB)) <= 0.5;
                    }
                    if (cDiff <= 4 || durMatch) {
                        eligible.add(a);
                        eligible.add(b);
                    }
                }
            }
            eligible.forEach(idx => {
                candidates.push({ item: vids[idx].item, chatJid: chat.jid });
            });
        }
    });

    collisionCandidates.forEach(c => candidates.push(c));

    if (candidates.length === 0) return;

    // Prioritize newest dates first (e.g. June 2026 before 2024)
    candidates.sort((a, b) => {
        const fnA = a.item.filename || '';
        const fnB = b.item.filename || '';
        return fnB.localeCompare(fnA);
    });

    // Cap queue to top 40 candidates for active chat to conserve RAM and disk I/O
    const boundedCandidates = candidates.slice(0, 40);

    if (isHighPriority) {
        window._videoHashQueue = boundedCandidates;
    } else {
        boundedCandidates.forEach(c => {
            const cKey = c.item.rel_path || c.item.filename;
            if (!window._videoHashQueue.some(q => (q.item.rel_path || q.item.filename) === cKey)) {
                window._videoHashQueue.push(c);
            }
        });
    }

    processNextVideoHashJob();
}

let _dupUIRefreshTimer = null;
function scheduleDebouncedDuplicateUIRefresh() {
    if (_dupUIRefreshTimer) return;
    _dupUIRefreshTimer = setTimeout(() => {
        _dupUIRefreshTimer = null;
        if (!activeChat) return;
        const runUpdate = () => {
            if (!activeChat) return;
            const prevDupCount = window._currentChatDupSet ? window._currentChatDupSet.size : 0;
            activeChat._dupCache = null;
            const { chatDupSet, dupInfoMap, duplicateGroups } = computeChatDuplicates(activeChat);
            window._currentChatDupSet = chatDupSet;
            window._currentChatDupInfo = dupInfoMap;
            window._currentChatDuplicateGroups = duplicateGroups;
            updateDuplicateReviewButtonUI();

            const hideDuplicates = document.getElementById('hideDuplicatesFilter')?.checked;
            if (hideDuplicates && chatDupSet.size !== prevDupCount) {
                filterAndRenderMedia({ preserveScroll: true, keepItemsCount: true });
            } else {
                updateGridDuplicateBadges();
            }
        };
        if (typeof requestAnimationFrame === 'function') {
            requestAnimationFrame(runUpdate);
        } else {
            runUpdate();
        }
    }, 300);
}

async function processNextVideoHashJob() {
    if (window._isVideoHashingRunning) return;
    if (!window._videoHashQueue || window._videoHashQueue.length === 0) return;

    // Zero UI Lag guarantee: If user is actively scrolling, touching, or typing, yield completely
    if (Date.now() - _lastUserInteractionTimestamp < 500) {
        setTimeout(processNextVideoHashJob, 400);
        return;
    }
    // Save CPU & power when tab is hidden or minimized
    if (typeof document !== 'undefined' && document.hidden) {
        setTimeout(processNextVideoHashJob, 1000);
        return;
    }

    window._isVideoHashingRunning = true;
    const job = window._videoHashQueue.shift();

    // Discard job immediately if user has switched away to another chat
    if (!activeChat || activeChat.jid !== job.chatJid) {
        window._isVideoHashingRunning = false;
        setTimeout(processNextVideoHashJob, 50);
        return;
    }

    try {
        const hashes = await computeVideo3FrameHash(job.item);
        if (hashes && activeChat && activeChat.jid === job.chatJid) {
            scheduleDebouncedDuplicateUIRefresh();
        }
    } catch (e) {
        // Non-fatal
    } finally {
        window._isVideoHashingRunning = false;
        const delay = (activeChat && activeChat.jid === job.chatJid) ? 250 : 800;
        if (typeof window.requestIdleCallback === 'function') {
            window.requestIdleCallback(() => setTimeout(processNextVideoHashJob, delay), { timeout: 1500 });
        } else {
            setTimeout(processNextVideoHashJob, delay);
        }
    }
}

function updateGridDuplicateBadges() {
    const cards = document.querySelectorAll('.media-card[data-rel-path]');
    const hideDuplicates = document.getElementById('hideDuplicatesFilter')?.checked;
    cards.forEach(card => {
        const relPath = card.getAttribute('data-rel-path');
        if (!relPath) return;
        const isDup = window._currentChatDupSet && window._currentChatDupSet.has(relPath);
        if (hideDuplicates && isDup) {
            card.style.display = 'none';
        }
        const badgeContainer = card.querySelector('.card-badges-left');
        if (!badgeContainer) return;
        let dupBadge = badgeContainer.querySelector('.badge-tag-dup');
        if (isDup && !dupBadge) {
            const dupInfo = (window._currentChatDupInfo && window._currentChatDupInfo[relPath]) || {};
            const primaryName = dupInfo.primaryFilename || '';
            const title = primaryName ? `Duplicate (Copy of ${primaryName})` : 'Duplicate';
            const el = document.createElement('div');
            el.className = 'badge-tag badge-tag-dup';
            el.title = title;
            el.innerText = 'DUPLICATE';
            badgeContainer.prepend(el);
        } else if (!isDup && dupBadge) {
            dupBadge.remove();
        }
    });
    updateDuplicateCountBadgesUI();
}
