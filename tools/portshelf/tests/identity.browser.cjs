// Focused browser contract for Chinese game identity, trusted artwork and old-cache upgrades.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const os = require('node:os');
const { chromium } = require(process.env.PORTSHELF_PLAYWRIGHT_MODULE || path.resolve(__dirname, '../../../frontend/node_modules/playwright'));
const { defaultConfig } = require('../web/automation.js');
const root = path.resolve(__dirname, '../web');
const token = 'e'.repeat(48);
const games = [
  { repo: 'peilika/LASRecomp', name: 'LASRecomp', description: 'A community source recompilation.', category: '冒险', stars: 2274 },
  { repo: 'demo/old', name: 'OldPort', description: 'The older port.', stars: 500 },
  { repo: 'demo/broken', name: 'ImagePort', description: 'An image fixture.', stars: 400 },
  { repo: 'demo/unknown', name: 'UnknownPort', description: 'No confirmed identity.', stars: 300 },
  { repo: 'demo/unsafe', name: 'UnsafePort', description: '<img src=x onerror="window.injected=1">', stars: 200 },
];
const discovered = { repo: 'demo/discovered', name: 'DiscoveredPort', description: 'A newly discovered game.', stars: 120 };
const oldDescription = '该项目将《塞尔达传说：织梦岛》静态重编译为电脑原生游戏。';
const cover = 'https://raw.githubusercontent.com/demo/art/main/cover.png';
const broken = 'https://user-images.githubusercontent.com/1/unavailable.png';
const records = {
  'peilika/lasrecomp': { repo: 'peilika/LASRecomp', status: 'ready', descriptionZh: oldDescription },
  'demo/old': { repo: 'demo/old', status: 'ready', descriptionZh: '这是保留下来的旧版游戏简介。' },
  'demo/broken': { repo: 'demo/broken', status: 'ready', descriptionZh: '一款有画面的经典游戏。', gameNameZh: '图片测试游戏', posterUrl: broken, posterSourceUrl: 'https://github.com/demo/broken', posterKind: 'cover', detailsVersion: 1 },
  'demo/unknown': { repo: 'demo/unknown', status: 'ready', descriptionZh: '游戏信息已核对，但原作暂时无法确认。', detailsVersion: 1 },
  'demo/unsafe': { repo: 'demo/unsafe', status: 'ready', descriptionZh: '游戏简介 <img src=x onerror="window.injected=2">', gameNameZh: '<img src=x onerror="window.injected=3">中文', posterUrl: 'javascript:window.injected=4', posterSourceUrl: 'https://github.com.evil.test/poster', detailsVersion: 1 },
  'demo/discovered': { repo: discovered.repo, status: 'ready', descriptionZh: '这是发现列表中的旧版游戏简介。' },
};
const completed = repo => ({ repo, status: 'ready', descriptionZh: repo.toLowerCase() === 'peilika/lasrecomp' ? oldDescription : '这是一款适合现代电脑的经典开源游戏。', gameNameZh: repo.toLowerCase() === 'peilika/lasrecomp' ? '塞尔达传说：织梦岛' : repo === 'demo/old' ? '旧作历险记' : '新发现的冒险', gameNameOriginal: 'The Original Adventure', posterUrl: cover, posterSourceUrl: 'https://github.com/demo/art/blob/main/README.md#screenshots', posterKind: 'screenshot', detailsVersion: 1 });
const posts = [], reads = [], imageRequests = [];
let finishPending = false, failOld = true;
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://local');
  const json = (value, status = 200) => { res.statusCode = status; res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(value)); };
  if (url.pathname.startsWith('/api/')) {
    assert.equal(req.headers.authorization, 'Bearer ' + token);
    let body; if (req.method === 'POST') { let raw = ''; for await (const part of req) raw += part; body = JSON.parse(raw || '{}'); }
    if (url.pathname === '/api/library') return json({ games, snapshots: Object.fromEntries(games.map(game => [game.repo.toLowerCase(), { stars: game.stars, starsCheckedAt: '2026-11-10T00:00:00Z', releaseCheckedAt: '2026-11-10T00:00:00Z' }])), descriptions: records, arch: 'amd64', version: 'test', hasAigcToken: true });
    if (url.pathname === '/api/status') return json({ running: false });
    if (url.pathname === '/api/descriptions') {
      if (req.method === 'POST') {
        assert.deepEqual(Object.keys(body), ['repo']); posts.push(body.repo);
        if (body.repo === 'demo/old' && failOld) return json({ error: 'mock enrichment unavailable' }, 503);
        const key = body.repo.toLowerCase();
        records[key] = key === 'peilika/lasrecomp' ? { repo: body.repo, status: 'pending' } : completed(body.repo);
        return json({ items: [records[key]], pollAfter: 3 });
      }
      const repos = (url.searchParams.get('repos') || '').split(','); reads.push(repos);
      for (const repo of repos) if (records[repo.toLowerCase()]?.status === 'pending' && finishPending) records[repo.toLowerCase()] = completed(repo);
      return json({ items: repos.map(repo => records[repo.toLowerCase()] || { repo, status: 'missing' }), pollAfter: 3 });
    }
    if (url.pathname === '/api/discover') return json({ items: [games[0], discovered], page: 1, nextPage: 0, hasMore: false, totalCandidates: 2 });
    if (url.pathname === '/api/automation') return json({ config: defaultConfig('amd64'), running: false, credentialStorageSupported: false, startOnLoginSupported: false });
    if (url.pathname === '/api/cloud') return json({ providers: [], downloadDir: 'C:\\PortShelf\\downloads' });
    if (url.pathname === '/api/transfers') return json({ jobs: [{ id: 'named', repo: games[0].repo, name: games[0].name, status: 'done', description: oldDescription, outputs: {} }] });
    if (url.pathname === '/api/quit') return json({ ok: true });
    return json({ error: 'Unmocked ' + url.pathname }, 404);
  }
  const name = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
  if (!['index.html', 'app.js', 'app.css', 'zh.js', 'cloud.js', 'automation.js', 'gamepad.svg'].includes(name)) { res.statusCode = 404; return res.end(); }
  res.setHeader('Content-Type', name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : name.endsWith('.svg') ? 'image/svg+xml' : 'text/html');
  res.end(fs.readFileSync(path.join(root, name)));
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const outputDir = fs.mkdtempSync(path.join(os.tmpdir(), 'portshelf-identity-ui-'));
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => { navigator.clipboard.writeText = async value => { window.copiedMaterial = value; }; });
    await page.route('https://**/*', async route => {
      const request = route.request(); imageRequests.push(request.url());
      assert.equal(request.headers().authorization, undefined); assert.equal(request.headers().referer, undefined);
      if (request.url() === cover) return route.fulfill({ status: 200, contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180"><rect width="320" height="180" fill="#d7e5f5"/><text x="160" y="95" text-anchor="middle" font-size="20" fill="#45658d">Upstream artwork fixture</text></svg>' });
      assert.equal(request.url(), broken); return route.fulfill({ status: 404, body: '' });
    });
    await page.goto(`http://127.0.0.1:${server.address().port}/#${token}`);
    await page.waitForFunction(() => document.getElementById('game-count').textContent === '5');
    await page.waitForFunction(() => document.querySelector('#game-demo-broken')?.closest('article').querySelector('.poster-placeholder')?.textContent === '图片暂不可用');
    const failedImageRequests = imageRequests.filter(url => url === broken).length;
    const card = repo => page.locator('#game-' + repo.replace(/[^a-zA-Z0-9_-]/g, '-')).locator('..');
    const las = card(games[0].repo), old = card('demo/old');
    assert.equal(await las.locator('.card-title').innerText(), 'LASRecomp');
    assert.match(await las.locator('.card-subtitle').innerText(), /中文名待确认/);
    assert.equal(await las.locator('.card-description').innerText(), oldDescription);
    assert.equal(await las.getByRole('button', { name: '补全中文名与海报', exact: true }).count(), 1);
    assert.equal(await card('demo/unknown').locator('.description-button').count(), 0);
    assert.equal(await card('demo/unsafe').locator('img').count(), 0);
    assert.equal(await card('demo/unsafe').locator('.poster-caption a').count(), 0);
    assert.equal(posts.length, 0, 'reading old caches must not silently spend generation credits');

    await las.getByRole('button', { name: '补全中文名与海报', exact: true }).click();
    await las.getByRole('button', { name: '核对生成进度', exact: true }).waitFor();
    assert.equal(await las.locator('.card-description').innerText(), oldDescription, 'pending upgrade must retain prior text');
    finishPending = true;
    await las.getByRole('button', { name: '核对生成进度', exact: true }).click();
    await page.waitForFunction(() => document.getElementById('game-peilika-LASRecomp').textContent === '塞尔达传说：织梦岛');
    assert.equal(posts.length, 1);
    const artwork = las.locator('img');
    assert.equal(await artwork.getAttribute('loading'), 'lazy'); assert.equal(await artwork.getAttribute('referrerpolicy'), 'no-referrer');
    assert.equal(await artwork.evaluate(image => getComputedStyle(image).objectFit), 'contain');
    assert.match(await las.locator('.poster-caption').innerText(), /游戏画面.*图片来源/s);
    assert.match(await las.locator('.card-subtitle').innerText(), /LASRecomp.*peilika\/LASRecomp/);
    await las.getByRole('button', { name: '查看 塞尔达传说：织梦岛 的下载' }).click();
    assert.equal(await page.locator('#detail-title').innerText(), '塞尔达传说：织梦岛');
    assert.equal(await page.locator('.detail-poster img').getAttribute('src'), cover);
    await page.locator('#detail-close').click();
    await old.getByRole('button', { name: '补全中文名与海报', exact: true }).click();
    await old.getByRole('button', { name: '重试游戏资料', exact: true }).waitFor();
    assert.equal(await old.locator('.card-description').innerText(), '这是保留下来的旧版游戏简介。');
    failOld = false;
    await page.locator('#library-descriptions-fill').click();
    await page.waitForFunction(() => document.getElementById('description-progress-label').textContent.includes('游戏资料提交完成'));
    assert.equal(await old.locator('.card-title').innerText(), '旧作历险记');
    assert.deepEqual(posts, ['peilika/LASRecomp', 'demo/old', 'demo/old']);
    assert.equal(await page.locator('#library-descriptions-fill').isDisabled(), true);

    await page.locator('#library-search').fill('织梦岛'); assert.equal(await page.locator('.game-card').count(), 1);
    await page.locator('#cloud-nav').click();
    await page.locator('[data-job-id="named"]').waitFor();
    assert.equal(await page.locator('.transfer-game strong').innerText(), '塞尔达传说：织梦岛');
    assert.equal(await page.locator('[data-job-id="named"] h3').innerText(), '塞尔达传说：织梦岛');
    await page.locator('[data-job-id="named"]').getByRole('button', { name: '复制分享资料', exact: true }).click();
    assert.match(await page.evaluate(() => window.copiedMaterial), /^塞尔达传说：织梦岛\n/);
    await page.locator('#library-nav').click(); await page.locator('#library-search').fill('');
    await page.locator('#list-view').click(); await page.locator('#grid-view').click();
    assert.equal(imageRequests.filter(url => url === broken).length, failedImageRequests, 'failed images must not refetch on every rerender');
    await page.locator('#discover-nav').click(); await page.locator('#discover-submit').click();
    const row = page.locator('[data-repository="peilika/lasrecomp"]'); await row.waitFor();
    assert.equal(await row.locator('h3').innerText(), '塞尔达传说：织梦岛');
    assert.equal(await row.locator('.search-poster img').getAttribute('src'), cover);
    await page.locator('#descriptions-fill').click();
    await page.waitForFunction(() => document.querySelector('[data-repository="demo/discovered"] h3')?.textContent === '新发现的冒险');
    assert.equal(posts.at(-1), discovered.repo); assert.equal(posts.length, 4);
    assert.equal(await page.locator('#descriptions-fill').isDisabled(), true);

    await page.locator('#library-nav').click(); await page.evaluate(() => { document.getElementById('toast').hidden = true; window.scrollTo(0, 0); });
    await page.screenshot({ path: path.join(outputDir, 'desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: path.join(outputDir, 'mobile.png'), fullPage: true });
    await page.locator('#list-view').click(); assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.locator('#discover-nav').click(); assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: path.join(outputDir, 'discovery-mobile.png'), fullPage: true });
    assert.equal(await page.evaluate(() => window.injected), undefined); assert.deepEqual(errors, []);
    console.log('PASS Chinese identity across library/details/discovery/download selection/share copy; explicit old-cache single/bulk upgrades; retained pending/failed descriptions; trusted images/source links/no auth leakage/lazy loading/error fallback without repeated requests; no re-enrichment loop; XSS and 390px grid/list/discovery.');
    console.log('Screenshots: ' + outputDir);
  } finally { await browser.close(); server.close(); }
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
