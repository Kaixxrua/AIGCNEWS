// Run with an available Playwright Chromium: node tools/portshelf/tests/transfers.browser.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const os = require('node:os');
const { chromium } = require(process.env.PORTSHELF_PLAYWRIGHT_MODULE || path.resolve(__dirname, '../../../frontend/node_modules/playwright'));
const { defaultConfig } = require('../web/automation.js');
const root = path.resolve(__dirname, '../web');
const token = 'c'.repeat(48);
const games = Array.from({ length: 205 }, (_, index) => ({ repo: `demo/game-${index}`, name: `Game${String(index).padStart(3, '0')}`, description: '由社区延续的经典游戏。', stars: 1000 + index, category: '动作游戏' }));
const initialJobs = [
  { id: 'failed', repo: 'demo/game-4', name: '下载失败的游戏', arch: 'amd64', status: 'failed', stage: 'download', error: '文件有变动，请先取消此任务再新建任务，原文件会保留', outputs: {} },
  { id: 'done', repo: 'demo/game-0', name: '完成的经典游戏', arch: 'amd64', version: 'v1.0', status: 'done', stage: 'done', localDeletedAt: '2026-11-10T00:00:00Z', downloadPath: 'C:\\PortShelf\\downloads\\game.zip', sha256: 'abc123', description: '一款经典动作游戏。', outputs: { baidu: { status: 'done', file: { id: 'b1', path: '/PortShelf/game.zip' }, share: { url: 'https://pan.baidu.com/s/demo', code: 'ab12' } }, quark: { status: 'done', share: { url: 'https://pan.quark.cn/s/demo', code: 'q123' } } } },
  { id: 'partial', repo: 'demo/game-1', name: '部分完成的游戏', arch: 'arm64', version: 'v2', status: 'partial', stage: 'share', downloadPath: 'C:\\downloads\\partial.zip', description: '中文简介 <img src=x onerror="window.injected=1">', dataNote: '需要原作素材', guide: '复制原作资源后运行。', error: '部分分享失败 <script>window.injected=2</script>', warnings: ['上游使用说明 <img src=x onerror="window.injected=3">'], outputs: { baidu: { status: 'done', file: { id: 'b2' }, share: { url: 'https://pan.baidu.com/s/partial', code: 'cd34' } }, quark: { status: 'failed', share: { url: 'javascript:alert(1)' }, error: '夸克服务暂不可用' } } },
  { id: 'waiting', repo: 'demo/game-2', name: '等待网盘连接', arch: 'amd64', status: 'waiting_auth', stage: 'upload', downloadPath: 'C:\\downloads\\waiting.zip', outputs: { quark: { status: 'waiting_auth', error: '请先连接网盘' } } },
  { id: 'running', repo: 'demo/game-3', name: '正在下载的游戏', arch: 'amd64', status: 'running', stage: 'download', completedBytes: 512, totalBytes: 1024, outputs: {} },
];
let jobs = structuredClone(initialJobs), pollCount = 0, failNextRead = false, failEnqueueAt = 0, authorizationURL = 'https://pan.quark.cn/open/v1/oauth/agent?device_id=test&device_name=PortShelf&agent_id=test&page_code=code#/agent-oauth';
Object.assign(jobs.find(job => job.id === 'done'), { gameNameZh: '完成的中文经典', gameNameOriginal: 'The Classic Game', bundleVersion: 1, bundlePath: 'C:\\PortShelf\\downloads\\complete-with-source.zip', sourceCommit: 'a'.repeat(40), sourceSha256: 'b'.repeat(64), bundleSha256: 'c'.repeat(64), sourceUrl: 'https://github.com/demo/game-0/archive/' + 'a'.repeat(40) + '.zip', legacyOutputs: { baidu: { share: { url: 'https://pan.baidu.com/s/legacy', code: '6789' } } } });
for (const output of Object.values(jobs.find(job => job.id === 'done').outputs)) output.payloadSha256 = 'c'.repeat(64);
const requests = [], enqueues = [], credentials = [], exportedFormats = [];
const accounts = { baidu: { id: 'baidu', name: '百度网盘', configured: false, authMode: 'cookie' }, quark: { id: 'quark', name: '夸克网盘', configured: false, authMode: 'authCode' } };
let credentialStorage = { supported: true, remember: true, saved: false, pending: [] }, failCredentialSave = false;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://local');
  const json = (value, status = 200) => { res.statusCode = status; res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(value)); };
  if (url.pathname.startsWith('/api/')) {
    assert.equal(req.headers.authorization, 'Bearer ' + token);
    let body; if (req.method === 'POST') { let raw = ''; for await (const part of req) raw += part; body = JSON.parse(raw || '{}'); }
    requests.push({ path: url.pathname, method: req.method, body });
    if (url.pathname === '/api/library') return json({ games, snapshots: {}, descriptions: {}, arch: 'arm64', version: 'test', hasToken: false, hasAigcToken: false });
    if (url.pathname === '/api/status') return json({ running: false });
    if (url.pathname === '/api/descriptions') return json({ items: [] });
    if (url.pathname === '/api/automation' && req.method === 'GET') return json({ config: defaultConfig('arm64'), running: false, nextRun: '', lastRun: '', lastError: '', exportDir: 'C:\\PortShelf\\exports', exportedAt: '', discovered: 0, queued: 0, unsupported: 0, credentialStorageSupported: false, startOnLoginSupported: false, credentialError: '' });
    if (url.pathname === '/api/cloud') return json({ providers: Object.values(accounts), downloadDir: 'C:\\PortShelf\\downloads', credentialStorage });
    if (url.pathname === '/api/cloud/quark/authorize') return json({ url: authorizationURL });
    if (/^\/api\/cloud\/(baidu|quark)$/.test(url.pathname)) {
      const id = url.pathname.split('/').pop(); credentials.push({ id, body }); await sleep(70);
      const configured = Boolean(body.cookie || body.authCode || body.accessToken); accounts[id] = { ...accounts[id], configured, account: configured ? '测试账号 <img onerror=alert(1)>' : '' };
      credentialStorage = { ...credentialStorage, saved: !failCredentialSave, error: failCredentialSave ? 'mock encrypted save failure' : '' };
      return json({ ...accounts[id], credentialStorage });
    }
    if (url.pathname === '/api/transfers' && req.method === 'GET') {
      pollCount++; if (failNextRead) { failNextRead = false; return json({ error: 'temporary read failure' }, 503); }
      return json({ jobs, downloadDir: 'C:\\PortShelf\\downloads', storeError: 'mock record warning' });
    }
    if (url.pathname === '/api/transfers' && req.method === 'POST') {
      enqueues.push(body); await sleep(60);
      if (enqueues.length === failEnqueueAt) return json({ error: 'queue temporarily unavailable' }, 503);
      return json({ added: body.repos.slice(1).map((_, index) => `added-${enqueues.length}-${index}`), skipped: body.repos.slice(0, 1) });
    }
    if (/^\/api\/transfers\/[^/]+\/(retry|cancel)$/.test(url.pathname)) {
      const [, , , id, action] = url.pathname.split('/'); await sleep(70);
      const job = jobs.find(item => item.id === id); if (job) job.status = action === 'retry' ? 'queued' : 'cancelled';
      return json({ ok: true });
    }
    if (url.pathname === '/api/transfers/open') return json({ ok: true });
    if (url.pathname === '/api/transfers/clear') { jobs = jobs.filter(job => !['done', 'cancelled'].includes(job.status)); return json({ removed: 1 }); }
    if (url.pathname === '/api/transfers/export') { exportedFormats.push(url.searchParams.get('format')); res.setHeader('Content-Type', 'text/plain'); return res.end('中文分享资料\nhttps://pan.baidu.com/s/partial\n提取码：cd34'); }
    if (url.pathname === '/api/quit') return json({ ok: true });
    return json({ error: 'unmocked ' + url.pathname }, 404);
  }
  const name = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
  if (!['index.html', 'app.js', 'app.css', 'zh.js', 'cloud.js', 'automation.js', 'gamepad.svg'].includes(name)) { res.statusCode = 404; return res.end(); }
  res.setHeader('Content-Type', name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : name.endsWith('.svg') ? 'image/svg+xml' : 'text/html');
  res.end(fs.readFileSync(path.join(root, name)));
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const outputDir = fs.mkdtempSync(path.join(os.tmpdir(), 'portshelf-transfers-ui-'));
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, acceptDownloads: true });
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    // Accelerate only the 2 s refresh delay; verify the production interval itself below.
    await page.addInitScript(() => { const original = window.setTimeout; window.transferDelays = []; window.setTimeout = (fn, delay, ...args) => { if (delay === 2000) window.transferDelays.push(delay); return original(fn, delay === 2000 ? 100 : delay, ...args); }; navigator.clipboard.writeText = async text => { window.copiedMaterial = text; }; });
    await page.goto(`http://127.0.0.1:${server.address().port}/#${token}`);
    await page.waitForFunction(() => document.getElementById('game-count').textContent === '205');
    assert.equal(pollCount, 0);
    await page.locator('#library-search').fill('Game000'); await page.locator('#cloud-nav').click();
    await page.locator('[data-job-id="partial"]').waitFor();
    assert.equal(await page.locator('#transfer-arch').inputValue(), 'arm64');
    assert.equal(await page.locator('.transfer-game').count(), 1);
    await page.locator('#transfer-select-visible').click();
    await page.locator('#transfer-search').fill('Game001'); assert.equal(await page.locator('.transfer-game').count(), 0);
    await page.locator('#transfer-use-filters').uncheck(); await page.locator('#transfer-select-visible').click();
    assert.match(await page.locator('#transfer-selection-count').innerText(), /已选 2.*筛选外 1/);
    await page.locator('#transfer-clear-selection').click(); await page.locator('#transfer-search').fill(''); await page.locator('#transfer-select-visible').click();
    assert.match(await page.locator('#transfer-selection-count').innerText(), /205/);
    await page.locator('#transfer-submit').click(); await page.waitForFunction(() => !document.getElementById('transfer-submit').textContent.includes('正在'));
    assert.deepEqual(enqueues.map(body => body.repos.length), [100, 100, 5]);
    assert.ok(enqueues.every(body => body.providers.length === 0 && body.arch === 'arm64' && body.enrich && body.shareDays === 0));
    assert.match(await page.locator('#transfer-enqueue-note').innerText(), /202 项.*3 项/);
    assert.match(await page.locator('#transfer-selection-count').innerText(), /已选 0/);

    await page.locator('#transfer-search').fill('Game000'); await page.locator('#transfer-select-visible').click();
    await page.locator('#transfer-baidu').check(); await page.locator('#transfer-quark').check();
    assert.equal(await page.locator('#transfer-private-share').isChecked(), true); assert.equal(await page.locator('#transfer-private-share').isDisabled(), true);
    await page.locator('#transfer-share-code').fill('bad'); await page.locator('#transfer-submit').click(); assert.equal(enqueues.length, 3); assert.match(await page.locator('#transfer-enqueue-error').innerText(), /4 位/);
    await page.locator('#transfer-share-code').fill('a1B2'); await page.locator('#transfer-share-days').selectOption('7');
    await page.evaluate(() => { const button = document.getElementById('transfer-submit'); button.click(); button.click(); });
    await page.waitForFunction(() => !document.getElementById('transfer-submit').textContent.includes('正在'));
    assert.equal(enqueues.length, 4); assert.deepEqual(enqueues[3].providers, ['baidu', 'quark']); assert.equal(enqueues[3].privateShare, true); assert.equal(enqueues[3].shareCode, 'a1B2'); assert.equal(enqueues[3].shareDays, 7);
    await page.locator('#transfer-baidu').uncheck(); await page.locator('#transfer-private-share').uncheck(); await page.locator('#transfer-select-visible').click(); await page.locator('#transfer-submit').click();
    await page.waitForFunction(() => !document.getElementById('transfer-submit').textContent.includes('正在'));
    assert.equal(enqueues[4].privateShare, false); assert.equal(enqueues[4].shareCode, '');
    await page.locator('#transfer-search').fill(''); await page.locator('#transfer-select-visible').click(); failEnqueueAt = enqueues.length + 2; await page.locator('#transfer-submit').click();
    await page.waitForFunction(() => !document.getElementById('transfer-submit').textContent.includes('正在'));
    assert.match(await page.locator('#transfer-selection-count').innerText(), /已选 105/); assert.match(await page.locator('#transfer-enqueue-error').innerText(), /已加入 99 项.*其余选择已保留/);
    const retryOffset = enqueues.length; failEnqueueAt = 0; await page.locator('#transfer-submit').click(); await page.waitForFunction(() => !document.getElementById('transfer-submit').textContent.includes('正在'));
    assert.deepEqual(enqueues.slice(retryOffset).map(body => body.repos.length), [100, 5]);

    const cleaned = page.locator('[data-job-id="done"]');
    assert.equal(await cleaned.locator('h3').innerText(), '完成的中文经典');
    assert.match(await cleaned.innerText(), /分享包已准备.*对应版本源码/);
    assert.equal(await cleaned.locator('.transfer-outputs').first().getByText('含对应版本源码', { exact: true }).count(), 2);
    assert.match(await cleaned.locator('.transfer-legacy summary').innerText(), /历史单文件分享.*不含源码/);
    assert.match(await cleaned.innerText(), /本地文件已自动清理/);
    assert.equal(await cleaned.getByRole('button', { name: '打开所在目录' }).count(), 0);
    await cleaned.getByRole('button', { name: '复制分享资料', exact: true }).click();
    assert.match(await page.evaluate(() => window.copiedMaterial), /双盘完成后已清理/);
    assert.match(await page.evaluate(() => window.copiedMaterial), /https:\/\/pan.baidu.com\/s\/demo/);
    assert.match(await page.evaluate(() => window.copiedMaterial), /https:\/\/pan.quark.cn\/s\/demo/);
    assert.match(await page.evaluate(() => window.copiedMaterial), /源码 Commit：a{40}/);
    assert.match(await page.evaluate(() => window.copiedMaterial), /分享包 SHA-256：c{64}/);
    assert.match(await page.evaluate(() => window.copiedMaterial), /历史单文件分享.*不含源码/);
    const partial = page.locator('[data-job-id="partial"]');
    assert.doesNotMatch(await partial.innerText(), /含对应版本源码|分享包已准备/);
    assert.equal(await partial.getByRole('button', { name: '取消任务', exact: true }).count(), 1);
    await page.locator('[data-job-id="failed"]').getByRole('button', { name: '取消任务', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('[data-job-id="failed"] .transfer-status').textContent === '已取消');
    assert.equal(await partial.locator('a[href^="javascript"]').count(), 0); assert.equal(await partial.locator('img,script').count(), 0);
    await partial.locator('summary').click(); assert.match(await partial.locator('pre').innerText(), /需要原作素材/);
    await partial.locator('summary').focus(); await page.waitForTimeout(250); assert.equal(await page.evaluate(() => document.activeElement?.closest('[data-job-id]')?.dataset.jobId), 'partial'); assert.equal(await partial.locator('details').evaluate(item => item.open), true);
    await partial.getByRole('button', { name: '复制分享资料', exact: true }).click();
    assert.match(await page.evaluate(() => window.copiedMaterial), /https:\/\/pan.baidu.com\/s\/partial/); assert.doesNotMatch(await page.evaluate(() => window.copiedMaterial), /javascript/);
    await partial.getByRole('button', { name: '打开所在目录' }).click(); assert.deepEqual(requests.find(item => item.path === '/api/transfers/open').body, { id: 'partial' });
    await page.locator('#transfer-open-folder').click(); assert.deepEqual(requests.filter(item => item.path === '/api/transfers/open').at(-1).body, {});
    assert.match(await page.locator('[data-job-id="running"] .transfer-progress-text').innerText(), /50%.*512 B.*1.0 KB/);
    assert.match(await page.locator('#transfer-store-error').innerText(), /记录保存异常/);
    failNextRead = true; await page.locator('#transfer-refresh').click(); await page.waitForFunction(() => !document.getElementById('transfer-poll-error').hidden);
    assert.equal(await page.locator('[data-job-id="partial"]').count(), 1);
    await page.locator('#library-nav').click(); await page.waitForTimeout(150); const pausedCount = pollCount; await page.waitForTimeout(220); assert.equal(pollCount, pausedCount);
    await page.locator('#cloud-nav').click(); await page.waitForFunction(() => document.getElementById('transfer-poll-error').hidden);
    assert.ok(await page.evaluate(() => window.transferDelays.includes(2000)));

    await page.locator('#transfer-auth-open').click();
    await page.waitForFunction(() => document.getElementById('credential-storage-state').dataset.state === 'waiting');
    assert.match(await page.locator('#credential-storage-state').innerText(), /等待首次保存/);
    await page.locator('#cloud-baidu-credential').fill('BDUSS=local-cookie-secret; STOKEN=local-only');
    await page.evaluate(() => { const button = document.getElementById('cloud-baidu-submit'); button.click(); button.click(); });
    await page.waitForFunction(() => !document.getElementById('cloud-baidu-submit').disabled);
    assert.equal(credentials.length, 1); assert.ok(credentials[0].body.cookie); assert.equal(credentials[0].body.accessToken, undefined); assert.equal(await page.locator('#cloud-baidu-credential').inputValue(), '');
    assert.equal(await page.locator('#credential-storage-state').getAttribute('data-state'), 'saved');
    assert.match(await page.locator('#credential-storage-state').innerText(), /已在本机加密保存.*无需开启无人值守/);
    await page.locator('#cloud-quark-authorize').click(); await page.locator('#cloud-quark-authorization a').waitFor(); assert.equal(await page.locator('#cloud-quark-authorization a').getAttribute('href'), authorizationURL);
    failCredentialSave = true;
    await page.locator('#cloud-quark-credential').fill('auth-code-local-only'); await page.locator('#cloud-quark-submit').click(); await page.waitForFunction(() => !document.getElementById('cloud-quark-submit').disabled);
    assert.deepEqual(credentials[1], { id: 'quark', body: { authCode: 'auth-code-local-only' } }); assert.equal(await page.locator('#cloud-quark-credential').inputValue(), '');
    assert.equal(await page.locator('#credential-storage-state').getAttribute('data-state'), 'error');
    assert.match(await page.locator('#credential-storage-state').innerText(), /本次已连接的账号仍可使用.*本机保存状态需处理.*mock encrypted save failure/);
    assert.match(await page.locator('#cloud-quark-state').innerText(), /已连接/);
    failCredentialSave = false;
    credentialStorage = { supported: true, remember: true, saved: true, pending: ['quark'] };
    accounts.quark.configured = false;
    await page.locator('#cloud-baidu-credential').fill('unsubmitted-local-draft');
    await page.evaluate(() => { window.credentialInputBeforeRefresh = document.getElementById('cloud-baidu-credential'); });
    await page.locator('#cloud-settings-refresh').click();
    await page.waitForFunction(() => document.getElementById('cloud-quark-state').textContent.includes('已保存授权正在恢复'));
    assert.doesNotMatch(await page.locator('#cloud-quark-state').innerText(), /未连接/);
    assert.equal(await page.locator('#cloud-baidu-credential').inputValue(), 'unsubmitted-local-draft');
    const restoreReadCount = requests.filter(item => item.path === '/api/cloud').length;
    await page.waitForTimeout(240);
    assert.ok(requests.filter(item => item.path === '/api/cloud').length > restoreReadCount, 'pending saved authorization should refresh without another login');
    assert.equal(credentials.length, 2);
    credentialStorage = { ...credentialStorage, saved: false, error: 'temporary restore failure <img src=x onerror="window.injected=5">' };
    await page.locator('#cloud-settings-refresh').click();
    await page.waitForFunction(() => document.getElementById('cloud-quark-state').textContent.includes('恢复待重试'));
    assert.equal(await page.locator('#credential-storage-state img').count(), 0);
    assert.equal(await page.locator('#cloud-baidu-credential').inputValue(), 'unsubmitted-local-draft');
    credentialStorage = { supported: true, remember: true, saved: true, pending: [] }; accounts.quark.configured = true;
    await page.waitForFunction(() => document.getElementById('cloud-quark-state').textContent.includes('已连接') && document.getElementById('credential-storage-state').dataset.state === 'saved');
    assert.equal(await page.evaluate(() => window.credentialInputBeforeRefresh === document.getElementById('cloud-baidu-credential')), true);
    assert.equal(await page.locator('#cloud-baidu-credential').inputValue(), 'unsubmitted-local-draft');
    assert.equal(credentials.length, 2);
    credentialStorage = { ...credentialStorage, remember: false };
    await page.locator('#cloud-settings-refresh').click(); await page.waitForFunction(() => document.getElementById('credential-storage-state').textContent.includes('已关闭'));
    assert.match(await page.locator('#credential-storage-state').innerText(), /仅在本次运行/);
    credentialStorage = { ...credentialStorage, supported: false };
    await page.locator('#cloud-settings-refresh').click(); await page.waitForFunction(() => document.getElementById('credential-storage-state').textContent.includes('当前平台不支持'));
    credentialStorage = { supported: true, remember: true, saved: true, pending: [] };
    await page.locator('#cloud-settings-refresh').click(); await page.waitForFunction(() => document.getElementById('credential-storage-state').dataset.state === 'saved');
    assert.equal(await page.evaluate(() => /local-cookie-secret|auth-code-local-only/.test(JSON.stringify(localStorage) + JSON.stringify(sessionStorage))), false);
    authorizationURL = 'https://evil.test/open/v1/oauth/agent'; await page.locator('#cloud-quark-authorize').click(); await page.waitForFunction(() => document.getElementById('cloud-quark-error').textContent.includes('受信任'));
    await page.locator('#cloud-baidu-clear').click(); await page.waitForFunction(() => !document.getElementById('cloud-baidu-submit').disabled); assert.deepEqual(credentials[2].body, { cookie: '', accessToken: '', authCode: '' });
    await page.locator('#cloud-baidu-credential').fill('unsubmitted-secret'); await page.keyboard.press('Escape'); await page.waitForFunction(() => !document.getElementById('settings-dialog').open && !document.getElementById('cloud-baidu-credential').value);
    await page.locator('#transfer-auth-open').click(); await page.locator('#credential-storage-options').click();
    assert.equal(await page.locator('#settings-dialog').evaluate(dialog => dialog.open), false);
    assert.equal(await page.locator('.automation-advanced').evaluate(details => details.open), true);
    assert.equal(requests.filter(item => item.path === '/api/automation' && item.method === 'POST').length, 0, 'storage settings navigation must not enable automation');

    const downloadEvent = page.waitForEvent('download'); await page.locator('#transfer-export').click(); const download = await downloadEvent;
    assert.match(download.suggestedFilename(), /^PortShelf-.*\.md$/); assert.match(fs.readFileSync(await download.path(), 'utf8'), /中文分享资料/); assert.deepEqual(exportedFormats, ['markdown']);
    await page.evaluate(() => { const button = [...document.querySelector('[data-job-id="partial"]').querySelectorAll('button')].find(item => item.textContent === '重试任务'); button.click(); button.click(); });
    await page.waitForFunction(() => document.querySelector('[data-job-id="partial"] .transfer-status').textContent === '排队中'); assert.equal(requests.filter(item => item.path === '/api/transfers/partial/retry').length, 1);
    await page.locator('[data-job-id="running"]').getByRole('button', { name: '取消任务', exact: true }).click(); await page.waitForFunction(() => document.querySelector('[data-job-id="running"] .transfer-status').textContent === '已取消');
    await page.locator('#transfer-clear-history').click(); await page.waitForFunction(() => !document.querySelector('[data-job-id="done"]')); assert.equal(await page.locator('[data-job-id="waiting"]').count(), 1);

    await page.locator('#cloud-view').scrollIntoViewIfNeeded(); await page.evaluate(() => window.scrollTo(0, 0)); await page.screenshot({ path: path.join(outputDir, 'desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 }); await page.evaluate(() => window.scrollTo(0, 0)); assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false); await page.screenshot({ path: path.join(outputDir, 'mobile.png'), fullPage: true });
    await page.locator('#transfer-auth-open').click(); assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false); await page.screenshot({ path: path.join(outputDir, 'settings-mobile.png') }); await page.keyboard.press('Escape');
    await page.locator('#quit-open').click(); await page.locator('#quit-confirm').click(); await page.locator('.stopped-message').waitFor(); await page.waitForTimeout(120); const quitCount = pollCount; await page.waitForTimeout(220); assert.equal(pollCount, quitCount);
    assert.equal(await page.evaluate(() => window.injected), undefined); assert.deepEqual(errors, []);
    console.log('PASS transfer selection/filtering/batches, source-share metadata, retry/cancel/clear/export, real encrypted-save receipts and errors, pending authorization restore polling without re-login or clearing typed input, explicit memory-only/unsupported state, independent storage settings navigation, official URL allowlist, visibility/quit polling, XSS and mobile layout.');
    console.log('Screenshots: ' + outputDir);
  } finally { await browser.close(); server.close(); }
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
