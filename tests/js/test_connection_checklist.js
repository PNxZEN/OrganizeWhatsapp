/**
 * Test Suite: Live connection checklist in the setup guide (phone tab)
 * The three steps tick themselves off from /api/device-status "stage", show stuck hints after a
 * while, and always keep the manual steps readable (fallback for phones USB detection misses).
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const ROOT = path.resolve(__dirname, '..', '..');

console.log('======================================================================');
console.log('RUNNING TEST SUITE: LIVE CONNECTION CHECKLIST');
console.log('======================================================================');

function loadGuide(platform) {
    const elements = {};
    const el = (id) => elements[id] || (elements[id] = {
        id, innerHTML: '', innerText: '', style: {}, attrs: {},
        setAttribute(k, v) { this.attrs[k] = v; },
        classList: { add() {}, remove() {}, contains() { return false; } },
    });
    const ctx = {
        console,
        navigator: { platform, userAgent: platform },
        document: { getElementById: el, querySelectorAll: () => [], addEventListener() {} },
        window: {},
        setTimeout, clearTimeout, setInterval, clearInterval,
        currentDeviceStatus: {},
    };
    vm.createContext(ctx);
    for (const rel of ['gallery_assets/js/core/format.js', 'gallery_assets/js/features/tutorial.js']) {
        vm.runInContext(fs.readFileSync(path.join(ROOT, rel), 'utf8'), ctx, { filename: rel });
    }
    return { ctx, elements };
}

const { ctx, elements } = loadGuide('Win32');
const build = (st, oem = 'samsung', os = 'windows') => ctx.buildConnectionChecklist(st, oem, os);
const states = (m) => m.steps.map(s => s.state).join(',');

// 1. Each stage lights up the right step
let m = build({ connected: false, stage: 'unplugged', stage_seconds: 0 });
assert.strictEqual(states(m), 'active,todo,todo');
assert.ok(m.steps[1].open, 'debugging steps are readable before the cable is in');
assert.ok(!m.steps[0].hint, 'no hint right away');

m = build({ connected: true, usb_debugging: false, stage: 'usb_only', vendor: 'Samsung', model: 'Galaxy S23', stage_seconds: 2 });
assert.strictEqual(states(m), 'done,active,todo');
assert.ok(m.steps[0].title.includes('Galaxy S23'), 'shows which phone was found');
assert.ok(m.steps[1].substeps.length >= 3, 'brand steps listed');
assert.ok(!m.steps[1].substeps.some(s => /allow/i.test(s.title)), '"Allow" lives in step 3, not repeated');

m = build({ connected: true, authorized: false, stage: 'unauthorized', stage_seconds: 1 });
assert.strictEqual(states(m), 'done,done,active');
assert.ok(m.steps[2].open && /Always allow/.test(m.steps[2].detail));

m = build({ connected: true, authorized: true, stage: 'ready', model: 'Pixel 8' });
assert.strictEqual(states(m), 'done,done,done');
assert.ok(m.steps[2].title.includes('Pixel 8'));
console.log('  -> Passed: unplugged, usb_only, unauthorized and ready map to the right steps');

// 2. Older servers without "stage" still work
assert.strictEqual(states(build({ connected: true, authorized: false, usb_debugging: false })), 'done,active,todo');
assert.strictEqual(states(build({ connected: true, authorized: false })), 'done,done,active');
assert.strictEqual(states(build({ connected: true, authorized: true })), 'done,done,done');
assert.strictEqual(states(build(null)), 'active,todo,todo');
console.log('  -> Passed: falls back to connected/authorized when stage is missing');

// 3. Stuck hints appear only after a while, and are specific
assert.ok(build({ stage: 'unplugged', stage_seconds: 25 }).steps[0].hint.includes('step 2'), 'unknown phones: carry on manually');
assert.ok(!build({ stage: 'usb_only', stage_seconds: 10 }).steps[1].hint);
assert.ok(build({ stage: 'usb_only', stage_seconds: 50, vendor: 'Samsung' }).steps[1].hint.includes('Samsung USB Driver'));
assert.ok(!build({ stage: 'usb_only', stage_seconds: 50, vendor: 'Samsung' }, 'samsung', 'mac').steps[1].hint.includes('Driver'), 'driver tip is Windows-only');
assert.ok(build({ stage: 'unauthorized', stage_seconds: 20 }).steps[2].hint.includes('No popup'));
assert.ok(build({ stage: 'offline' }).steps[2].hint.includes('plug it back in'));
assert.ok(build({ stage: 'no_permission' }, 'pixel', 'linux').steps[2].hint.includes('udev') ||
          build({ stage: 'no_permission' }, 'pixel', 'linux').steps[2].hint.includes('android-sdk-platform-tools-common'));
assert.ok(build({ stage: 'no_adb' }, 'pixel', 'linux').steps[1].hint.includes('install.sh'));
assert.ok(build({ stage: 'no_adb' }, 'pixel', 'windows').steps[1].hint.includes('ZIP'));
console.log('  -> Passed: stuck hints wait, then name the likely fix');

// 4. Every brand has steps, Xiaomi skips the security-settings extras
for (const oem of ['xiaomi', 'samsung', 'oneplus', 'vivo', 'motorola', 'nothing', 'pixel', 'unknown-brand']) {
    const subs = build({ stage: 'usb_only' }, oem).steps[1].substeps;
    assert.ok(subs.length >= 3, `${oem} has steps`);
}
assert.ok(!build({ stage: 'usb_only' }, 'xiaomi').steps[1].substeps.some(s => /Install via USB/.test(s.text)));
console.log('  -> Passed: brand steps for every phone, without optional Xiaomi extras');

// 5. Rendering: marks, open steps, and no re-render when nothing changed
ctx.currentDeviceStatus = { connected: true, usb_debugging: false, stage: 'usb_only', vendor: 'Xiaomi', stage_seconds: 3 };
ctx.renderTutOemContent('xiaomi');
const box = elements.tutOemContent;
assert.ok(box.innerHTML.includes('tut-check-done') && box.innerHTML.includes('tut-check-active'));
assert.ok(box.innerHTML.includes('&#10003;'), 'done steps show a tick');
assert.strictEqual(box.attrs['data-stage'], 'usb_only');
const first = box.innerHTML;
box.innerHTML = 'untouched';
ctx.renderTutOemContent('xiaomi');
assert.strictEqual(box.innerHTML, 'untouched', 'unchanged checklist is not re-rendered every poll');
ctx.currentDeviceStatus = { connected: true, authorized: true, stage: 'ready', model: 'Redmi Note 12' };
ctx.renderTutOemContent('xiaomi');
assert.ok(box.innerHTML !== first && box.innerHTML.includes('Redmi Note 12'));
console.log('  -> Passed: renders ticks and skips identical re-renders');

// 6. The page links what the checklist needs
const html = fs.readFileSync(path.join(ROOT, 'gallery.html'), 'utf8');
assert.ok(html.includes('id="tutOemContent"'));
const css = fs.readFileSync(path.join(ROOT, 'gallery_assets/css/tutorial.css'), 'utf8');
for (const cls of ['.tut-check-active', '.tut-check-done', '.tut-check-hint', '.tut-check-substeps']) {
    assert.ok(css.includes(cls), cls);
}
console.log('  -> Passed: markup and styles are present');

console.log('\nCONNECTION CHECKLIST TESTS PASSED');
