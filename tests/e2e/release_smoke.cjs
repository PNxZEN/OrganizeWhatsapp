/**
 * Release smoke test: drives an installed, running copy of the app in a real browser.
 * Run by .github/workflows/cross-platform.yml on Ubuntu, macOS and Windows.
 *
 * Environment:
 *   BASE_URL          e.g. http://127.0.0.1:8000
 *   OUTPUT_DIR        the gallery's output folder (to check files on disk)
 *   OLDER_DIR         an older output folder to import (tests/e2e/make_fixture.py)
 *   EXPECT_VERSION    version the app must report
 *   SHOTS_DIR         where to save screenshots (optional)
 *   PW_CHROMIUM_PATH  use this Chromium instead of Playwright's (optional)
 */

const fs = require('fs');
const path = require('path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

const BASE = process.env.BASE_URL || 'http://127.0.0.1:8000';
const OUT = process.env.OUTPUT_DIR;
const OLDER = process.env.OLDER_DIR;
const VERSION = process.env.EXPECT_VERSION;
const SHOTS = process.env.SHOTS_DIR || '';

const results = [];
function check(name, ok, detail = '') {
    results.push({ name, ok: !!ok, detail });
    console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  (' + detail + ')' : ''}`);
}

const expectedFileManager = process.platform === 'darwin' ? 'Finder' : process.platform === 'win32' ? 'File Explorer' : 'Files';
const onDisk = (rel) => fs.existsSync(path.join(OUT, ...rel.split('/')));

(async () => {
    const browser = await chromium.launch(process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {});
    const context = await browser.newContext({ viewport: { width: 1366, height: 820 } });
    const page = await context.newPage();
    const pageErrors = [];
    const outsideRequests = [];
    const updateChecks = [];
    context.on('request', q => {
        if (!q.url().startsWith(BASE) && !q.url().startsWith('data:')) outsideRequests.push(q.url());
        if (q.url().includes('/api/update/check')) updateChecks.push(q.url());
    });
    page.on('pageerror', e => pageErrors.push(e.message));
    page.on('dialog', d => d.accept());
    const shot = async (name) => { if (SHOTS) await page.screenshot({ path: path.join(SHOTS, `${process.platform}_${name}.png`) }); };

    // 1. Health and version
    const health = await (await fetch(`${BASE}/api/health`)).json();
    check('server identifies as this app', health.app === 'wa-media-organizer', JSON.stringify(health));
    if (VERSION) check(`reports version ${VERSION}`, health.version === VERSION, health.version);

    // 2. Gallery loads
    await page.goto(`${BASE}/gallery.html`);
    await page.waitForTimeout(2000);
    if (await page.locator('#modalTutorial.open').count()) await page.evaluate(() => closeModal('modalTutorial'));
    await shot('01_gallery');
    check('version badge', (await page.locator('#appVersionBadge').innerText()) === `v${health.version}`);
    const chatCount = await page.locator('#chatList .chat-item').count();
    check('chats listed', chatCount === 3, `${chatCount}`);
    await page.locator('#chatList .chat-item', { hasText: 'Andi mandi' }).first().click();
    await page.waitForTimeout(1000);
    const startCards = await page.locator('.media-card').count();
    check('media cards shown for a chat whose name has a comma and emoji', startCards > 0, `${startCards}`);
    check('long chat name has a tooltip', ((await page.locator('#currentChatName').getAttribute('title')) || '').includes('College'));

    // 3. Right-click menu and the system file manager
    await page.locator('.media-card').first().click({ button: 'right' });
    await page.waitForTimeout(300);
    check('context menu opens', await page.locator('#mediaContextMenu').isVisible());
    const revealLabel = await page.locator('#ctxActionReveal span').innerText();
    check(`"Show in ${expectedFileManager}" label`, revealLabel === `Show in ${expectedFileManager}`, revealLabel);
    const revealResp = page.waitForResponse(r => r.url().includes('/api/open-folder'));
    await page.click('#ctxActionReveal');
    const reveal = await revealResp;
    // CI machines may have no desktop session; the call must still not crash the server
    check('show in file manager answered', [200, 500].includes(reveal.status()), `${reveal.status()}`);
    await shot('02_context_menu');

    // 4. Recycle with Undo, then delete permanently
    let rel = await page.locator('.media-card').first().getAttribute('data-rel-path');
    await page.locator('.media-card').first().click({ button: 'right' });
    await page.click('#ctxActionRecycle');
    await page.waitForTimeout(1200);
    check('move to Recycle Bin removes the card', (await page.locator('.media-card').count()) === startCards - 1);
    check('file moved into the Recycle Bin', fs.existsSync(path.join(OUT, '.duplicates_recycle_bin', ...rel.split('/'))));
    await page.locator('#toastContainer .toast button').first().click();
    await page.waitForTimeout(1500);
    check('Undo puts it back', (await page.locator('.media-card').count()) === startCards && onDisk(rel));

    rel = await page.locator('.media-card').first().getAttribute('data-rel-path');
    await page.locator('.media-card').first().click({ button: 'right' });
    await page.click('#ctxActionDelete');
    await page.waitForTimeout(1500);
    check('delete permanently removes the file', !onDisk(rel));
    check('...and its card', (await page.locator('.media-card').count()) === startCards - 1);

    // 5. Recycle Bin: rows aligned, single delete
    await page.evaluate(() => openDuplicateReviewModal('recycle-bin'));
    await page.waitForTimeout(1200);
    await shot('03_recycle_bin');
    const rows = await page.locator('.recycle-bin-item').count();
    check('Recycle Bin lists items', rows >= 1, `${rows}`);
    const metaX = await page.locator('.recycle-item-meta').evaluateAll(els => els.map(e => Math.round(e.children[1].getBoundingClientRect().left)));
    check('size column lines up on every row', new Set(metaX).size <= 1, metaX.join(','));
    const binRel = await page.locator('.recycle-bin-item-cb').first().getAttribute('data-rel-path');
    await page.locator('.recycle-bin-item .recycle-btn-danger').first().click();
    await page.waitForTimeout(1500);
    check('per-item Delete removes it from the bin', (await page.locator('.recycle-bin-item').count()) === rows - 1
        && !fs.existsSync(path.join(OUT, '.duplicates_recycle_bin', ...binRel.split('/'))));
    await page.evaluate(() => closeModal('modalDuplicateReview'));

    // 6. Settings: About (no update check unless asked) and Import
    await page.evaluate(() => openKeyModal('about'));
    await page.waitForTimeout(800);
    await shot('04_about');
    check('About shows the installed version', (await page.locator('#aboutVersionPill').innerText()) === `v${health.version}`);
    check('automatic update check is off by default', !(await page.locator('#settingAutoCheckUpdates').isChecked()));
    if (OLDER) {
        await page.evaluate(() => switchSettingsTab('import'));
        await page.fill('#importFolderPathInput', OLDER);
        await page.evaluate(() => onImportPathChanged());
        await page.click('#btnAnalyzeImportFolder');
        await page.waitForTimeout(2000);
        check('import warns about a different backup key', await page.locator('#importKeyNotice').isVisible());
        await page.click('#btnStartImport');
        await page.locator('#importResultBox').waitFor({ timeout: 60000 });
        await shot('05_import_result');
        const resultText = await page.locator('#importResultDetails').innerText();
        check('import finished and kept the current key', /copied/.test(resultText) && /current key was kept/.test(resultText), resultText.split('\n')[0]);
        await page.evaluate(() => closeModal('modalKey'));
        await page.waitForTimeout(1500);
        check('imported chat appears', (await page.locator('#chatList .chat-item').count()) === 4);
    }

    // 7. Two tabs stay in step
    const second = await context.newPage();
    second.on('pageerror', e => pageErrors.push('tab 2: ' + e.message));
    await second.goto(`${BASE}/gallery.html`);
    await second.waitForTimeout(1500);
    await second.locator('#chatList .chat-item', { hasText: 'Mom' }).first().click();
    await second.waitForTimeout(800);
    const before = await second.locator('.media-card').count();
    const momRel = await second.locator('.media-card').first().getAttribute('data-rel-path');
    await page.evaluate(async (r) => {
        await fetch('/api/duplicates/recycle', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ rel_paths: [r] }) });
    }, momRel);
    await second.bringToFront();
    await second.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
    await second.waitForTimeout(2000);
    check('the other tab drops media recycled elsewhere', (await second.locator('.media-card').count()) === before - 1);

    // 8. Privacy and stability
    check('no request left this computer', outsideRequests.length === 0, outsideRequests.slice(0, 3).join(' '));
    check('no update check was made by itself', updateChecks.length === 0);
    check('no JavaScript errors', pageErrors.length === 0, pageErrors.slice(0, 3).join(' | '));

    await browser.close();
    const failed = results.filter(r => !r.ok);
    console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
    process.exit(failed.length ? 1 : 0);
})().catch(err => {
    console.error(err);
    process.exit(1);
});
