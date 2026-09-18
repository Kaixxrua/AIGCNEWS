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
`watch` polls only explicitly active bindings, rechecks live PR SHA and local
clean head, then delivers base-update or exact-head CI failure feedback via AO.
Merged tasks additionally receive notify-only active-production completion or
verified containing-carrier status/failure. These events use the lineage probe,
explicit task bindings, durable identities and a second evidence/ownership check;
carrier task names are never inferred. Completion deduplicates across later
active releases; carrier events distinguish source, run, attempt and status.
The prompts prohibit edits and deployments, and failures await coordinator action.
Run the adapter from the repository scripts tree (with its sibling
`../release/delivery_probe.py`), preserving that layout if packaged separately.
The production root comes from `aigcnews.productionRoot` or the shared Git
repository's sibling `AIGCNEWS-production`; unavailable state or Git ancestry
fails closed. No service installation or live notification is implied by tests.
Inactive migration entries remain held. CI pause still pauses this loop. On this
host `aigcnews-ao-delivery.service` replaces the desktop feedback watcher; never
run both for the same tasks. Only one controller may own a branch for writing.
Native ownership import, automatic handoff activation and full production
acceptance remain pending; the adapter deliberately has no implicit activation.

For new work, `new --name <name> --prompt-file <file>` launches an AO controller
that first creates its real session worktree through dev_session and binds its
own AO ID. It holds until the coordinator validates the receipt. Use
`activate --branch <branch> --expect-head <sha> --handoff-evidence <evidence>`
only after verifying no competing writer. This is coordinator responsibility,
not a new per-task user approval. Activation refuses dirty/changed branches or
busy AO controllers. The watcher attaches newly opened PRs by exact branch.

## 合并后 main CI 失败恢复

适配器只把当前 `main` 的精确 landing SHA 上最新一次 `Contract Baseline`
`push` 失败派发给该 landing PR 的已登记 AO 任务。任务是修复调查负责人，
不代表其代码一定造成故障；禁止把祖先提交的失败广播给其他任务。
已上线、已有更新 main、验证正在重试、任务忙碌、工作树脏或归属变化时不派发。
同一个 run/attempt 只派发一次，网络结果不明不盲目重发。

任务应先读取失败日志，再通过 `dev_session.py start` 创建干净后继工作树，
执行安装目录中 `ao_delivery_adapter.py recover --old-branch ... --branch ...
--worktree ... --event ...`。该命令核对 AO_SESSION_ID、创建时任务归属、
旧 PR/head、当前失败证据和最新 main，原子保存 `recovery_lineage` 后迁移绑定。
不需要协调者或用户再次批准，旧工作树与事件保留；修复仍经测试、提交、普通
push、自动 PR、CI、合并及生产门禁。明确外部配置/权限阻塞仍须如实报告。

事件状态区分：`accepted` 为 AO 接受发送；`responded` 为同一自动化消息
turn 内出现 Agent 回复；`executed` 为同一 turn 内至少一个命令成功完成。
回执记录 turn、消息与命令 ID。`executed` **不表示修复成功或已部署**，
修复需以新 PR/精确 SHA 的 CI 和生产 active release 为准。
这些 AO 任务在 AO 中运行，不保证桌面原历史对话会显示新的唤醒消息。

安装/升级时须一并复制 `ao_delivery_adapter.py`、`ao_recovery.py` 和
`delivery_ownership.py` 到同一受控运行目录；保留已有数据库、凭据及 lineage
probe。重启适配器只恢复观察，不重启 CI runner 或生产服务。
