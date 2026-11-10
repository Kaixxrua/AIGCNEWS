// Browser contract fixtures exercise explicit bulk repair; all artwork responses are local mocks.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require(process.env.PORTSHELF_PLAYWRIGHT_MODULE || path.resolve(__dirname, '../../../frontend/node_modules/playwright'));
const root = path.resolve(__dirname, '../web');
const token = 'c'.repeat(48);
const baseTime = Date.now();
const cachedURL = digit => 'https://aigcnews.cn/api/media/site/game-posters/' + digit.repeat(64) + '.jpg';
const games = [
  { repo: 'demo/broken-one', name: 'BrokenOne', stars: 500 },
  { repo: 'demo/broken-two', name: 'BrokenTwo', stars: 400 },
  { repo: 'demo/healthy', name: 'Healthy', stars: 300 },
  { repo: 'demo/missing', name: 'Missing', stars: 200 },
  { repo: 'demo/cooling', name: 'Cooling', stars: 100 },
];
const brokenURLs = ['https://raw.githubusercontent.com/demo/art/main/one.png', 'https://raw.githubusercontent.com/demo/art/main/two.png', 'https://raw.githubusercontent.com/demo/art/main/cooling.png'];
const records = Object.fromEntries(games.map(game => [game.repo, { repo: game.repo, status: 'ready', detailsVersion: 1, descriptionZh: '这是一个经典游戏的开源移植。', gameNameZh: '测试游戏 ' + game.name, gameNameOriginal: game.name, posterUrl: '', posterSourceUrl: '', posterKind: '', checkedAt: new Date(baseTime).toISOString() }]));
for (const [index, url] of [[0, brokenURLs[0]], [1, brokenURLs[1]], [4, brokenURLs[2]]]) Object.assign(records[games[index].repo], { posterUrl: url, posterSourceUrl: 'https://github.com/demo/art', posterKind: 'screenshot', posterStatus: 'ready' });
Object.assign(records[games[2].repo], { posterUrl: cachedURL('c'), posterSourceUrl: 'https://example.com/healthy', posterKind: 'cover', posterStatus: 'ready', posterSearchVersion: 1 });
Object.assign(records[games[4].repo], { posterSearchVersion: 1, posterRetryAfter: 300, posterStatus: 'unavailable' });
const posts = [], imageRequests = [];
let pendingRepo = '';
let expireHealthy = false;
const completed = repo => ({ ...records[repo], status: 'ready', posterUrl: cachedURL(String(games.findIndex(game => game.repo === repo) + 1)), posterSourceUrl: 'https://example.com/' + repo, posterKind: 'cover', posterStatus: 'ready', posterSearchVersion: 1, posterRetryAfter: 60, checkedAt: new Date(baseTime).toISOString() });
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://local');
  const json = (value, status = 200) => { res.statusCode = status; res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(value)); };
  if (url.pathname.startsWith('/api/')) {
    assert.equal(req.headers.authorization, 'Bearer ' + token);
    let body; if (req.method === 'POST') { let raw = ''; for await (const chunk of req) raw += chunk; body = JSON.parse(raw || '{}'); }
    if (url.pathname === '/api/library') return json({ games, descriptions: records, snapshots: Object.fromEntries(games.map(game => [game.repo, { stars: game.stars, releaseCheckedAt: new Date(baseTime).toISOString() }])), arch: 'amd64', version: 'test', hasAigcToken: true });
    if (url.pathname === '/api/status') return json({ running: false });
    if (url.pathname === '/api/discover') return json({ items: games, page: 1, nextPage: 0, hasMore: false, totalCandidates: games.length });
    if (url.pathname === '/api/descriptions') {
      if (req.method === 'POST') {
        const broken = ['demo/broken-one', 'demo/broken-two'].includes(body.repo);
        assert.deepEqual(body, { repo: body.repo, ...(broken ? { refreshPoster: true } : {}) });
        assert.ok(['demo/broken-one', 'demo/broken-two', 'demo/missing', 'demo/healthy'].includes(body.repo));
        posts.push(body);
        if (body.repo === 'demo/healthy') expireHealthy = false;
        if (body.repo === 'demo/broken-one') {
          assert.equal(pendingRepo, ''); pendingRepo = body.repo;
          records[body.repo] = { ...records[body.repo], status: 'pending' };
        } else records[body.repo] = completed(body.repo);
        return json({ items: [records[body.repo]], pollAfter: 3 });
      }
      const repos = (url.searchParams.get('repos') || '').split(',');
      if (pendingRepo && repos.includes(pendingRepo)) { records[pendingRepo] = completed(pendingRepo); pendingRepo = ''; }
      if (expireHealthy && repos.includes('demo/healthy')) {
        records['demo/healthy'] = { ...records['demo/healthy'], posterStatus: 'missing', posterRetryAfter: 0 };
        for (const field of ['posterUrl', 'posterSourceUrl', 'posterKind']) delete records['demo/healthy'][field]; // Go's omitempty form of an authoritative ready record.
      }
      return json({ items: repos.map(repo => records[repo]), pollAfter: 3 });
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
    const page = await browser.newPage({ viewport: { width: 1440, height: 2000 } });
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(now => { Date.now = () => now; }, baseTime);
    const jpeg = Buffer.from(await page.evaluate(() => { const canvas = document.createElement('canvas'); canvas.width = 2; canvas.height = 3; return canvas.toDataURL('image/jpeg').split(',')[1]; }), 'base64');
    await page.route('https://**/*', route => {
      const url = route.request().url(); imageRequests.push(url);
      assert.equal(route.request().headers().authorization, undefined); assert.equal(route.request().headers().referer, undefined);
      if (brokenURLs.includes(url)) return route.fulfill({ status: 404, body: 'missing old image' });
      assert.match(url, /^https:\/\/aigcnews\.cn\/api\/media\/site\/game-posters\/[0-9a-f]{64}\.jpg$/);
      return route.fulfill({ status: 200, contentType: 'image/jpeg', body: jpeg });
    });
    await page.goto(`http://127.0.0.1:${server.address().port}/#${token}`);
    await page.waitForFunction(() => document.getElementById('game-count').textContent === '5');
    const card = repo => page.locator('#game-' + repo.replace(/[^a-zA-Z0-9_-]/g, '-')).locator('..');
    for (const repo of ['demo/broken-one', 'demo/broken-two', 'demo/cooling']) await card(repo).getByRole('button', { name: '重试图片', exact: true }).waitFor();
    const bulk = page.locator('#library-descriptions-fill');
    assert.equal(posts.length, 0, 'image errors update eligibility without submitting enrichment');
    assert.match(await bulk.innerText(), /（3）/, 'both distinct failed images and the missing image join the explicit batch, with healthy and cooling games excluded');
    assert.equal(await bulk.isEnabled(), true);
    const failedImageLoads = imageRequests.filter(url => brokenURLs.includes(url)).length;
    await page.locator('#library-search').fill('');
    await bulk.evaluate(button => { button.click(); button.click(); });
    await page.waitForFunction(() => document.getElementById('description-progress-label').textContent.includes('游戏资料提交完成'));
    assert.deepEqual(posts, [{ repo: 'demo/broken-one', refreshPoster: true }, { repo: 'demo/broken-two', refreshPoster: true }, { repo: 'demo/missing' }]);
    assert.equal(imageRequests.filter(url => brokenURLs.includes(url)).length, failedImageLoads, 'batch progress must not reload known-bad old artwork');
    assert.equal(await card('demo/healthy').locator('img').getAttribute('src'), cachedURL('c'));
    assert.equal(await bulk.isDisabled(), true);
    await bulk.evaluate(button => button.click());
    assert.equal(posts.length, 3, 'double clicks and a completed batch never re-search healthy repaired images');

    expireHealthy = true;
    await card('demo/healthy').getByRole('button', { name: '查看 测试游戏 Healthy 的下载', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('.detail-poster')?.dataset.state === 'missing' && !document.querySelector('.detail-poster img'));
    assert.equal(await page.locator('#detail-content .detail-description').innerText(), records['demo/healthy'].descriptionZh);
    assert.equal(await card('demo/healthy').locator('img').count(), 0, 'GET clearing an expired cached poster must not resurrect the old URL');
    assert.equal(posts.length, 3, 'a missing-cache GET never starts a paid replacement search');
    await page.locator('#detail-close').click();
    assert.match(await bulk.innerText(), /（1）/);
    await page.locator('#discover-nav').click(); await page.locator('#discover-submit').click();
    await page.locator('[data-repository="demo/healthy"]').waitFor();
    await page.locator('#descriptions-fill').evaluate(button => { button.click(); button.click(); });
    await page.waitForFunction(() => document.getElementById('description-progress-label').textContent.includes('游戏资料提交完成') && document.querySelector('[data-repository="demo/healthy"] img'));
    assert.deepEqual(posts, [{ repo: 'demo/broken-one', refreshPoster: true }, { repo: 'demo/broken-two', refreshPoster: true }, { repo: 'demo/missing' }, { repo: 'demo/healthy' }]);
    assert.equal(await page.locator('[data-repository="demo/healthy"] img').getAttribute('src'), cachedURL('3'));
    assert.equal(await page.locator('#descriptions-fill').isDisabled(), true);
    assert.deepEqual(errors, []);
    console.log('PASS explicit batch repairs two distinct failed images with refreshPoster:true and missing art with plain repo; healthy/cooling images skipped; duplicate clicks/pending polling do not repeat POST; authoritative ready GET clears expired cache without auto-generation; discovery batch replaces only that missing artwork.');
  } finally { await browser.close(); server.close(); }
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
