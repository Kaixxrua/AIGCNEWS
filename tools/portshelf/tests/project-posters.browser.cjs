// OpenRA's multi-game identity is intentional. Artwork here is a local protocol fixture, not a live image verification.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require(process.env.PORTSHELF_PLAYWRIGHT_MODULE || path.resolve(__dirname, '../../../frontend/node_modules/playwright'));
const root = path.resolve(__dirname, '../web');
const token = 'd'.repeat(48);
const checkedAt = new Date().toISOString();
const cachedURL = digit => 'https://aigcnews.cn/api/media/site/game-posters/' + digit.repeat(64) + '.jpg';
const openra = { repo: 'OpenRA/OpenRA', name: 'OpenRA', description: 'An engine for classic real-time strategy games.', stars: 18000 };
const batch = { repo: 'demo/multi-game', name: 'MultiGame', stars: 300 };
const healthy = { repo: 'demo/healthy', name: 'HealthyProject', stars: 200 };
const cooling = { repo: 'demo/cooling', name: 'CoolingProject', stars: 100 };
const discovered = { repo: 'demo/discovered', name: 'DiscoveredEngine', stars: 20 };
const games = [openra, batch, healthy, cooling];
const description = 'OpenRA 是一个支持多款经典即时战略游戏的开源引擎。';
const recordFor = game => ({ repo: game.repo, status: 'ready', source: 'aigcnews', detailsVersion: 1, descriptionZh: game === openra ? description : '这是一个支持多款经典游戏的开源引擎。', gameNameZh: '', gameNameOriginal: '', posterUrl: '', posterSourceUrl: '', posterKind: '', posterStatus: 'missing', posterSearchVersion: 1, posterRetryAfter: 0, checkedAt });
const records = Object.fromEntries([...games, discovered].map(game => [game.repo.toLowerCase(), recordFor(game)]));
const complete = repo => ({ ...records[repo.toLowerCase()], status: 'ready', posterUrl: cachedURL(repo.toLowerCase() === 'openra/openra' ? 'd' : 'c'), posterSourceUrl: 'https://www.openra.net/media/', posterKind: 'screenshot', posterStatus: 'ready', posterRetryAfter: 60, checkedAt: new Date().toISOString() });
Object.assign(records[healthy.repo], complete(healthy.repo));
records[cooling.repo].posterRetryAfter = 300;
records[cooling.repo].posterStatus = 'unavailable';
const posts = [], imageRequests = [];
let finishOpenRA = false;
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://local');
  const json = (value, status = 200) => { res.statusCode = status; res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(value)); };
  if (url.pathname.startsWith('/api/')) {
    assert.equal(req.headers.authorization, 'Bearer ' + token);
    let body; if (req.method === 'POST') { let raw = ''; for await (const chunk of req) raw += chunk; body = JSON.parse(raw || '{}'); }
    if (url.pathname === '/api/library') return json({ games, descriptions: records, snapshots: Object.fromEntries(games.map(game => [game.repo.toLowerCase(), { stars: game.stars, releaseCheckedAt: checkedAt }])), arch: 'amd64', version: 'test', hasAigcToken: true });
    if (url.pathname === '/api/status') return json({ running: false });
    if (url.pathname === '/api/discover') return json({ items: [openra, discovered], page: 1, nextPage: 0, hasMore: false, totalCandidates: 2 });
    if (url.pathname === '/api/descriptions') {
      if (req.method === 'POST') {
        assert.deepEqual(body, { repo: body.repo, ...(body.repo === openra.repo ? { refreshPoster: true } : {}) });
        assert.ok([openra.repo, batch.repo, discovered.repo].includes(body.repo)); posts.push(body);
        const key = body.repo.toLowerCase();
        assert.equal(records[key].gameNameZh, ''); assert.equal(records[key].gameNameOriginal, '');
        if (body.repo === openra.repo) {
          records[key] = { ...records[key], status: 'pending' };
          return json({ items: [{ repo: openra.repo, status: 'pending', detailsVersion: 1 }], pollAfter: 3 });
        }
        records[key] = body.repo === batch.repo ? { ...records[key], posterStatus: 'unavailable', posterRetryAfter: 300, checkedAt: new Date().toISOString() } : complete(body.repo);
        return json({ items: [records[key]], pollAfter: 3 });
      }
      const repos = (url.searchParams.get('repos') || '').split(',');
      if (finishOpenRA && records['openra/openra'].status === 'pending') records['openra/openra'] = complete(openra.repo);
      return json({ items: repos.map(repo => records[repo.toLowerCase()] || { repo, status: 'missing' }), pollAfter: 3 });
    }
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
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 1500 } });
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    const jpeg = Buffer.from(await page.evaluate(() => { const canvas = document.createElement('canvas'); canvas.width = 4; canvas.height = 3; return canvas.toDataURL('image/jpeg').split(',')[1]; }), 'base64');
    await page.route('https://**/*', route => {
      assert.match(route.request().url(), /^https:\/\/aigcnews\.cn\/api\/media\/site\/game-posters\/[cd]{64}\.jpg$/);
      assert.equal(route.request().headers().authorization, undefined); assert.equal(route.request().headers().referer, undefined);
      imageRequests.push(route.request().url());
      return route.fulfill({ status: 200, contentType: 'image/jpeg', body: jpeg });
    });
    await page.goto(`http://127.0.0.1:${server.address().port}/#${token}`);
    await page.waitForFunction(() => document.getElementById('game-count').textContent === '4');
    const card = repo => page.locator('#game-' + repo.replace(/[^a-zA-Z0-9_-]/g, '-')).locator('..');
    const target = card(openra.repo), bulk = page.locator('#library-descriptions-fill');
    assert.equal(await target.locator('.card-title').innerText(), 'OpenRA');
    assert.match(await target.locator('.card-subtitle').innerText(), /中文名待确认/);
    assert.equal(await target.getByRole('button', { name: '联网重找海报', exact: true }).isEnabled(), true);
    assert.match(await target.locator('.description-control').innerText(), /按项目查图.*使用现有富化额度/);
    assert.match(await bulk.innerText(), /（2）/);
    assert.equal(await card(cooling.repo).getByRole('button', { name: '稍后联网重找', exact: true }).isDisabled(), true);
    assert.deepEqual(posts, [], 'reading a completed no-original-name record must never submit a paid search');

    await target.getByRole('button', { name: '联网重找海报', exact: true }).evaluate(button => { button.click(); button.click(); });
    await target.getByRole('button', { name: '核对生成进度', exact: true }).waitFor();
    assert.equal(await target.locator('.card-title').innerText(), 'OpenRA');
    assert.equal(await target.locator('.card-description').innerText(), description);
    assert.match(await target.locator('.description-control').innerText(), /正在联网查找海报/);
    finishOpenRA = true;
    await target.getByRole('button', { name: '核对生成进度', exact: true }).click();
    await page.waitForFunction(() => document.getElementById('game-OpenRA-OpenRA').closest('article').querySelector('img')?.naturalWidth > 0);
    assert.deepEqual(posts, [{ repo: openra.repo, refreshPoster: true }]);
    assert.equal(await target.locator('.card-title').innerText(), 'OpenRA');
    assert.match(await target.locator('.card-subtitle').innerText(), /中文名待确认/);
    assert.match(await target.locator('.poster-caption').innerText(), /项目画面.*图片来源/s);
    assert.equal(await target.locator('.poster-caption a').getAttribute('href'), 'https://www.openra.net/media/');
    await target.getByRole('button', { name: '查看 OpenRA 的下载', exact: true }).click();
    await page.locator('.detail-poster img').waitFor();
    assert.equal(await page.locator('#detail-title').innerText(), 'OpenRA');
    assert.equal(await page.locator('.detail-description').innerText(), description);
    assert.match(await page.locator('#detail-content .description-control').innerText(), /按项目官方资料查找海报或画面/);
    await page.locator('#detail-close').click();

    assert.match(await bulk.innerText(), /（1）/);
    await bulk.evaluate(button => { button.click(); button.click(); });
    await page.waitForFunction(() => document.getElementById('description-progress-label').textContent.includes('游戏资料提交完成'));
    assert.deepEqual(posts, [{ repo: openra.repo, refreshPoster: true }, { repo: batch.repo }]);
    assert.equal(await card(batch.repo).locator('.card-title').innerText(), batch.name);
    assert.equal(await card(batch.repo).locator('.card-description').innerText(), records[batch.repo].descriptionZh);
    assert.match(await card(batch.repo).locator('.poster-placeholder').innerText(), /海报暂未取得，可重试/);
    assert.equal(await card(batch.repo).getByRole('button', { name: '稍后联网重找', exact: true }).isDisabled(), true);
    assert.equal(await bulk.isDisabled(), true, 'healthy and cooling projects do not remain in the next batch');

    await page.locator('#discover-nav').click(); await page.locator('#discover-submit').click();
    await page.locator('[data-repository="demo/discovered"]').waitFor();
    await page.locator('#descriptions-fill').evaluate(button => { button.click(); button.click(); });
    await page.waitForFunction(() => document.querySelector('[data-repository="demo/discovered"] img'));
    assert.deepEqual(posts, [{ repo: openra.repo, refreshPoster: true }, { repo: batch.repo }, { repo: discovered.repo }]);
    assert.equal(await page.locator('[data-repository="demo/discovered"] h3').innerText(), discovered.name);
    assert.match(await page.locator('[data-repository="demo/discovered"] .poster-caption').innerText(), /项目画面/);
    assert.equal(await page.locator('#descriptions-fill').isDisabled(), true);
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.locator('#library-nav').click();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.reload(); await page.waitForFunction(() => document.getElementById('game-count').textContent === '4');
    assert.equal(posts.length, 3, 'reload and polling never repeat completed poster submissions');
    assert.equal(await target.locator('img').getAttribute('src'), cachedURL('d'));
    assert.equal(records['openra/openra'].gameNameZh, ''); assert.equal(records['openra/openra'].gameNameOriginal, '');
    assert.ok(imageRequests.length > 0); assert.deepEqual(errors, []);
    console.log('PASS OpenRA multi-game project: explicit forced search, pending text/identity preservation, official-project screenshot display, library/discovery batch without invented names, healthy/cooling skips, failure cooldown, no duplicate or implicit POST, and 390px layout.');
  } finally { await browser.close(); server.close(); }
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
