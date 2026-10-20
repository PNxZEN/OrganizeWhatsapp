/* Browser back/forward navigation across chats, modals and lightbox
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

window.addEventListener('popstate', (e) => {
    const state = e.state;

    // 0. If a modal or lightbox was just programmatically closed via its X/cancel button,
    // the resulting history.back() was strictly to clean the history stack. Consume it and do nothing else!
    if (window._closingModalViaBack) {
        window._closingModalViaBack = null;
        return;
    }

    // 1. Check if lightbox is open
    const lightbox = document.getElementById('lightbox');
    if (lightbox && lightbox.classList.contains('active')) {
        if (!state || state.view !== 'lightbox') {
            if (typeof window.closeLightbox === 'function') {
                window.closeLightbox(false);
            }
            return;
        }
    }

    // 2. Check if dup compare lightbox is open
    const dupLb = document.getElementById('lightboxDupCompare');
    if (dupLb && dupLb.style.display !== 'none') {
        if (typeof closeDuplicateCompareLightbox === 'function') {
            closeDuplicateCompareLightbox();
            return;
        }
    }

    // 3. Check if exit modal is open
    // If user presses back while exit modal is open, close it safely and do NOT exit.
    // App only exits when user explicitly presses the "Shut Down and Exit" button!
    const exitModal = document.getElementById('modalExit');
    if (_exitModalOpen || (exitModal && exitModal.classList.contains('open'))) {
        cancelExitApp();
        try {
            history.pushState({ app: 'wa_gallery', view: 'gallery_main' }, '');
        } catch (e) {}
        return;
    }

    // 4. Check if any other modal is open
    const topModal = getTopOpenModal();
    if (topModal) {
        if (topModal.id !== 'modalExit') {
            if (!state || state.view !== 'modal' || state.modal !== topModal.id) {
                closeModal(topModal.id, false);
                return;
            }
        }
    }

    // 5. Chat navigation
    if (state && state.view === 'chat' && state.chat) {
        if (!activeChat || activeChat.jid !== state.chat) {
            const currentChats = getChatsArray();
            const target = (currentChats || []).find(c => c.jid === state.chat);
            if (target) selectChat(target, false);
        }
        return;
    } else if (state && state.view === 'modal') {
        openModal(state.modal, false);
        return;
    } else if (state && state.view === 'lightbox') {
        openLightbox(state.index, false);
        return;
    }

    // 6. If inside an active chat and user clicked back towards root:
    if (activeChat && (!state || state.view === 'gallery_main' || state.view === 'exit_trap')) {
        selectChat(null, false);
        try {
            history.pushState({ app: 'wa_gallery', view: 'gallery_main' }, '');
        } catch (e) {}
        return;
    }

    // 7. Last state reached (root of gallery / exit_trap):
    // Show exit confirmation modal instead of navigating to homescreen.
    if (!state || state.view === 'exit_trap') {
        try {
            history.pushState({ app: 'wa_gallery', view: 'modal_exit' }, '');
        } catch (e) {}
        confirmExitApp(false);
    }
});
