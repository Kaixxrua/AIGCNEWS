# Git 提交与 PR 工作流

本文定义 AIGCNEWS 的提交信息、PR-sized 工作单元和自动推送约束，适用于开发者及 AI Agent。

## 1. 提交信息格式

提交标题使用 Conventional Commits：

```text
<type>(<scope>): <subject>
```

- `type`：必填，表示变更性质。
- `scope`：必填，使用小写 kebab-case，表示主要影响域。
- `!`：可选，仅用于不兼容变更，且必须同时配 `BREAKING CHANGE:` footer（见第 2 节）；普通变更不得使用 `!`。
- `subject`：必填，使用简洁中文或英文，描述结果而非过程；标题总长度不超过 100 个字符。
- 冒号后必须有一个空格。

### 允许的 type

| type | 用途 |
| --- | --- |
| `feat` | 新增用户可见能力 |
| `fix` | 修复缺陷 |
| `refactor` | 不改变外部行为的结构调整 |
| `perf` | 性能优化 |
| `test` | 新增或调整测试 |
| `docs` | 文档变更 |
| `build` | 构建、镜像或依赖变更 |
| `ci` | CI/CD 与自动化配置 |
| `chore` | 不属于以上类型的维护工作 |
| `revert` | 回滚既有提交 |

### 推荐 scope

优先使用稳定的业务域或基础设施名称：

- 后端：`auth`、`api`、`chat`、`projects`、`papers`、`mcp`、`ops`、`ingestion`、`repository`、`database`、`config`、`email`、`attachments`
- 前端：`frontend`、`auth-ui`、`projects-ui`、`chat-ui`、`monitor-ui`、`router`、`styles`
- 工程：`tests`、`deps`、`docker`、`ci`、`docs`、`workflow`

一个提交只选一个主要 scope。不得使用 `misc`、`temp`、`changes` 等无法表达边界的名称。

### 示例

```text
feat(projects): 增加个人工具网站收藏
fix(ingestion): 补充 settings 配置导入
refactor(repository): 抽取共享数据库连接池
test(mcp): 固化 JSON-RPC 错误契约
perf(chat-ui): 批量提交流式消息更新
ci(workflow): 校验 Conventional Commits
```

不合规示例：

```text
update code
feat: 添加功能
fix(Project): bug
chore(workflow): WIP
```

## 2. Body、Footer 与不兼容变更

简单提交可以只有标题。需要解释设计或迁移方式时，在标题后空一行填写 body，说明“为什么”和行为影响，不复述 diff。

关联事项写在 footer：

```text
Refs: #123
Closes: #456
```

不兼容变更必须同时使用标题中的 `!`，并在 footer 中说明迁移方式：

```text
feat(api)!: 调整项目分页响应

BREAKING CHANGE: `items` 移入 `data.items`；调用方必须同步更新。
```

回滚提交优先使用：

```text
revert(projects): 回滚项目筛选状态迁移

Reverts: <commit-sha>
```

## 3. PR-sized 工作单元

每个 PR-sized 工作单元必须满足：

1. 只有一个明确意图，默认净变更 50–250 行；纯移动可放宽，但不得夹带逻辑变更。
2. 提交前完成与影响面匹配的测试、类型检查或构建；失败时不得提交或推送。
3. 不覆盖、暂存或提交其他开发者及用户已有的无关修改。
4. 提交信息通过本规范校验。
5. 开发工作必须通过 `scripts/dev_session.py start <slug>` 创建 branch-backed worktree；会话分支命名为唯一的 `session/<slug>-<id>`，以最新 `origin/main` 为基线。不得在 `main`、detached HEAD 或未注册的 worktree 中开展会话工作。
6. 在提交前运行 `scripts/dev_session.py check`；它会拒绝 detached/main、ghost parent、分支或 worktree 复用，以及 dirty/staged/untracked 状态。该工具 fail-closed，不执行 reset、stash、rebase 或清理。
7. 推送前仍须按 Green/Yellow/Red 风险等级完成相应验证；自动推送不等于自动发布。

## 4. “PR 完成”的自动推送语义

在受管 session 工作流中，“PR 完成”定义为：

1. 当前 PR-sized 工作单元实现完成；
2. 影响范围检查全部通过；
3. 仅暂存该工作单元的文件；
4. Conventional Commit 创建成功；
5. 当前分支是唯一的 `session/<slug>-<id>` 任务分支，并已通过对应风险等级的验证。

成功执行 `git commit` 后，tracked `.githooks/post-commit` 自动推送当前任务分支：

- 仅允许推送 `session/*` 任务分支；
- 禁止直接推送 `main`，也禁止 force push；
- detached HEAD、无 `origin` 或非任务分支时跳过并报告；
- push 失败必须如实报告，提交仍保留在本地；可用 `AIGCNEWS_SKIP_AUTO_PUSH=1` 显式跳过；
- 需要进入 `main` 时，必须使用经过验证的 serialized landing 命令，执行 non-force CAS，并由远端分支保护规则完成最终拒绝/接受。

推送 `session/*` 后，GitHub Actions 自动创建 PR；PR 的 `Contract Baseline` 对精确 head SHA 验证成功后启用 squash auto-merge。合并后的 `main` 再次通过基线才会构建 digest 镜像并进入串行生产部署。完整前置条件、并发和回滚语义见 [`automatic-delivery.md`](automatic-delivery.md)。

### 任务完成后的自主合并与部署

用户对符合本工作流的任务收尾授予持续授权：修改完成、冲突解决且验证通过后，执行者应自行完成合并、部署和监测，不再为创建或更新 PR、合并以及触发标准部署逐项请求用户确认。

自主收尾必须同时满足以下条件：

1. 当前工作单元的检查全部通过，且提交中不包含其他任务或用户的无关修改。
2. 目标分支发生变化或解决过冲突时，必须基于最新目标分支重新验证；不得以“冲突已消除”代替测试和检查。
3. 合并仍须遵守分支保护、serialized landing、non-force CAS 及禁止 force push 等既有约束；不得为完成自主收尾而绕过保护规则。
4. 合并成功后按第 5 节先执行部署去重判断：已有部署完整包含本任务修改时复用并监测，否则自行触发标准部署并监测到验收完成。
5. 遇到检查失败、合并保护拒绝、部署失败、凭据缺失、目标环境不明确，或需要超出当前任务范围的破坏性操作时，应停止相关步骤并如实报告，不得降低门禁或猜测处理。

## 5. 部署去重与监测复用

当任务明确要求部署时，执行者必须先检查目标环境中正在进行及最近成功的部署，避免多个并行任务重复发布：

1. 明确本任务要求上线的全部提交、目标环境和待复用部署的实际版本；不得仅凭分支名、触发时间或最新提交 SHA 推断包含关系。
2. 优先使用 Git 提交祖先关系确认待复用版本包含本任务的全部提交；发生 squash、cherry-pick 或制品脱离 Git 提交时，必须改用可审计的源码清单、制品摘要或等效证据。
3. 若正在进行的部署已完整包含本任务修改，不得再次触发部署；应复用该部署并持续监测，直至部署完成和健康检查通过。
4. 若最近成功的部署已完整包含本任务修改，不得重复部署；仍须执行本任务所需的部署后验证，已有验证结果充分且可追溯时可以复用。
5. 只有在部署失败、被取消、目标环境不一致、未完整包含本任务修改，或无法可靠确认包含关系时，才允许重新部署。
6. 多个任务可能同时决策时，部署入口必须使用部署锁、幂等键或等效串行化机制，防止检查后并发触发相同部署。
7. 跳过部署时必须报告所复用的部署、目标环境、实际版本、包含关系依据及最终监测结果；跳过部署不等于跳过监测或验收。

## 6. 本地 Git hook

仓库提供 `.githooks/commit-msg`，用于在提交创建前校验标题。首次克隆或 hooks 路径失效时，在每个 linked worktree 中执行（避免把主 checkout 的绝对路径共享给其他 worktree）：

```bash
git config extensions.worktreeConfig true
git config --worktree core.hooksPath .githooks
```

检查当前 worktree 配置：

```bash
git config --worktree --get core.hooksPath
```

`.githooks/pre-commit` 按暂存文件的影响面执行三段门禁，任一失败即阻断提交；`post-commit` 只对 `session/*` 执行普通 push，`pre-push` 拒绝未持有 landing nonce 的 `main` 推送：

1. **ruff 快检**：仅检查暂存的 Python 文件（基线配置 `backend/pyproject.toml`）；
2. **后端受影响测试快筛**：`backend/app` 变更映射同名测试文件、`backend/tests` 变更直接运行；
3. **前端门禁**：全量类型检查（`vue-tsc --noEmit`）+ `vitest related` 只跑与暂存文件存在依赖关系的测试。
