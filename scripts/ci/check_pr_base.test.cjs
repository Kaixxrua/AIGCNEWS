const test = require('node:test');
const assert = require('node:assert/strict');
const check = require('./check_pr_base.cjs');

for (const status of ['ahead', 'identical', 'behind', 'diverged', 'unknown']) {
  test(`admission: ${status}`, async () => {
    const errors = [];
    const github = { rest: {
      pulls: { get: async () => ({data: {state: 'open', base: {ref: 'main'}, head: {sha: 'head'}}}) },
      git: { getRef: async () => ({data: {object: {sha: 'main'}}}) },
      repos: { compareCommitsWithBasehead: async () => ({data: {status}}) },
    }};
    await check({github, core: {setFailed: e => errors.push(e)}, context: {
      eventName: 'pull_request', repo: {owner: 'owner', repo: 'repo'},
      payload: {pull_request: {number: 1, head: {sha: 'head'}}},
    }});
    assert.equal(errors.length, ['ahead', 'identical'].includes(status) ? 0 : 1);
  });
}

test('main push remains eligible for its existing baseline', async () => {
  await check({ context: {eventName: 'push'} });
});

test('main changing during admission rejects CI', async () => {
  let calls = 0;
  const errors = [];
  await check({github: {rest: {
    pulls: {get: async () => ({data: {state: 'open', base: {ref: 'main'}, head: {sha: 'head'}}})},
    git: {getRef: async () => ({data: {object: {sha: String(calls++)}}})},
    repos: {compareCommitsWithBasehead: async () => ({data: {status: 'ahead'}})},
  }}, core: {setFailed: e => errors.push(e)}, context: {
    eventName: 'pull_request', repo: {}, payload: {pull_request: {number: 1, head: {sha: 'head'}}},
  }});
  assert.equal(errors.length, 1);
});
