/* Persist / restore last chat and filter state
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

// Save and Restore App State
function saveAppState() {
    if (!activeChat) return;
    const state = {
        activeChatJid: activeChat.jid,
        activeTypes: Array.from(activeTypes),
        activeType: activeTypes.has('all') ? 'all' : Array.from(activeTypes).join(','),
        searchQuery: document.getElementById('searchFilter').value,
        selectedSender: document.getElementById('senderFilter').value,
        startDateVal: document.getElementById('startDateFilter').value,
        endDateVal: document.getElementById('endDateFilter').value,
        hideDuplicates: document.getElementById('hideDuplicatesFilter').checked,
        directionVal: document.getElementById('directionFilter').value,
        starredOnly: document.getElementById('starredFilter').checked,
        forwardedOnly: document.getElementById('forwardedFilter').checked,
        freqForwardedOnly: document.getElementById('freqForwardedFilter').checked,
        sortBy: document.getElementById('sortFilter').value
    };
    try {
        localStorage.setItem('wa_media_organizer_state', JSON.stringify(state));
    } catch (e) {}
}

async function restoreAppState() {
    let stateStr = null;
    try {
        stateStr = localStorage.getItem('wa_media_organizer_state');
    } catch (e) {}
    if (!stateStr) {
        const chats = getChatsArray();
        if (chats && chats.length > 0) {
            await selectChat(chats[0], false);
        } else {
            renderGallery();
        }
        return;
    }
    try {
        const state = JSON.parse(stateStr);
        const targetChat = getChatsArray().find(c => c.jid === state.activeChatJid);
        if (!targetChat) {
            const chats = getChatsArray();
            if (chats && chats.length > 0) {
                await selectChat(chats[0], false);
            } else {
                renderGallery();
            }
            return;
        }

        await selectChat(targetChat, false);

        if (state.searchQuery) document.getElementById('searchFilter').value = state.searchQuery;
        if (state.selectedSender) {
            // Only restore a sender that still exists, otherwise the select falls back to '' and hides everything
            const senderSelect = document.getElementById('senderFilter');
            if (Array.from(senderSelect.options).some(o => o.value === state.selectedSender)) {
                senderSelect.value = state.selectedSender;
            }
        }
        if (state.sortBy) document.getElementById('sortFilter').value = state.sortBy;
        if (state.hideDuplicates !== undefined) document.getElementById('hideDuplicatesFilter').checked = state.hideDuplicates !== false;
        if (state.directionVal) document.getElementById('directionFilter').value = state.directionVal;
        if (state.starredOnly !== undefined) document.getElementById('starredFilter').checked = !!state.starredOnly;
        if (state.forwardedOnly !== undefined) document.getElementById('forwardedFilter').checked = !!state.forwardedOnly;
        if (state.freqForwardedOnly !== undefined) document.getElementById('freqForwardedFilter').checked = !!state.freqForwardedOnly;
        if (state.startDateVal) document.getElementById('startDateFilter').value = state.startDateVal;
        if (state.endDateVal) document.getElementById('endDateFilter').value = state.endDateVal;
        if (state.startDateVal || state.endDateVal) {
            calSelectedStartDate = state.startDateVal || null;
            calSelectedEndDate = state.endDateVal || null;
            if (state.startDateVal) {
                const parts = state.startDateVal.split('-');
                if (parts.length >= 2) {
                    calCurrentYear = parseInt(parts[0], 10);
                    calCurrentMonth = parseInt(parts[1], 10) - 1;
                }
            }
        }
        updateDateFilterButtonUI();

        if (state.activeTypes && Array.isArray(state.activeTypes)) {
            activeTypes = new Set(state.activeTypes);
        } else if (state.activeType) {
            if (state.activeType.includes(',')) {
                activeTypes = new Set(state.activeType.split(','));
            } else {
                activeTypes = new Set([state.activeType]);
            }
        } else {
            activeTypes = new Set(['all']);
        }
        updateTypeFilterButtonsUI();

        filterAndRenderMedia();
    } catch (e) {
        console.error("Failed to restore app state:", e);
    }
}
