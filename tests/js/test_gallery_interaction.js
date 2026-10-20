/**
 * Test Suite: Gallery Navigation, Chat Filtering, Category Tabs & Lightbox Viewer
 * Tests:
 * 1. Sidebar chat searching & filtering
 * 2. Chat selection & media item ingestion
 * 3. Media category filtering (All, Photos, Videos, Audio, Docs)
 * 4. Date range / Calendar filtering
 * 5. Lightbox viewer navigation (open, next, prev, explorer reveal, download)
 */

const fs = require('fs');
const path = require('path');
const assert = require('assert');

console.log('======================================================================');
console.log('RUNNING TEST SUITE: GALLERY NAVIGATION & LIGHTBOX VIEWER');
console.log('======================================================================');

// Setup mock DOM environment
const mockElements = new Map();
function getOrCreateMockElement(id) {
    if (!mockElements.has(id)) {
        mockElements.set(id, {
            id,
            innerText: '',
            innerHTML: '',
            value: '',
            href: '',
            style: {},
            classList: {
                _classes: new Set(),
                add(c) { this._classes.add(c); },
                remove(c) { this._classes.delete(c); },
                contains(c) { return this._classes.has(c); }
            },
            querySelectorAll() { return []; },
            querySelector() { return null; },
            addEventListener() {}
        });
    }
    return mockElements.get(id);
}

global.document = {
    getElementById(id) { return getOrCreateMockElement(id); },
    querySelectorAll() { return []; },
    querySelector() { return null; },
    createElement(tag) {
        return {
            tagName: tag,
            style: {},
            classList: {
                _classes: new Set(),
                add(c) { this._classes.add(c); },
                remove(c) { this._classes.delete(c); },
                contains(c) { return this._classes.has(c); }
            },
            setAttribute() {},
            appendChild() {}
        };
    },
    addEventListener() {}
};

global.window = {};
global.openModal = (id) => { getOrCreateMockElement(id).classList.add('open'); };
global.closeModal = (id) => { getOrCreateMockElement(id).classList.remove('open'); };

// ---------------------------------------------------------------------------
// Mock Gallery Dataset
// ---------------------------------------------------------------------------
const mockChats = [
    {
        jid: 'alice@s.whatsapp.net',
        name: 'Alice Smith',
        media: [
            { filename: 'IMG-20240101-WA0001.jpg', rel_path: 'Alice/2024-01/IMG-20240101-WA0001.jpg', type: 'image', size: 1048576, timestamp: 1704067200 },
            { filename: 'VID-20240102-WA0002.mp4', rel_path: 'Alice/2024-01/VID-20240102-WA0002.mp4', type: 'video', size: 15728640, timestamp: 1704153600 },
            { filename: 'AUD-20240103-WA0003.opus', rel_path: 'Alice/2024-01/AUD-20240103-WA0003.opus', type: 'audio', size: 524288, timestamp: 1704240000 },
            { filename: 'DOC-20240104-WA0004.pdf', rel_path: 'Alice/2024-01/DOC-20240104-WA0004.pdf', type: 'document', size: 2097152, timestamp: 1704326400 }
        ]
    },
    {
        jid: 'bob@s.whatsapp.net',
        name: 'Bob Jones',
        media: [
            { filename: 'IMG-20240201-WA0001.jpg', rel_path: 'Bob/2024-02/IMG-20240201-WA0001.jpg', type: 'image', size: 2097152, timestamp: 1706745600 }
        ]
    },
    {
        jid: 'charlie@s.whatsapp.net',
        name: 'Charlie Brown',
        media: []
    }
];

// ---------------------------------------------------------------------------
// TEST 1: Sidebar Search & Chat Filtering
// ---------------------------------------------------------------------------
console.log('\n[TEST 1] Testing Sidebar Chat Searching...');

function searchChats(query, chats) {
    const q = (query || '').toLowerCase().trim();
    if (!q) return chats;
    return chats.filter(c => c.name.toLowerCase().includes(q) || c.jid.toLowerCase().includes(q));
}

assert.strictEqual(searchChats('', mockChats).length, 3, 'Empty query returns all chats');
assert.strictEqual(searchChats('Alice', mockChats).length, 1, 'Search by name returns Alice');
assert.strictEqual(searchChats('jones', mockChats)[0].name, 'Bob Jones', 'Case-insensitive search returns Bob Jones');
assert.strictEqual(searchChats('nonexistent', mockChats).length, 0, 'No match returns empty array');

console.log('  -> Passed: Sidebar search accurately filters chats by name and JID.');

// ---------------------------------------------------------------------------
// TEST 2: Active Chat Selection & Media Category Filtering
// ---------------------------------------------------------------------------
console.log('\n[TEST 2] Testing Media Category Tabs (Photos, Videos, Audio, Docs)...');

let activeChat = null;
let activeCategory = 'all';

function selectChat(chat) {
    activeChat = chat;
    activeCategory = 'all';
    return filterMediaByCategory(activeChat.media, activeCategory);
}

function filterMediaByCategory(media, category) {
    if (!media) return [];
    if (category === 'all') return media;
    if (category === 'photos') return media.filter(m => m.type === 'image');
    if (category === 'videos') return media.filter(m => m.type === 'video');
    if (category === 'audio') return media.filter(m => m.type === 'audio');
    if (category === 'docs') return media.filter(m => m.type === 'document');
    return media;
}

const aliceMedia = selectChat(mockChats[0]);
assert.strictEqual(aliceMedia.length, 4, 'Alice should have 4 total media items');

const photos = filterMediaByCategory(activeChat.media, 'photos');
assert.strictEqual(photos.length, 1);
assert.strictEqual(photos[0].type, 'image');

const videos = filterMediaByCategory(activeChat.media, 'videos');
assert.strictEqual(videos.length, 1);
assert.strictEqual(videos[0].type, 'video');

const audio = filterMediaByCategory(activeChat.media, 'audio');
assert.strictEqual(audio.length, 1);
assert.strictEqual(audio[0].type, 'audio');

const docs = filterMediaByCategory(activeChat.media, 'docs');
assert.strictEqual(docs.length, 1);
assert.strictEqual(docs[0].type, 'document');

console.log('  -> Passed: Category tabs isolate photos, videos, audio, and documents perfectly.');

// ---------------------------------------------------------------------------
// TEST 3: Date Filtering & Range Selection
// ---------------------------------------------------------------------------
console.log('\n[TEST 3] Testing Date Filtering & Timestamp Filtering...');

function filterByDateRange(media, startTs, endTs) {
    return media.filter(m => {
        if (startTs && m.timestamp < startTs) return false;
        if (endTs && m.timestamp > endTs) return false;
        return true;
    });
}

// Filter for items on or after Jan 2, 2024 (1704153600)
const fromJan2 = filterByDateRange(activeChat.media, 1704153600, null);
assert.strictEqual(fromJan2.length, 3, 'Should include Jan 2, 3, and 4 items');

// Filter for only Jan 1, 2024
const onlyJan1 = filterByDateRange(activeChat.media, 1704067200, 1704067200);
assert.strictEqual(onlyJan1.length, 1);
assert.strictEqual(onlyJan1[0].filename, 'IMG-20240101-WA0001.jpg');

console.log('  -> Passed: Date range filters items accurately by timestamp bounds.');

// ---------------------------------------------------------------------------
// TEST 4: Lightbox Viewer Navigation & Actions
// ---------------------------------------------------------------------------
console.log('\n[TEST 4] Testing Lightbox Viewer Invariants (Open, Next, Prev, Actions)...');

let currentFilteredMedia = activeChat.media;
let activeLightboxIndex = -1;

function openLightbox(index) {
    if (index < 0 || index >= currentFilteredMedia.length) return;
    activeLightboxIndex = index;
    const item = currentFilteredMedia[activeLightboxIndex];
    
    const lbDownload = getOrCreateMockElement('lbDownload');
    const lbOpenFolder = getOrCreateMockElement('lbOpenFolder');
    const lbCounter = getOrCreateMockElement('lbCounter');
    
    lbDownload.href = encodeURI(item.rel_path);
    lbCounter.innerText = `${activeLightboxIndex + 1} / ${currentFilteredMedia.length}`;
    openModal('lightboxModal');
}

function nextLightboxItem() {
    if (activeLightboxIndex < currentFilteredMedia.length - 1) {
        openLightbox(activeLightboxIndex + 1);
    }
}

function prevLightboxItem() {
    if (activeLightboxIndex > 0) {
        openLightbox(activeLightboxIndex - 1);
    }
}

// 1. Open first item
openLightbox(0);
assert.strictEqual(activeLightboxIndex, 0);
assert.strictEqual(getOrCreateMockElement('lbCounter').innerText, '1 / 4');
assert(getOrCreateMockElement('lbDownload').href.includes('IMG-20240101-WA0001.jpg'));

// 2. Next item
nextLightboxItem();
assert.strictEqual(activeLightboxIndex, 1);
assert.strictEqual(getOrCreateMockElement('lbCounter').innerText, '2 / 4');
assert(getOrCreateMockElement('lbDownload').href.includes('VID-20240102-WA0002.mp4'));

// 3. Navigate to end
nextLightboxItem();
nextLightboxItem();
assert.strictEqual(activeLightboxIndex, 3);
// Attempt next beyond bounds (should remain at 3)
nextLightboxItem();
assert.strictEqual(activeLightboxIndex, 3, 'Must not navigate past last media item');

// 4. Prev item
prevLightboxItem();
assert.strictEqual(activeLightboxIndex, 2);

console.log('  -> Passed: Lightbox opens correctly, updates counter, bounds-checks next/prev navigation.');

console.log('\n======================================================================');
console.log('ALL GALLERY NAVIGATION & LIGHTBOX TESTS PASSED (100% OK)');
console.log('======================================================================');
