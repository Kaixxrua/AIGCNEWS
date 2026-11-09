const assert = require('node:assert/strict');
const { test } = require('node:test');
const { defaultConfig, validateConfig, taskNotice } = require('../web/automation.js');
const { systemsLabel, materialFor } = require('../web/cloud.js');
const windows = { credentialStorageSupported: true, startOnLoginSupported: true };

test('unattended defaults discover from 10 Stars, every six hours, ten games daily, both drives and current architecture', () => {
  const config = defaultConfig('arm64');
  assert.equal(config.minStars, 10); assert.equal(config.maxStars, null);
  assert.equal(config.intervalHours, 6); assert.equal(config.dailyLimit, 10);
  assert.deepEqual(config.providers, ['baidu', 'quark']); assert.equal(config.arch, 'arm64');
  assert.equal(defaultConfig('other').arch, 'amd64');
});

test('Stars zero is a real bound and all numeric limits are checked before changing automation', () => {
  assert.equal(validateConfig({ ...defaultConfig(), minStars: 0, maxStars: 0 }, windows).maxStars, 0);
  const unrestricted = validateConfig({ ...defaultConfig(), minStars: '', maxStars: '' }, windows);
  assert.equal(unrestricted.minStars, 0); assert.equal(unrestricted.maxStars, null);
  for (const patch of [{ minStars: -1 }, { minStars: '1e3' }, { minStars: 10, maxStars: 9 }, { maxStars: 1000000001 }, { intervalHours: 0 }, { intervalHours: 169 }, { intervalHours: 1.5 }, { dailyLimit: 0 }, { dailyLimit: 101 }, { providers: [] }, { providers: ['other'] }, { arch: 'linux' }, { shareDays: 2 }]) assert.throws(() => validateConfig({ ...defaultConfig(), ...patch }, windows));
  assert.equal(validateConfig({ ...defaultConfig(), intervalHours: 168, dailyLimit: 100 }, windows).dailyLimit, 100);
});

test('unsupported platforms cannot request credential persistence or login startup', () => {
  const source = { ...defaultConfig(), enabled: true, rememberCredentials: true, startOnLogin: true };
  const localOnly = validateConfig(source, {});
  assert.equal(localOnly.rememberCredentials, false); assert.equal(localOnly.startOnLogin, false);
  const protectedConfig = validateConfig(source, windows);
  assert.equal(protectedConfig.rememberCredentials, true); assert.equal(protectedConfig.startOnLogin, true);
});

test('Baidu is private with an optional valid code and Quark can be public', () => {
  const baidu = validateConfig({ ...defaultConfig(), privateShare: false, shareCode: 'a1B2' }, windows);
  assert.equal(baidu.privateShare, true); assert.equal(baidu.shareCode, 'a1B2');
  assert.throws(() => validateConfig({ ...defaultConfig(), shareCode: 'bad' }, windows), /4 位/);
  const quark = validateConfig({ ...defaultConfig(), providers: ['quark'], privateShare: false, shareCode: 'ignore' }, windows);
  assert.equal(quark.privateShare, false); assert.equal(quark.shareCode, '');
});

test('only explicit scheduled retries are promised; attention, paused and unscheduled failure stay distinct', () => {
  assert.equal(taskNotice({ automatic: false, status: 'failed' }), null);
  const base = { automatic: true, status: 'failed', attempts: 2 };
  assert.equal(taskNotice(base).pendingRetry, false);
  assert.match(taskNotice(base).text, /尚未安排/);
  const retry = taskNotice({ ...base, nextRetryAt: '2027-01-01T01:00:00Z' });
  assert.equal(retry.pendingRetry, true); assert.match(retry.text, /下次自动重试/); assert.match(retry.attempts, /2 次/);
  const attention = taskNotice({ ...base, needsAttention: true, error: '验证码需要本人处理', nextRetryAt: '2027-01-01T01:00:00Z' });
  assert.equal(attention.pendingRetry, false); assert.match(attention.text, /验证码/);
  assert.equal(taskNotice({ ...base, status: 'paused', nextRetryAt: '2027-01-01T01:00:00Z' }).kind, 'paused');
  assert.equal(taskNotice({ ...base, status: 'done', nextRetryAt: '2027-01-01T01:00:00Z' }).pendingRetry, false);
});

test('system information uses explicit release evidence and is never inferred from project names or descriptions', () => {
  assert.equal(systemsLabel([]), '支持系统待核实'); assert.equal(systemsLabel(undefined), '支持系统待核实');
  assert.equal(systemsLabel(['Windows x64', 'macOS', 'Linux x64', 'Windows x64']), '支持系统：Windows x64、macOS、Linux x64');
  assert.match(materialFor({ name: 'Windows Linux game', description: '支持所有系统', arch: 'amd64' }), /支持系统待核实/);
  const material = materialFor({ name: '游戏', supportedSystems: ['Windows ARM64', 'macOS'] });
  assert.match(material, /支持系统：Windows ARM64、macOS/);
  assert.equal(systemsLabel(['Linux <img onerror=alert(1)>']), '支持系统：Linux <img onerror=alert(1)>');
});
