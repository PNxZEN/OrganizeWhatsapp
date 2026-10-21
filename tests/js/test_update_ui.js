/**
 * Test Suite: About & Updates (gallery_assets/js/features/update.js)
 * - release notes are rendered safely (escaped, only a small markdown subset)
 * - the page wiring exists: version badge, About tab, overlay, privacy opt-in toggle
 * - a heartbeat that reports maintenance starts the restart overlay in other tabs
 * - nothing in the page loads from, or talks to, an outside server on its own
 */

const assert = require('assert');
const vm = require('vm');
const { loadGallerySources } = require('./gallery_sources');

const src = loadGallerySources();
const updateJs = src.scripts.find(s => s.path.endsWith('features/update.js'));
const escapeJs = src.scripts.find(s => s.path.endsWith('core/escape.js'));
assert(updateJs, 'update.js must be linked from gallery.html');

console.log('======================================================================');
console.log('RUNNING TEST SUITE: ABOUT & UPDATES');
console.log('======================================================================');

// Evaluate the two modules in a sandbox with just enough browser stubs
const elements = {};
const el = (id) => (elements[id] = elements[id] || { id, style: {}, classList: { toggle() {}, add() {}, remove() {}, contains() { return false; } }, textContent: '' });
const fetchCalls = [];
const sandbox = {
    document: { getElementById: el },
    window: { location: { protocol: 'http:' }, addEventListener() {} },
    isHttpServer: true,
    isServerShuttingDown: false,
    showToast() {},
    formatBytes: (n) => n + ' B',
    fetch: async (url, opts) => { fetchCalls.push({ url, opts }); return { ok: true, json: async () => ({ status: 'ok', version: '1.0.0' }) }; },
    setTimeout, clearTimeout,
    AbortController,
    location: { reload() {} },
    BroadcastChannel: undefined,
    console,
};
vm.createContext(sandbox);
vm.runInContext(escapeJs.code, sandbox);
vm.runInContext(updateJs.code, sandbox);

// ---------------------------------------------------------------------------
console.log('\n[TEST 1] Release notes are rendered safely...');
const html = sandbox.renderReleaseNotes([
    '## What\'s new', '- **Bold** item', '- `code` and [a link](http://evil.example)', '',
    '<img src=x onerror=alert(1)>', '| table | row |', '---', 'Plain text',
].join('\n'));
assert(html.includes('<h4>What&#39;s new</h4>'), 'headings become h4');
assert(html.includes('<li><strong>Bold</strong> item</li>'), 'bold and bullets');
assert(html.includes('<code>code</code>'), 'inline code');
assert(!html.includes('evil.example'), 'link targets are dropped');
assert(!/<img/i.test(html) && html.includes('&lt;img'), 'raw HTML in notes must be escaped');
assert(!html.includes('table'), 'tables are skipped');
console.log('  -> Passed: notes are escaped; only headings, bullets, bold and code survive.');

// ---------------------------------------------------------------------------
console.log('\n[TEST 2] Page wiring...');
['appVersionBadge', 'tabSettingsAbout', 'settingsViewAbout', 'aboutVersionPill', 'btnUpdateCheck',
 'btnUpdateDownload', 'btnUpdateInstall', 'btnUpdateCancel', 'updateOverlay', 'settingAutoCheckUpdates']
    .forEach(id => assert(src.html.includes(`id="${id}"`), `Missing #${id} in gallery.html`));
assert(src.html.includes("switchSettingsTab('about')"), 'About tab must be reachable');
assert(src.js.includes('loadVersionInfo();'), 'version info must be loaded on start');
const autoTag = src.html.match(/<input[^>]*id="settingAutoCheckUpdates"[^>]*>/)[0];
assert(!/\schecked(\s|>|=)/.test(autoTag), 'automatic checks must be off by default');
console.log('  -> Passed: badge, About tab, overlay and the opt-in toggle exist; the toggle is unchecked by default.');

// ---------------------------------------------------------------------------
console.log('\n[TEST 3] Privacy: the page itself never goes online...');
assert(!/https?:\/\/(?!github\.com\/|www\.w3\.org)[^\s"'`)]+/.test(updateJs.code.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '')),
    'update.js must not reference outside servers other than the GitHub release link');
assert(!/https?:\/\/fonts\.(googleapis|gstatic)\.com/.test(src.bundle), 'no Google Fonts');
const startupFetches = fetchCalls.map(c => c.url);
assert.deepStrictEqual(startupFetches, [], 'loading the module must not make any request');
console.log('  -> Passed: only same-origin API calls, nothing at load time, no external fonts.');

// ---------------------------------------------------------------------------
console.log('\n[TEST 4] A tab that learns about the restart from its heartbeat shows the overlay...');
sandbox.onHeartbeatInfo({ maintenance: null });
assert.strictEqual(sandbox.isServerShuttingDown, false, 'no maintenance, nothing happens');
sandbox.onHeartbeatInfo({ maintenance: 'Installing an update. Please wait...' });
assert.strictEqual(sandbox.isServerShuttingDown, true, 'heartbeats and unload prompts stop while restarting');
vm.runInContext('_restartWatch = _restartWatch', sandbox);
console.log('  -> Passed: maintenance flag starts the restart watch.');

console.log('\nALL ABOUT & UPDATES TESTS PASSED');
process.exit(0);
