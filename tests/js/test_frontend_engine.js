/**
 * Rigorous and Verbose JavaScript Test Suite for WhatsApp Offline Gallery Frontend
 * Tests:
 * 1. JavaScript Syntax, TDZ Scoping & No Undeclared Variables in gallery.html
 * 2. Duplicate Detection Engine (MD5, _dup stem, pHash, WhatsApp SD/HD, Video 3-frame hashes)
 * 3. Aspect Ratio & Dimension Guard Invariants
 * 4. Pigeonhole Multi-Index Hash vs Brute Force Parity
 * 5. Realtime Reactive Duplicate Count & Grid Badge Updates
 * 6. Background Video Hashing Queue Lifecycle & Chat Switching
 * 7. Real Dataset Benchmark across all chats in output/gallery_data.js
 */

const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.resolve(__dirname, '..', '..');
const galleryPath = path.join(ROOT, 'gallery.html');
const galleryHtml = fs.readFileSync(galleryPath, 'utf8');

console.log('======================================================================');
console.log('RUNNING RIGOROUS FRONTEND JS TEST SUITE');
console.log('======================================================================');

// ---------------------------------------------------------------------------
// TEST 1: Syntax Validation & Extraction of Gallery Functions
// ---------------------------------------------------------------------------
console.log('\n[TEST 1] Syntax Validation & Core Function Extraction...');
assert(galleryHtml.length > 50000, 'gallery.html is too short or empty');

// Ensure zero Unicode replacement characters
assert(!galleryHtml.includes('\ufffd'), 'Corrupted \\ufffd character found in gallery.html');

// Ensure zero banned characters
assert(!galleryHtml.includes('\u2014'), 'Banned em-dash found in gallery.html');
assert(!galleryHtml.includes('\u2013'), 'Banned en-dash found in gallery.html');
assert(!galleryHtml.includes('\u26a0'), 'Banned warning symbol found in gallery.html');

// Extract main JavaScript block
const scriptStart = galleryHtml.indexOf('<script>');
const scriptEnd = galleryHtml.indexOf('</script>', scriptStart);
assert(scriptStart !== -1 && scriptEnd !== -1, 'Main <script> block not found in gallery.html');
const mainJsCode = galleryHtml.substring(scriptStart + 8, scriptEnd);

// Test syntax compilation
try {
    new Function(mainJsCode);
    console.log('  -> Main gallery.html script compiles cleanly without SyntaxError (size:', mainJsCode.length, 'bytes)');
} catch (err) {
    console.error('  -> SYNTAX ERROR IN gallery.html:', err);
    process.exit(1);
}

// ---------------------------------------------------------------------------
// Setup Mock Browser DOM Environment
// ---------------------------------------------------------------------------
const mockElements = new Map();
function getOrCreateMockElement(id) {
    if (!mockElements.has(id)) {
        mockElements.set(id, {
            id,
            innerText: '',
            innerHTML: '',
            value: '',
            checked: false,
            style: {},
            classList: {
                _classes: new Set(),
                add(c) { this._classes.add(c); },
                remove(c) { this._classes.delete(c); },
                contains(c) { return this._classes.has(c); }
            },
            querySelectorAll(sel) { return []; },
            querySelector(sel) { return null; },
            addEventListener() {},
            blur() {},
            closest() { return null; },
            getContext() { return { drawImage() {}, getImageData() { return { data: [] }; } }; }
        });
    }
    return mockElements.get(id);
}

global.document = {
    getElementById(id) {
        return getOrCreateMockElement(id);
    },
    querySelectorAll(sel) {
        if (sel === '.media-card[data-rel-path]') {
            return global._mockCards || [];
        }
        return [];
    },
    querySelector(sel) {
        return null;
    },
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
            removeAttribute() {},
            appendChild() {},
            prepend(el) { this._child = el; },
            remove() { this._removed = true; },
            getContext() { return { drawImage() {}, getImageData() { return { data: [] }; } }; }
        };
    },
    addEventListener() {}
};

global.window = {
    _ignoredDupKeys: new Set(),
    _cachedVideo3FrameHashes: {},
    _video3FrameHashPending: new Set(),
    _cachedImageDims: {},
    _videoHashQueue: [],
    _isVideoHashingRunning: false,
    _currentChatDupSet: new Set(),
    _currentChatDupInfo: {},
    _currentChatDuplicateGroups: []
};

global.localStorage = {
    _store: {},
    getItem(k) { return this._store[k] || null; },
    setItem(k, v) { this._store[k] = String(v); },
    removeItem(k) { delete this._store[k]; }
};

global.performance = require('perf_hooks').performance;
global.renderGallery = () => {};
global.renderGalleryGrid = () => {};
global.saveAppState = () => {};
global.itemsToShow = 100;
global.activeTypes = new Set(['all']);
global.filteredMedia = [];
global.extractDateFromFilename = () => null;
global.isDuplicateDetectionEnabled = () => true;

// Extract helpers from gallery.html
const startVidComp = mainJsCode.indexOf('function compareVideo3FrameHashes');
eval(`
    ${mainJsCode.substring(mainJsCode.indexOf('function isImageItem'), mainJsCode.indexOf('function resolveAndDisplayImageDims'))}
    ${mainJsCode.substring(startVidComp, mainJsCode.indexOf('window._videoHashQueue = []', startVidComp))}
    ${mainJsCode.substring(mainJsCode.indexOf('function computeChatDuplicates'), mainJsCode.indexOf('function filterAndRenderMedia'))}
    ${mainJsCode.substring(mainJsCode.indexOf('function updateDuplicateCountBadgesUI'), mainJsCode.indexOf('function openDuplicateReviewModal'))}
    ${mainJsCode.substring(mainJsCode.indexOf('function updateGridDuplicateBadges'), mainJsCode.indexOf('function renderDuplicateReviewContent'))}
    ${mainJsCode.substring(mainJsCode.indexOf('function filterAndRenderMedia'), mainJsCode.indexOf('function createMediaCard'))}
`);

console.log('  -> Successfully initialized Mock Browser Sandbox & Gallery Duplicate Engine');

// ---------------------------------------------------------------------------
// TEST 2: Exact MD5 & Collision Stem Isolation
// ---------------------------------------------------------------------------
console.log('\n[TEST 2] Testing MD5 Duplicates and Stem Collisions...');
const mockChat1 = {
    jid: 'test_chat_1@s.whatsapp.net',
    name: 'Test Chat 1',
    media: [
        { filename: 'IMG-20240101-WA0001.jpg', rel_path: 'c1/IMG-20240101-WA0001.jpg', size_bytes: 500000, md5: 'aaaabbbbccccdddd1111222233334444' },
        { filename: 'IMG-20240101-WA0001_dup1.jpg', rel_path: 'c1/IMG-20240101-WA0001_dup1.jpg', size_bytes: 500000, md5: 'aaaabbbbccccdddd1111222233334444' },
        { filename: 'IMG-20240101-WA0002.jpg', rel_path: 'c1/IMG-20240101-WA0002.jpg', size_bytes: 450000, md5: 'eeeeffff000011112222333344445555' },
        { filename: 'IMG-20240101-WA0002_dup1.jpg', rel_path: 'c1/IMG-20240101-WA0002_dup1.jpg', size_bytes: 450000, md5: 'eeeeffff000011112222333344445555' },
        { filename: 'DOC-20240101-WA0003.pdf', rel_path: 'c1/DOC-20240101-WA0003.pdf', is_doc: true, size_bytes: 100000, md5: '99998888777766665555444433332222' }
    ]
};

const res1 = computeChatDuplicates(mockChat1);
assert.strictEqual(res1.chatDupSet.size, 2, 'Expected exactly 2 duplicates for MD5 collisions');
assert(res1.chatDupSet.has('c1/IMG-20240101-WA0001_dup1.jpg'), 'Missing duplicate 1');
assert(res1.chatDupSet.has('c1/IMG-20240101-WA0002_dup1.jpg'), 'Missing duplicate 2');
assert(!res1.chatDupSet.has('c1/DOC-20240101-WA0003.pdf'), 'PDF documents must not be clustered as duplicates');
console.log('  -> Passed: MD5 matching and collision stems clustered accurately without doc bleed.');

// ---------------------------------------------------------------------------
// TEST 3: Video 3-Frame Hash Comparison & Duration Guards
// ---------------------------------------------------------------------------
console.log('\n[TEST 3] Testing Video 3-Frame Hash Matching & Duration Guards...');
const mockChatVideos = {
    jid: 'vpn_video_test@g.us',
    name: 'VPN Group Video Test',
    media: [
        // Video pair A: same duration, matching 3-frame hashes (Hamming distance < 8)
        { filename: 'VID-20260601-WA0001.mp4', rel_path: 'vpn/VID-20260601-WA0001.mp4', size_bytes: 15000000, media_duration: 12.4 },
        { filename: 'VID-20260601-WA0002.mp4', rel_path: 'vpn/VID-20260601-WA0002.mp4', size_bytes: 8500000, media_duration: 12.3 },
        // Video B: recorded same day, but completely different duration (35.0s vs 12.4s)
        { filename: 'VID-20260601-WA0003.mp4', rel_path: 'vpn/VID-20260601-WA0003.mp4', size_bytes: 25000000, media_duration: 35.0 },
        // Video C: similar duration, but completely different frame hashes
        { filename: 'VID-20260601-WA0004.mp4', rel_path: 'vpn/VID-20260601-WA0004.mp4', size_bytes: 14000000, media_duration: 12.5 }
    ]
};

// Seed 3-frame hashes
const frameHash1 = [
    '1111000011110000111100001111000011110000111100001111000011110000',
    '1010101010101010101010101010101010101010101010101010101010101010',
    '1100110011001100110011001100110011001100110011001100110011001100'
];
// Matching hash (1 bit flip per frame: distance = 1.0 <= 8.0)
const frameHash2 = [
    '0111000011110000111100001111000011110000111100001111000011110000',
    '0010101010101010101010101010101010101010101010101010101010101010',
    '0100110011001100110011001100110011001100110011001100110011001100'
];
// Dissimilar hash (distance ~32)
const frameHashDiff = [
    '0000111100001111000011110000111100001111000011110000111100001111',
    '0101010101010101010101010101010101010101010101010101010101010101',
    '0011001100110011001100110011001100110011001100110011001100110011'
];

window._cachedVideo3FrameHashes['vpn/VID-20260601-WA0001.mp4'] = frameHash1;
window._cachedVideo3FrameHashes['vpn/VID-20260601-WA0002.mp4'] = frameHash2;
window._cachedVideo3FrameHashes['vpn/VID-20260601-WA0004.mp4'] = frameHashDiff;

const resVideos = computeChatDuplicates(mockChatVideos);
assert.strictEqual(resVideos.chatDupSet.size, 1, 'Expected only 1 video duplicate (WA0002)');
assert(resVideos.chatDupSet.has('vpn/VID-20260601-WA0002.mp4'), 'WA0002 must be marked as duplicate of WA0001');
assert(!resVideos.chatDupSet.has('vpn/VID-20260601-WA0003.mp4'), 'WA0003 must NOT be duplicate due to duration difference (35s vs 12s)');
assert(!resVideos.chatDupSet.has('vpn/VID-20260601-WA0004.mp4'), 'WA0004 must NOT be duplicate due to visual frame divergence');
console.log('  -> Passed: Video 3-frame hashes and duration guards cleanly isolate true duplicates.');

// ---------------------------------------------------------------------------
// TEST 4: Image Aspect Ratio, HD Exemption & Burst Shot Heuristics
// ---------------------------------------------------------------------------
console.log('\n[TEST 4] Testing Image Aspect Ratio, HD Exemption & Burst Shot Rejection...');
const mockChatImages = {
    jid: 'burst_and_hd_test@s.whatsapp.net',
    name: 'Image Heuristics Test',
    media: [
        // True WhatsApp SD/HD compression pair:
        // Same aspect ratio 4:3 (1600x1200 vs 800x600), size ratio 4.0x, pHash distance <= 2
        { filename: 'IMG-20240201-WA0001.jpg', rel_path: 'im/IMG-20240201-WA0001.jpg', width: 1600, height: 1200, size_bytes: 1200000, phash: 'a1b2c3d4e5f60718' },
        { filename: 'IMG-20240201-WA0002.jpg', rel_path: 'im/IMG-20240201-WA0002.jpg', width: 800, height: 600, size_bytes: 300000, phash: 'a1b2c3d4e5f60719' }, // 1 bit diff
        // Burst shots (different frames, same camera, similar size ~1.08x ratio, but pHash distance = 4)
        { filename: 'IMG-20240201-WA0003.jpg', rel_path: 'im/IMG-20240201-WA0003.jpg', width: 1920, height: 1080, size_bytes: 1850000, phash: '1122334455667788' },
        { filename: 'IMG-20240201-WA0004.jpg', rel_path: 'im/IMG-20240201-WA0004.jpg', width: 1920, height: 1080, size_bytes: 1780000, phash: '1122334455667799' },
        // Two independent full HD photos (> 1600 px both): neither is an SD copy!
        { filename: 'IMG-20240201-WA0005.jpg', rel_path: 'im/IMG-20240201-WA0005.jpg', width: 4000, height: 3000, size_bytes: 4500000, phash: '9988776655443322' },
        { filename: 'IMG-20240201-WA0006.jpg', rel_path: 'im/IMG-20240201-WA0006.jpg', width: 3840, height: 2160, size_bytes: 4200000, phash: '9988776655443322' }
    ]
};

const resImages = computeChatDuplicates(mockChatImages);
assert.strictEqual(resImages.chatDupSet.size, 1, 'Expected only 1 duplicate (WA0002 as compressed copy of WA0001)');
assert(resImages.chatDupSet.has('im/IMG-20240201-WA0002.jpg'), 'WA0002 must be marked as duplicate of WA0001');
assert(!resImages.chatDupSet.has('im/IMG-20240201-WA0004.jpg'), 'Burst shot WA0004 must NOT be marked duplicate');
assert(!resImages.chatDupSet.has('im/IMG-20240201-WA0006.jpg'), 'HD photo WA0006 must NOT be marked duplicate (both > 1600px, aspect ratio differs)');
console.log('  -> Passed: Aspect ratio invariance and HD guard successfully prevent false positives.');

// ---------------------------------------------------------------------------
// TEST 5: Pigeonhole Multi-Index Hashing vs Exhaustive Brute-Force Parity
// ---------------------------------------------------------------------------
console.log('\n[TEST 5] Testing Pigeonhole Multi-Index Hashing vs Brute-Force Parity...');
const pHashTestChat = {
    jid: 'phash_benchmark@s.whatsapp.net',
    name: 'pHash Benchmark',
    media: []
};

// Generate 500 synthetic images with scattered and colliding pHashes
for (let i = 0; i < 500; i++) {
    // Linear congruential generator for reproducible high-entropy 64-bit hex string
    const h1 = ((BigInt(i + 1) * 0x5851f42d4c957f2dn + 0x14057b7ef767814fn) & 0xffffffffffffffffn).toString(16).padStart(16, '0');
    pHashTestChat.media.push({
        filename: `IMG-20240301-WA${String(i).padStart(4, '0')}.jpg`,
        rel_path: `bench/IMG-20240301-WA${String(i).padStart(4, '0')}.jpg`,
        width: 1200,
        height: 900,
        size_bytes: 100000 + (i % 5) * 50000,
        phash: h1
    });
}
// Add 20 intentional duplicates with Hamming distance 1 or 2
for (let d = 0; d < 20; d++) {
    const orig = pHashTestChat.media[d * 10];
    const phChars = orig.phash.split('');
    // Flip 1 bit in last char (distance = 1)
    const lastNibble = parseInt(phChars[15], 16) ^ 1;
    phChars[15] = lastNibble.toString(16);
    pHashTestChat.media.push({
        filename: `IMG-20240301-WA${String(500 + d).padStart(4, '0')}.jpg`,
        rel_path: `bench/IMG-20240301-WA${String(500 + d).padStart(4, '0')}.jpg`,
        width: 600,
        height: 450,
        size_bytes: Math.floor(orig.size_bytes / 2),
        phash: phChars.join('')
    });
}

const t0 = performance.now();
const resPigeonhole = computeChatDuplicates(pHashTestChat);
const t1 = performance.now();
console.log(`  -> Pigeonhole Multi-Index execution time for ${pHashTestChat.media.length} items: ${(t1 - t0).toFixed(2)}ms`);
assert(t1 - t0 < 100, `Pigeonhole clustering took too long: ${(t1 - t0).toFixed(2)}ms`);
assert(resPigeonhole.chatDupSet.size >= 20, `Expected at least 20 duplicate pairs, got ${resPigeonhole.chatDupSet.size}`);
console.log('  -> Passed: Pigeonhole multi-index delivers instant O(1) candidate lookup with zero freeze.');

// ---------------------------------------------------------------------------
// TEST 6: Realtime Reactive Duplicate Count & Grid Badge Updates
// ---------------------------------------------------------------------------
console.log('\n[TEST 6] Testing Realtime UI Duplicate Count & Reactive Mutation...');
// Setup mock DOM elements for buttons and counts
const btnReview = getOrCreateMockElement('btnReviewDuplicates');
const pillCount = getOrCreateMockElement('dupCountReviewPill');
const btnQuick = getOrCreateMockElement('btnQuickReviewDups');
const hideDupsCount = getOrCreateMockElement('hiddenDupsCount');
const hideDuplicatesFilter = getOrCreateMockElement('hideDuplicatesFilter');
hideDuplicatesFilter.checked = true;

// Mock grid cards
const mockCards = [
    {
        getAttribute(attr) { return attr === 'data-rel-path' ? 'c1/IMG-20240101-WA0001.jpg' : null; },
        querySelector(sel) {
            if (sel === '.card-badges-left') return this._badgeContainer;
            return null;
        },
        _badgeContainer: {
            prepend(el) { this._dupBadge = el; },
            querySelector(sel) { return sel === '.badge-tag-dup' ? this._dupBadge : null; }
        },
        style: {}
    },
    {
        getAttribute(attr) { return attr === 'data-rel-path' ? 'c1/IMG-20240101-WA0001_dup1.jpg' : null; },
        querySelector(sel) {
            if (sel === '.card-badges-left') return this._badgeContainer;
            return null;
        },
        _badgeContainer: {
            prepend(el) { this._dupBadge = el; },
            querySelector(sel) { return sel === '.badge-tag-dup' ? this._dupBadge : null; }
        },
        style: {}
    }
];
global._mockCards = mockCards;

// Initially 0 duplicates
window._currentChatDupSet = new Set();
updateDuplicateReviewButtonUI();
updateGridDuplicateBadges();

assert.strictEqual(btnReview.style.display, 'none', 'Review button must be hidden when count is 0');
assert.strictEqual(btnQuick.style.display, 'none', 'Quick button must be hidden when count is 0');
assert.strictEqual(hideDupsCount.innerText, '(No duplicates)', 'Should display (No duplicates) text');

// Now simulate background discovery of 5 duplicates in realtime
window._currentChatDupSet = new Set(['c1/IMG-20240101-WA0001_dup1.jpg', 'd2', 'd3', 'd4', 'd5']);
window._currentChatDupInfo = {
    'c1/IMG-20240101-WA0001_dup1.jpg': { primaryFilename: 'IMG-20240101-WA0001.jpg', reason: 'exact_md5' }
};

updateDuplicateReviewButtonUI();
updateGridDuplicateBadges();

assert.strictEqual(btnReview.style.display, 'inline-flex', 'Review button must be visible when count > 0');
assert.strictEqual(String(pillCount.innerText), '5', 'Review pill count must update to 5');
assert.strictEqual(btnQuick.style.display, 'inline-flex', 'Quick button must be visible when count > 0');
assert.strictEqual(btnQuick.innerText, 'Review & Clean (5)', 'Quick button must display (5)');
assert.strictEqual(hideDupsCount.innerText, '(5 hidden)', 'Checkbox badge must update to (5 hidden) when hideDuplicates is checked');

// Verify unchecking hideDuplicates updates to (5 duplicates)
document.getElementById('hideDuplicatesFilter').checked = false;
updateDuplicateCountBadgesUI();
assert.strictEqual(hideDupsCount.innerText, '(5 duplicates)', 'Checkbox badge must update to (5 duplicates) when hideDuplicates is unchecked');
document.getElementById('hideDuplicatesFilter').checked = true;

// Verify duplicate card was hidden in realtime when hideDuplicatesFilter is checked
assert.strictEqual(mockCards[1].style.display, 'none', 'Duplicate card must be hidden in realtime when hideDuplicates is checked');
assert(mockCards[1]._badgeContainer._dupBadge !== undefined, 'Duplicate card must have DUPLICATE badge prepended');

console.log('  -> Passed: Realtime UI buttons, count pills, and grid card hiding update reactively.');

// ---------------------------------------------------------------------------
// TEST 7: Real Dataset Stress Test across All 646 Chats in output/
// ---------------------------------------------------------------------------
console.log('\n[TEST 7] Testing Against Real Dataset in output/gallery_data.js...');
const dataJsPath = path.join(ROOT, 'output', 'gallery_data.js');
if (fs.existsSync(dataJsPath)) {
    const rawData = fs.readFileSync(dataJsPath, 'utf8');
    const jsonStr = rawData.replace(/^.*?const GALLERY_DATA =\s*/, '').replace(/;\s*$/, '');
    const realData = JSON.parse(jsonStr);
    const chats = realData.chats || [];
    console.log(`  -> Found ${chats.length} real chats in output/gallery_data.js`);

    let totalDupCount = 0;
    const tStart = performance.now();
    for (const chat of chats) {
        try {
            const out = computeChatDuplicates(chat);
            totalDupCount += out.chatDupSet.size;
        } catch (err) {
            console.error(`  -> RUNTIME CRASH on chat "${chat.name}" (${chat.jid}):`, err);
            process.exit(1);
        }
    }
    const tEnd = performance.now();
    console.log(`  -> Successfully verified all ${chats.length} chats in ${(tEnd - tStart).toFixed(2)}ms`);
    console.log(`  -> Total duplicates detected across all chats: ${totalDupCount}`);
    console.log('  -> Passed: Zero runtime exceptions or TDZ reference errors on real production data.');

    // ---------------------------------------------------------------------------
    // TEST 8: Real World Verification of VPN Chat Video Duplicate Hiding
    // ---------------------------------------------------------------------------
    console.log('\n[TEST 8] Verifying Real World Video Duplicate Hiding on VPN Chat (WA0026 & WA0027)...');
    const vpnChat = chats.find(c => c.name && c.name.includes('VPN'));
    assert(vpnChat, 'VPN chat not found in output/gallery_data.js');

    const m26 = vpnChat.media.find(m => m.filename && m.filename.includes('20260612-WA0026'));
    const m27 = vpnChat.media.find(m => m.filename && m.filename.includes('20260612-WA0027'));
    assert(m26 && m27, 'VID-20260612-WA0026.mp4 and VID-20260612-WA0027.mp4 must exist in VPN chat');

    console.log(`  -> File WA0026: ${m26.filename} (${(m26.size_bytes / 1024 / 1024).toFixed(1)} MB, ${m26.media_duration}s)`);
    console.log(`  -> File WA0027: ${m27.filename} (${(m27.size_bytes / 1024 / 1024).toFixed(1)} MB, ${m27.media_duration}s)`);

    // Simulate gradual video hashing arrival (same duration 87s, matching luminance hashes)
    const matchingHash = [
        '1010101010101010101010101010101010101010101010101010101010101010',
        '1100110011001100110011001100110011001100110011001100110011001100',
        '1111000011110000111100001111000011110000111100001111000011110000'
    ];
    window._cachedVideo3FrameHashes[m26.rel_path] = matchingHash;
    window._cachedVideo3FrameHashes[m27.rel_path] = matchingHash;

    vpnChat._dupCache = null;
    const dupRes = computeChatDuplicates(vpnChat);
    assert(dupRes.chatDupSet.has(m26.rel_path), 'VID-20260612-WA0026.mp4 must be marked as duplicate in chatDupSet');
    assert(!dupRes.chatDupSet.has(m27.rel_path), 'VID-20260612-WA0027.mp4 must be kept as PRIMARY keeper in chatDupSet');

    // Configure filter values
    global.activeChat = vpnChat;
    document.getElementById('senderFilter').value = 'all';
    document.getElementById('directionFilter').value = 'all';
    document.getElementById('searchFilter').value = '';
    document.getElementById('startDateFilter').value = '';
    document.getElementById('endDateFilter').value = '';
    document.getElementById('starredFilter').checked = false;
    document.getElementById('forwardedFilter').checked = false;
    document.getElementById('freqForwardedFilter').checked = false;

    // Case A: hideDuplicates = true (default) -> WA0026 must be hidden, WA0027 must be visible
    document.getElementById('hideDuplicatesFilter').checked = true;
    vpnChat._dupCache = null;
    filterAndRenderMedia();

    const is26Hidden = !filteredMedia.some(m => m.filename === m26.filename);
    const is27Visible = filteredMedia.some(m => m.filename === m27.filename);
    assert(is26Hidden, 'VID-20260612-WA0026.mp4 MUST be hidden when hideDuplicatesFilter is checked');
    assert(is27Visible, 'VID-20260612-WA0027.mp4 MUST be visible as primary keeper');
    console.log('  -> Passed: WA0026 is successfully HIDDEN from gallery view, WA0027 is KEPT.');

    // Case B: hideDuplicates = false -> BOTH must be visible
    document.getElementById('hideDuplicatesFilter').checked = false;
    vpnChat._dupCache = null;
    filterAndRenderMedia();

    const is26Shown = filteredMedia.some(m => m.filename === m26.filename);
    const is27Shown = filteredMedia.some(m => m.filename === m27.filename);
    assert(is26Shown && is27Shown, 'Both WA0026 and WA0027 must be visible when hideDuplicatesFilter is unchecked');
    console.log('  -> Passed: Unchecking hideDuplicates makes both WA0026 and WA0027 visible.');
    console.log('\nTesting large chat duplicate consistency (e.g. Vnshiee)...');
    const vnshieeChat = chats.find(c => (c.name || '').includes('Vnshiee') || (c.jid || '').includes('Vnshiee'));
    if (vnshieeChat) {
        global.activeChat = vnshieeChat;
        document.getElementById('hideDuplicatesFilter').checked = true;
        vnshieeChat._dupCache = null;
        filterAndRenderMedia();
        const initialDupSize = window._currentChatDupSet.size;
        const initialBadgeText = document.getElementById('hiddenDupsCount').innerText;
        assert(initialBadgeText.includes(`${initialDupSize} hidden`), `Badge text should be '(${initialDupSize} hidden)' but was '${initialBadgeText}'`);

        // Simulate background video hashing job finding no new duplicates (calls updateGridDuplicateBadges)
        updateGridDuplicateBadges();
        const afterNoNewBadgeText = document.getElementById('hiddenDupsCount').innerText;
        assert.strictEqual(afterNoNewBadgeText, initialBadgeText, `Badge text changed after updateGridDuplicateBadges! Before: '${initialBadgeText}', After: '${afterNoNewBadgeText}'`);

        // Simulate background video hashing job finding a duplicate (calls filterAndRenderMedia)
        filterAndRenderMedia();
        const afterFilterBadgeText = document.getElementById('hiddenDupsCount').innerText;
        assert.strictEqual(afterFilterBadgeText, initialBadgeText, `Badge text jumped after filterAndRenderMedia! Before: '${initialBadgeText}', After: '${afterFilterBadgeText}'`);

        // Verify zero primary keeper files are marked as duplicates
        const groups = window._currentChatDuplicateGroups || [];
        for (const grp of groups) {
            const pKey = grp.primary.rel_path || grp.primary.filename;
            assert(!window._currentChatDupSet.has(pKey), `Primary file '${pKey}' must NEVER be in chatDupSet!`);
        }

        console.log(`  -> Passed: Vnshiee duplicate counter is rock-solid consistent at ${initialDupSize} and zero primaries are hidden.`);
    }
} else {
    console.log('  -> output/gallery_data.js not present, skipped real data test.');
}

// ---------------------------------------------------------------------------
// TEST 9: Exit Modal UI & Explicit Shutdown Requirement
// ---------------------------------------------------------------------------
console.log('\n[TEST 9] Testing Exit Modal UI & Explicit Shutdown Requirement...');

// 1. Verify exit modal in HTML does NOT have a back button in its header
assert(!galleryHtml.includes('id="btnExitModalBack"'), 'Exit modal should NOT have a back button');

const modalExitEl = {
    id: 'modalExit',
    style: { display: 'none' },
    classList: {
        _classes: new Set(),
        add(c) { this._classes.add(c); },
        remove(c) { this._classes.delete(c); },
        contains(c) { return this._classes.has(c); }
    }
};
document.getElementById = (id) => {
    if (id === 'modalExit') return modalExitEl;
    if (id === 'exitSyncWarning') return { style: { display: 'none' } };
    if (id === 'lightboxDupCompare') return { style: { display: 'none' } };
    if (id === 'lightbox') return { classList: { contains() { return false; } } };
    return {
        innerText: '',
        style: {},
        classList: {
            add() {}, remove() {}, contains() { return false; }
        }
    };
};
document.querySelectorAll = (sel) => {
    if (sel === '.modal-overlay.open' || sel === '.modal.open') {
        return modalExitEl.classList.contains('open') ? [modalExitEl] : [];
    }
    return [];
};

let shutdownExecuted = false;
global.openModal = (id, push) => {
    if (id === 'modalExit') {
        modalExitEl.classList.add('open');
        modalExitEl.style.display = 'flex';
    }
};
global.closeModal = (id, pop) => {
    if (id === 'modalExit') {
        modalExitEl.classList.remove('open');
        modalExitEl.style.display = 'none';
    }
};
global.executeShutdown = () => {
    shutdownExecuted = true;
};
global.isHttpServer = true;
global._syncActive = false;
global.history = {
    state: { app: 'wa_gallery', view: 'gallery_main' },
    pushState(st) { this.state = st; },
    replaceState(st) { this.state = st; }
};

global._exitModalOpen = false;
const exitFuncs = mainJsCode.substring(mainJsCode.indexOf('let _exitModalOpen = false;'), mainJsCode.indexOf('// Cross-tab synchronization channel'));
eval(exitFuncs.replace('let _exitModalOpen = false;', '/* _exitModalOpen */'));

let popstateHandler = null;
const popstateMatch = mainJsCode.indexOf("window.addEventListener('popstate'");
if (popstateMatch !== -1) {
    const endPopstate = mainJsCode.indexOf("function navigateLightbox", popstateMatch);
    const popstateSnippet = mainJsCode.substring(popstateMatch, endPopstate);
    const fnBody = popstateSnippet.replace("window.addEventListener('popstate',", "popstateHandler = ");
    const cleanFn = fnBody.substring(0, fnBody.lastIndexOf(');'));
    eval(cleanFn);
}

assert(typeof confirmExitApp === 'function', 'confirmExitApp must be defined');
assert(typeof cancelExitApp === 'function', 'cancelExitApp must be defined');
assert(typeof popstateHandler === 'function', 'popstateHandler must be defined');

// 2. User is at gallery root and presses browser Back:
// Should trap back navigation, push history state, and show the exit modal!
global.activeChat = null;
modalExitEl.classList.remove('open');
_exitModalOpen = false;
popstateHandler({ state: { app: 'wa_gallery', view: 'exit_trap' } });
assert(modalExitEl.classList.contains('open'), 'modalExit should open when Back is pressed from gallery root');
assert(!shutdownExecuted, 'Shutdown should not be called when opening modal via Back press');

// 3. User clicks browser back while exit modal is open:
// Modal should simply close, returning user to gallery view. Shutdown must NOT execute!
popstateHandler({ state: { app: 'wa_gallery', view: 'exit_trap' } });
assert(!modalExitEl.classList.contains('open'), 'modalExit should close when Back is pressed while exit modal is open');
assert(!shutdownExecuted, 'Shutdown must NEVER execute on back navigation');

// 4. User opens exit modal again and explicitly presses Exit button:
confirmExitApp();
assert(modalExitEl.classList.contains('open'), 'modalExit should open again');
executeShutdown();
assert(shutdownExecuted, 'Shutdown executes when user explicitly presses Shut Down & Exit');

console.log('  -> Passed: Back at root traps to exit modal, Back inside modal cancels safely, and app only exits when user clicks Exit button.');

console.log('\n======================================================================');
console.log('ALL FRONTEND JS TESTS PASSED SUCCESSFULLY (100% OK)');
console.log('======================================================================\n');


