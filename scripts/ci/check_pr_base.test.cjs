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

function fixture() {
  const errors = [], waits = [];
  return {errors, waits, args: {
    github: {rest: {
      pulls: {get: async () => ({data: {state: 'open', base: {ref: 'main'}, head: {sha: 'head'}}})},
      git: {getRef: async () => ({data: {object: {sha: 'main'}}})},
      repos: {compareCommitsWithBasehead: async () => ({data: {status: 'ahead'}})},
    }},
    core: {setFailed: e => errors.push(e)}, sleep: async ms => waits.push(ms),
    context: {eventName: 'pull_request', repo: {owner: 'owner', repo: 'repo'},
      payload: {pull_request: {number: 1, head: {sha: 'head'}}}},
  }};
}

for (const error of [500, 502, 503, 504].map(status => Object.assign(new Error('fetch failed'), {status}))
  .concat([Object.assign(new Error('reset'), {code: 'ECONNRESET'}),
    new TypeError('fetch failed'), new Error('network', {cause: {code: 'UND_ERR_CONNECT_TIMEOUT'}})])) {
  test(`transient read recovers: ${error.status ?? error.code ?? error.message}`, async () => {
    const {args, waits, errors} = fixture();
    let calls = 0;
    args.github.rest.git.getRef = async () => {
      if (++calls <= 3) throw error;
      return {data: {object: {sha: 'main'}}};
    };
    await check(args);
    assert.equal(calls, 5); // fourth attempt succeeds; final live main check still runs
    assert.deepEqual(waits, [1000, 2000, 4000]);
    assert.deepEqual(errors, []);
  });
}

for (const status of [400, 401, 403, 404, 409, 422, 429]) {
  test(`non-transient status ${status} is not retried`, async () => {
    const {args, waits} = fixture();
    const error = Object.assign(new Error('fetch failed'), {status});
    let calls = 0;
    args.github.rest.pulls.get = async () => { calls++; throw error; };
    await assert.rejects(check(args), e => e === error);
    assert.equal(calls, 1);
    assert.deepEqual(waits, []);
  });
}

test('exhausted comparison read fails closed after four attempts', async () => {
  const {args, waits} = fixture();
  let calls = 0;
  const error = Object.assign(new Error('unavailable'), {status: 503});
  args.github.rest.repos.compareCommitsWithBasehead = async () => { calls++; throw error; };
  await assert.rejects(check(args), e => e === error);
  assert.equal(calls, 4);
  assert.deepEqual(waits, [1000, 2000, 4000]);
});

test('transient recovery does not suppress changed-main rejection', async () => {
  const {args, errors} = fixture();
  let calls = 0;
  args.github.rest.git.getRef = async () => {
    if (++calls === 2) throw Object.assign(new Error('fetch failed'), {status: 500});
    return {data: {object: {sha: calls === 1 ? 'old' : 'new'}}};
  };
  await check(args);
  assert.equal(errors.length, 1);
  assert.match(errors[0], /Main advanced/);
});

test('recovered PR read still rejects obsolete head', async () => {
  const {args, errors} = fixture();
  let calls = 0;
  args.github.rest.pulls.get = async () => {
    if (++calls === 1) throw Object.assign(new Error('fetch failed'), {status: 500});
    return {data: {state: 'open', base: {ref: 'main'}, head: {sha: 'new'}}};
  };
  await check(args);
  assert.equal(errors.length, 1);
  assert.match(errors[0], /PR changed/);
});
