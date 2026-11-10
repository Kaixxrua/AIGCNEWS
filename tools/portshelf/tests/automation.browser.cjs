// Uses the existing Playwright installation; no new runtime dependency.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const os = require('node:os');
const { chromium } = require(process.env.PORTSHELF_PLAYWRIGHT_MODULE || path.resolve(__dirname, '../../../frontend/node_modules/playwright'));
const { defaultConfig } = require('../web/automation.js');
const webRoot = path.resolve(__dirname, '../web');
const token = 'd'.repeat(48);
let platformSupported = true, failSave = false, failRead = false, statusReads = 0, libraryReads = 0;
let config = { ...defaultConfig('arm64'), rememberCredentials: true, startOnLogin: true };
let running = false, lastError = '', credentialError = '', queued = 0;
const saves = [], actions = [], pageErrors = [], discoveryRequests = [];
let games = [{ repo: 'demo/known', name: '已核验游戏', description: '一款经典的开源移植游戏。', stars: 50 }, { repo: 'demo/unknown', name: 'Windows Linux name', description: '简介提到多个系统，但没有附件核验。', stars: 20 }];
const jobs = [
  { id: 'retry', repo: 'demo/known', name: '可自动恢复', status: 'failed', stage: 'upload', automatic: true, attempts: 2, nextRetryAt: '2027-01-01T01:00:00Z', supportedSystems: ['Windows ARM64', 'macOS', 'Linux x64'], outputs: {} },
  { id: 'attention', repo: 'demo/unknown', name: '需要重新授权', status: 'failed', stage: 'share', automatic: true, attempts: 3, needsAttention: true, error: '验证码 <img src=x onerror="window.injected=1">', supportedSystems: [], outputs: {} },
  { id: 'unscheduled', repo: 'demo/unknown', name: '未安排重试', status: 'failed', stage: 'release', automatic: true, attempts: 1, supportedSystems: [], outputs: {} },
  { id: 'manual', repo: 'demo/unknown', name: '手动失败任务', status: 'failed', stage: 'download', outputs: {} },
];
function status() { return { config, running, nextRun: '2027-01-01T03:00:00Z', lastRun: queued ? '2027-01-01T00:00:00Z' : '', lastError, credentialError, exportDir: 'C:\\PortShelf\\exports', exportedAt: queued ? '2027-01-01T01:00:00Z' : '', discovered: queued * 2, queued, unsupported: queued, credentialStorageSupported: platformSupported, startOnLoginSupported: platformSupported }; }
const wait = delay => new Promise(resolve => setTimeout(resolve, delay));
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://local');
  const json = (value, code = 200) => { res.statusCode = code; res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(value)); };
  if (url.pathname.startsWith('/api/')) {
    assert.equal(req.headers.authorization, 'Bearer ' + token);
    let body; if (req.method === 'POST') { let raw = ''; for await (const part of req) raw += part; body = JSON.parse(raw || '{}'); }
    if (url.pathname === '/api/library') { libraryReads++; return json({ games, snapshots: { 'demo/known': { stars: 50, releaseCheckedAt: '2026-11-09T00:00:00Z', release: { tag_name: 'v1', html_url: 'https://github.com/demo/known/releases/tag/v1', supportedSystems: ['Windows ARM64', 'macOS', 'Linux x64'], assets: [] } } }, descriptions: {}, arch: 'arm64', version: 'automation-test', hasToken: false, hasAigcToken: false }); }
    if (url.pathname === '/api/status') return json({ running: false });
    if (url.pathname === '/api/descriptions') return json({ items: [] });
    if (url.pathname === '/api/cloud') return json({ providers: [{ id: 'baidu', configured: false }, { id: 'quark', configured: false }], downloadDir: 'C:\\PortShelf\\downloads' });
    if (url.pathname === '/api/transfers') return json({ jobs, downloadDir: 'C:\\PortShelf\\downloads' });
    if (url.pathname === '/api/discover') { discoveryRequests.push(Object.fromEntries(url.searchParams)); return json({ items: [{ repo: 'new/linux-name', name: 'Linux game', description: 'A Windows and Linux game', stars: 100 }], page: 1, nextPage: 0, hasMore: false, totalCandidates: 1 }); }
    if (url.pathname === '/api/automation' && req.method === 'GET') { statusReads++; if (failRead) return json({ error: 'mock status error' }, 503); return json(status()); }
    if (url.pathname === '/api/automation' && req.method === 'POST') {
      saves.push(body); await wait(70); if (failSave) return json({ error: 'mock configuration error' }, 500);
      config = body; if (!config.enabled) running = false; return json(status());
    }
    if (url.pathname === '/api/automation/run') { actions.push({ path: url.pathname, body }); running = true; queued++; if (games.length === 2) games.push({ repo: 'demo/automatic', name: '自动加入的新游戏', stars: 15, description: '自动发现并加入目录的游戏。' }); return json(status(), 202); }
    if (url.pathname === '/api/automation/open') { actions.push({ path: url.pathname, body }); return json({ ok: true }); }
    if (url.pathname === '/api/quit') return json({ ok: true });
    return json({ error: 'unmocked ' + url.pathname }, 404);
  }
  const name = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
  if (!['index.html', 'app.js', 'app.css', 'zh.js', 'cloud.js', 'automation.js', 'gamepad.svg'].includes(name)) { res.statusCode = 404; return res.end(); }
  res.setHeader('Content-Type', name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : name.endsWith('.svg') ? 'image/svg+xml' : 'text/html');
  res.setHeader('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'");
  res.end(fs.readFileSync(path.join(webRoot, name)));
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const outputDir = fs.mkdtempSync(path.join(os.tmpdir(), 'portshelf-automation-ui-'));
  async function newPage() {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
    page.on('pageerror', error => pageErrors.push(error.message));
    // Speed up only the 2 s local status polling while retaining assertions about its requested interval.
    await page.addInitScript(() => { const original = setTimeout; window.pollIntervals = []; window.setTimeout = (fn, delay, ...args) => { if (delay === 2000) window.pollIntervals.push(delay); return original(fn, delay === 2000 ? 100 : delay, ...args); }; navigator.clipboard.writeText = async value => { window.copiedMaterial = value; }; });
    await page.goto(`http://127.0.0.1:${server.address().port}/#${token}`); await page.locator('.game-card').first().waitFor();
    return page;
  }
  try {
    const page = await newPage();
    assert.equal(statusReads, 0);
    assert.match(await page.locator('[aria-labelledby="game-demo-known"] .card-systems').innerText(), /Windows ARM64、macOS、Linux x64/);
    assert.equal(await page.locator('[aria-labelledby="game-demo-unknown"] .card-systems').innerText(), '支持系统待核实');
    await page.locator('[aria-labelledby="game-demo-known"]').getByRole('button', { name: /查看.*下载/ }).click(); await page.locator('#detail-dialog').waitFor(); assert.match(await page.locator('#detail-content .systems-info').innerText(), /macOS/); await page.locator('#detail-close').click();
    await page.locator('#discover-nav').click(); assert.equal(await page.locator('#discover-min-stars').inputValue(), '10'); assert.equal(await page.locator('[data-min-stars="10"]').getAttribute('aria-pressed'), 'true');
    await page.locator('#discover-submit').click(); await page.locator('.search-result').waitFor(); assert.equal(await page.locator('.search-result .systems-info').innerText(), '支持系统待核实'); assert.deepEqual(discoveryRequests, [{ minStars: '10', page: '1' }]);
    await page.locator('#cloud-nav').click(); await page.waitForFunction(() => document.getElementById('automation-status').textContent === '已暂停');
    assert.equal(await page.locator('#automation-min-stars').inputValue(), '10'); assert.equal(await page.locator('#automation-interval').inputValue(), '6'); assert.equal(await page.locator('#automation-daily-limit').inputValue(), '10'); assert.equal(await page.locator('#automation-arch').inputValue(), 'arm64');
    assert.equal(await page.locator('#automation-remember').isChecked(), true); assert.equal(await page.locator('#automation-start-on-login').isChecked(), true); assert.equal(await page.locator('#automation-remember').isDisabled(), false);
    assert.match(await page.locator('#automation-storage-help').textContent(), /无需开启无人值守.*暂停不会清除授权/);
    await page.evaluate(() => { const button = document.getElementById('automation-toggle'); button.click(); button.click(); }); await page.waitForFunction(() => document.getElementById('automation-status').textContent === '已开启');
    assert.equal(saves.length, 1); assert.equal(saves[0].enabled, true); assert.equal(saves[0].minStars, 10); assert.equal(saves[0].rememberCredentials, true); assert.equal(saves[0].startOnLogin, true);

    await page.locator('#automation-min-stars').fill('20'); await page.locator('#automation-max-stars').fill('1000'); await page.locator('#automation-interval').fill('8'); await page.locator('#automation-daily-limit').fill('15');
    lastError = '上次扫描失败 <img src=x onerror="window.injected=2">'; credentialError = '授权过期 <script>window.injected=3</script>';
    await page.waitForFunction(() => document.getElementById('automation-credential-error').textContent.includes('授权过期')); await page.waitForTimeout(230);
    assert.equal(await page.locator('#automation-min-stars').inputValue(), '20'); assert.equal(await page.locator('#automation-interval').inputValue(), '8'); assert.equal(config.minStars, 10); assert.equal(await page.locator('#automation-run').isDisabled(), true); assert.equal(await page.locator('.automation-panel img,.automation-panel script').count(), 0);
    await page.locator('#automation-toggle').click(); await page.waitForFunction(() => document.getElementById('automation-status').textContent === '已暂停');
    assert.equal(saves[1].enabled, false); assert.equal(saves[1].minStars, 10); assert.equal(await page.locator('#automation-min-stars').inputValue(), '20'); assert.match(await page.locator('#automation-dirty-note').innerText(), /未保存/);
    assert.equal(saves[1].rememberCredentials, true); assert.match(await page.locator('#automation-save-note').innerText(), /已记住的授权继续保留/);
    failSave = true; await page.locator('#automation-toggle').click(); await page.waitForFunction(() => document.getElementById('automation-form-error').textContent.includes('mock configuration error')); assert.equal(await page.locator('#automation-status').innerText(), '已暂停'); assert.equal(await page.locator('#automation-min-stars').inputValue(), '20');
    failSave = false; lastError = ''; credentialError = ''; await page.locator('#automation-toggle').click(); await page.waitForFunction(() => document.getElementById('automation-status').textContent === '已开启' && !document.getElementById('automation-toggle').disabled);
    assert.equal(config.minStars, 20); assert.equal(config.maxStars, 1000); assert.equal(config.intervalHours, 8); assert.equal(config.dailyLimit, 15);
    const beforeInvalid = saves.length; await page.locator('#automation-min-stars').fill('50'); await page.locator('#automation-max-stars').fill('49'); await page.locator('#automation-save').click(); assert.equal(saves.length, beforeInvalid); assert.match(await page.locator('#automation-form-error').innerText(), /不能大于/);
    await page.locator('#automation-min-stars').fill('0'); await page.locator('#automation-max-stars').fill('0'); await page.locator('#automation-save').click(); await page.waitForFunction(() => document.getElementById('automation-save').textContent === '保存设置'); assert.equal(config.minStars, 0); assert.equal(config.maxStars, 0);
    await page.locator('.automation-advanced summary').click(); await page.locator('#automation-baidu').uncheck(); await page.locator('#automation-private-share').uncheck(); await page.locator('#automation-share-days').selectOption('30'); await page.locator('#automation-save').click(); await page.waitForFunction(() => document.getElementById('automation-save').textContent === '保存设置'); assert.deepEqual(config.providers, ['quark']); assert.equal(config.privateShare, false); assert.equal(config.shareDays, 30); assert.equal(config.shareCode, '');
    await page.locator('#automation-run').click(); await page.waitForFunction(() => document.getElementById('automation-status').textContent === '正在扫描'); assert.equal(await page.locator('#automation-run').isDisabled(), true); assert.deepEqual(actions[0], { path: '/api/automation/run', body: {} }); await page.waitForFunction(() => document.getElementById('nav-count').textContent === '3'); assert.ok(libraryReads > 1);
    running = false; await page.waitForFunction(() => document.getElementById('automation-status').textContent === '已开启'); await page.locator('#automation-open').click(); assert.deepEqual(actions[1], { path: '/api/automation/open', body: {} }); assert.match(await page.locator('#automation-export').innerText(), /JSON.*CSV.*Markdown.*最近写入/);
    const retry = page.locator('[data-job-id="retry"]'); assert.match(await retry.locator('.transfer-automation').innerText(), /已尝试 2 次.*下次自动重试/s); assert.match(await retry.locator('.transfer-systems').innerText(), /Windows ARM64、macOS、Linux x64/);
    assert.match(await page.locator('[data-job-id="attention"] .transfer-automation').innerText(), /需要本人处理.*验证码/s); assert.doesNotMatch(await page.locator('[data-job-id="attention"] .transfer-automation').innerText(), /下次自动重试/);
    assert.match(await page.locator('[data-job-id="unscheduled"] .transfer-automation').innerText(), /尚未安排自动重试/); assert.equal(await page.locator('[data-job-id="manual"] .transfer-automation').count(), 0);
    await retry.getByRole('button', { name: '复制分享资料', exact: true }).click(); assert.match(await page.evaluate(() => window.copiedMaterial), /支持系统：Windows ARM64、macOS、Linux x64/);

    failRead = true; await page.locator('#automation-refresh').click(); await page.waitForFunction(() => document.getElementById('automation-load-error').textContent.includes('mock status error')); assert.equal(await page.locator('#automation-status').innerText(), '已开启'); failRead = false;
    await page.locator('#library-nav').click(); await page.waitForTimeout(140); const pausedReads = statusReads; await page.waitForTimeout(220); assert.equal(statusReads, pausedReads);
    await page.locator('#cloud-nav').click(); await page.waitForFunction(() => document.getElementById('automation-load-error').hidden);
    await page.evaluate(() => { window.mockHidden = true; Object.defineProperty(document, 'hidden', { configurable: true, get: () => window.mockHidden }); document.dispatchEvent(new Event('visibilitychange')); }); await page.waitForTimeout(140); const hiddenReads = statusReads; await page.waitForTimeout(220); assert.equal(statusReads, hiddenReads);
    await page.evaluate(() => { window.mockHidden = false; document.dispatchEvent(new Event('visibilitychange')); }); await page.waitForTimeout(140); assert.ok(statusReads > hiddenReads); assert.ok(await page.evaluate(() => window.pollIntervals.includes(2000)));
    await page.evaluate(() => { document.getElementById('toast').hidden = true; window.scrollTo(0, 0); }); await page.screenshot({ path: path.join(outputDir, 'desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 }); assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false); await page.screenshot({ path: path.join(outputDir, 'mobile.png'), fullPage: true });
    await page.locator('#quit-open').click(); await page.locator('#quit-confirm').click(); await page.locator('.stopped-message').waitFor(); await page.waitForTimeout(140); const quitReads = statusReads; await page.waitForTimeout(220); assert.equal(statusReads, quitReads); assert.equal(await page.evaluate(() => window.injected), undefined);

    platformSupported = false; config = defaultConfig('arm64'); running = false; const nonWindows = await newPage(); await nonWindows.locator('#cloud-nav').click(); await nonWindows.waitForFunction(() => document.getElementById('automation-status').textContent === '已暂停');
    await nonWindows.locator('.automation-advanced summary').click(); assert.equal(await nonWindows.locator('#automation-remember').isDisabled(), true); assert.equal(await nonWindows.locator('#automation-start-on-login').isDisabled(), true); assert.match(await nonWindows.locator('#automation-startup-help').innerText(), /本次工具进程/); assert.match(await nonWindows.locator('#automation-storage-help').innerText(), /当前平台不支持/);
    await nonWindows.locator('#automation-toggle').click(); await nonWindows.waitForFunction(() => document.getElementById('automation-status').textContent === '已开启'); assert.equal(saves.at(-1).rememberCredentials, false); assert.equal(saves.at(-1).startOnLogin, false);
    assert.equal(await nonWindows.evaluate(() => Object.keys(localStorage).length), 0); assert.deepEqual(await nonWindows.evaluate(() => Object.keys(sessionStorage)), ['portshelf-session']);
    await nonWindows.setViewportSize({ width: 390, height: 844 }); assert.equal(await nonWindows.evaluate(() => document.documentElement.scrollWidth > innerWidth), false); await nonWindows.screenshot({ path: path.join(outputDir, 'non-windows-mobile.png'), fullPage: true });
    assert.deepEqual(pageErrors, []);
    console.log('PASS unattended defaults10, enable/pause/save/run, duplicate submit and invalid bounds guards, draft preservation across polling and pause/errors, private/public, Windows capability gates, automatic queue/library updates, explicit retry/attention, verified/unknown supported systems and copied materials, XSS, visible/quit polling, no credential storage, 390px layout.');
    console.log('Screenshots: ' + outputDir);
  } finally { await browser.close(); server.close(); }
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
