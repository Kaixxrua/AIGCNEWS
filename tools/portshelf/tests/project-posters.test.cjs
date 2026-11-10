const assert = require('node:assert/strict');
const { test } = require('node:test');
require('../web/zh.js');
const { identity, canSearchPoster, needsPoster, needsDetails, posterEvidence, mergeRecord } = globalThis.PortShelfDescriptions;

const project = { repo: 'OpenRA/OpenRA', name: 'OpenRA', description: 'An engine for classic real-time strategy games.' };
const details = { repo: project.repo, status: 'ready', source: 'aigcnews', detailsVersion: 1, descriptionZh: 'OpenRA 是一个支持多款经典即时战略游戏的开源引擎。', gameNameZh: '', gameNameOriginal: '', posterStatus: 'missing', posterSearchVersion: 1, posterRetryAfter: 0 };

test('a verified multi-game project can find artwork without pretending to have a unique original game', () => {
  assert.equal(canSearchPoster(project, details), true);
  assert.equal(needsPoster(project, details), true);
  assert.equal(needsDetails(project, details), true);
  assert.equal(identity(project, details).title, 'OpenRA');
  assert.equal(identity(project, details).nameZh, '');
  assert.equal(identity(project, details).original, '');
  assert.equal(identity(project, details).pending, true);
  assert.equal(canSearchPoster({}, details), true, 'cache-only cooldown refresh can identify the project from its repository');
  for (const repo of ['', '../..', 'owner/.', 'owner/..', '_owner/game', 'owner/game/extra', 'https://github.com/OpenRA/OpenRA']) assert.equal(canSearchPoster({ ...project, repo }, { ...details, repo }), false, repo);
  for (const patch of [{ detailsVersion: 0 }, { detailsVersion: 2 }, { descriptionZh: '' }, { descriptionZh: 'An untranslated description.' }]) assert.equal(canSearchPoster(project, { ...details, ...patch }), false);
});

test('project artwork remains tied to a trusted image and source while names and text survive pending or failure', () => {
  const image = 'https://aigcnews.cn/api/media/site/game-posters/' + 'd'.repeat(64) + '.jpg';
  const complete = { ...details, posterUrl: image, posterSourceUrl: 'https://www.openra.net/media/', posterKind: 'screenshot', posterStatus: 'ready' };
  assert.equal(posterEvidence(project, complete).url, image);
  assert.equal(needsDetails(project, complete), false, 'a complete project does not remain in every bulk batch');
  assert.equal(canSearchPoster(project, complete), true, 'a deliberate later re-search is still available');
  for (const status of ['pending', 'failed']) {
    const kept = mergeRecord(complete, { repo: project.repo, status });
    for (const field of ['descriptionZh', 'gameNameZh', 'gameNameOriginal', 'posterUrl', 'posterSourceUrl']) assert.equal(kept[field], complete[field], field);
  }
  assert.equal(posterEvidence(project, { ...complete, posterSourceUrl: 'https://127.0.0.1/private' }).url, null);
  assert.equal(posterEvidence(project, { ...complete, posterUrl: 'https://upload.wikimedia.org/wikipedia/en/f/fb/The_Legend_of_Zelda_Tears_of_the_Kingdom_cover.jpg', posterSourceUrl: 'https://en.wikipedia.org/wiki/The_Legend_of_Zelda:_Tears_of_the_Kingdom' }).url, null, 'project fallback cannot weaken the exact-original-game check for direct Wikipedia images');
});
