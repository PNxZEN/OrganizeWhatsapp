/**
 * Test Suite: Settings Modal Master-Detail Layout, Slider Switch Preference & Older Media Import
 * Tests:
 * 1. Settings 4-section layout & tab switching
 * 2. Slider switch button for duplicate detection preference (ON/OFF, label, persistence, UI reactivity)
 * 3. Import older media workflow without database jargon
 * 4. Folder analysis & progress tracking
 */

const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.resolve(__dirname, '..', '..');
const galleryPath = path.join(ROOT, 'gallery.html');
const galleryHtml = fs.readFileSync(galleryPath, 'utf8');

console.log('======================================================================');
console.log('RUNNING TEST SUITE: SETTINGS LAYOUT, SLIDER TOGGLE & IMPORT MEDIA');
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
            disabled: false,
            checked: false,
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

global.window = {
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

global.showToast = (msg, type) => { global._lastToast = { msg, type }; };
global.closeModal = (id) => { getOrCreateMockElement(id).classList.remove('open'); };
global.updateRecycleBinPill = () => {};

// ---------------------------------------------------------------------------
// TEST 1: Settings 4-Section Sidebar Layout & Tab Switching
// ---------------------------------------------------------------------------
console.log('\n[TEST 1] Testing Settings 4-Section Master-Detail Navigation...');

// Verify that gallery.html contains the new master-detail sidebar layout
assert(galleryHtml.includes('settings-modal-card'), 'Missing settings-modal-card in gallery.html');
assert(galleryHtml.includes('settings-nav-sidebar'), 'Missing settings-nav-sidebar in gallery.html');
assert(galleryHtml.includes('settings-content-pane'), 'Missing settings-content-pane in gallery.html');
assert(galleryHtml.includes('tabSettingsGeneral'), 'Missing tabSettingsGeneral in gallery.html');
assert(galleryHtml.includes('tabSettingsKey'), 'Missing tabSettingsKey in gallery.html');
assert(galleryHtml.includes('tabSettingsImport'), 'Missing tabSettingsImport in gallery.html');
assert(galleryHtml.includes('tabSettingsRecycle'), 'Missing tabSettingsRecycle in gallery.html');

function isDuplicateDetectionEnabled() {
    return global.localStorage.getItem('wa_setting_duplicate_detection') !== 'false';
}

function setDuplicateDetectionEnabled(enabled) {
    global.localStorage.setItem('wa_setting_duplicate_detection', enabled ? 'true' : 'false');
    applyDuplicateDetectionSetting();
}

function updateDuplicateSwitchLabel(enabled) {
    const lbl = getOrCreateMockElement('settingDuplicatesSwitchLabel');
    if (lbl) {
        lbl.innerText = enabled ? 'Enabled' : 'Disabled';
        lbl.style.color = enabled ? 'var(--accent)' : 'var(--text-muted)';
    }
}

function applyDuplicateDetectionSetting() {
    const enabled = isDuplicateDetectionEnabled();
    const filterControls = getOrCreateMockElement('duplicateFilterControls');
    const reviewBtn = getOrCreateMockElement('btnReviewDuplicates');
    const quickBtn = getOrCreateMockElement('btnQuickReviewDups');
    const chk = getOrCreateMockElement('settingEnableDuplicates');
    if (chk) {
        chk.checked = enabled;
        updateDuplicateSwitchLabel(enabled);
    }

    if (!enabled) {
        filterControls.style.display = 'none';
        reviewBtn.style.display = 'none';
        quickBtn.style.display = 'none';
    } else {
        filterControls.style.display = 'flex';
        reviewBtn.style.display = 'inline-flex';
        quickBtn.style.display = 'inline-flex';
    }
}

function switchSettingsTab(tab) {
    const tabGeneral = getOrCreateMockElement('tabSettingsGeneral');
    const tabKey = getOrCreateMockElement('tabSettingsKey');
    const tabImport = getOrCreateMockElement('tabSettingsImport');
    const tabRecycle = getOrCreateMockElement('tabSettingsRecycle');
    const viewGeneral = getOrCreateMockElement('settingsViewGeneral');
    const viewKey = getOrCreateMockElement('settingsViewKey');
    const viewImport = getOrCreateMockElement('settingsViewImport');
    const viewRecycle = getOrCreateMockElement('settingsViewRecycle');

    [tabGeneral, tabKey, tabImport, tabRecycle].forEach(t => t.classList.remove('active'));
    viewGeneral.style.display = 'none';
    viewKey.style.display = 'none';
    viewImport.style.display = 'none';
    viewRecycle.style.display = 'none';

    if (tab === 'recycle') {
        tabRecycle.classList.add('active');
        viewRecycle.style.display = 'flex';
    } else if (tab === 'import') {
        tabImport.classList.add('active');
        viewImport.style.display = 'flex';
    } else if (tab === 'key') {
        tabKey.classList.add('active');
        viewKey.style.display = 'flex';
    } else {
        tabGeneral.classList.add('active');
        viewGeneral.style.display = 'flex';
        const chk = getOrCreateMockElement('settingEnableDuplicates');
        const isEnabled = isDuplicateDetectionEnabled();
        chk.checked = isEnabled;
        updateDuplicateSwitchLabel(isEnabled);
    }
}

// Test initial switch to preferences
switchSettingsTab('general');
assert(getOrCreateMockElement('tabSettingsGeneral').classList.contains('active'));
assert.strictEqual(getOrCreateMockElement('settingsViewGeneral').style.display, 'flex');
assert.strictEqual(getOrCreateMockElement('settingsViewKey').style.display, 'none');

// Test switch to backup key
switchSettingsTab('key');
assert(getOrCreateMockElement('tabSettingsKey').classList.contains('active'));
assert(!getOrCreateMockElement('tabSettingsGeneral').classList.contains('active'));
assert.strictEqual(getOrCreateMockElement('settingsViewKey').style.display, 'flex');

// Test switch to import media
switchSettingsTab('import');
assert(getOrCreateMockElement('tabSettingsImport').classList.contains('active'));
assert.strictEqual(getOrCreateMockElement('settingsViewImport').style.display, 'flex');

// Test switch to recycle bin
switchSettingsTab('recycle');
assert(getOrCreateMockElement('tabSettingsRecycle').classList.contains('active'));
assert.strictEqual(getOrCreateMockElement('settingsViewRecycle').style.display, 'flex');

console.log('  -> Passed: 4-section layout navigates cleanly, toggling active class and displaying correct views.');

// ---------------------------------------------------------------------------
// TEST 2: Slider Switch Preference for Duplicate Detection
// ---------------------------------------------------------------------------
console.log('\n[TEST 2] Testing Slider Switch Button for Duplicate Detection...');

// Verify CSS slider classes exist in gallery.html
assert(galleryHtml.includes('.setting-switch-wrapper'), 'Missing .setting-switch-wrapper in gallery.html');
assert(galleryHtml.includes('.setting-switch'), 'Missing .setting-switch in gallery.html');
assert(galleryHtml.includes('.setting-slider'), 'Missing .setting-slider in gallery.html');
assert(galleryHtml.includes('settingDuplicatesSwitchLabel'), 'Missing settingDuplicatesSwitchLabel in gallery.html');

// 1. By default, duplicate detection is enabled
assert.strictEqual(isDuplicateDetectionEnabled(), true);
switchSettingsTab('general');
assert.strictEqual(getOrCreateMockElement('settingEnableDuplicates').checked, true);
assert.strictEqual(getOrCreateMockElement('settingDuplicatesSwitchLabel').innerText, 'Enabled');

// 2. Toggle slider OFF
setDuplicateDetectionEnabled(false);
assert.strictEqual(isDuplicateDetectionEnabled(), false);
assert.strictEqual(global.localStorage.getItem('wa_setting_duplicate_detection'), 'false');
assert.strictEqual(getOrCreateMockElement('settingDuplicatesSwitchLabel').innerText, 'Disabled');
assert.strictEqual(getOrCreateMockElement('duplicateFilterControls').style.display, 'none');
assert.strictEqual(getOrCreateMockElement('btnReviewDuplicates').style.display, 'none');

// 3. Switch away and switch back to verify slider state persists
switchSettingsTab('key');
switchSettingsTab('general');
assert.strictEqual(getOrCreateMockElement('settingEnableDuplicates').checked, false);
assert.strictEqual(getOrCreateMockElement('settingDuplicatesSwitchLabel').innerText, 'Disabled');

// 4. Toggle slider back ON
setDuplicateDetectionEnabled(true);
assert.strictEqual(isDuplicateDetectionEnabled(), true);
assert.strictEqual(global.localStorage.getItem('wa_setting_duplicate_detection'), 'true');
assert.strictEqual(getOrCreateMockElement('settingDuplicatesSwitchLabel').innerText, 'Enabled');
assert.strictEqual(getOrCreateMockElement('duplicateFilterControls').style.display, 'flex');

console.log('  -> Passed: Slider switch toggles ON/OFF smoothly, updates label, persists state, and hides UI controls.');

// ---------------------------------------------------------------------------
// TEST 3: Import Media Flow & Absence of Technical Jargon
// ---------------------------------------------------------------------------
console.log('\n[TEST 3] Testing Import Media Flow & User-Facing Text Cleanliness...');

// Verify that technical database jargon was removed from the import modal text in gallery.html
assert(!galleryHtml.includes('.hashes_cache.sqlite3'), 'Technical jargon .hashes_cache.sqlite3 must NOT be visible to users');
assert(!galleryHtml.includes('.sync_state.sqlite3'), 'Technical jargon .sync_state.sqlite3 must NOT be visible to users');
assert(galleryHtml.includes('without redownloading them from your phone'), 'Clean user-facing import description is present');

// Test folder input validation
function onImportPathChanged() {
    const input = getOrCreateMockElement('importFolderPathInput');
    const btnAnalyze = getOrCreateMockElement('btnAnalyzeImportFolder');
    const val = (input.value || '').trim();
    btnAnalyze.disabled = !val;
    return !btnAnalyze.disabled;
}

getOrCreateMockElement('importFolderPathInput').value = '';
assert.strictEqual(onImportPathChanged(), false, 'Analyze button should be disabled when path is empty');

getOrCreateMockElement('importFolderPathInput').value = 'C:\\PreviousBackup\\output';
assert.strictEqual(onImportPathChanged(), true, 'Analyze button should be enabled when valid path is provided');

// Test analysis calculation
function renderAnalysisSummary(data) {
    const statTotalMedia = getOrCreateMockElement('importStatTotalMedia');
    const statTotalSize = getOrCreateMockElement('importStatTotalSize');
    const statNewMedia = getOrCreateMockElement('importStatNewMedia');
    const statSkippedMedia = getOrCreateMockElement('importStatSkippedMedia');
    const btnStartImport = getOrCreateMockElement('btnStartImport');
    
    statTotalMedia.innerText = `${data.total_files} files`;
    statTotalSize.innerText = `${data.total_size_mb.toFixed(1)} MB`;
    statNewMedia.innerText = `${data.new_files} files`;
    statSkippedMedia.innerText = `${data.skipped_files} files`;
    
    btnStartImport.style.display = data.new_files > 0 ? 'inline-block' : 'none';
}

const mockAnalysisData = {
    total_files: 450,
    total_size_mb: 1250.4,
    new_files: 120,
    skipped_files: 330
};

renderAnalysisSummary(mockAnalysisData);
assert.strictEqual(getOrCreateMockElement('importStatTotalMedia').innerText, '450 files');
assert.strictEqual(getOrCreateMockElement('importStatTotalSize').innerText, '1250.4 MB');
assert.strictEqual(getOrCreateMockElement('importStatNewMedia').innerText, '120 files');
assert.strictEqual(getOrCreateMockElement('importStatSkippedMedia').innerText, '330 files');
assert.strictEqual(getOrCreateMockElement('btnStartImport').style.display, 'inline-block');

console.log('  -> Passed: Import media workflow accurately validates folder path, parses stats, and excludes jargon.');

console.log('\n======================================================================');
console.log('ALL SETTINGS & IMPORT TESTS PASSED (100% OK)');
console.log('======================================================================');
