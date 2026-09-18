// Lightweight admission check; stale PRs must return to their owning task.
module.exports = async ({ github, context, core }) => {
  if (context.eventName !== 'pull_request') return;
  const { owner, repo } = context.repo;
  const number = context.payload.pull_request.number;
  const expected = context.payload.pull_request.head.sha;
  const { data: pr } = await github.rest.pulls.get({ owner, repo, pull_number: number });
  if (pr.state !== 'open' || pr.draft || pr.base.ref !== 'main' || pr.head.sha !== expected) {
    core.setFailed('PR changed or is not ready; do not run the old CI attempt.');
    return;
  }
  const readMain = async () => (await github.rest.git.getRef({ owner, repo, ref: 'heads/main' })).data.object.sha;
  const main = await readMain();
  const { data: comparison } = await github.rest.repos.compareCommitsWithBasehead({
    owner, repo, basehead: `${main}...${expected}`,
  });
  if (!['ahead', 'identical'].includes(comparison.status) || pr.mergeable === false) {
    core.setFailed(`BASE_UPDATE_REQUIRED: PR #${number} must merge origin/main (${main}) in its own task before CI.`);
    return;
  }
  if (await readMain() !== main) core.setFailed('Main advanced during admission; retry after synchronization.');
};
