const assert = require('node:assert/strict');
const { test } = require('node:test');
require('../web/zh.js');
const { describe } = globalThis.PortShelfDescriptions;
const { identity, imageURL, mergeRecord, needsDetails, posterEvidence, needsPoster, canSearchPoster, posterRetrySeconds } = globalThis.PortShelfDescriptions;

test('AIGCNEWS Chinese takes precedence and keeps the exact upstream original', () => {
  const original = 'A Doom 3 source port.';
  assert.deepEqual(describe({ description: original, descriptionZh: '面向现代系统的 Doom 3 源码移植。' }), {
    text: '面向现代系统的 Doom 3 源码移植。', source: 'aigcnews', original,
  });
  assert.equal(describe({ description_zh: '支持现代电脑的游戏移植。' }).source, 'aigcnews');
  assert.equal(describe({ descriptionZh: '《毁灭战士》的经典关卡与第一人称射击。' }).source, 'aigcnews');
});

test('existing Chinese and missing or Japanese descriptions are distinguished', () => {
  assert.equal(describe({ description: '开源重现主题医院，让经典医院经营玩法继续生长。' }).source, 'upstream');
  for (const description of ['日本語説明', 'ゲームを移植する開源项目', 'An unknown game.', '']) {
    assert.equal(describe({ description }).source, 'unknown');
    assert.equal(describe({ description }).original, description);
  }
});

test('malformed values cannot run scripts or replace the original with invented details', () => {
  for (const value of [null, undefined, 1, 'game', {}, { description: {} }, { descriptionZh: [] }]) {
    assert.equal(describe(value).source, 'unknown');
  }
  const original = '<img src=x onerror="throw 1"> English game description';
  assert.equal(describe({ description: original }).original, original);
  assert.equal(describe({ name: 'Doom', repo: 'fake/doom' }).source, 'unknown');
});

test('actual Chinese identity is distinct from the port repository and unconfirmed names stay explicit', () => {
  const game = { name: 'LASRecomp', repo: 'peilika/LASRecomp', description: 'A port of a game.' };
  assert.equal(identity(game).pending, true);
  assert.equal(identity(game).title, 'LASRecomp');
  const named = identity(game, { gameNameZh: '塞尔达传说：织梦岛', gameNameOriginal: "The Legend of Zelda: Link's Awakening" });
  assert.equal(named.title, '塞尔达传说：织梦岛');
  assert.equal(named.pending, false);
  assert.match(named.secondary, /LASRecomp.*peilika\/LASRecomp/);
  assert.equal(identity({ ...game, subtitle: '已知的游戏中文名' }).nameZh, '已知的游戏中文名');
  assert.equal(identity({ ...game, descriptionZh: '包含《甲》和《乙》的游戏。' }).nameZh, '');
  for (const gameNameZh of ['Fake Translation', '日本語ゲーム', '<img src=x onerror=alert(1)>中文', {}, []]) assert.equal(identity(game, { gameNameZh }).pending, true);
});

test('posters only use trusted HTTPS image hosts, with source links checked separately', () => {
  for (const url of ['https://raw.githubusercontent.com/owner/game/main/poster.png', 'https://user-images.githubusercontent.com/1/image.png', 'https://github.com/user-attachments/assets/abcd-1234']) assert.equal(imageURL(url), url);
  assert.equal(imageURL('https://github.com/owner/game/blob/main/README.md#screenshots', true), 'https://github.com/owner/game/blob/main/README.md#screenshots');
  for (const url of ['javascript:alert(1)', 'data:image/svg+xml,<svg/>', 'http://raw.githubusercontent.com/a/b/main/a.jpg', 'https://raw.githubusercontent.com.evil.test/a.jpg', 'https://127.0.0.1/poster', 'https://user@raw.githubusercontent.com/a.jpg', 'https://raw.githubusercontent.com:443/a.jpg', 'https://raw.githubusercontent.com:8443/a.jpg', 'https://raw.githubusercontent.com/a/b/../a.jpg', 'https://raw.githubusercontent.com/a/b/%2f/a.jpg', 'https://raw.githubusercontent.com/a/b/main/a.jpg?token=secret', 'https://github.com/owner/game', 'https://github.com/user-attachments/assets/asset/extra', 'https:\\raw.githubusercontent.com/a.jpg', ' https://raw.githubusercontent.com/a/b/image.jpg', 'https://raw.githubusercontent.com/a/b/ima\nge.jpg']) assert.equal(imageURL(url), null, url);
});

test('old Chinese descriptions are upgraded on request while pending and failed responses preserve useful data', () => {
  const game = { repo: 'demo/game', description: 'English description' };
  const old = { repo: game.repo, status: 'ready', descriptionZh: '这是一款经典的游戏。' };
  assert.equal(needsDetails(game, old), true);
  const pending = mergeRecord(old, { repo: game.repo, status: 'pending' });
  assert.equal(pending.status, 'pending');
  assert.equal(pending.descriptionZh, old.descriptionZh);
  assert.equal(mergeRecord(pending, { status: 'missing' }), pending);
  const failed = mergeRecord(pending, { repo: game.repo, status: 'failed', error: 'temporary failure' });
  assert.equal(failed.descriptionZh, old.descriptionZh);
  assert.equal(failed.error, 'temporary failure');
  const ready = mergeRecord(failed, { ...old, detailsVersion: 1, gameNameZh: '经典游戏' });
  assert.equal(needsDetails(game, ready), false);
  assert.equal(mergeRecord(ready, old).gameNameZh, '经典游戏');
  assert.equal(mergeRecord(ready, old).detailsVersion, 1);
  assert.equal(needsDetails(game, { ...ready, gameNameZh: '', posterUrl: '' }), false, 'verified unknown artwork must not cause automatic generation loops');
  assert.equal(needsDetails(game, { ...ready, detailsVersion: 2 }), true, 'unknown protocol versions must be checked again');
});

test('Wikimedia posters are raster images tied to the exact original game article, not arbitrary Wikipedia images', () => {
  const game = { detailsVersion: 1, gameNameOriginal: 'The Legend of Zelda: Tears of the Kingdom' };
  const url = 'https://upload.wikimedia.org/wikipedia/en/f/fb/The_Legend_of_Zelda_Tears_of_the_Kingdom_cover.jpg';
  const source = 'https://en.wikipedia.org/wiki/The_Legend_of_Zelda:_Tears_of_the_Kingdom';
  assert.equal(imageURL(url), url); assert.equal(imageURL(source, true), source);
  assert.equal(posterEvidence(game, { posterUrl: url, posterSourceUrl: source }).url, url);
  assert.equal(posterEvidence(game, { posterUrl: url, posterSourceUrl: 'https://en.wikipedia.org/wiki/Another_game' }).url, null);
  assert.equal(posterEvidence(game, { posterUrl: url, posterSourceUrl: 'https://github.com/valentderah/totk-pc-recomp' }).url, null);
  assert.equal(posterEvidence(game, { posterUrl: url }).url, null);
  for (const format of ['jpg', 'jpeg', 'png', 'webp']) {
    const thumb = 'https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Game_cover.' + format + '/320px-Game_cover.' + format;
    assert.equal(imageURL(thumb), thumb);
  }
  assert.ok(posterEvidence({ gameNameOriginal: 'Example' }, { posterUrl: url, posterSourceUrl: 'https://en.wikipedia.org/wiki/Example_(video_game)' }).url);
  for (const bad of [url + '?width=100', url + '?', url + '#x', url + '#', url.replace('wikimedia.org/', 'wikimedia.org:443/'), url.replace('en/', 'evil/'), url.replace('.jpg', '.svg'), url.replace('.jpg', '.svg.png'), url.replace('.jpg', '.SVG.jpg'), url.replace('.jpg', '.gif'), url.replace('/f/fb/', '/../../'), url.replace('upload.wikimedia.org', 'evil.test'), url.replace('https:', 'http:')]) assert.equal(imageURL(bad), null, bad);
  for (const bad of [source + '?redirect=no', source + '?', source + '#section', source + '#', source.replace('en.wikipedia.org/', 'en.wikipedia.org:443/'), source.replace('en.wikipedia.org', 'en.wikipedia.org.evil.test'), 'https://en.wikipedia.org/wiki/File:Game_cover.jpg', 'https://en.wikipedia.org/wiki/%3Cscript%3E', 'https://en.wikipedia.org/wiki/Game%2Fcover', 'https://en.wikipedia.org/w/index.php']) assert.equal(imageURL(bad, true), null, bad);
  assert.equal(imageURL(source), null); assert.equal(imageURL(url, true), null);
});

test('verified Wikipedia game titles match equivalent curly quotes without losing meaningful punctuation', () => {
  const url = 'https://upload.wikimedia.org/wikipedia/en/a/ab/Links_Awakening_cover.jpg';
  const source = "https://en.wikipedia.org/wiki/The_Legend_of_Zelda:_Link's_Awakening";
  for (const quote of ['‘', '’']) {
    const game = { gameNameOriginal: `The Legend of Zelda: Link${quote}s Awakening` };
    assert.equal(posterEvidence(game, { posterUrl: url, posterSourceUrl: source }).url, url);
  }
  assert.equal(posterEvidence({ gameNameOriginal: '"Example"' }, { posterUrl: url, posterSourceUrl: 'https://en.wikipedia.org/wiki/%E2%80%9CExample%E2%80%9D' }).url, url);
  assert.equal(posterEvidence({ gameNameOriginal: 'The Legend of Zelda: Links Awakening' }, { posterUrl: url, posterSourceUrl: source }).url, null);
});

test('version-one records with a known game but no image can be retried without regenerating their Chinese text', () => {
  const game = { repo: 'valentderah/totk-pc-recomp', name: 'totk-pc-recomp' };
  const cached = { repo: game.repo, status: 'ready', descriptionZh: '这是《塞尔达传说：王国之泪》的电脑移植项目。', gameNameZh: '塞尔达传说：王国之泪', gameNameOriginal: 'The Legend of Zelda: Tears of the Kingdom', detailsVersion: 1, posterUrl: '' };
  assert.equal(needsDetails(game, cached), true); assert.equal(needsPoster(game, cached), true);
  assert.equal(needsPoster(game, { ...cached, gameNameOriginal: '' }), false);
  assert.equal(needsPoster(game, { ...cached, descriptionZh: '' }), false, 'missing text must not be labelled as a poster-only operation');
  const pending = mergeRecord(cached, { repo: game.repo, status: 'pending', detailsVersion: 1 });
  assert.equal(pending.gameNameZh, cached.gameNameZh); assert.equal(pending.descriptionZh, cached.descriptionZh);
  const failed = mergeRecord(pending, { repo: game.repo, status: 'failed', posterStatus: 'unavailable' });
  assert.equal(failed.gameNameOriginal, cached.gameNameOriginal); assert.equal(failed.descriptionZh, cached.descriptionZh);
  assert.equal(failed.posterStatus, 'unavailable');
});

test('poster retry cooldown uses the original checkedAt, so repeated local cache reads and reloads cannot extend it', () => {
  const checkedAt = '2026-11-10T03:00:00Z';
  const record = { status: 'ready', posterStatus: 'unavailable', posterRetryAfter: 300, checkedAt };
  const now = Date.parse(checkedAt) + 120000;
  assert.equal(posterRetrySeconds(record, now), 180);
  assert.equal(posterRetrySeconds(mergeRecord(record, record), now), 180);
  assert.equal(posterRetrySeconds(record, now + 180001), 0);
  assert.equal(posterRetrySeconds({ ...record, posterRetryAfter: 86400 }, now), 86280);
  for (const patch of [{ checkedAt: '' }, { posterRetryAfter: 0 }, { posterRetryAfter: Infinity }, { posterRetryAfter: -1 }]) assert.equal(posterRetrySeconds({ ...record, ...patch }, now), 0);
});

test('cached web posters use the exact AIGCNEWS content address and a safe public HTTPS source, never arbitrary image hosts', () => {
  const url = 'https://aigcnews.cn/api/media/site/game-posters/' + 'a'.repeat(64) + '.jpg';
  const source = 'https://openrct2.org/screenshots?view=all#classic';
  assert.equal(imageURL(url), url);
  assert.equal(posterEvidence({}, { posterUrl: url, posterSourceUrl: source }).url, url);
  assert.equal(posterEvidence({}, { posterUrl: url, posterSourceUrl: source }).source, source);
  assert.equal(posterEvidence({}, { posterUrl: url }).url, null, 'cached artwork requires the verified source page');
  assert.equal(imageURL(source), null, 'permitting source pages must not permit their images to load directly');
  for (const bad of [url + '?x=1', url + '?', url + '#source', url + '#', url + '\n', url.replace('aigcnews.cn/', 'aigcnews.cn:443/'), url.replace('aigcnews.cn/', 'user@aigcnews.cn/'), url.replace('aigcnews.cn', 'aigcnews.cn.evil.com'), url.replace('https:', 'http:'), url.replace('a'.repeat(64), 'A'.repeat(64)), url.replace('a'.repeat(64), 'a'.repeat(63)), url.replace('a'.repeat(64), '%61' + 'a'.repeat(63)), url.replace('/game-posters/', '/other/../game-posters/'), url.replace('.jpg', '.png'), url.replace('.jpg', '.svg'), url + '/extra']) assert.equal(imageURL(bad), null, bad);
  for (const bad of ['javascript:alert(1)', 'data:text/html,test', 'http://openrct2.org/screenshots', 'https://user:secret@openrct2.org/screenshots', 'https://openrct2.org:443/screenshots', 'https://openrct2.org:8443/screenshots', 'https://localhost/poster', 'https://localhost./poster', 'https://x.localhost/poster', 'https://server.local/poster', 'https://server.internal/poster', 'https://router.home.arpa/poster', 'https://127.0.0.1/poster', 'https://127.1/poster', 'https://2130706433/poster', 'https://10.0.0.1/poster', 'https://172.16.0.1/poster', 'https://192.168.0.1/poster', 'https://169.254.169.254/poster', 'https://[::1]/poster', 'https://%6cocalhost/poster', 'https://openrct2.org/%3Cscript%3E', 'https://openrct2.org/%0d%0a', 'https://openrct2.org/%5cattack', 'https://en.wikipedia.org/wiki/File:Other.jpg', 'https://github.com/demo/game?private=1']) {
    const evidence = posterEvidence({}, { posterUrl: url, posterSourceUrl: bad });
    assert.equal(evidence.url, null, bad); assert.equal(evidence.source, null, bad);
  }
});

test('known version-one game text can explicitly re-search existing artwork without adding complete records to ordinary bulk enrichment', () => {
  const game = { repo: 'OpenRCT2/OpenRCT2', name: 'OpenRCT2' };
  const record = { detailsVersion: 1, descriptionZh: '这是《过山车大亨 2》的开源重现。', gameNameOriginal: 'RollerCoaster Tycoon 2', posterUrl: 'https://raw.githubusercontent.com/OpenRCT2/OpenRCT2/develop/screenshot.png', posterSourceUrl: 'https://github.com/OpenRCT2/OpenRCT2', posterKind: 'screenshot' };
  assert.equal(canSearchPoster(game, record), true);
  assert.equal(needsPoster(game, record), false);
  assert.equal(needsDetails(game, record), false);
  assert.equal(canSearchPoster(game, { ...record, posterUrl: '' }), true);
  for (const patch of [{ gameNameOriginal: '' }, { descriptionZh: '' }, { detailsVersion: 0 }, { detailsVersion: 2 }]) assert.equal(canSearchPoster(game, { ...record, ...patch }), false);
});

test('poster search progress and negative results retain names, text, old artwork and fixed cooldown metadata', () => {
  const previous = { repo: 'OpenRCT2/OpenRCT2', status: 'ready', detailsVersion: 1, gameNameZh: '过山车大亨 2', gameNameOriginal: 'RollerCoaster Tycoon 2', descriptionZh: '这是经典游戏的开源重现。', posterUrl: 'https://raw.githubusercontent.com/demo/art/main/old.png', posterSourceUrl: 'https://github.com/demo/art', posterKind: 'screenshot', posterStatus: 'ready', posterSearchVersion: 1, checkedAt: '2026-11-10T06:00:00Z', posterRetryAfter: 60 };
  const pending = mergeRecord(previous, { repo: previous.repo, status: 'pending' });
  assert.equal(pending.posterSearchVersion, 1); assert.equal(pending.checkedAt, previous.checkedAt); assert.equal(pending.posterRetryAfter, 60);
  for (const result of [{ status: 'failed', posterStatus: 'unavailable' }, { status: 'ready', detailsVersion: 1, posterSearchVersion: 1, posterStatus: 'missing', posterUrl: previous.posterUrl, posterSourceUrl: previous.posterSourceUrl, posterKind: previous.posterKind, checkedAt: '2026-11-10T06:01:00Z', posterRetryAfter: 3600 }]) {
    const updated = mergeRecord(pending, { repo: previous.repo, ...result });
    for (const field of ['gameNameZh', 'gameNameOriginal', 'descriptionZh', 'posterUrl', 'posterSourceUrl', 'posterKind']) assert.equal(updated[field], previous[field], field);
    assert.equal(updated.posterStatus, result.posterStatus);
    assert.equal(updated.posterSearchVersion, 1);
  }
  const missing = mergeRecord(previous, { ...previous, posterStatus: 'missing', posterRetryAfter: 3600 });
  assert.equal(posterRetrySeconds(missing, Date.parse(previous.checkedAt) + 120000), 3480, 'an old image does not eliminate the latest search cooldown');
  assert.equal(posterRetrySeconds(mergeRecord(missing, missing), Date.parse(previous.checkedAt) + 120000), 3480);
  assert.equal(mergeRecord(null, { status: 'ready' }).posterSearchVersion, 0);
  assert.equal(mergeRecord(previous, { ...previous, posterSearchVersion: 2 }).posterSearchVersion, 0);
});

test('authoritative missing-cache records clear stale artwork while sparse pending or failed responses retain it', () => {
  const previous = { repo: 'demo/expired', status: 'ready', detailsVersion: 1, posterSearchVersion: 1, descriptionZh: '这是经典游戏的开源重现。', gameNameZh: '测试游戏', gameNameOriginal: 'Test Game', posterUrl: 'https://aigcnews.cn/api/media/site/game-posters/' + 'e'.repeat(64) + '.jpg', posterSourceUrl: 'https://example.com/game', posterKind: 'cover', posterStatus: 'ready' };
  const missing = { repo: previous.repo, status: 'ready', detailsVersion: 1, posterSearchVersion: 1, descriptionZh: previous.descriptionZh, gameNameZh: previous.gameNameZh, gameNameOriginal: previous.gameNameOriginal, posterStatus: 'missing', posterRetryAfter: 0 };
  for (const patch of [{}, { posterUrl: '', posterSourceUrl: '', posterKind: '' }]) {
    const record = mergeRecord(previous, { ...missing, ...patch });
    for (const field of ['posterUrl', 'posterSourceUrl', 'posterKind']) assert.equal(record[field], '', field);
    for (const field of ['descriptionZh', 'gameNameZh', 'gameNameOriginal']) assert.equal(record[field], previous[field], field);
    assert.equal(posterEvidence({}, record).url, null);
    assert.equal(needsPoster({}, record), true);
  }
  for (const status of ['pending', 'failed']) {
    const sparse = mergeRecord(previous, { repo: previous.repo, status });
    assert.equal(sparse.posterUrl, previous.posterUrl);
    const explicitlyCleared = mergeRecord(previous, { repo: previous.repo, status, posterUrl: '', posterSourceUrl: '', posterKind: '' });
    for (const field of ['posterUrl', 'posterSourceUrl', 'posterKind']) assert.equal(explicitlyCleared[field], '', field);
  }
});
