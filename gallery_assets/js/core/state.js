/* Shared gallery state and global view helpers
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

let activeChat = null;
let filteredMedia = [];
let itemsToShow = 100;
let renderedCount = 0;
let chatsToShow = 10;
let sidebarSearchQuery = "";
let selectModeActive = false;
let selectedFiles = [];
let currentViewMode = 'gallery'; // 'gallery' | 'reclaim'

function isModalOrLightboxOpen() {
    const openModal = document.querySelector('.modal-overlay.open');
    if (openModal) return true;
    const mediaLightbox = document.getElementById('lightbox');
    if (mediaLightbox && mediaLightbox.classList.contains('active')) return true;
    const dupLb = document.getElementById('lightboxDupCompare');
    if (dupLb && dupLb.style.display !== 'none') return true;
    return false;
}

function isUserTyping() {
    const el = document.activeElement;
    if (!el) return false;
    const tag = (el.tagName || '').toUpperCase();
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
    if (el.isContentEditable) return true;
    return false;
}

function getChatsArray() {
    if (window.GALLERY_DATA && Array.isArray(window.GALLERY_DATA.chats)) {
        return window.GALLERY_DATA.chats;
    }
    if (typeof GALLERY_DATA !== 'undefined' && Array.isArray(GALLERY_DATA.chats)) {
        return GALLERY_DATA.chats;
    }
    return [];
}
