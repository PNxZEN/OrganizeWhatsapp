/* Core filter + sort pipeline
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

// Core filter and render function
function filterAndRenderMedia(options = {}) {
    if (!activeChat) return;

    const preserveScroll = !!(options && options.preserveScroll);
    const targetScrollTop = (options && options.prevScrollTop !== undefined) ? options.prevScrollTop : null;

    if (!preserveScroll) {
        if (!options || !options.keepItemsCount) {
            itemsToShow = 100;
        }
    } else {
        itemsToShow = Math.max(itemsToShow, 100);
    }

    const searchQuery = document.getElementById('searchFilter').value.toLowerCase();
    const selectedSender = document.getElementById('senderFilter').value;
    const startDateVal = document.getElementById('startDateFilter').value;
    const endDateVal = document.getElementById('endDateFilter').value;
    const hideDuplicates = document.getElementById('hideDuplicatesFilter').checked;
    const directionVal = document.getElementById('directionFilter').value;
    const starredOnly = document.getElementById('starredFilter').checked;
    const forwardedOnly = document.getElementById('forwardedFilter').checked;
    const freqForwardedOnly = document.getElementById('freqForwardedFilter').checked;

    // Instant lookup from cached chat duplicates
    const { chatDupSet, dupInfoMap, duplicateGroups } = computeChatDuplicates(activeChat);
    window._currentChatDupSet = chatDupSet;
    window._currentChatDupInfo = dupInfoMap;
    window._currentChatDuplicateGroups = duplicateGroups;
    updateDuplicateReviewButtonUI();

    // Manage Hide Duplicates checkbox and label state
    const hideDuplicatesFilter = document.getElementById('hideDuplicatesFilter');
    const hiddenDupsBadge = document.getElementById('hiddenDupsCount');
    const hideDuplicatesLabel = hideDuplicatesFilter ? hideDuplicatesFilter.closest('label') : null;

    if (chatDupSet.size === 0) {
        if (hideDuplicatesFilter) {
            hideDuplicatesFilter.disabled = true;
        }
        if (hideDuplicatesLabel) {
            hideDuplicatesLabel.style.opacity = '0.5';
            hideDuplicatesLabel.style.cursor = 'not-allowed';
        }
    } else {
        if (hideDuplicatesFilter) {
            hideDuplicatesFilter.disabled = false;
        }
        if (hideDuplicatesLabel) {
            hideDuplicatesLabel.style.opacity = '1';
            hideDuplicatesLabel.style.cursor = 'pointer';
        }
    }

    let hiddenDuplicatesCount = 0;

    const MONTH_NAMES = [
        'january', 'february', 'march', 'april', 'may', 'june',
        'july', 'august', 'september', 'october', 'november', 'december'
    ];
    const MONTH_SHORT = [
        'jan', 'feb', 'mar', 'apr', 'may', 'jun',
        'jul', 'aug', 'sep', 'oct', 'nov', 'dec'
    ];

    // Normalize effective start and end dates
    let effStart = startDateVal;
    let effEnd = endDateVal;
    if (effStart && effEnd && effStart > effEnd) {
        const temp = effStart;
        effStart = effEnd;
        effEnd = temp;
    }

    filteredMedia = (activeChat.media || []).filter(item => {
        // Multi-Attribute Search (Date, Month, Sender, Doc Name, Filename)
        if (searchQuery) {
            const fn = (item.filename || '').toLowerCase();
            const sName = (item.sender_name || '').toLowerCase();
            const sJid = (item.sender_jid || '').toLowerCase();
            const rec = (item.received_at || '').toLowerCase();

            let dateTerms = '';
            if (rec) {
                const datePart = rec.split(' ')[0] || '';
                const parts = datePart.split('-');
                if (parts.length === 3) {
                    const y = parts[0];
                    const mIdx = parseInt(parts[1], 10) - 1;
                    const d = parts[2];
                    if (mIdx >= 0 && mIdx < 12) {
                        dateTerms = `${y} ${MONTH_NAMES[mIdx]} ${MONTH_SHORT[mIdx]} ${d} ${y}-${parts[1]} ${parts[1]}`;
                    }
                }
            }

            const searchable = `${fn} ${sName} ${sJid} ${rec} ${dateTerms}`.toLowerCase();
            const queryTokens = searchQuery.trim().split(/\s+/);
            const allMatch = queryTokens.every(tok => searchable.includes(tok));
            if (!allMatch) {
                return false;
            }
        }

        // Media Type Filter (Multi-select support)
        const mime = item.mime_type || '';
        const isDoc = item.is_doc || false;
        if (!activeTypes.has('all')) {
            let matchesAny = false;
            if (activeTypes.has('image') && !isDoc && mime.startsWith('image/')) matchesAny = true;
            if (activeTypes.has('video') && mime.startsWith('video/')) matchesAny = true;
            if (activeTypes.has('audio') && mime.startsWith('audio/')) matchesAny = true;
            if (activeTypes.has('doc')) {
                if (isDoc || (!mime.startsWith('image/') && !mime.startsWith('video/') && !mime.startsWith('audio/'))) {
                    matchesAny = true;
                }
            }
            if (!matchesAny) return false;
        }

        // Sender filter
        if (selectedSender && selectedSender !== 'all') {
            try {
                const allowedJids = JSON.parse(selectedSender);
                if (!allowedJids.includes(item.sender_jid)) {
                    return false;
                }
            } catch (e) {
                if (item.sender_jid !== selectedSender) return false;
            }
        }

        // Starred filter
        if (starredOnly && !item.starred) {
            return false;
        }

        // Forwarded filter
        if (forwardedOnly && (!item.forward_score || item.forward_score < 1)) {
            return false;
        }

        // Frequently Forwarded filter
        if (freqForwardedOnly && (!item.forward_score || (item.forward_score < 5 && item.forward_score !== 127))) {
            return false;
        }

        // Direction filter
        if (directionVal !== 'all') {
            if (directionVal === 'sent' && !item.from_me) return false;
            if (directionVal === 'received' && item.from_me) return false;
        }

        // Date filter (Single date or date range)
        let itemDate = null;
        if (item.received_at) {
            itemDate = item.received_at.split(' ')[0];
        } else {
            const parsed = extractDateFromFilename(item.rel_path || item.filename);
            if (parsed) itemDate = parsed.dateStr.split(' ')[0];
        }
        if (itemDate) {
            if (effStart && itemDate < effStart) return false;
            if (effEnd && itemDate > effEnd) return false;
        } else if (effStart || effEnd) {
            return false;
        }

        // Duplicate filter
        const isItemDup = chatDupSet.has(item.rel_path || item.filename);
        if (isItemDup) {
            if (hideDuplicates) {
                hiddenDuplicatesCount++;
                return false;
            }
        }

        return true;
    });

    // Update hidden duplicates badge
    updateDuplicateCountBadgesUI();

    // Apply sorting
    const sortBy = document.getElementById('sortFilter').value;
    const getItemSortTime = (item) => {
        if (item.received_at) {
            const t = new Date(item.received_at.replace(/-/g, '/')).getTime();
            if (!isNaN(t)) return t;
        }
        const parsed = extractDateFromFilename(item.rel_path || item.filename);
        if (parsed) {
            const t = new Date(parsed.dateStr.replace(/-/g, '/')).getTime();
            if (!isNaN(t)) return t;
        }
        return 0;
    };
    if (sortBy === 'newest') {
        filteredMedia.sort((a, b) => getItemSortTime(b) - getItemSortTime(a));
    } else if (sortBy === 'oldest') {
        filteredMedia.sort((a, b) => {
            const ta = getItemSortTime(a) || 9999999999999;
            const tb = getItemSortTime(b) || 9999999999999;
            return ta - tb;
        });
    } else if (sortBy === 'largest') {
        filteredMedia.sort((a, b) => (b.size_bytes || 0) - (a.size_bytes || 0));
    } else if (sortBy === 'smallest') {
        filteredMedia.sort((a, b) => (a.size_bytes || 0) - (b.size_bytes || 0));
    }

    renderGallery({ preserveScroll, targetScrollTop });
    saveAppState();
}

// Helper to format duration in seconds to MM:SS
function formatDuration(sec) {
    if (!sec || isNaN(sec) || sec <= 0) return '';
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m}:${s < 10 ? '0' : ''}${s}`;
}
