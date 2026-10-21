/**
 * Test Suite: deleting media and showing it in the file manager
 * - Recycle Bin rows have Restore and Delete; selection offers Restore/Delete Selected
 * - the gallery's right-click menu offers Move to Recycle Bin and Delete Permanently
 * - the permanent-delete warning tells the truth (gone for good; the phone copy comes back on sync)
 * - "Show in ..." uses the system's own file manager name
 */

const assert = require('assert');
const vm = require('vm');
const { loadGallerySources } = require('./gallery_sources');

const src = loadGallerySources();
const code = (name) => src.scripts.find(s => s.path.endsWith(name)).code;

console.log('======================================================================');
console.log('RUNNING TEST SUITE: DELETE & SHOW IN FILE MANAGER');
console.log('======================================================================');

// ---------------------------------------------------------------------------
console.log('\n[TEST 1] Wiring...');
['ctxActionRecycle', 'ctxActionDelete', 'btnDeleteSelected'].forEach(id =>
    assert(src.html.includes(`id="${id}"`), `Missing #${id}`));
assert(/executeDeleteRecycledItem\('\$\{escapeJsAttr\(item\.rel_path\)\}'\)/.test(src.js), 'each Recycle Bin row has a Delete button');
assert(/class="recycle-item-meta"/.test(src.js), 'row details use the aligned grid');
assert(/grid-template-columns: minmax\(0, 1fr\) 96px 120px/.test(src.css), 'chat, size and reason sit in fixed columns');
assert(src.js.includes("fetch('/api/media/delete'"), 'gallery delete calls the permanent-delete API');
assert(src.js.includes("fetch('/api/duplicates/purge-items'"), 'single Recycle Bin items can be deleted');
assert(/e\.key === 'Delete'/.test(src.js) && /e\.shiftKey \? |if \(e\.shiftKey\)/.test(src.js), 'Delete / Shift+Delete shortcuts');
console.log('  -> Passed.');

// ---------------------------------------------------------------------------
console.log('\n[TEST 2] Warnings and labels...');
const sandbox = { navigator: { platform: 'MacIntel' }, document: { querySelectorAll: () => [] }, console };
vm.createContext(sandbox);
vm.runInContext(code('core/format.js'), sandbox);
vm.runInContext(code('features/recycle-bin.js'), sandbox);
assert.strictEqual(sandbox.fileManagerName(), 'Finder');
sandbox.navigator.platform = 'Win32';
assert.strictEqual(sandbox.fileManagerName(), 'File Explorer');
sandbox.navigator.platform = 'Linux x86_64';
assert.strictEqual(sandbox.fileManagerName(), 'Files');
const one = sandbox.permanentDeleteWarning(1);
const many = sandbox.permanentDeleteWarning(3);
assert(/this file permanently/.test(one) && /these 3 files permanently/.test(many));
assert(/cannot be undone/i.test(one), 'says it cannot be undone');
assert(/next sync will download it again/.test(one), 'explains that the phone copy comes back on the next sync');
console.log('  -> Passed: Finder / File Explorer / Files; honest warning text.');

console.log('\nALL DELETE UI TESTS PASSED');
