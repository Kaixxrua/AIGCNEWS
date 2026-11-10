// Browser protocol regression uses route fixtures. Set PORTSHELF_LIVE_POSTER=1 for a separate anonymous live-image decode check.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const os = require('node:os');
const { chromium } = require(process.env.PORTSHELF_PLAYWRIGHT_MODULE || path.resolve(__dirname, '../../../frontend/node_modules/playwright'));
const root = path.resolve(__dirname, '../web');
const token = 'f'.repeat(48);
const imageURL = 'https://upload.wikimedia.org/wikipedia/en/f/fb/The_Legend_of_Zelda_Tears_of_the_Kingdom_cover.jpg';
const sourceURL = 'https://en.wikipedia.org/wiki/The_Legend_of_Zelda:_Tears_of_the_Kingdom';
const totk = { repo: 'valentderah/totk-pc-recomp', name: 'totk-pc-recomp', description: 'A PC recompilation project.', stars: 99 };
const games = [totk, { repo: 'demo/no-cover', name: 'NoCover', stars: 80 }, { repo: 'demo/network', name: 'NetworkPort', stars: 60 }, { repo: 'demo/unknown', name: 'UnknownOriginal', stars: 40 }];
const batchGame = { repo: 'demo/batch', name: 'BatchPort', stars: 20 };
const checkedAt = new Date().toISOString();
const description = '这是《塞尔达传说：王国之泪》的电脑移植项目，需要自备合法原作资源。';
const recordFor = (game, patch = {}) => ({ repo: game.repo, status: 'ready', descriptionZh: '这是一个经典游戏的开源移植。', gameNameZh: '测试游戏', gameNameOriginal: game.name, detailsVersion: 1, checkedAt, ...patch });
const records = {
  [totk.repo]: recordFor(totk, { gameNameZh: '塞尔达传说：王国之泪', gameNameOriginal: 'The Legend of Zelda: Tears of the Kingdom', descriptionZh: description, posterUrl: '', posterSourceUrl: '', posterKind: '' }),
  'demo/no-cover': recordFor(games[1], { gameNameZh: '未找到封面的游戏', posterStatus: 'missing', posterRetryAfter: 3600, posterSearchVersion: 1 }),
  'demo/network': recordFor(games[2], { gameNameZh: '网络失败的游戏', posterStatus: 'unavailable', posterRetryAfter: 300, posterSearchVersion: 1 }),
  'demo/unknown': recordFor(games[3], { gameNameZh: '', gameNameOriginal: '', posterStatus: 'missing', posterRetryAfter: 0 }),
  [batchGame.repo]: recordFor(batchGame, { gameNameZh: '批量补图游戏' }),
};
const posts = [], reads = [], imageRequests = [];
let finishPoster = false;
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://local');
  const json = (value, status = 200) => { res.statusCode = status; res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(value)); };
  if (url.pathname.startsWith('/api/')) {
    assert.equal(req.headers.authorization, 'Bearer ' + token);
    let body; if (req.method === 'POST') { let raw = ''; for await (const chunk of req) raw += chunk; body = JSON.parse(raw || '{}'); }
    if (url.pathname === '/api/library') return json({ games, descriptions: records, snapshots: Object.fromEntries(games.map(game => [game.repo, { stars: game.stars, releaseCheckedAt: checkedAt }])), arch: 'amd64', version: 'test', hasAigcToken: true });
    if (url.pathname === '/api/status') return json({ running: false });
    if (url.pathname === '/api/descriptions') {
      if (req.method === 'POST') {
        assert.deepEqual(body, { repo: body.repo, ...(body.repo === batchGame.repo ? {} : { refreshPoster: true }) }); posts.push(body.repo);
        assert.equal(records[body.repo].detailsVersion, 1, 'fixture requests only supplement posters for existing detailed text');
        if (body.repo === totk.repo) {
          records[totk.repo] = { ...records[totk.repo], status: 'pending' };
          return json({ items: [{ repo: totk.repo, status: 'pending', detailsVersion: 1 }], pollAfter: 3 });
        }
        records[body.repo] = { ...records[body.repo], posterStatus: 'missing', posterRetryAfter: 3600, posterSearchVersion: 1, checkedAt: new Date().toISOString() };
        return json({ items: [records[body.repo]] });
      }
      const repos = (url.searchParams.get('repos') || '').split(','); reads.push(repos);
      if (finishPoster && records[totk.repo].status === 'pending') records[totk.repo] = { ...records[totk.repo], status: 'ready', posterUrl: imageURL, posterSourceUrl: sourceURL, posterKind: 'cover', posterStatus: 'ready', posterRetryAfter: 60, posterSearchVersion: 1, checkedAt: new Date().toISOString() };
      return json({ items: repos.map(repo => records[repo] || { repo, status: 'missing' }), pollAfter: 3 });
    }
    if (url.pathname === '/api/discover') return json({ items: [totk, batchGame], page: 1, nextPage: 0, hasMore: false, totalCandidates: 2 });
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
  const outputDir = fs.mkdtempSync(path.join(os.tmpdir(), 'portshelf-posters-ui-'));
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => { const actualNow = Date.now; window.posterClockOffset = 0; Date.now = () => actualNow() + window.posterClockOffset; });
    await page.route('https://**/*', async route => {
      assert.equal(route.request().url(), imageURL); assert.equal(route.request().headers().authorization, undefined); assert.equal(route.request().headers().referer, undefined);
      imageRequests.push(route.request().url());
      if (imageRequests.length === 1) return route.fulfill({ status: 503, body: 'temporary image failure' });
      return route.fulfill({ status: 200, contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="260" height="380"><rect width="260" height="380" fill="#d7e5f5"/><text x="130" y="170" text-anchor="middle" font-size="19" fill="#45658d">TOTK poster fixture</text><text x="130" y="205" text-anchor="middle" font-size="12" fill="#45658d">Protocol test, not real artwork</text></svg>' });
    });
    await page.goto(`http://127.0.0.1:${server.address().port}/#${token}`);
    await page.waitForFunction(() => document.getElementById('game-count').textContent === '4');
    const card = repo => page.locator('#game-' + repo.replace(/[^a-zA-Z0-9_-]/g, '-')).locator('..');
    const target = card(totk.repo), network = card('demo/network'), missing = card('demo/no-cover');
    assert.equal(await target.locator('.card-title').innerText(), '塞尔达传说：王国之泪');
    assert.equal(await target.getByRole('button', { name: '联网重找海报', exact: true }).isEnabled(), true);
    assert.equal(posts.length, 0, 'old v1 cache reads must not automatically submit enrichment');
    assert.match(await missing.locator('.poster-placeholder').innerText(), /暂未找到匹配海报/);
    assert.equal(await missing.getByRole('button', { name: '稍后联网重找', exact: true }).isDisabled(), true);
    assert.match(await network.locator('.poster-placeholder').innerText(), /海报暂未取得，可重试/);
    assert.equal(await network.getByRole('button', { name: '稍后联网重找', exact: true }).isDisabled(), true);
    assert.equal(await card('demo/unknown').locator('.description-button').count(), 0);

    await target.getByRole('button', { name: '联网重找海报', exact: true }).click();
    await target.getByRole('button', { name: '核对生成进度', exact: true }).waitFor();
    assert.equal(await target.locator('.card-description').innerText(), description);
    assert.equal(await target.locator('.card-title').innerText(), '塞尔达传说：王国之泪');
    finishPoster = true;
    await target.getByRole('button', { name: '核对生成进度', exact: true }).click();
    await target.getByRole('button', { name: '重试图片', exact: true }).waitFor();
    assert.deepEqual(posts, [totk.repo]);
    const failures = imageRequests.length;
    await page.locator('#library-search').fill('王国之泪'); await page.locator('#library-search').fill('');
    assert.equal(imageRequests.length, failures, 'rerendering an image failure must not retry network requests');
    await target.getByRole('button', { name: '重试图片', exact: true }).evaluate(button => { button.click(); button.click(); });
    await target.locator('img').waitFor();
    await page.waitForFunction(() => document.querySelector('#game-valentderah-totk-pc-recomp').closest('article').querySelector('img')?.naturalWidth > 0);
    assert.equal(imageRequests.length, failures + 1, 'a deliberate image retry performs one request');
    assert.equal(posts.length, 1, 'image reload must not submit or regenerate text');
    assert.equal(await target.locator('.poster-caption a').getAttribute('href'), sourceURL);
    assert.equal(await target.locator('img').evaluate(img => getComputedStyle(img).objectFit), 'contain');

    await page.evaluate(() => { window.posterClockOffset = 120000; document.getElementById('library-search').dispatchEvent(new Event('input')); });
    assert.match(await network.locator('.description-control').innerText(), /约 3 分钟后/);
    await network.getByRole('button', { name: '查看 网络失败的游戏 的下载' }).click();
    await page.waitForFunction(() => document.querySelector('#detail-content .description-control')?.textContent.includes('约 3 分钟后'));
    await page.locator('#detail-close').click();
    assert.equal(posts.length, 1, 'checking cached cooldown does not submit a retry');
    await page.evaluate(() => { window.posterClockOffset = 301000; document.getElementById('library-search').dispatchEvent(new Event('input')); });
    await network.getByRole('button', { name: '联网重找海报', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('#game-demo-network').closest('article').querySelector('.poster-placeholder')?.textContent === '暂未找到匹配海报');
    assert.equal(await network.locator('.card-description').innerText(), records['demo/network'].descriptionZh);
    assert.equal(await network.getByRole('button', { name: '稍后联网重找', exact: true }).isDisabled(), true);
    assert.equal(await page.locator('#library-descriptions-fill').isDisabled(), true);
    assert.match(await page.locator('#library-descriptions-fill').innerText(), /海报稍后可重试/);

    await page.locator('#discover-nav').click(); await page.locator('#discover-submit').click();
    await page.locator('[data-repository="demo/batch"]').waitFor();
    await page.locator('#descriptions-fill').click();
    await page.waitForFunction(() => document.getElementById('description-progress-label').textContent.includes('游戏资料提交完成'));
    assert.deepEqual(posts, [totk.repo, 'demo/network', 'demo/batch']);
    assert.equal(await page.locator('#descriptions-fill').isDisabled(), true);
    assert.match(await page.locator('[data-repository="demo/batch"] .poster-placeholder').innerText(), /暂未找到匹配海报/);
    assert.match(await page.locator('#descriptions-fill').innerText(), /海报稍后可重试/);
    await page.locator('#library-nav').click(); await page.evaluate(() => { document.getElementById('toast').hidden = true; window.scrollTo(0, 0); });
    await page.screenshot({ path: path.join(outputDir, 'desktop-fixture.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 }); assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: path.join(outputDir, 'mobile-fixture.png'), fullPage: true });
    await page.reload(); await page.waitForFunction(() => document.getElementById('game-count').textContent === '4');
    assert.deepEqual(posts, [totk.repo, 'demo/network', 'demo/batch']);
    assert.equal(await target.getByRole('button', { name: '稍后联网重找', exact: true }).isDisabled(), true);
    assert.equal(await target.locator('img').getAttribute('src'), imageURL);
    assert.deepEqual(errors, []);
    console.log('PASS fixture: actual TOTK v1 field shape, poster-only explicit POST, pending text/name preservation, Wikipedia/raster source pairing, missing/unavailable/cooldown states, cached checkedAt countdown, current-result batch, no implicit repeat POST, one deliberate image retry, 390px layout.');
    console.log('Fixture screenshots: ' + outputDir);
    if (process.env.PORTSHELF_LIVE_POSTER === '1') {
      const live = await browser.newPage();
      await live.setContent('<img id="live-poster" alt="TOTK actual cover" referrerpolicy="no-referrer">');
      await live.locator('img').evaluate((image, url) => { image.src = url; }, imageURL);
      await live.waitForFunction(() => document.getElementById('live-poster').naturalWidth > 0, null, { timeout: 20000 });
      const dimensions = await live.locator('img').evaluate(img => ({ width: img.naturalWidth, height: img.naturalHeight, url: img.currentSrc }));
      console.log('PASS live anonymous Chromium image decode: ' + JSON.stringify(dimensions));
      await live.close();
    }
  } finally { await browser.close(); server.close(); }
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
