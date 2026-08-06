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
5. 当前项目采用主干开发，完成并验证后直接提交到 `main`，不创建长期任务分支。
6. 推送前仍须按 Green/Yellow/Red 风险等级完成相应验证；自动推送不等于自动发布。

## 4. “PR 完成”的自动推送语义

在 Claude Code 工作流中，“PR 完成”定义为：

1. 当前 PR-sized 工作单元实现完成；
2. 影响范围检查全部通过；
3. 仅暂存该工作单元的文件；
4. Conventional Commit 创建成功；
5. 当前分支是 `main`，且本地 `main` 已基于最新 `origin/main`。

成功执行 `git commit` 后，项目的 Claude Code `PostToolUse` hook 自动推送当前 `HEAD`：

- `main` 已有 upstream：`git push`；
- `main` 没有 upstream：`git push -u origin main`；
- 禁止 force push；
- 非 `main` 分支、detached HEAD、无 `origin` 时跳过并报告；
- push 失败必须如实报告，提交仍保留在本地；
- 设置 `AIGCNEWS_SKIP_AUTO_PUSH=1` 可对单次紧急操作禁用自动推送。

该 hook 只响应 Claude Code 成功完成的 Bash `git commit` 操作，不会自动创建或合并 GitHub PR，也不会自动发布。开发者在 Claude Code 外部创建的提交不受该 hook 影响。

## 5. 本地 Git hook

仓库提供 `.githooks/commit-msg`，用于在提交创建前校验标题。首次克隆或 hooks 路径失效时执行：

```bash
git config core.hooksPath .githooks
```

检查当前配置：

```bash
git config --get core.hooksPath
```

`.githooks/pre-commit` 按暂存文件的影响面执行三段门禁，任一失败即阻断提交：

1. **ruff 快检**：仅检查暂存的 Python 文件（基线配置 `backend/pyproject.toml`）；
2. **后端受影响测试快筛**：`backend/app` 变更映射同名测试文件、`backend/tests` 变更直接运行；
3. **前端门禁**：全量类型检查（`vue-tsc --noEmit`）+ `vitest related` 只跑与暂存文件存在依赖关系的测试。
