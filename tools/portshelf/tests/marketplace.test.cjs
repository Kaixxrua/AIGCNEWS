const assert = require('node:assert/strict');
const { test } = require('node:test');
const { defaultConfig, priceToFen, priceText, validateConfig, listingState, safeItemURL } = require('../web/marketplace.js');

const status = { connected: true, shops: [{ user_name: 'game-shop', is_valid: 1 }] };
const ready = { ...defaultConfig(), enabled: true, shopUserName: 'game-shop', spBizType: 22, categoryId: '5001', province: 330000, city: 330100, district: 330106, priceFen: 29, stock: 2 };

test('first setup is disabled and contains no invented price, stock, shop or credentials', () => {
  const config = defaultConfig();
  assert.equal(config.enabled, false); assert.equal(config.priceFen, 0); assert.equal(config.stock, 0);
  assert.equal(config.shopUserName, ''); assert.equal(config.spBizType, 0); assert.equal(config.categoryId, '');
  assert.deepEqual(validateConfig(config), config);
  assert.equal('appKey' in config, false); assert.equal('appSecret' in config, false);
});

test('money conversion is exact to cents, including decimals that binary floating point cannot multiply exactly', () => {
  for (const [input, expected] of [['', 0], ['0.01', 1], ['0.29', 29], ['1.01', 101], ['12.3', 1230], ['0002.30', 230], ['99999999', 9999999900]]) assert.equal(priceToFen(input), expected);
  for (const input of ['1e2', '1.001', '-1', '+1', '1,000', '1.', 'NaN', 'Infinity', '99999999.01', '9'.repeat(500)]) assert.throws(() => priceToFen(input));
  assert.equal(priceText(29), '0.29'); assert.equal(priceText(101), '1.01'); assert.equal(priceText(0), ''); assert.equal(priceText(1.2), '');
});

test('disabled draft saves are allowed, but enabled publishing requires a valid detected shop and explicit settings', () => {
  assert.equal(validateConfig({ ...defaultConfig(), titlePrefix: '已选前缀' }).titlePrefix, '已选前缀');
  assert.deepEqual(validateConfig(ready, status), ready);
  for (const patch of [{ shopUserName: '' }, { shopUserName: 'another-shop' }, { spBizType: 0 }, { categoryId: '' }, { province: 0 }, { city: 0 }, { district: 0 }, { priceFen: 0 }, { stock: 0 }]) assert.throws(() => validateConfig({ ...ready, ...patch }, status));
  assert.throws(() => validateConfig(ready, { ...status, connected: false }), /凭据/);
  assert.throws(() => validateConfig(ready, { ...status, shops: [{ user_name: 'game-shop', is_valid: 0 }] }), /有效/);
  assert.throws(() => validateConfig(ready, { ...status, shops: [{ user_name: 'game-shop' }] }), /有效/);
});

test('stock, geographic codes and price limits are checked before API publication', () => {
  assert.equal(validateConfig({ ...ready, priceFen: 9999999900, stock: 399960 }, status).stock, 399960);
  for (const patch of [{ priceFen: 9999999901 }, { priceFen: 0.01 }, { stock: 399961 }, { stock: '1e2' }, { stock: -1 }, { province: '浙江' }, { district: 2147483648 }, { titlePrefix: '文'.repeat(41) }]) assert.throws(() => validateConfig({ ...ready, ...patch }, status));
});

test('required dynamic properties, duplicate IDs and incomplete hand-entered attributes block enabled publication', () => {
  const schema = [{ property_id: 'system', property_name: '适用系统', required: 1 }];
  const property = { property_id: 'system', property_name: '适用系统', value_id: 'win', value_name: 'Windows' };
  assert.throws(() => validateConfig(ready, status, schema), /适用系统/);
  assert.deepEqual(validateConfig({ ...ready, properties: [property] }, status, schema).properties, [property]);
  assert.throws(() => validateConfig({ ...ready, properties: [property, property] }, status, schema), /重复/);
  assert.throws(() => validateConfig({ ...ready, properties: [{ ...property, value_name: '' }] }, status, schema), /都需要/);
  assert.deepEqual(validateConfig({ ...defaultConfig(), properties: [{}] }).properties, []);
});

test('submission acknowledgements and unknown creation results are never displayed as confirmed publication', () => {
  for (const value of ['pending', 'waiting_materials', 'queued', 'creating', 'created', 'create_unknown', 'publishing', 'confirming', 'attention', 'failed', 'paused', 'done', 'success', 'future']) assert.equal(listingState({ status: value }).published, false);
  assert.equal(listingState({ status: 'published' }).published, true);
  assert.equal(listingState({ status: 'create_unknown' }).reconcile, true);
  assert.equal(listingState({ status: 'create_unknown' }).retry, true);
  assert.equal(listingState({ status: 'creating' }).retry, false);
  assert.equal(listingState({ status: 'published' }).retry, false);
  assert.equal(listingState({ status: 'unexpected' }).label, '状态待核实');
});

test('marketplace item links reject script, credentials and lookalike hosts', () => {
  assert.equal(safeItemURL('https://www.goofish.com/item?id=123'), 'https://www.goofish.com/item?id=123');
  assert.equal(safeItemURL('https://2.taobao.com/item?id=123'), 'https://2.taobao.com/item?id=123');
  for (const value of ['javascript:alert(1)', 'http://www.goofish.com/item', 'https://www.goofish.com.evil.test/item', 'https://user:secret@www.goofish.com/item', 'https://www.goofish.com:8080/item', 'https://example.test/item', '/item']) assert.equal(safeItemURL(value), '');
});
