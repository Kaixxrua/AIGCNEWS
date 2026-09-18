# AO integration and migration

AO is installed outside the product repository, pinned to upstream commit
`1935f4e7d3de06cc02c618a2ab3bdd3f9e704de4`. The isolated daemon listens only on
127.0.0.1:8792 and stores state in `~/.local/state/aigcnews-ao/`.
The user service is `aigcnews-ao.service`; the pinned CLI is under
`~/.local/lib/aigcnews-ao/ao`. No provider authentication files are migrated.

The initial integration uses AO standalone controller sessions so AO does not
create competing Git worktrees. Actual development must still use
`scripts/dev_session.py start` and its session branch. Existing worktrees are
preserved during explicit legacy handoff. `ao_delivery_adapter.py` binds each
branch to one AO controller, a verified Git worktree, source evidence and PR.
It rejects duplicate bindings, branch changes and foreign repositories. This is
an adapter-managed PR association, not a native AO `claim-pr` import.

Legacy migration creates held handoff tasks. It does not import or rewrite old
Codex history, resume the original conversation, or grant a second writer.
Original conversations remain the source record. Before activation, establish
the old controller is no longer writing, audit dirty changes and PR ancestry,
and provide a task-specific handoff. The generic held message is inventory,
not evidence of complete context migration. Never start all writers at once.

AO's built-in conflict request uses rebase. Our adapter instructions must require
merging current origin/main into the task branch, no force push and fresh local
validation. GitHub retains the CI/merge gates and the production controller;
AO does not bypass these or start a second deployment queue.

The registry and dispatch outbox are private SQLite files outside Git. Dispatch
uses AO's documented `send` command, checks exact task identity and idle state,
and writes intent before sending. CLI acceptance is not proof of agent execution:
read the session conversation for the matching event and completed response.
Ambiguous delivery is not retried blindly. Busy tasks wait.

`observe` collects live PR states and appends timestamped evidence. Completion
timing must also include exact-head workflow run/job timestamps and the active
production release. Held tasks and local tests are not a deployment success.
Native ownership import, automatic handoff activation and the full production
acceptance remain pending; the adapter deliberately has no implicit activation.
