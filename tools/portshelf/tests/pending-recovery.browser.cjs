// Fake metadata and artwork only. Accelerate 3-second poll timers while controlling wall-clock deadlines.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require(process.env.PORTSHELF_PLAYWRIGHT_MODULE || path.resolve(__dirname, '../../../frontend/node_modules/playwright'));
const root = path.resolve(__dirname, '../web');
const token = 'a'.repeat(48), startedAt = Date.now();
const imageURL = digit => 'https://aigcnews.cn/api/media/site/game-posters/' + digit.repeat(64) + '.jpg';
const games = [{ repo: 'demo/first', name: 'FirstGame', stars: 300 }, { repo: 'demo/second', name: 'SecondGame', stars: 200 }];
const record = game => ({ repo: game.repo, status: 'ready', source: 'aigcnews', descriptionZh: '这是一个已核对中文资料的经典游戏。', gameNameZh: game === games[0] ? '第一个游戏' : '第二个游戏', gameNameOriginal: game.name, detailsVersion: 1, posterUrl: imageURL('a'), posterSourceUrl: 'https://example.com/game', posterKind: 'cover', posterStatus: 'ready', posterSearchVersion: 1, checkedAt: new Date(startedAt).toISOString() });
let fixture;
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://local');
  const json = value => { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(value)); };
  if (url.pathname.startsWith('/api/')) {
    assert.equal(req.headers.authorization, 'Bearer ' + token);
    if (url.pathname === '/api/library') return json({ games: fixture.games, descriptions: fixture.saved, snapshots: Object.fromEntries(fixture.games.map(game => [game.repo, { stars: game.stars, releaseCheckedAt: new Date(startedAt).toISOString() }])), arch: 'amd64', version: 'test', hasAigcToken: true });
    if (url.pathname === '/api/status') return json({ running: false });
    if (url.pathname === '/api/descriptions') {
      if (req.method === 'POST') {
        let raw = ''; for await (const chunk of req) raw += chunk;
        const body = JSON.parse(raw); fixture.posts.push(body);
        assert.deepEqual(body, { repo: body.repo, ...(fixture.mode.startsWith('batch') ? {} : { refreshPoster: true }) });
        if (body.repo === games[0].repo) {
          fixture.pending = true;
          // Mirrors Go: persist ready old artwork/text while clearing checkedAt.
          fixture.saved[body.repo] = { ...fixture.saved[body.repo], checkedAt: '' };
          return json({ items: [{ ...fixture.saved[body.repo], status: 'pending' }], pollAfter: 3 });
        }
        fixture.saved[body.repo] = { ...fixture.saved[body.repo], posterUrl: imageURL('c'), posterStatus: 'ready' };
        return json({ items: [fixture.saved[body.repo]], pollAfter: 3 });
      }
      const repos = url.searchParams.get('repos').split(',');
      const items = repos.map(repo => {
        if (repo === games[0].repo && fixture.pending) {
          fixture.reads++;
          if (!fixture.complete) return { ...fixture.saved[repo], status: 'pending' };
          fixture.pending = false;
          fixture.saved[repo] = { ...fixture.saved[repo], status: 'ready', posterUrl: imageURL('b'), posterStatus: 'ready', checkedAt: new Date(startedAt + 270000).toISOString() };
        }
        return fixture.saved[repo];
      });
      return json({ items, pollAfter: 3 });
    }
    res.statusCode = 404; return json({ error: 'unmocked ' + url.pathname });
  }
  const name = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
  if (!['index.html', 'app.js', 'app.css', 'zh.js', 'cloud.js', 'automation.js', 'gamepad.svg'].includes(name)) { res.statusCode = 404; return res.end(); }
  res.setHeader('Content-Type', name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : name.endsWith('.svg') ? 'image/svg+xml' : 'text/html');
  res.end(fs.readFileSync(path.join(root, name)));
});
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function waitFor(predicate, message) {
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) { if (await predicate()) return; await delay(10); }
  assert.fail(message);
}
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  try {
    for (const mode of ['single', 'batch', 'bounded', 'batch-bounded', 'reload', 'cached-failure']) {
      const batchMode = mode.startsWith('batch');
      fixture = { mode, games: batchMode ? games : [games[0]], saved: Object.fromEntries(games.map(game => [game.repo, record(game)])), posts: [], pending: false, complete: false, reads: 0 };
      if (batchMode) for (const item of Object.values(fixture.saved)) { item.posterUrl = ''; item.posterStatus = 'missing'; }
      if (mode === 'cached-failure') {
        Object.assign(fixture.saved[games[0].repo], { posterStatus: 'unavailable', posterRetryAfter: 300, checkedAt: new Date(startedAt - 60000).toISOString() });
        fixture.pending = fixture.complete = true;
      }
      const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
      const errors = []; page.on('pageerror', error => errors.push(error.message));
      await page.addInitScript(now => {
        window.posterTestNow = now; Date.now = () => window.posterTestNow;
        const realTimeout = window.setTimeout.bind(window);
        window.setTimeout = (callback, milliseconds, ...args) => realTimeout(callback, milliseconds === 3000 ? 10 : milliseconds, ...args);
      }, startedAt);
      const jpeg = Buffer.from(await page.evaluate(() => { const canvas = document.createElement('canvas'); canvas.width = 3; canvas.height = 4; return canvas.toDataURL('image/jpeg').split(',')[1]; }), 'base64');
      await page.route('https://**/*', route => {
        assert.match(route.request().url(), /^https:\/\/aigcnews\.cn\/api\/media\/site\/game-posters\/[abc]{64}\.jpg$/);
        return route.fulfill({ contentType: 'image/jpeg', body: jpeg });
      });
      await page.goto(`http://127.0.0.1:${server.address().port}/#${token}`);
      await waitFor(() => page.locator('#game-demo-first').count(), 'fixture library did not load');
      const card = page.locator('#game-demo-first').locator('..');
      if (mode === 'cached-failure') {
        await waitFor(async () => await card.locator('img').getAttribute('src') === imageURL('b'), 'loading a failed search with old artwork did not GET its short-cache result');
        assert.equal(fixture.reads, 1);
        assert.deepEqual(fixture.posts, []);
        assert.equal(await card.locator('.card-description').innerText(), record(games[0]).descriptionZh);
        assert.deepEqual(errors, []); await page.close(); continue;
      }
      const trigger = batchMode ? page.locator('#library-descriptions-fill') : card.getByRole('button', { name: '联网重找海报', exact: true });
      await trigger.evaluate(button => { button.click(); button.click(); });
      await waitFor(() => fixture.posts.length === 1 && fixture.pending, 'initial generation was not accepted once');
      assert.equal(await card.locator('.card-description').innerText(), record(games[0]).descriptionZh);
      if (!batchMode) assert.equal(await card.locator('img').getAttribute('src'), imageURL('a'));

      if (mode === 'reload') {
        const before = fixture.reads;
        await page.reload();
        await waitFor(() => fixture.reads > before, 'reload with complete old artwork and cleared checkedAt did not resume GET');
        assert.equal(fixture.posts.length, 1);
        assert.equal(await card.locator('img').getAttribute('src'), imageURL('a'));
        assert.equal(await card.getByRole('button', { name: '核对生成进度', exact: true }).count(), 1);
      } else {
        await page.evaluate(now => { window.posterTestNow = now; }, startedAt + 270000);
        await waitFor(() => fixture.reads > 25, 'pending GET polling stopped before 270 seconds or retained the old 20-request limit');
        assert.equal(fixture.posts.length, 1, 'waiting must never submit another paid request or advance the batch early');
      }

      if (mode === 'bounded' || mode === 'batch-bounded') {
        await page.evaluate(now => { window.posterTestNow = now; }, startedAt + 301000);
        await waitFor(async () => (await page.locator('#description-notice').innerText()).includes('自动核对已暂歇'), 'polling did not stop after its bounded window');
        const stoppedReads = fixture.reads; await delay(100);
        assert.equal(fixture.reads, stoppedReads, 'expired automatic polling must stop GET requests');
        if (batchMode) await waitFor(async () => (await page.locator('#description-progress-label').innerText()).includes('游戏资料提交已中断'), 'expired batch did not stop before submitting the next game');
        else assert.equal(await card.locator('img').getAttribute('src'), imageURL('a'));
        fixture.complete = true;
        await card.getByRole('button', { name: '核对生成进度', exact: true }).evaluate(button => button.click());
      } else fixture.complete = true;
      await waitFor(async () => await card.locator('img').getAttribute('src') === imageURL('b'), 'completed image was not read and displayed');
      if (mode === 'batch') {
        await waitFor(() => fixture.posts.length === 2, 'batch did not continue after the slow first game completed');
        await waitFor(async () => (await page.locator('#description-progress-label').innerText()).includes('游戏资料提交完成'), 'batch did not complete');
        assert.deepEqual(fixture.posts, [{ repo: games[0].repo }, { repo: games[1].repo }]);
      } else assert.deepEqual(fixture.posts, [{ repo: games[0].repo, ...(batchMode ? {} : { refreshPoster: true }) }]);
      assert.equal(await card.locator('.card-description').innerText(), record(games[0]).descriptionZh);
      assert.deepEqual(errors, []); await page.close();
    }
    console.log('PASS single and batch GET polling remain active after 270 seconds and 25+ reads; both stop after five minutes; progress resumes with GET only; reload retains old art and retrieves new results from a cleared checkedAt marker; cached failed searches refresh by GET even with old artwork; no duplicate POST.');
  } finally { await browser.close(); server.close(); }
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
