/**
 * Test Suite: live phone-cleanup progress (gallery_assets/js/features/reclaim.js)
 * Between the phone's confirmations the count moves on at the measured pace, but never past the
 * batch in flight; the final render shows exactly what the phone confirmed.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const ROOT = path.resolve(__dirname, '..', '..');
console.log('======================================================================');
console.log('RUNNING TEST SUITE: LIVE CLEANUP PROGRESS');
console.log('======================================================================');

const els = {};
const el = (id) => (els[id] = els[id] || { id, style: {}, textContent: '', innerText: '', innerHTML: '' });
let nowMs = 0;
const ctx = {
    console, setInterval: () => 1, clearInterval: () => {}, requestAnimationFrame: () => 1, cancelAnimationFrame: () => {},
    performance: { now: () => nowMs },
    document: { getElementById: el, querySelectorAll: () => [], addEventListener: () => {} },
    window: {}, localStorage: { getItem: () => null, setItem: () => {} },
};
vm.createContext(ctx);
for (const f of ['gallery_assets/js/core/escape.js', 'gallery_assets/js/core/format.js', 'gallery_assets/js/features/reclaim.js']) {
    vm.runInContext(fs.readFileSync(path.join(ROOT, f), 'utf8'), ctx);
}
const setSnap = (o) => { ctx.__snap = o; vm.runInContext('_cleanLive.snap = __snap;', ctx); };
const file = (n, size = 1000) => ({ name: `IMG-${n}.jpg`, chat: 'Family', size });
const current = [file(26), file(27), file(28), file(29), file(30)];

// Prediction: pace 0.1 s per file, 0.25 s into the batch -> 2 files probably gone
const snap = { active: true, total: 30, deleted: 25, freed_bytes: 25000, seconds_per_file: 0.1,
               batch_elapsed: 0.25, current, recent: [file(24), file(25)], failed: 0 };
assert.strictEqual(ctx.cleanLivePrediction(snap, 0), 2);
assert.strictEqual(ctx.cleanLivePrediction(snap, 0.2), 4);
assert.strictEqual(ctx.cleanLivePrediction(snap, 10), 4, 'never the whole batch in flight: the phone has not confirmed it');
assert.strictEqual(ctx.cleanLivePrediction({ ...snap, seconds_per_file: null }, 5), 0, 'no pace measured yet: no guessing');
assert.strictEqual(ctx.cleanLivePrediction({ ...snap, active: false }, 5), 0);
console.log('  -> Passed: the prediction stays inside the batch the phone is working on');

// Render while running
vm.runInContext('_cleanLive.shown = 0; _cleanLive.receivedAt = 0;', ctx);
setSnap(snap);
nowMs = 0;
ctx.renderCleanLiveProgress(false);
assert.ok(el('reclaimExecutionProgressText').innerText.startsWith('27 of 30 files deleted'), el('reclaimExecutionProgressText').innerText);
assert.strictEqual(el('reclaimExecutionProgressBar').style.width, '90.0%');
assert.strictEqual(el('reclaimLiveNowName').textContent, 'IMG-28.jpg', 'the file probably being deleted now');
assert.strictEqual(el('reclaimLiveNow').style.display, 'flex');
assert.ok(el('reclaimLiveRecent').innerHTML.indexOf('IMG-25.jpg') < el('reclaimLiveRecent').innerHTML.indexOf('IMG-24.jpg'), 'newest first');
console.log('  -> Passed: count, bar, file being deleted and confirmed list while running');

// A slower poll never makes the count go back
setSnap({ ...snap, batch_elapsed: 0 });
ctx.renderCleanLiveProgress(false);
assert.ok(el('reclaimExecutionProgressText').innerText.startsWith('27 of 30'), 'the shown count never goes back');
console.log('  -> Passed: the shown count only goes up while running');

// Final render: exactly what the phone confirmed, failures named
setSnap({ ...snap, active: false, deleted: 29, failed: 1, current: [], failed_files: [file(30)],
                        recent: [file(26), file(27), file(28), file(29)], freed_bytes: 29000 });
ctx.renderCleanLiveProgress(true);
assert.ok(el('reclaimExecutionProgressText').innerText.startsWith('29 of 30 files deleted'));
assert.strictEqual(el('reclaimLiveNow').style.display, 'none');
assert.ok(el('reclaimLiveFailed').textContent.includes('IMG-30.jpg'));
console.log('  -> Passed: the final numbers are the confirmed ones');

// File names from the phone are shown as text, not markup
setSnap({ ...snap, active: false, recent: [{ name: '<img src=x onerror=alert(1)>.jpg', chat: '<b>x</b>' }], deleted: 30 });
vm.runInContext('_cleanLive.lastRecentKey = "";', ctx);
ctx.renderCleanLiveProgress(true);
assert.ok(!el('reclaimLiveRecent').innerHTML.includes('<img'), 'names are escaped');
console.log('  -> Passed: file names are escaped');

console.log('\nALL LIVE CLEANUP PROGRESS TESTS PASSED');
