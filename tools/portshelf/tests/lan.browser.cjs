const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const net = require('node:net');
const { spawn, spawnSync, execFileSync } = require('node:child_process');
const { chromium } = require(process.env.PORTSHELF_PLAYWRIGHT_MODULE || path.resolve(__dirname, '../../../frontend/node_modules/playwright'));

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const output = fs.mkdtempSync(path.join(os.tmpdir(), 'portshelf-lan-ui-'));
const data = path.join(output, 'data');
const binary = process.env.PORTSHELF_TEST_BINARY || path.join(output, 'portshelf');
if (!process.env.PORTSHELF_TEST_BINARY) execFileSync('go', ['build', '-o', binary, '.'], { cwd: path.resolve(__dirname, '..') });
let service, serviceLog = '';

async function stopService() {
  if (!service || service.exitCode !== null) return;
  const child = service;
  await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => { child.kill('SIGKILL'); reject(new Error('service did not handle SIGTERM')); }, 20000);
    child.once('exit', (code) => { clearTimeout(timeout); code === 0 ? resolve() : reject(new Error('unclean shutdown: ' + code)); });
    child.kill('SIGTERM');
  });
  service = null;
}

(async () => {
  const probe = net.createServer();
  await new Promise(resolve => probe.listen(0, '127.0.0.1', resolve));
  const port = probe.address().port;
  await new Promise(resolve => probe.close(resolve));
  const base = `http://127.0.0.1:${port}`;
  async function startService() {
    service = spawn(binary, ['-lan', '-listen', `127.0.0.1:${port}`, '-data-dir', data], { stdio: ['ignore', 'pipe', 'pipe'] });
    service.stdout.on('data', part => { serviceLog += part; });
    service.stderr.on('data', part => { serviceLog += part; });
    for (let attempt = 0; attempt < 200; attempt++) {
      if (service.exitCode !== null) throw new Error('service failed to start');
      try { if ((await fetch(base + '/runtime.json')).ok) return; } catch (_) { /* Startup only. */ }
      await sleep(50);
    }
    throw new Error('startup timeout');
  }
  await startService();
  const duplicate = spawnSync(binary, ["-lan", "-listen", `127.0.0.1:${port}`, "-data-dir", data], { timeout: 5000 });
  assert.equal(duplicate.status, 1, "a duplicate LAN service must report failure");
  const token = new URL(fs.readFileSync(path.join(data, 'session.url'), 'utf8')).hash.slice(1);
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1080 } });
    // This checks the real local service and UI without live enrichment traffic.
    await context.route('**/api/descriptions?*', route => route.fulfill({ contentType: 'application/json', body: '{"items":[]}' }));
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(base);
    await page.locator('#access-dialog[open]').waitFor();
    assert.equal((await page.request.get(base + '/api/library')).status(), 401);
    await page.locator('#access-code').fill('0'.repeat(48));
    await page.locator('#access-form button').click();
    await page.locator('#access-error').waitFor();
    assert.match(await page.locator('#access-error').textContent(), /访问码无效/);
    await page.locator('#access-code').fill(token);
    await page.locator('#access-form button').click();
    await page.waitForFunction(() => document.getElementById('version-label').textContent.includes('内网版'));
    assert.match(await page.locator('#version-label').textContent(), /v1\.8\.2/);
    assert.equal(new URL(page.url()).hash, '');
    await page.locator('#cloud-nav').click();
    await page.waitForFunction(() => !document.getElementById('automation-remember').disabled);
    assert.equal(await page.locator('#automation-remember').isChecked(), true);
    assert.equal(await page.locator('#automation-start-on-login').isDisabled(), true);
    assert.equal(await page.locator('#transfer-open-folder').isVisible(), false);
    assert.equal(await page.locator('#automation-open').isVisible(), false);
    assert.match(await page.locator('#download-directory-title').textContent(), /服务器/);
    assert.match(await page.locator('#automation-storage-help').textContent(), /服务器上加密保存/);
    await page.locator('#automation-min-stars').fill('500');
    await page.locator('#automation-save').click();
    await page.waitForFunction(() => document.getElementById('automation-dirty-note').textContent.includes('设置已保存'));
    await page.locator('#settings-open').click();
    await page.locator('#token-input').fill('lan-browser-test-sentinel');
    await page.locator('#token-submit').click();
    const headers = { Authorization: 'Bearer ' + token };
    for (let attempt = 0; attempt < 100; attempt++) {
      const state = await (await page.request.get(base + '/api/cloud', { headers })).json();
      if (state.credentialStorage.saved) break;
      if (attempt === 99) throw new Error('credential was not saved');
      await sleep(50);
    }
    await page.screenshot({ path: path.join(output, 'lan-cloud.png'), fullPage: true });
    await stopService();
    await startService();
    assert.equal(new URL(fs.readFileSync(path.join(data, 'session.url'), 'utf8')).hash.slice(1), token);
    assert.equal(serviceLog.includes(token), false, 'access code leaked into logs');
    const fresh = await context.newPage();
    await fresh.goto(base);
    await fresh.waitForFunction(() => document.getElementById('version-label').textContent.includes('内网版'));
    assert.equal(await fresh.locator('#access-dialog').isVisible(), false, 'remembered browser lost access');
    const library = await (await fresh.request.get(base + '/api/library', { headers })).json();
    assert.equal(library.hasToken, true);
    const automation = await (await fresh.request.get(base + '/api/automation', { headers })).json();
    assert.equal(automation.config.minStars, 500);
    assert.equal(automation.config.enabled, false);
    assert.equal((await fresh.request.post(base + '/api/quit', { headers, data: {} })).status(), 409);
    await fresh.locator('#quit-open').click();
    assert.match(await fresh.locator('#quit-dialog').textContent(), /服务器.*任务继续运行/);
    await fresh.locator('#quit-confirm').click();
    await fresh.locator('#access-dialog[open]').waitFor();
    assert.equal(await fresh.evaluate(() => localStorage.getItem('portshelf-lan-access')), null);
    assert.equal((await fresh.request.get(base + '/api/library', { headers })).status(), 200, 'logout stopped the service');
    await fresh.screenshot({ path: path.join(output, 'lan-login.png'), fullPage: true });
    assert.deepEqual(errors, []);
    console.log('PASS real LAN service: access control, login/logout, browser persistence, restart with encrypted credentials/settings, headless controls and no secret logs.');
    console.log('Screenshots: ' + output);
  } finally {
    await browser.close();
    await stopService();
  }
})().catch(error => { if (service) service.kill('SIGKILL'); console.error(error); process.exitCode = 1; });
