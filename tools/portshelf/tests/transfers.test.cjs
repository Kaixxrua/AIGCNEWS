const assert = require('node:assert/strict');
const { test } = require('node:test');
const { uniqueRepos, transferBatches, shareURL, authorizationURL, progressOf, materialFor, hasSourceBundle, credentialStorageState } = require('../web/cloud.js');

const options = { providers: [], arch: 'amd64', shareDays: 0, shareCode: '', privateShare: true, enrich: true };

test('credential status distinguishes encrypted receipts, memory-only, first save and pending restore without treating a failed write as saved', () => {
  const baseline = { supported: true, remember: true, saved: false, pending: [] };
  assert.equal(credentialStorageState(undefined).kind, 'unknown');
  assert.equal(credentialStorageState({ supported: 'true', remember: true, saved: true }).kind, 'unknown');
  assert.equal(credentialStorageState(baseline).kind, 'waiting');
  assert.match(credentialStorageState(baseline).text, /等待首次保存.*无需开启无人值守/);
  assert.equal(credentialStorageState({ ...baseline, saved: true }).kind, 'saved');
  assert.match(credentialStorageState({ ...baseline, saved: true }).text, /加密保存.*暂停也不清除/);
  assert.match(credentialStorageState({ ...baseline, saved: true, remember: false }).text, /已关闭.*仅在本次运行/);
  assert.match(credentialStorageState({ ...baseline, supported: false }).text, /当前平台不支持.*本次运行/);
  const restoring = credentialStorageState({ ...baseline, saved: true, pending: ['quark', 'quark', 'untrusted'] });
  assert.deepEqual(restoring.pending, ['quark']); assert.equal(restoring.kind, 'restoring');
  assert.match(restoring.text, /已保存授权正在恢复.*无需重复/);
  const failed = credentialStorageState({ ...baseline, saved: true, pending: ['baidu'], error: 'write or restore failed <img src=x>' });
  assert.equal(failed.kind, 'error'); assert.deepEqual(failed.pending, ['baidu']);
  assert.match(failed.text, /保存或恢复出错/); assert.doesNotMatch(failed.text, /已在本机加密保存/);
});

test('selection deduplicates repositories and batches at the server limit without dropping games', () => {
  const repos = Array.from({ length: 205 }, (_, index) => `games/game-${index}`);
  const batches = transferBatches([...repos, 'GAMES/Game-0', 'https://github.com/not/a-repo', null], options);
  assert.deepEqual(batches.map(batch => batch.repos.length), [100, 100, 5]);
  assert.deepEqual(batches.flatMap(batch => batch.repos), repos);
  assert.deepEqual(uniqueRepos(['owner/repo', 'OWNER/REPO', 'invalid', 'a/b/c', '<script>/repo']), ['owner/repo']);
  assert.equal(batches[0].shareDays, 0);
  assert.deepEqual(batches[0].providers, []);
});

test('Baidu always uses a private share, while Quark can use public shares', () => {
  const [baidu] = transferBatches(['a/game'], { ...options, providers: ['baidu', 'quark', 'baidu'], privateShare: false, shareCode: 'a1B2' });
  assert.equal(baidu.privateShare, true);
  assert.equal(baidu.shareCode, 'a1B2');
  assert.deepEqual(baidu.providers, ['baidu', 'quark']);
  const [quark] = transferBatches(['a/game'], { ...options, providers: ['quark'], privateShare: false, shareCode: 'ignored' });
  assert.equal(quark.privateShare, false);
  assert.equal(quark.shareCode, '');
  assert.equal(transferBatches(['a/game'], { ...options, shareCode: 'ignored' })[0].shareCode, '');
  assert.throws(() => transferBatches(['a/game'], { ...options, providers: ['baidu'], shareCode: 'bad' }), /4 位/);
});

test('invalid request choices are rejected before any remote queue change', () => {
  for (const patch of [{ arch: 'linux' }, { shareDays: 2 }, { providers: ['evil'] }]) {
    assert.throws(() => transferBatches(['owner/repo'], { ...options, ...patch }));
  }
  assert.throws(() => transferBatches([], options), /至少一款/);
  for (const shareDays of [0, 1, 7, 30]) assert.equal(transferBatches(['a/b'], { ...options, shareDays })[0].shareDays, shareDays);
});

test('share links are restricted to each provider and official authorization is restricted to its exact endpoint', () => {
  assert.equal(shareURL('https://pan.baidu.com/s/abcd?pwd=a1B2', 'baidu'), 'https://pan.baidu.com/s/abcd?pwd=a1B2');
  assert.equal(shareURL('https://pan.quark.cn/s/abcd', 'quark'), 'https://pan.quark.cn/s/abcd');
  for (const value of ['javascript:alert(1)', 'https://pan.baidu.com.evil.test/s/id', 'https://user@pan.baidu.com/s/id', 'http://pan.baidu.com/s/id', 'https://pan.baidu.com:8443/s/id', 'https://pan.baidu.com:443/s/id', 'https://pan.baidu.com/disk/main', 'https://pan.quark.cn/s/id', 'https://yun.baidu.com/s/id']) assert.equal(shareURL(value, 'baidu'), null);
  for (const [provider, host] of [['baidu', 'pan.baidu.com'], ['quark', 'pan.quark.cn']]) {
    for (const suffix of ['/s/id#fragment', '/s/id#', '/s/id/', '/s/id/extra', '/s/id/../other', '/s/%69d', '/s/id%2Fextra', '/s/id%2fextra', '/s/id%5Cextra', '/s/id%252Fextra', '/s/id%00', '/s/id%0a', '/s/id\\extra', '/s/', '/s/../id']) {
      assert.equal(shareURL('https://' + host + suffix, provider), null, suffix);
    }
    assert.equal(shareURL('https://' + host + '/s/a_B-12', provider), 'https://' + host + '/s/a_B-12');
  }
  const url = 'https://pan.quark.cn/open/v1/oauth/agent?device_id=id&device_name=PortShelf&agent_id=agent&page_code=code';
  assert.equal(authorizationURL(url), url);
  assert.equal(authorizationURL(url + '#/agent-oauth'), url + '#/agent-oauth');
  assert.equal(authorizationURL('https://pan.quark.cn/open/v1/oauth/agent?page_code=code#/agent-oauth'), 'https://pan.quark.cn/open/v1/oauth/agent?page_code=code#/agent-oauth');
  for (const value of ['https://pan.quark.cn/other', 'https://evil.test/open/v1/oauth/agent', url + '&redirect=https://evil.test', url + '#fragment', url + '#/agent-oauth/other', url + '#%2Fagent-oauth', url + '#/agent%2doauth', 'javascript:alert(1)', url.replace('&page_code=code', ''), url.replace('page_code=code', 'page_code='), url + '&page_code=again', url + '&device_id=again', url + '&%70age_code=again', url.replace('/open/', '/%6fpen/'), url.replace('pan.quark.cn/', 'pan.quark.cn:443/')]) assert.equal(authorizationURL(value), null, value);
});

test('progress stays bounded and unknown totals stay indeterminate', () => {
  assert.deepEqual(progressOf({ completedBytes: 40, totalBytes: 100 }), { completed: 40, total: 100, percent: 40 });
  assert.equal(progressOf({ completedBytes: 200, totalBytes: 100 }).percent, 100);
  assert.deepEqual(progressOf({ completedBytes: -1, totalBytes: Infinity }), { completed: 0, total: 0, percent: null });
  assert.equal(progressOf({ completedBytes: 1, totalBytes: 0 }).percent, null);
});

test('share materials retain Chinese instructions and successful partial results without unsafe links or local secrets', () => {
  const materials = materialFor({ name: '经典游戏', repo: 'owner/game', description: '中文游戏简介', guide: '启动前配置游戏数据。', dataNote: '需自备原作素材。', downloadPath: 'C:\\private\\game.zip', sha256: 'abc123', outputs: { baidu: { share: { url: 'https://pan.baidu.com/s/result', code: 'a1B2' } }, quark: { error: 'retry later', share: { url: 'javascript:alert(1)', code: 'secret' } } } });
  assert.match(materials, /中文游戏简介/);
  assert.match(materials, /需自备原作素材/);
  assert.match(materials, /配置游戏数据/);
  assert.match(materials, /https:\/\/pan.baidu.com\/s\/result/);
  assert.match(materials, /提取码：a1B2/);
  assert.match(materials, /SHA-256：abc123/);
  assert.doesNotMatch(materials, /javascript|secret|private/);
});

test('cleaned downloads retain share materials without advertising a missing local file', () => {
  const materials = materialFor({ name: '游戏', repo: 'demo/game', localDeletedAt: '2026-11-10T00:00:00Z', downloadPath: 'removed.zip', outputs: { baidu: { share: { url: 'https://pan.baidu.com/s/kept', code: '1234' } }, quark: { share: { url: 'https://pan.quark.cn/s/kept', code: '5678' } } } });
  assert.match(materials, /双盘完成后已清理/);
  assert.match(materials, /https:\/\/pan.baidu.com\/s\/kept/);
  assert.match(materials, /https:\/\/pan.quark.cn\/s\/kept/);
  assert.doesNotMatch(materials, /removed.zip/);
});

test('source bundles identify the real Chinese game, source commit and separate digests without relabelling old shares', () => {
  const job = { repo: 'demo/game', name: 'CommunityPort', gameNameZh: '经典冒险', gameNameOriginal: 'Classic Adventure', bundleVersion: 1, bundlePath: 'C:\\private\\game-with-source.zip', bundleSha256: 'b'.repeat(64), sourceSha256: 'c'.repeat(64), sourceCommit: 'd'.repeat(40), sourceUrl: 'https://github.com/demo/game/archive/' + 'd'.repeat(40) + '.zip', sha256: 'a'.repeat(64), outputs: { baidu: { payloadSha256: 'b'.repeat(64), share: { url: 'https://pan.baidu.com/s/source', code: '1234' } }, quark: { payloadSha256: 'a'.repeat(64), share: { url: 'https://pan.quark.cn/s/old' } } }, legacyOutputs: { baidu: { share: { url: 'https://pan.baidu.com/s/legacy', code: '5678' } } } };
  assert.equal(hasSourceBundle(job), true);
  const text = materialFor(job);
  assert.match(text, /^经典冒险\n/);
  assert.match(text, /项目名称：CommunityPort/);
  assert.match(text, /游戏原名：Classic Adventure/);
  assert.match(text, /百度网盘（含对应版本源码）：https:\/\/pan.baidu.com\/s\/source/);
  assert.match(text, /夸克网盘（未核实为源码分享包）/);
  assert.match(text, /历史单文件分享.*不含源码.*legacy/);
  assert.match(text, /原发布附件 SHA-256：a{64}/);
  assert.match(text, /源码 Commit：d{40}/);
  assert.match(text, /源码 SHA-256：c{64}/);
  assert.match(text, /分享包 SHA-256：b{64}/);
  assert.match(text, /分享包：game-with-source.zip/);
  assert.doesNotMatch(text, /C:|private/);
  assert.equal(hasSourceBundle({ ...job, bundleVersion: 0 }), false);
  assert.equal(hasSourceBundle({ ...job, bundleVersion: 2 }), false);
  assert.equal(hasSourceBundle({ ...job, sourceCommit: 'd'.repeat(41) }), false);
  assert.doesNotMatch(materialFor({ ...job, bundleVersion: undefined }), /含对应版本源码|源码 Commit/);
  assert.doesNotMatch(materialFor({ ...job, sourceUrl: 'javascript:alert(1)' }), /javascript/);
});
