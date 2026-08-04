# AIGCNEWS Agent 约束

## Git 与 PR

- 所有提交必须遵守 `docs/git-workflow.md`，标题格式为 `<type>(<scope>): <subject>`；`scope` 必填；`!` 仅用于不兼容变更，且必须配 `BREAKING CHANGE:` footer。
- 一个提交对应一个 PR-sized 工作单元；仅暂存本次工作涉及的文件，不得夹带、覆盖或回滚用户已有修改。
- 提交前必须运行与影响面匹配的测试、类型检查或构建。检查失败时不得提交或推送，并应如实报告。
- 当前项目采用主干开发：完成并验证一个 PR-sized 工作单元后，直接提交并推送到 `main`。
- 成功提交后，由项目 Claude Code hook 自动 push `main`。不得使用 `--force`、`--force-with-lease` 或任何等效强制推送。
- 自动 push 不代表自动发布；若需要创建或合并远程 PR，仍需独立授权或既定流程。
- Git 提交必须保留 Claude Code 要求的 `Co-Authored-By: Claude <noreply@anthropic.com>` trailer。

## 重构执行

- 遵循已批准的分层渐进式重构方案：Contract → Extract → Adapt → Switch → Delete。
- 保持 REST、MCP、SSE、SQL 查询行为和路由行为兼容；行为变化必须单独说明并增加契约测试。
- 热点文件 `backend/app/repositories/postgres_project_catalog.py` 与 `frontend/src/views/GitHubProjectsView.vue` 同一时间只允许一个写入者。
- 安全、权限、事务、schema migration、MCP/SSE wire format 属于 Red 变更，必须进行额外验证。
