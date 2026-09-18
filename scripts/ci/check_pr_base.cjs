// Lightweight admission check; stale PRs must return to their owning task.
const transientStatus = new Set([500, 502, 503, 504]);
const transientCode = new Set(['ECONNRESET', 'ECONNREFUSED', 'ETIMEDOUT', 'EAI_AGAIN',
  'UND_ERR_CONNECT_TIMEOUT', 'UND_ERR_SOCKET', 'UND_ERR_HEADERS_TIMEOUT']);

// Retry only these read calls, never the guard or its rejection decisions.
async function readWithRetry(read, sleep) {
  for (let attempt = 0; ; attempt++) {
    try {
      return await read();
    } catch (error) {
      const transient = error.status != null
        ? transientStatus.has(error.status)
        : transientCode.has(error.code ?? error.cause?.code) ||
          (error instanceof TypeError && error.message === 'fetch failed');
      if (!transient || attempt === 3) throw error;
      await sleep(1000 * 2 ** attempt);
    }
  }
}

module.exports = async ({ github, context, core,
  sleep = ms => new Promise(resolve => setTimeout(resolve, ms)) }) => {
  if (context.eventName !== 'pull_request') return;
  const { owner, repo } = context.repo;
  const number = context.payload.pull_request.number;
  const expected = context.payload.pull_request.head.sha;
  const read = operation => readWithRetry(operation, sleep);
  const { data: pr } = await read(() => github.rest.pulls.get({ owner, repo, pull_number: number }));
  if (pr.state !== 'open' || pr.draft || pr.base.ref !== 'main' || pr.head.sha !== expected) {
    core.setFailed('PR changed or is not ready; do not run the old CI attempt.');
    return;
  }
  const readMain = async () => (await read(() => github.rest.git.getRef({ owner, repo, ref: 'heads/main' }))).data.object.sha;
  const main = await readMain();
  const { data: comparison } = await read(() => github.rest.repos.compareCommitsWithBasehead({
    owner, repo, basehead: `${main}...${expected}`,
  }));
  if (!['ahead', 'identical'].includes(comparison.status) || pr.mergeable === false) {
    core.setFailed(`BASE_UPDATE_REQUIRED: PR #${number} must merge origin/main (${main}) in its own task before CI.`);
    return;
  }
  if (await readMain() !== main) core.setFailed('Main advanced during admission; retry after synchronization.');
};
