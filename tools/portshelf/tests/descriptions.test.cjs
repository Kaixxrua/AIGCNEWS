const assert = require('node:assert/strict');
const { test } = require('node:test');
require('../web/zh.js');
const { describe } = globalThis.PortShelfDescriptions;

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
