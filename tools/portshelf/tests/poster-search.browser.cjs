// Protocol fixtures model OpenRCT2's failed old screenshot; mock artwork is not a live poster verification.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const os = require('node:os');
const { chromium } = require(process.env.PORTSHELF_PLAYWRIGHT_MODULE || path.resolve(__dirname, '../../../frontend/node_modules/playwright'));
const root = path.resolve(__dirname, '../web');
const token = 'd'.repeat(48);
const game = { repo: 'OpenRCT2/OpenRCT2', name: 'OpenRCT2', stars: 16551, description: 'An open-source re-implementation of RollerCoaster Tycoon 2.' };
const brokenURL = 'https://raw.githubusercontent.com/OpenRCT2/OpenRCT2/develop/old-screenshot.png';
const cachedURL = 'https://aigcnews.cn/api/media/site/game-posters/' + 'b'.repeat(64) + '.jpg';
const sourceURL = 'https://openrct2.org/screenshots';
const chineseDescription = '这是《过山车大亨 2》的开源重现，可以在现代系统上经营游乐园。';
const baseTime = Date.now();
let fixtureTime = baseTime;
let mode = 'pending';
let finishSearch = false;
let record = { repo: game.repo, status: 'ready', detailsVersion: 1, gameNameZh: '过山车大亨 2', gameNameOriginal: 'RollerCoaster Tycoon 2', descriptionZh: chineseDescription, posterUrl: brokenURL, posterSourceUrl: 'https://github.com/OpenRCT2/OpenRCT2', posterKind: 'screenshot', posterStatus: 'ready', posterRetryAfter: 86400, checkedAt: new Date(baseTime).toISOString() };
const posts = [], reads = [], imageRequests = [];

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://local');
  const json = (value, status = 200) => { res.statusCode = status; res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(value)); };
  if (url.pathname.startsWith('/api/')) {
    assert.equal(req.headers.authorization, 'Bearer ' + token);
    let body; if (req.method === 'POST') { let raw = ''; for await (const chunk of req) raw += chunk; body = JSON.parse(raw || '{}'); }
    if (url.pathname === '/api/library') return json({ games: [game], descriptions: { [game.repo.toLowerCase()]: record }, snapshots: { [game.repo.toLowerCase()]: { stars: game.stars, releaseCheckedAt: new Date(baseTime).toISOString() } }, arch: 'amd64', version: 'test', hasAigcToken: true });
    if (url.pathname === '/api/status') return json({ running: false });
    if (url.pathname === '/api/discover') return json({ items: [game], page: 1, nextPage: 0, hasMore: false, totalCandidates: 1 });
    if (url.pathname === '/api/descriptions') {
      if (req.method === 'POST') {
        assert.deepEqual(body, { repo: game.repo, refreshPoster: true }); posts.push(body);
        if (mode === 'httpfail') return json({ error: '联网搜索服务暂时不可用 <script>window.injected=1</script>' }, 503);
        if (mode === 'pending') {
          record = { ...record, status: 'pending' };
          return json({ items: [{ repo: game.repo, status: 'pending', detailsVersion: 1 }], pollAfter: 3 });
        }
        const update = { repo: game.repo, status: 'ready', detailsVersion: 1, posterSearchVersion: 1, posterStatus: mode, checkedAt: new Date(fixtureTime).toISOString(), posterRetryAfter: mode === 'missing' ? 3600 : 300 };
        record = { ...record, ...update };
        return json({ items: [record] }); // Search failure explicitly retains any still-available previous artwork.
      }
      reads.push(url.searchParams.get('repos'));
      if (finishSearch && record.status === 'pending') record = { ...record, status: 'ready', posterUrl: cachedURL, posterSourceUrl: sourceURL, posterKind: 'cover', posterStatus: 'ready', posterSearchVersion: 1, posterRetryAfter: 60, checkedAt: new Date(fixtureTime).toISOString() };
      return json({ items: [record], pollAfter: 3 });
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
  const outputDir = fs.mkdtempSync(path.join(os.tmpdir(), 'portshelf-poster-search-ui-'));
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(now => {
      window.posterFixtureClock = now;
      try { window.posterFixtureClock = Number(sessionStorage.getItem('poster-fixture-clock')) || now; } catch (_) { /* Initial blank page. */ }
      Date.now = () => window.posterFixtureClock;
    }, baseTime);
    const jpeg = Buffer.from(await page.evaluate(() => {
      const canvas = document.createElement('canvas'); canvas.width = 240; canvas.height = 320;
      const context = canvas.getContext('2d'); context.fillStyle = '#d9e5ef'; context.fillRect(0, 0, 240, 320);
      context.fillStyle = '#39516e'; context.font = '18px sans-serif'; context.textAlign = 'center'; context.fillText('Mock poster', 120, 150); context.font = '12px sans-serif'; context.fillText('Protocol fixture only', 120, 180);
      return canvas.toDataURL('image/jpeg').split(',')[1];
    }), 'base64');
    await page.route('https://**/*', async route => {
      const url = route.request().url(); assert.ok([brokenURL, cachedURL].includes(url), url);
      assert.equal(route.request().headers().authorization, undefined); assert.equal(route.request().headers().referer, undefined);
      imageRequests.push(url);
      if (url === brokenURL) return route.fulfill({ status: 404, body: 'old screenshot removed' });
      return route.fulfill({ status: 200, contentType: 'image/jpeg', body: jpeg });
    });
    await page.goto(`http://127.0.0.1:${server.address().port}/#${token}`);
    await page.waitForFunction(() => document.getElementById('game-count').textContent === '1');
    const card = page.locator('#game-OpenRCT2-OpenRCT2').locator('..');
    await card.getByRole('button', { name: '重试图片', exact: true }).waitFor();
    assert.equal(await card.getByRole('button', { name: '联网重找海报', exact: true }).isEnabled(), true, 'legacy poster cooldown must not block the first web search');
    assert.equal(posts.length, 0, 'loading a failed screenshot must never submit a search');
    const firstImageAttempts = imageRequests.length;
    await page.locator('#library-search').fill('OpenRCT2'); await page.locator('#library-search').fill('');
    assert.equal(imageRequests.length, firstImageAttempts, 'failed artwork rerenders do not repeatedly reload or search');
    assert.equal(posts.length, 0);
    assert.match(await card.locator('.description-control').innerText(), /使用现有富化额度/);
    await card.getByRole('button', { name: '联网重找海报', exact: true }).evaluate(button => { button.click(); button.click(); });
    await card.getByRole('button', { name: '核对生成进度', exact: true }).waitFor();
    assert.equal(posts.length, 1, 'a double click produces only one explicit search');
    assert.match(await card.locator('.description-control').innerText(), /正在联网查找海报/);
    assert.equal(await card.locator('.card-title').innerText(), '过山车大亨 2');
    assert.equal(await card.locator('.card-description').innerText(), chineseDescription);
    assert.equal(await card.locator('.poster-caption a').getAttribute('href'), 'https://github.com/OpenRCT2/OpenRCT2');

    finishSearch = true;
    await card.getByRole('button', { name: '核对生成进度', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('#game-OpenRCT2-OpenRCT2').closest('article').querySelector('img')?.naturalWidth > 0);
    assert.equal(await card.locator('img').getAttribute('src'), cachedURL);
    assert.equal(await card.locator('.poster-caption a').getAttribute('href'), sourceURL);
    assert.match(await card.locator('.poster-caption').innerText(), /游戏海报/);
    assert.equal(await card.getByRole('button', { name: '稍后联网重找', exact: true }).isDisabled(), true);
    assert.match(await card.locator('.description-control').innerText(), /约 60 秒后/);
    assert.equal(await page.locator('#library-descriptions-fill').isDisabled(), true, 'ordinary batch enrichment must skip the complete game');

    const setClock = async seconds => {
      fixtureTime = baseTime + seconds * 1000;
      await page.evaluate(now => { window.posterFixtureClock = now; sessionStorage.setItem('poster-fixture-clock', String(now)); document.getElementById('library-search').dispatchEvent(new Event('input')); }, fixtureTime);
    };
    await setClock(30);
    assert.match(await card.locator('.description-control').innerText(), /约 30 秒后/);
    await card.getByRole('button', { name: '查看 过山车大亨 2 的下载', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('#detail-content .description-control')?.textContent.includes('约 30 秒后'));
    assert.equal(await page.locator('.detail-poster img').getAttribute('src'), cachedURL);
    await page.locator('#detail-close').click();
    assert.equal(posts.length, 1, 'cached progress reads do not submit searches or restart cooldown');

    await setClock(61); mode = 'missing';
    await card.getByRole('button', { name: '联网重找海报', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('#game-OpenRCT2-OpenRCT2').closest('article').textContent.includes('本次联网搜索未找到匹配海报'));
    assert.equal(posts.length, 2);
    assert.equal(await card.locator('img').getAttribute('src'), cachedURL, 'negative search results retain the usable old image');
    assert.equal(await card.locator('.card-description').innerText(), chineseDescription);
    assert.match(await page.locator('#toast').innerText(), /未找到匹配海报/);
    assert.doesNotMatch(await page.locator('#toast').innerText(), /已更新/);
    assert.equal(await card.getByRole('button', { name: '稍后联网重找', exact: true }).isDisabled(), true);
    await setClock(181);
    assert.match(await card.locator('.description-control').innerText(), /约 58 分钟后/);
    await page.reload(); await page.waitForFunction(() => document.getElementById('game-count').textContent === '1');
    assert.match(await card.locator('.description-control').innerText(), /约 58 分钟后/, 'reload must retain the original checkedAt deadline');
    assert.equal(posts.length, 2);

    await setClock(3662); mode = 'unavailable';
    await card.getByRole('button', { name: '联网重找海报', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('#game-OpenRCT2-OpenRCT2').closest('article').textContent.includes('联网查图暂未完成'));
    assert.equal(posts.length, 3);
    assert.equal(await card.locator('img').getAttribute('src'), cachedURL);
    assert.equal(await card.locator('.card-title').innerText(), '过山车大亨 2');
    assert.match(await page.locator('#toast').innerText(), /联网查图暂未完成/);
    assert.doesNotMatch(await page.locator('#toast').innerText(), /已更新/);
    assert.equal(await card.getByRole('button', { name: '稍后联网重找', exact: true }).isDisabled(), true);

    await setClock(3963); mode = 'httpfail';
    await card.getByRole('button', { name: '联网重找海报', exact: true }).click();
    await page.waitForFunction(() => document.getElementById('toast').textContent.includes('联网搜索服务暂时不可用'));
    assert.equal(posts.length, 4);
    assert.equal(await card.locator('.card-description').innerText(), chineseDescription);
    assert.equal(await card.locator('img').getAttribute('src'), cachedURL);
    assert.match(await page.locator('#library-descriptions-fill').innerText(), /部分海报需联网重找/, 'the old image must not make failed search results appear complete');
    assert.equal(await page.evaluate(() => window.injected), undefined);
    await page.locator('#discover-nav').click(); await page.locator('#discover-submit').click();
    const discovered = page.locator('[data-repository="openrct2/openrct2"]');
    await discovered.waitFor();
    assert.equal(await discovered.getByRole('button', { name: '联网重找海报', exact: true }).isEnabled(), true);
    assert.equal(posts.length, 4, 'browsing, cooldown expiry and cached reads never submit another search');
    await page.locator('#library-nav').click(); await page.evaluate(() => { document.getElementById('toast').hidden = true; window.scrollTo(0, 0); });
    await page.screenshot({ path: path.join(outputDir, 'desktop-fixture.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: path.join(outputDir, 'mobile-fixture.png'), fullPage: true });
    assert.deepEqual(errors, []);
    assert.ok(reads.length > 0);
    console.log('PASS OpenRCT2 failed screenshot -> explicit refreshPoster -> trusted cached poster; no onerror/duplicate/batch POST; source and quota text; retained pending/negative/HTTP-failure content; old-version bypass and fixed success/failure cooldowns across reload; details/discovery/390px/XSS.');
    console.log('Fixture screenshots: ' + outputDir);
  } finally { await browser.close(); server.close(); }
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
