/**
 * Test Suite: Guided WhatsApp key setup panel (gallery_assets/js/features/wa-guide.js)
 * Which view shows for each guide status, the manual-slides fallback, and that WhatsApp's own
 * text (dialog messages) is escaped.
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const ROOT = path.resolve(__dirname, '..', '..');

console.log('======================================================================');
console.log('RUNNING TEST SUITE: GUIDED KEY SETUP PANEL');
console.log('======================================================================');

const ctx = { console, navigator: {}, document: { getElementById: () => null }, setInterval, clearInterval, setTimeout };
vm.createContext(ctx);
for (const rel of ['gallery_assets/js/core/escape.js', 'gallery_assets/js/features/wa-guide.js']) {
    vm.runInContext(fs.readFileSync(path.join(ROOT, rel), 'utf8'), ctx, { filename: rel });
}
const view = (c) => ctx.buildWaGuideView(Object.assign({ deviceReady: true, keySet: false, showManual: false }, c));
const steps = [{ key: 'settings', title: 'Open WhatsApp Settings', state: 'done' }, { key: 'chats', title: 'Chats', state: 'active' }];

// 1. No phone: manual slides, no buttons that need the phone
let v = view({ deviceReady: false, guide: { phase: 'idle' } });
assert.strictEqual(v.state, 'no_phone');
assert.ok(v.showManual);
assert.ok(!v.html.includes('Do it for me'));
console.log('  -> Passed: without a phone the manual steps show');

// 2. Start card: both modes, have-key and manual links; manual hidden by default
v = view({ guide: { phase: 'idle' } });
assert.strictEqual(v.state, 'start');
assert.ok(!v.showManual);
for (const t of ['Do it for me', 'Guide me step by step', 'I already have my key', 'Show all steps instead']) assert.ok(v.html.includes(t), t);
assert.ok(!view({ guide: { phase: 'idle' }, haveKeyOpen: false }).html.includes('wagKeyInput'));
const hk = view({ guide: { phase: 'idle' }, haveKeyOpen: true }).html;
assert.ok(hk.includes('Paste key') && hk.includes('wagKeyInput') && hk.includes('older version'), 'paste + older-version import');
assert.ok(view({ guide: { phase: 'idle' }, keySet: true, maskedKey: 'abcd…wxyz' }).html.includes('already saved'));
assert.ok(view({ guide: { phase: 'idle' }, keySet: true }).showFinish, 'a saved key can finish right away');
console.log('  -> Passed: start card offers auto, guided, have-key and manual');

// 3. Running: instruction, mode switch, steps, never Finish mid-way
v = view({ guide: { active: true, phase: 'running', mode: 'auto', input_allowed: true, instruction: 'Tapping “Chats”…', steps } });
assert.strictEqual(v.state, 'running');
assert.ok(v.html.includes('Doing it for you') && v.html.includes('Let me tap myself') && v.html.includes('Stop'));
assert.ok(v.html.includes('wag-step-done') && v.html.includes('wag-step-active'));
assert.ok(!v.showFinish, 'Finish would close the guide before Create');
v = view({ guide: { active: true, phase: 'running', mode: 'guide', input_allowed: false, notice: 'This phone does not let apps tap for you.', steps } });
assert.ok(v.html.includes('Follow along') && !v.html.includes('Do it for me'), 'no auto switch when taps are blocked');
assert.ok(v.html.includes('does not let apps tap'));
v = view({ guide: { active: true, phase: 'needs_user', mode: 'auto', instruction: 'Confirm with your screen lock on the phone.', steps } });
assert.ok(v.html.includes('Your turn'));
v = view({ guide: { active: true, phase: 'low_storage', mode: 'auto', warning: 'only 0.3 GB free', steps } });
assert.ok(v.html.includes('Continue anyway'));
v = view({ guide: { active: true, phase: 'running', mode: 'auto', key_captured: true, masked_key: '0123…cdef', steps } });
assert.ok(v.html.includes('Key read from your phone and saved (0123…cdef)'));
console.log('  -> Passed: running view, your-turn, low storage and key captured');

// 3b. The tutorial screenshot of the same screen shows in both modes
ctx.TUTORIAL_SLIDES_DATA = Array.from({ length: 12 }, (_, i) => ({ title: 'Slide ' + i }));
for (const mode of ['auto', 'guide']) {
    v = view({ guide: { active: true, phase: 'running', mode, slide: 2, instruction: 'x', steps } });
    assert.ok(v.html.includes('/assets/tutorial/wa_step2.webp'), mode + ' shows the screenshot');
    assert.ok(v.html.includes('Slide 2') && v.html.includes('may look a little different'));
}
v = view({ guide: { active: true, phase: 'running', mode: 'auto', slide: null, instruction: 'x', steps } });
assert.ok(!v.html.includes('wa_step') && v.html.includes('no-shot'), 'no screenshot for screens without one');
console.log('  -> Passed: the matching tutorial screenshot sits beside the live guide');

// 3b'. Newer WhatsApp ("You" tab): its own pictures
for (const key of ['you_home', 'you_page']) {
    v = view({ guide: { active: true, phase: 'running', mode: 'auto', slide: key, instruction: 'x', steps } });
    assert.ok(v.html.includes(`/assets/tutorial/wa_step_${key}.webp`), key);
    assert.ok(fs.existsSync(path.join(ROOT, 'core/assets/tutorial', `wa_step_${key}.webp`)), key + ' picture exists');
}
assert.ok(view({ guide: { active: true, phase: 'running', mode: 'auto', slide: 'you_page', instruction: 'x', steps } }).html.includes('Swipe up'));
v = view({ guide: { active: true, phase: 'running', mode: 'auto', slide: 'nonsense', instruction: 'x', steps } });
assert.ok(!v.html.includes('wa_step'), 'unknown picture names are not used');
const tutSrc = fs.readFileSync(path.join(ROOT, 'gallery_assets/js/features/tutorial.js'), 'utf8');
assert.ok(tutSrc.includes('toggleTutYouVersion') && tutSrc.includes('wa_step_you_home.webp'), 'manual slide 1 can show the You version');
console.log('  -> Passed: the "You" tab pictures for newer WhatsApp');

// 3c. Locked phone, backing up, backup failed
v = view({ guide: { active: true, phase: 'locked', mode: 'auto', instruction: 'Unlock your phone. (This app never enters or sees your PIN.)', steps } });
assert.ok(v.html.includes('Your turn') && v.html.includes('Waiting for you'));
v = view({ guide: { active: true, phase: 'backing_up', mode: 'auto', slide: 11, instruction: 'WhatsApp is making the backup', steps } });
assert.ok(v.showFinish, 'the sync can take over while WhatsApp makes the backup');
assert.ok(!v.html.includes('Let me tap myself'));
v = view({ guide: { active: true, phase: 'backup_failed', mode: 'auto', instruction: 'WhatsApp says: “no space”', storage_warning: 'Your phone has 0.4 GB free', steps } });
assert.ok(v.html.includes('try again') && v.html.includes('waGuideRetryBackup()'));
assert.ok(v.html.includes('0.4 GB free') && v.html.includes('Your key is already saved'));
assert.ok(!v.showFinish);
v = view({ guide: { active: true, phase: 'running', mode: 'auto', storage_warning: 'Your phone has 0.4 GB free', instruction: 'x', steps } });
assert.ok(v.html.includes('0.4 GB free'), 'the storage warning shows from the start');
console.log('  -> Passed: locked phone, backup running and backup failed (with retry)');

// 3d. Paused (another app, a call): progress kept; Continue only when the user left WhatsApp
v = view({ guide: { active: true, phase: 'paused', pause_reason: 'away', mode: 'auto', screen: 'settings', instruction: 'Paused: your phone shows another app.', steps } });
assert.ok(v.state === 'running' && v.html.includes('Paused') && v.html.includes('waGuideContinue()'));
assert.ok(v.html.includes('wag-step-done'), 'the steps done so far stay ticked');
v = view({ guide: { active: true, phase: 'paused', pause_reason: 'call', mode: 'auto', instruction: 'Paused during your phone call.', steps } });
assert.ok(v.html.includes('phone call') && !v.html.includes('waGuideContinue()'), 'no Continue during a call');
v = view({ guide: { active: false, phase: 'paused', pause_reason: 'away', steps } });
assert.strictEqual(v.state, 'running');
console.log('  -> Passed: paused for another app or a call');

// 4. Fallback keeps watching but shows the slides
v = view({ guide: { active: true, phase: 'running', mode: 'auto', fallback: true, fallback_reason: 'Unknown screen.', steps } });
assert.ok(v.showManual && v.html.includes('still watches for your key'));
console.log('  -> Passed: unknown screens bring back the manual steps');

// 5. Already encrypted: the two choices, and the have-key panel after choosing
v = view({ guide: { active: true, phase: 'needs_choice', choice: null } });
assert.ok(v.html.includes('I have my 64-digit key') && v.html.includes('Make a new key'));
assert.ok(!v.html.includes('wagKeyInput'));
v = view({ guide: { active: true, phase: 'have_key', choice: 'have_key' } });
assert.ok(v.html.includes('wagKeyInput') && v.html.includes('Paste key'));
console.log('  -> Passed: existing encrypted backup offers paste/import or a new key');

// 6. Done and errors; WhatsApp text is escaped
v = view({ guide: { phase: 'done', masked_key: '0123…cdef', message: 'WhatsApp is now making the encrypted backup.' } });
assert.ok(v.html.includes('Key saved') && v.html.includes('Finish &amp; Sync Phone'));
assert.ok(!v.showFinish, 'one Finish button, in the card');
v = view({ guide: { active: true, phase: 'running', mode: 'guide', instruction: 'WhatsApp says: “<img src=x onerror=alert(1)>”', steps } });
assert.ok(!v.html.includes('<img') && v.html.includes('&lt;img'));
v = view({ guide: { phase: 'error', message: 'Could not reach the phone' } });
assert.ok(v.state === 'error' && v.html.includes('Could not reach the phone') && v.html.includes('Do it for me'));
console.log('  -> Passed: done, error, and escaping');

// 7. Wiring in the page
const html = fs.readFileSync(path.join(ROOT, 'gallery.html'), 'utf8');
assert.ok(html.includes('id="tutWaGuide"') && html.includes('id="tutManualSteps"'));
assert.ok(html.indexOf('<script src="gallery_assets/js/features/tutorial.js">') < html.indexOf('<script src="gallery_assets/js/features/wa-guide.js">'));
const tut = fs.readFileSync(path.join(ROOT, 'gallery_assets/js/features/tutorial.js'), 'utf8');
assert.ok(tut.includes('waGuideOnTabShown(tab)') && tut.includes('waGuideSyncFooter()'));
console.log('  -> Passed: panel, manual wrapper and hooks are in place');

console.log('\nGUIDED KEY SETUP PANEL TESTS PASSED');
