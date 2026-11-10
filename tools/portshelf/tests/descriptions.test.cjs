const assert = require('node:assert/strict');
const { test } = require('node:test');
require('../web/zh.js');
const { describe } = globalThis.PortShelfDescriptions;
const { identity, imageURL, mergeRecord, needsDetails } = globalThis.PortShelfDescriptions;

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
