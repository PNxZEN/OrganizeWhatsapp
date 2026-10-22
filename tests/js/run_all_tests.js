/**
 * Master Test Runner for all Frontend JavaScript Suites
 * Executes tests across the complete user lifecycle:
 * - Onboarding, Device Detection & Backup Key Decryption
 * - Settings Sidebar Layout, Slider Toggle Preference & Import Media
 * - Gallery Navigation, Filters, Pagination & Lightbox Viewer
 * - Duplicate Detection, Realtime Hashing & Large Chat Stability
 * - Phone Storage Reclaim & Safety Invariant Engine
 */

const { execSync } = require('child_process');
const path = require('path');

const suites = [
    { name: 'Onboarding, Device & Backup Key Decryption', file: 'test_onboarding_and_key.js' },
    { name: 'Settings Layout, Slider Switch & Import Flow', file: 'test_settings_and_import.js' },
    { name: 'Gallery Browsing, Category Filters & Lightbox', file: 'test_gallery_interaction.js' },
    { name: 'Duplicate Detection Engine & Large Dataset Invariants', file: 'test_frontend_engine.js' },
    { name: 'Phone Storage Reclaim Lifecycle & Safety Engine', file: 'test_phone_storage_reclaim.js' },
    { name: 'About & Updates (safe notes, opt-in privacy, restart overlay)', file: 'test_update_ui.js' },
    { name: 'Multi-tab consistency & close protection', file: 'test_multi_tab_ui.js' },
    { name: 'Delete & show in file manager', file: 'test_delete_ui.js' },
    { name: 'Live connection checklist (setup guide)', file: 'test_connection_checklist.js' },
    { name: 'Guided WhatsApp key setup panel', file: 'test_wa_guide_ui.js' }
];

console.log('======================================================================');
console.log('WHATSAPP MEDIA ORGANIZER - MASTER FRONTEND TEST RUNNER');
console.log('======================================================================');

let passedCount = 0;
let failedCount = 0;
const startTime = Date.now();

for (const suite of suites) {
    const filePath = path.join(__dirname, suite.file);
    const suiteStart = Date.now();
    process.stdout.write(`\n[RUNNING] ${suite.name} (${suite.file})...\n`);
    try {
        const out = execSync(`node "${filePath}"`, { stdio: 'inherit' });
        const dur = Date.now() - suiteStart;
        console.log(`[PASS] ${suite.name} (${dur}ms)`);
        passedCount++;
    } catch (err) {
        console.error(`[FAIL] ${suite.name} FAILED!`);
        failedCount++;
    }
}

const totalDur = ((Date.now() - startTime) / 1000).toFixed(2);
console.log('\n======================================================================');
console.log(`MASTER TEST RESULTS: ${passedCount} PASSED, ${failedCount} FAILED in ${totalDur}s`);
console.log('======================================================================');

if (failedCount > 0) {
    process.exit(1);
} else {
    console.log('ALL FRONTEND TEST SUITES COMPLETED WITH 100% SUCCESS!\n');
    process.exit(0);
}
