// Runs the actual bundled UI against authenticated local API fixtures; no external publication.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const os = require('node:os');
const { chromium } = require(process.env.PORTSHELF_PLAYWRIGHT_MODULE || path.resolve(__dirname, '../../../frontend/node_modules/playwright'));
const { defaultConfig } = require('../web/marketplace.js');
const { defaultConfig: automationConfig } = require('../web/automation.js');
const webRoot = path.resolve(__dirname, '../web');
const token = 'a'.repeat(48);
let config = defaultConfig(), connected = false, credentialSaved = false, supported = true, running = false;
let failSave = false, failRead = false, failChild = false, serviceError = '', reads = 0;
const requests = [], saves = [], pageErrors = [];
let shops = [];
const jobs = [
  { id: 'waiting', transferId: 'transfer-1', repo: 'demo/waiting', title: '待补齐资料', status: 'waiting_materials', error: '等待可用海报' },
  { id: 'unknown', transferId: 'transfer-2', repo: 'demo/unknown', title: '创建结果未确认', status: 'create_unknown', shopUserName: 'game-shop', priceFen: 29, error: '远端响应超时 <img src=x onerror="window.injected=1">' },
  { id: 'confirmed', transferId: 'transfer-3', repo: 'demo/confirmed', title: '已有上架记录', status: 'published', shopUserName: 'game-shop', priceFen: 1230, productId: '9001', itemId: '8001', itemUrl: 'https://www.goofish.com/item?id=8001', content: '开源项目文件与源码。\n保留上游许可说明。<img src=x onerror="window.injected=4">', posterUrl: 'https://aigcnews.cn/api/media/site/game-posters/' + 'b'.repeat(64) + '.jpg' },
  { id: 'unsafe', transferId: 'transfer-4', repo: 'demo/unsafe', title: '<script>window.injected=2</script>', status: 'attention', itemUrl: 'javascript:alert(1)' },
];
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const status = () => ({ config, connected, credentialSaved, credentialStorageSupported: supported, shops, running, error: serviceError });
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://local');
  const json = (value, code = 200) => { res.statusCode = code; res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(value)); };
  if (url.pathname.startsWith('/api/')) {
    assert.equal(req.headers.authorization, 'Bearer ' + token);
    let body; if (req.method === 'POST') { let raw = ''; for await (const part of req) raw += part; body = JSON.parse(raw || '{}'); }
    if (url.pathname === '/api/library') return json({ games: [{ repo: 'demo/game', name: '已发现游戏', stars: 15, description: '开源游戏。' }], snapshots: {}, descriptions: {}, arch: 'amd64', hasToken: false, hasAigcToken: false, version: 'marketplace-test' });
    if (url.pathname === '/api/status') return json({ running: false });
    if (url.pathname === '/api/descriptions') return json({ items: [] });
    if (url.pathname === '/api/cloud') return json({ providers: [{ id: 'baidu', configured: true }, { id: 'quark', configured: true }], downloadDir: 'C:\\PortShelf\\downloads' });
    if (url.pathname === '/api/transfers') return json({ jobs: [], downloadDir: 'C:\\PortShelf\\downloads' });
    if (url.pathname === '/api/automation') return json({ config: automationConfig(), running: false, credentialStorageSupported: supported });
    if (url.pathname === '/api/marketplace') { reads++; if (failRead) return json({ error: 'mock status unavailable' }, 503); return json(status()); }
    if (url.pathname === '/api/marketplace/jobs') return json({ jobs, error: '' });
    if (url.pathname.startsWith('/api/marketplace/')) requests.push({ path: url.pathname, body });
    if (url.pathname === '/api/marketplace/config') { saves.push(body); await wait(70); if (failSave) return json({ error: 'mock save error' }, 500); config = body; return json(status()); }
    if (url.pathname === '/api/marketplace/connect') { await wait(70); connected = true; credentialSaved = supported; return json(status()); }
    if (url.pathname === '/api/marketplace/disconnect') { connected = false; credentialSaved = false; shops = []; config.enabled = false; return json(status()); }
    if (url.pathname === '/api/marketplace/check') { shops = [{ user_name: 'game-shop', shop_name: '游戏资料店', user_nick: '玩家', is_valid: 1, item_biz_types: '2' }, { user_name: 'expired', shop_name: '过期店铺', is_valid: 0, item_biz_types: '2' }]; return json(status()); }
    if (url.pathname === '/api/marketplace/categories') return json({ items: [{ sp_biz_type: 22, sp_biz_name: '虚拟游戏', channel_cat_id: '5001', channel_cat_name: '已准入测试类目' }] });
    if (url.pathname === '/api/marketplace/properties') {
      if (body.propertyId) { assert.equal(body.propertyId, 'os-detail'); if (failChild) return json({ error: 'mock child property unavailable' }, 503); return json({ items: [{ property_id: 'arch', property_name: '架构', required: 1, items: [{ value_id: 'x64', value_name: 'x64' }, { value_id: 'arm64', value_name: 'ARM64' }] }] }); }
      return json({ items: [{ property_id: 'platform', property_name: '运行平台', required: 1, items: [{ value_id: 'pc', value_name: '电脑', sub_property_id: 'os-detail' }, { value_id: 'mobile', value_name: '手机' }] }] });
    }
    if (url.pathname === '/api/marketplace/addresses') return json({ items: [{ address_id: 1, province: 330000, city: 330100, district: 330106, region: '浙江省 杭州市 西湖区', address: '测试街道' }] });
    if (url.pathname === '/api/marketplace/enqueue') return json({ added: 0 });
    if (url.pathname === '/api/marketplace/run') { running = true; return json({ added: 0 }, 202); }
    if (url.pathname === '/api/marketplace/jobs/unknown/retry') { jobs[1].status = 'confirming'; jobs[1].error = ''; return json({ ok: true }); }
    if (url.pathname === '/api/quit') return json({ ok: true });
    return json({ error: 'unmocked ' + url.pathname }, 404);
  }
  const name = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
  if (!['index.html', 'app.js', 'app.css', 'zh.js', 'cloud.js', 'automation.js', 'marketplace.js', 'gamepad.svg'].includes(name)) { res.statusCode = 404; return res.end(); }
  res.setHeader('Content-Type', name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : name.endsWith('.svg') ? 'image/svg+xml' : 'text/html');
  res.setHeader('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'");
  res.end(fs.readFileSync(path.join(webRoot, name)));
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const outputDir = fs.mkdtempSync(path.join(os.tmpdir(), 'portshelf-marketplace-ui-'));
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  page.on('pageerror', error => pageErrors.push(error.message));
  await page.addInitScript(() => { const original = setTimeout; window.marketplacePollIntervals = []; window.setTimeout = (fn, delay, ...args) => { if (delay === 2500) window.marketplacePollIntervals.push(delay); return original(fn, delay === 2500 ? 100 : delay, ...args); }; });
  const ready = () => page.waitForFunction(() => !document.getElementById('marketplace-toggle').disabled && !document.getElementById('marketplace-refresh').disabled);
  const saved = () => page.waitForFunction(() => document.getElementById('marketplace-save').textContent === '保存铺货设置' && !document.getElementById('marketplace-toggle').disabled);
  try {
    await page.goto(`http://127.0.0.1:${server.address().port}/#${token}`); await page.locator('.game-card').first().waitFor(); assert.equal(reads, 0);
    await page.locator('#cloud-nav').click(); await ready();
    assert.equal(await page.locator('#marketplace-status').textContent(), '已暂停');
    assert.equal(await page.locator('#marketplace-price').inputValue(), ''); assert.equal(await page.locator('#marketplace-stock').inputValue(), '');
    assert.equal(await page.locator('#marketplace-biz').inputValue(), ''); assert.equal(await page.locator('#marketplace-run').isDisabled(), true);
    assert.equal(await page.locator('#marketplace-check').isDisabled(), true); assert.equal(saves.length, 0);
    assert.match(await page.locator('#marketplace-credential-help').textContent(), /尚未保存.*无人值守.*勾选.*在此电脑记住凭据/);
    assert.doesNotMatch(await page.locator('#marketplace-credential-help').textContent(), /已加密保存|连接时将/);
    await page.locator('#marketplace-toggle').click(); assert.match(await page.locator('#marketplace-form-error').textContent(), /凭据/); assert.equal(saves.length, 0);
    await page.locator('#marketplace-title-prefix').fill('开源资料'); await page.locator('#marketplace-save').click(); await saved();
    assert.equal(saves.length, 1); assert.equal(saves[0].enabled, false); assert.equal(saves[0].priceFen, 0); assert.equal(saves[0].stock, 0);
    assert.match(await page.locator('#marketplace-save-note').textContent(), /保持暂停/);

    await page.locator('#marketplace-app-key').fill('test-key-never-store'); await page.locator('#marketplace-app-secret').fill('test-secret-never-store');
    await page.evaluate(() => { const button = document.getElementById('marketplace-connect'); button.click(); button.click(); });
    await page.waitForFunction(() => document.getElementById('marketplace-connection-state').textContent.includes('已连接')); await ready();
    assert.equal(requests.filter(item => item.path === '/api/marketplace/connect').length, 1);
    assert.equal(await page.locator('#marketplace-app-key').inputValue(), ''); assert.equal(await page.locator('#marketplace-app-secret').inputValue(), '');
    assert.match(await page.locator('#marketplace-credential-help').textContent(), /加密.*升级无需重填/);
    assert.equal(await page.evaluate(() => document.querySelector('.marketplace-panel').textContent.includes('test-secret')), false);
    assert.equal(await page.evaluate(() => Object.keys(localStorage).length), 0); assert.deepEqual(await page.evaluate(() => Object.keys(sessionStorage)), ['portshelf-session']);
    await page.locator('#marketplace-check').click(); await page.waitForFunction(() => document.querySelectorAll('#marketplace-shop option').length === 3); await ready();
    assert.equal(await page.locator('#marketplace-shop option[value="expired"]').evaluate(option => option.disabled), true);
    await page.locator('#marketplace-shop').selectOption('game-shop'); await page.locator('#marketplace-biz').selectOption('22');
    await page.locator('#marketplace-categories-load').click(); await page.locator('#marketplace-category-select option[value="5001"]').waitFor({ state: 'attached' }); await ready();
    assert.deepEqual(requests.find(item => item.path.endsWith('/categories')).body, { itemBizType: 2, spBizType: 22 });
    await page.locator('#marketplace-category-select').selectOption('5001'); assert.equal(await page.locator('#marketplace-category').inputValue(), '5001');
    await page.locator('#marketplace-properties-load').click(); await page.locator('[data-property-id="platform"]').waitFor(); await ready();
    await page.locator('#marketplace-addresses-load').click(); await page.waitForFunction(() => document.querySelectorAll('#marketplace-address-select option').length === 2); await ready();
    await page.locator('#marketplace-address-select').selectOption('0'); assert.equal(await page.locator('#marketplace-province').inputValue(), '330000'); assert.equal(await page.locator('#marketplace-city').inputValue(), '330100'); assert.equal(await page.locator('#marketplace-district').inputValue(), '330106');
    await page.locator('#marketplace-price').fill('0.29'); await page.locator('#marketplace-stock').fill('2');
    const beforeInvalid = saves.length; await page.locator('#marketplace-toggle').click(); assert.match(await page.locator('#marketplace-form-error').textContent(), /必填.*运行平台/); assert.equal(saves.length, beforeInvalid);
    failChild = true; await page.locator('[data-property-id="platform"]').selectOption('pc'); await page.waitForFunction(() => document.getElementById('marketplace-form-error').textContent.includes('mock child')); await ready();
    await page.locator('#marketplace-toggle').click(); assert.match(await page.locator('#marketplace-form-error').textContent(), /关联属性尚未/); assert.equal(saves.length, beforeInvalid);
    failChild = false; await page.locator('#marketplace-properties-load').click(); await page.locator('[data-property-id="arch"]').waitFor(); await ready();
    await page.locator('[data-property-id="arch"]').selectOption('x64');
    await page.locator('#marketplace-property-add').click(); await page.locator('[data-manual-property$=":property_id"]').fill('incomplete');
    await page.locator('#marketplace-toggle').click(); assert.match(await page.locator('#marketplace-form-error').textContent(), /都需要填写/); assert.equal(saves.length, beforeInvalid);
    await page.locator('.marketplace-manual-property button').click();
    await page.evaluate(() => { const button = document.getElementById('marketplace-toggle'); button.click(); button.click(); });
    await page.waitForFunction(() => document.getElementById('marketplace-status').textContent === '已开启'); await ready();
    assert.equal(saves.length, beforeInvalid + 1); assert.equal(config.priceFen, 29); assert.equal(config.stock, 2); assert.equal(config.itemBizType, 2);
    assert.deepEqual(config.properties, [{ property_id: 'platform', property_name: '运行平台', value_id: 'pc', value_name: '电脑' }, { property_id: 'arch', property_name: '架构', value_id: 'x64', value_name: 'x64' }]);

    const unknown = page.locator('[data-marketplace-job="unknown"]');
    assert.match(await unknown.textContent(), /创建结果待核实.*先查询远端/s); assert.match(await unknown.textContent(), /远端响应超时 <img/);
    assert.equal(await page.locator('.marketplace-panel img,.marketplace-panel script').count(), 0);
    assert.equal(await page.locator('[data-marketplace-job="unsafe"] a').count(), 0);
    assert.equal(await page.locator('[data-marketplace-job="confirmed"]').getByRole('link', { name: '查看已上架商品 ↗' }).getAttribute('href'), 'https://www.goofish.com/item?id=8001');
    await page.locator('[data-marketplace-job="confirmed"] summary').click();
    assert.match(await page.locator('[data-marketplace-job="confirmed"] pre').textContent(), /<img src=x/);
    await page.waitForTimeout(230); assert.equal(await page.locator('[data-marketplace-job="confirmed"] details').evaluate(detail => detail.open), true);
    await unknown.getByRole('button', { name: '核对结果' }).click(); await page.waitForFunction(() => document.querySelector('[data-marketplace-job="unknown"]').textContent.includes('正在核对上架')); await ready();
    assert.doesNotMatch(await unknown.textContent(), /已确认上架/); assert.equal(requests.filter(item => item.path.endsWith('/unknown/retry')).length, 1);
    assert.equal(await page.locator('[data-marketplace-job="confirmed"] details').evaluate(detail => detail.open), true);
    assert.match(await page.locator('#marketplace-queue-summary').textContent(), /1 个已确认上架/);

    await page.locator('#marketplace-price').fill('12.30'); await page.locator('#marketplace-title-prefix').fill('未保存前缀');
    serviceError = '远端授权需要检查 <script>window.injected=3</script>';
    await page.waitForFunction(() => document.getElementById('marketplace-service-error').textContent.includes('远端授权需要检查')); await page.waitForTimeout(120);
    assert.equal(await page.locator('#marketplace-price').inputValue(), '12.30'); assert.equal(config.priceFen, 29); assert.equal(await page.locator('#marketplace-run').isDisabled(), true);
    assert.equal(await page.locator('#marketplace-enqueue').isDisabled(), true);
    await page.locator('#marketplace-toggle').click(); await page.waitForFunction(() => document.getElementById('marketplace-status').textContent === '已暂停'); await ready();
    assert.equal(config.enabled, false); assert.equal(config.priceFen, 29); assert.equal(await page.locator('#marketplace-price').inputValue(), '12.30'); assert.match(await page.locator('#marketplace-save-note').textContent(), /修改仍已保留/);
    failSave = true; await page.locator('#marketplace-save').click(); await page.waitForFunction(() => document.getElementById('marketplace-form-error').textContent.includes('mock save')); await ready();
    assert.equal(await page.locator('#marketplace-price').inputValue(), '12.30'); assert.equal(config.priceFen, 29);
    failSave = false; serviceError = ''; await page.locator('#marketplace-save').click(); await saved(); assert.equal(config.enabled, false); assert.equal(config.priceFen, 1230);
    await page.locator('#marketplace-enqueue').click(); await page.waitForFunction(() => document.getElementById('marketplace-action-note').textContent.includes('仍保持暂停')); await ready();
    assert.equal(config.enabled, false); assert.equal(requests.filter(item => item.path.endsWith('/enqueue')).length, 1);
    await page.locator('#marketplace-toggle').click(); await page.waitForFunction(() => document.getElementById('marketplace-status').textContent === '已开启'); await ready();
    await page.locator('#marketplace-run').click(); await page.waitForFunction(() => document.getElementById('marketplace-status').textContent === '正在处理');
    assert.equal(await page.locator('#marketplace-run').isDisabled(), true); assert.equal(requests.filter(item => item.path.endsWith('/run')).length, 1);
    running = false; jobs[1].status = 'published'; jobs[1].itemId = '8002'; jobs[1].itemUrl = 'https://www.goofish.com/item?id=8002';
    await page.waitForFunction(() => document.getElementById('marketplace-queue-summary').textContent.includes('2 个已确认上架')); await ready();
    assert.equal(await unknown.getByRole('link').textContent(), '查看已上架商品 ↗');

    await page.locator('#marketplace-price').fill('1.001'); const beforeBadPrice = saves.length; await page.locator('#marketplace-save').click(); assert.match(await page.locator('#marketplace-form-error').textContent(), /两位小数/); assert.equal(saves.length, beforeBadPrice);
    await page.locator('#marketplace-reset').click(); assert.equal(await page.locator('#marketplace-price').inputValue(), '12.30');
    failRead = true; await page.locator('#marketplace-refresh').click(); await page.waitForFunction(() => document.getElementById('marketplace-load-error').textContent.includes('mock status unavailable'));
    assert.equal(await page.locator('#marketplace-status').textContent(), '已开启'); failRead = false;
    await page.locator('#library-nav').click(); await page.waitForTimeout(130); const hiddenReads = reads; await page.waitForTimeout(240); assert.equal(reads, hiddenReads);
    await page.locator('#cloud-nav').click(); await page.waitForFunction(() => document.getElementById('marketplace-load-error').hidden); await ready();
    await page.evaluate(() => { window.mockHidden = true; Object.defineProperty(document, 'hidden', { configurable: true, get: () => window.mockHidden }); document.dispatchEvent(new Event('visibilitychange')); });
    await page.waitForTimeout(130); const tabHiddenReads = reads; await page.waitForTimeout(240); assert.equal(reads, tabHiddenReads);
    await page.evaluate(() => { window.mockHidden = false; document.dispatchEvent(new Event('visibilitychange')); }); await ready();
    assert.ok(await page.evaluate(() => window.marketplacePollIntervals.includes(2500)));
    await page.locator('.marketplace-panel').screenshot({ path: path.join(outputDir, 'desktop.png') });
    await page.setViewportSize({ width: 390, height: 844 }); assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.locator('.marketplace-panel').screenshot({ path: path.join(outputDir, 'mobile.png') });
    await page.locator('#marketplace-disconnect').click(); await page.waitForFunction(() => document.getElementById('marketplace-connection-state').textContent.includes('还未连接')); await ready();
    assert.equal(config.enabled, false); assert.equal(await page.locator('#marketplace-status').textContent(), '已暂停'); assert.equal(credentialSaved, false);
    supported = false; await page.locator('#marketplace-refresh').click(); await page.waitForFunction(() => document.getElementById('marketplace-credential-help').textContent.includes('本次工具运行期间'));
    await page.locator('#marketplace-app-secret').fill('unsent-secret'); await page.locator('#library-nav').click(); assert.equal(await page.locator('#marketplace-app-secret').inputValue(), '');
    await page.locator('#cloud-nav').click(); await ready();
    await page.locator('#quit-open').click(); await page.locator('#quit-confirm').click(); await page.locator('.stopped-message').waitFor();
    await page.waitForTimeout(150); const quitReads = reads; await page.waitForTimeout(230); assert.equal(reads, quitReads);
    assert.equal(await page.evaluate(() => window.injected), undefined); assert.deepEqual(pageErrors, []);
    console.log('PASS marketplace: disabled/no-price drafts, credentials cleared/no browser storage, duplicate guards, detected shop, category and child properties, address codes, exact cents, unknown/pending/confirmed status, safe links/XSS, retained drafts on polling/pause/errors, enqueue/run/retry, mobile layout, visibility/quit polling.');
    console.log('Screenshots: ' + outputDir);
  } finally { await browser.close(); server.close(); }
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
