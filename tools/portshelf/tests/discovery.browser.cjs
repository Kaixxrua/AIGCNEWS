// Public discovery fixtures only: no real GitHub requests or transfer jobs.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const os = require('node:os');
const { chromium } = require(process.env.PORTSHELF_PLAYWRIGHT_MODULE || path.resolve(__dirname, '../../../frontend/node_modules/playwright'));
const webRoot = path.resolve(__dirname, '../web');
const token = 'f'.repeat(48);
const calls = [], errors = [];
let secondAttempts = 0;
const game = (id, stars = 10) => ({ repo: 'demo/game' + id, name: 'Game ' + id, description: 'An open game with no verified Windows release.', stars });
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://local');
  const json = (value, code = 200) => { res.statusCode = code; res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(value)); };
  if (url.pathname.startsWith('/api/')) {
    assert.equal(req.headers.authorization, 'Bearer ' + token);
    if (req.method !== 'GET') return json({ error: 'No writes expected' }, 405);
    if (url.pathname === '/api/library') return json({ games: [], snapshots: {}, descriptions: {}, arch: 'amd64', version: 'discovery-test', hasToken: false, hasAigcToken: false });
    if (url.pathname === '/api/descriptions') return json({ descriptions: {} });
    if (url.pathname === '/api/status') return json({ running: false, done: 0, total: 0, errors: [] });
    if (url.pathname === '/api/discover') {
      const params = Object.fromEntries(url.searchParams); calls.push(params);
      if (params.minStars === '25') return json({ items: [], page: 1, nextPage: 0, hasMore: false, totalCandidates: 0 });
      assert.equal(params.minStars, '10');
      if (params.page === '1') { assert.equal(params.cursor, undefined); return json({ items: Array.from({ length: 100 }, (_, i) => game(i, 109 - i)), page: 1, nextPage: 2, nextCursor: 'split-cursor', hasMore: true, totalCandidates: 1400 }); }
      if (params.page === '2') {
        assert.equal(params.cursor, 'split-cursor'); secondAttempts++;
        if (secondAttempts === 1) return json({ items: [game(99), game(100)], page: 2, nextPage: 2, nextCursor: 'split-cursor', hasMore: true, evidencePending: true, warning: 'README 暂时限流 <img src=x onerror="window.injected=1">', totalCandidates: 700 });
        return json({ items: [game(100), game(101)], page: 2, nextPage: 11, nextCursor: 'next-query-cursor', hasMore: true, totalCandidates: 700 });
      }
      assert.equal(params.page, '11'); assert.equal(params.cursor, 'next-query-cursor');
      return json({ items: [game(102)], page: 11, nextPage: 0, hasMore: false, totalCandidates: 1 });
    }
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
  const output = fs.mkdtempSync(path.join(os.tmpdir(), 'portshelf-discovery-ui-'));
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/#${token}`);
    await page.locator('#discover-nav').click();
    assert.equal(await page.locator('#discover-min-stars').inputValue(), '10');
    await page.locator('#discover-submit').click();
    await page.waitForFunction(() => document.querySelectorAll('.search-result').length === 100);
    assert.equal(await page.locator('.search-result .systems-info').first().innerText(), '支持系统待核实');
    assert.match(await page.locator('#discovery-page-summary').innerText(), /本分段上游候选/);
    await page.locator('#discover-more').click();
    await page.waitForFunction(() => document.querySelectorAll('.search-result').length === 101);
    assert.match(await page.locator('#discover-error').innerText(), /README 暂时限流/);
    assert.equal(await page.locator('#discover-error img').count(), 0);
    assert.match(await page.locator('#discover-more').innerText(), /重试第 2 页/);
    await page.locator('#discover-more').click();
    await page.waitForFunction(() => document.querySelectorAll('.search-result').length === 102);
    await page.locator('#discover-more').click();
    await page.waitForFunction(() => document.querySelectorAll('.search-result').length === 103);
    assert.equal(await page.locator('#discover-more').isVisible(), false);
    assert.deepEqual(calls.map(call => call.page), ['1', '2', '2', '11']);
    assert.equal(await page.evaluate(() => window.injected), undefined);
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
    await page.screenshot({ path: path.join(output, 'discovery-mobile.png'), fullPage: false });
    await page.locator('#discover-min-stars').fill('25'); await page.locator('#discover-submit').click();
    await page.waitForFunction(() => document.getElementById('discover-count').textContent.includes('0 个游戏项目'));
    assert.deepEqual(calls.at(-1), { page: '1', minStars: '25' });
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ ok: true, confirmedGames: 103, requests: calls.length, output }));
  } finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
})().catch(error => { console.error(error); process.exitCode = 1; });
