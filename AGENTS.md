# AIGCNEWS Codex 约束

## Git 与 PR

- 所有提交必须遵守 `docs/git-workflow.md`，标题格式为 `<type>(<scope>): <subject>`；`scope` 必填；`!` 仅用于不兼容变更，且必须配 `BREAKING CHANGE:` footer。
- 一个提交对应一个 PR-sized 工作单元；仅暂存本次工作涉及的文件，不得夹带、覆盖或回滚用户已有修改。
- 提交前必须运行与影响面匹配的测试、类型检查或构建。检查失败时不得提交或推送，并应如实报告。
- 开发任务在实现和验证通过后必须由 Agent 自行暂存本工作单元并创建提交，不得停在“创建 PR”按钮或把正常提交留给用户；只有验证失败、缺少必要外部配置或用户明确要求不提交时才停止自动交付。
- 开发工作必须通过 `scripts/dev_session.py start <slug>` 创建 branch-backed worktree；会话分支命名为唯一的 `session/<slug>-<id>`，以最新 `origin/main` 为基线。
- 提交前运行 `scripts/dev_session.py check`；工具拒绝 `main`、detached HEAD、ghost parent、复用的分支/worktree，以及 dirty/staged/untracked 状态；工具不会执行 reset、stash、rebase 或清理。
- 成功提交后，由 tracked `.githooks/post-commit` 自动 push 当前会话分支。不得使用 `--force`、`--force-with-lease` 或任何等效强制推送。
- 自动推送后的建 PR、精确 SHA 自动合并和生产部署遵循 `docs/automatic-delivery.md` 的既定流水线，无需逐次授权；流水线外手工创建/合并 PR、直接 landing 或部署仍需独立授权。
- 不要为 Codex 新生成的提交添加 Claude 专属的 `Co-Authored-By` trailer，也不要删除历史提交中真实存在的 attribution。

## 重构执行

- 遵循已批准的分层渐进式重构方案：Contract → Extract → Adapt → Switch → Delete。
- 保持 REST、MCP、SSE、SQL 查询行为和路由行为兼容；行为变化必须单独说明并增加契约测试。
- 热点文件 `backend/app/repositories/postgres_project_catalog.py` 与 `frontend/src/views/GitHubProjectsView.vue` 同一时间只允许一个写入者。
- 安全、权限、事务、schema migration、MCP/SSE wire format 属于 Red 变更，必须进行额外验证。

## Codex 工作流

- 项目生命周期 hooks 位于 `.codex/hooks.json`。首次加载或内容变化后，通过 `/hooks` 检查并信任准确的 hook 定义。
- `Stop` hook 会阻止有开发提交的 session 在推送、PR、精确 SHA 合并和生产 active release 闭环前结束；Agent 必须继续跟踪既定流水线，不得把“创建 PR”按钮或是否部署留给用户。只有生产已包含本任务，或存在已核实且带证据的外部阻塞时才允许结束。
- 项目 Skill 位于 `.agents/skills/`；运行 Docker Compose 后端与出站代理验证时使用 `$verify`。
- 项目、论文、已索引内容或资讯流的发现型任务，优先使用 AIGCNEWS MCP 中对应的搜索工具；MCP-first hook 默认只观察并提示，只有显式设置 `AIGCNEWS_MCP_FIRST_MODE=enforce` 才阻断不合规路由。
- Codex 的权限与沙箱模型不同于 Claude Code，不复制 `.claude/settings.local.json` 中的宽泛 Bash/网络白名单；按 Codex 的项目信任和审批机制处理。
