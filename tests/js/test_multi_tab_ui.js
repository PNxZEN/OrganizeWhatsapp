/**
 * Test Suite: tabs stay in step and closing a tab never cuts off work
 * - a heartbeat that reports a new library version refreshes this tab (never on the first one)
 * - long operations started here mark the tab busy, so closing it asks first
 * - the duplicate-detection choice is saved to the app and picked up from it
 */

const assert = require('assert');
const vm = require('vm');
const { loadGallerySources } = require('./gallery_sources');

const src = loadGallerySources();
const code = (name) => src.scripts.find(s => s.path.endsWith(name)).code;

console.log('======================================================================');
console.log('RUNNING TEST SUITE: MULTI-TAB CONSISTENCY & CLOSE PROTECTION');
console.log('======================================================================');

const listeners = {};
let heartbeatReply = { status: 'ok', data_version: 3 };
const posted = [];
const sandbox = {
    window: { location: { protocol: 'http:' }, addEventListener(type, fn) { (listeners['w:' + type] = listeners['w:' + type] || []).push(fn); } },
    document: { hidden: false, addEventListener(type, fn) { (listeners['d:' + type] = listeners['d:' + type] || []).push(fn); }, getElementById() { return null; } },
    navigator: {},
    localStorage: { _s: {}, getItem(k) { return this._s[k] === undefined ? null : this._s[k]; }, setItem(k, v) { this._s[k] = String(v); } },
    isHttpServer: true,
    fetch: async (url, opts) => {
        posted.push({ url, body: opts && opts.body });
        if (url === '/api/heartbeat') return { ok: true, json: async () => heartbeatReply };
        return { ok: true, json: async () => ({}) };
    },
    setInterval: () => 1, clearInterval() {}, setTimeout, console,
};
sandbox.window.addEventListener = sandbox.window.addEventListener.bind(sandbox.window);
vm.createContext(sandbox);
// tab-lifecycle registers listeners on window/document globals
vm.runInContext('var addEventListener = window.addEventListener;', sandbox);
vm.runInContext(code('core/tab-lifecycle.js'), sandbox);

(async () => {
    // ---------------------------------------------------------------------------
    console.log('\n[TEST 1] Changes made in another tab refresh this one...');
    let refreshes = 0;
    sandbox.applyExternalLibraryChange = () => { refreshes++; };
    await sandbox.sendHeartbeat();
    assert.strictEqual(refreshes, 0, 'the first heartbeat only records the version');
    await sandbox.sendHeartbeat();
    assert.strictEqual(refreshes, 0, 'no change, no refresh');
    heartbeatReply = { status: 'ok', data_version: 4 };
    await sandbox.sendHeartbeat();
    assert.strictEqual(refreshes, 1, 'a new library version refreshes the tab');
    const vis = listeners['d:visibilitychange'] || [];
    assert(vis.length, 'switching back to the tab must check for changes at once');
    console.log('  -> Passed: refresh on version change only, and on returning to the tab.');

    // ---------------------------------------------------------------------------
    console.log('\n[TEST 2] Closing the tab during a long operation asks first...');
    const beforeUnload = (listeners['w:beforeunload'] || [])[0];
    assert(beforeUnload, 'beforeunload handler registered');
    const ev = () => ({ prevented: false, preventDefault() { this.prevented = true; }, returnValue: undefined });
    let e = ev(); beforeUnload(e);
    assert.strictEqual(e.prevented, false, 'idle tab closes without a prompt');
    let release;
    const gate = new Promise(r => { release = r; });
    sandbox.fetch = async () => { await gate; return { ok: true }; };
    const pending = sandbox.trackedFetch('zip-backup', '/api/backup-chat', {});
    e = ev(); beforeUnload(e);
    assert.strictEqual(e.prevented, true, 'a running ZIP backup must make closing ask first');
    release(); await pending;
    e = ev(); beforeUnload(e);
    assert.strictEqual(e.prevented, false, 'the prompt goes away when it finishes');
    sandbox.setBusyOperation('import', true);
    e = ev(); beforeUnload(e);
    assert.strictEqual(e.prevented, true, 'a running import too');
    sandbox.setBusyOperation('import', false);
    console.log('  -> Passed: backups, cleanups, restores and imports protect the tab.');

    // ---------------------------------------------------------------------------
    console.log('\n[TEST 3] Wiring...');
    ['/api/backup-chat', '/api/backup-files', '/api/clean/execute', '/api/restore/chat'].forEach(url =>
        assert(new RegExp(`trackedFetch\\('[\\w-]+', '${url.replace(/\//g, '\\/')}'`).test(src.js), `${url} must use trackedFetch`));
    assert(src.js.includes("setBusyOperation('import', job.state === 'running')"), 'import polling marks the tab busy');
    assert(src.js.includes('async function applyExternalLibraryChange'), 'refresh function exists');
    assert(/duplicate_detection: !!enabled/.test(src.js), 'the duplicate setting is saved to the app');
    assert(/cfg\.duplicate_detection/.test(src.js), 'and read back from it');
    assert(/key === 'wa_setting_duplicate_detection'/.test(src.js), 'other tabs of this browser follow at once');
    assert(/document\.hidden && Date\.now\(\) - _lastDevicePoll < 60000/.test(src.js), 'hidden tabs poll the phone rarely');
    console.log('  -> Passed.');

    console.log('\nALL MULTI-TAB TESTS PASSED');
    process.exit(0);
})().catch(err => { console.error(err); process.exit(1); });
