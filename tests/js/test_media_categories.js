/**
 * Test Suite: media categories (gallery_assets/js/features/filter-render.js mediaCategory)
 * Stickers, GIFs and voice notes are their own categories, also in libraries organised before
 * "media_kind" was recorded; the type filter offers a button for each.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const ROOT = path.resolve(__dirname, '..', '..');
console.log('======================================================================');
console.log('RUNNING TEST SUITE: MEDIA CATEGORIES');
console.log('======================================================================');

const ctx = { console, document: { getElementById: () => null } };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(ROOT, 'gallery_assets/js/features/filter-render.js'), 'utf8'), ctx);
const cat = (item) => ctx.mediaCategory(item);

// recorded kind first
assert.strictEqual(cat({ filename: 'IMG-1.jpg', mime_type: 'image/jpeg', media_kind: 'sticker' }), 'sticker');
assert.strictEqual(cat({ filename: 'VID-20240101-WA0001.mp4', mime_type: 'video/mp4', media_kind: 'gif' }), 'gif');
assert.strictEqual(cat({ filename: 'PTT-1.opus', mime_type: 'audio/ogg', media_kind: 'voice' }), 'voice');
console.log('  -> Passed: the kind recorded while organising decides');

// older libraries: by name
assert.strictEqual(cat({ filename: 'STK-20230101-WA0003.webp', mime_type: 'image/webp' }), 'sticker');
assert.strictEqual(cat({ filename: 'funny.gif', mime_type: 'image/gif' }), 'gif');
assert.strictEqual(cat({ filename: 'PTT-20230101-WA0001.opus', mime_type: 'audio/ogg' }), 'voice');
assert.strictEqual(cat({ filename: 'IMG-20230101-WA0001.jpg', mime_type: 'image/jpeg' }), 'image');
assert.strictEqual(cat({ filename: 'VID-20230101-WA0001.mp4', mime_type: 'video/mp4' }), 'video');
assert.strictEqual(cat({ filename: 'AUD-20230101-WA0001.mp3', mime_type: 'audio/mpeg' }), 'audio');
assert.strictEqual(cat({ filename: 'report.pdf', mime_type: 'application/pdf', is_doc: true }), 'doc');
assert.strictEqual(cat({ filename: 'photo.jpg', mime_type: 'image/jpeg', is_doc: true }), 'doc', 'a photo sent as a document is a document');
assert.strictEqual(cat({ filename: 'mystery.bin' }), 'doc');
console.log('  -> Passed: older libraries are sorted by WhatsApp file names');

const html = fs.readFileSync(path.join(ROOT, 'gallery.html'), 'utf8');
for (const t of ['all', 'image', 'video', 'gif', 'sticker', 'voice', 'audio', 'doc']) {
    assert.ok(html.includes(`data-type="${t}"`), `filter button ${t}`);
}
console.log('  -> Passed: a filter button for every category');
console.log('\nMEDIA CATEGORY TESTS PASSED');
