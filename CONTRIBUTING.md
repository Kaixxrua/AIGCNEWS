# 贡献指南

感谢你对 AIGCNEWS 的关注！本项目是一个 AI 发现数据平台（FastAPI + PostgreSQL 后端，Vue 3 + Vite 前端，AIGC Radar MCP 旗舰接口）。

## 开发环境

按 [README](README.md) 的"快速开始"完成依赖安装与核心栈启动（`scripts/manage_main_stack.sh up`）。核心栈只需要本仓库即可运行；`docker/docker-compose.yml` 头部注释描述了可选 overlay 机制（私有部署扩展，不影响开源贡献）。

## 提交规范

本项目使用 Conventional Commits，且 `scope` 必填：

```text
<type>(<scope>): <subject>
```

完整规则（允许的 type、推荐 scope、BREAKING CHANGE 约定、PR-sized 工作单元）见 [docs/git-workflow.md](docs/git-workflow.md)。仓库启用了 `core.hooksPath` 指向 `.githooks/`，`commit-msg` hook 会校验标题格式。

## 提交前必须通过的检查

按影响面运行匹配的检查，**失败时请不要提交**：

| 影响面 | 命令 |
| --- | --- |
| 后端代码 | `backend/.venv/bin/python -m pytest backend/tests -q`（或至少受影响测试）+ `backend/.venv/bin/python -m ruff check backend/app backend/tests` |
| 前端代码 | `cd frontend && npm run test:unit && npm run typecheck && npm run lint && npm run build` |
| 编排/镜像 | `docker compose --file docker/docker-compose.yml config --quiet`；改了 Dockerfile 需干净构建对应镜像 |

`.githooks/pre-commit` 会对暂存的 Python 文件跑 ruff 并按"受影响测试映射"快筛，但它不是全部测试的替代品。

## 架构约束（重要）

- 分层方向由契约测试守护（`backend/tests/test_layer_boundaries.py`）：api → services → repositories → domain，禁止反向依赖；services 层不得抛 `fastapi.HTTPException`。
- 数据库变更走 `backend/migrations/postgres/NNNN_name.sql` 手写迁移（连续编号、checksum 台账），新迁移请保持幂等（`IF NOT EXISTS` / DO 块），参考 0034 的先例。
- REST / MCP / SSE / SQL 查询行为保持兼容；行为变化必须在提交信息中说明并补契约测试。
- 安全、权限、事务、schema migration、MCP/SSE wire format 属于高风险变更，请附带额外验证说明。

## PR 流程

1. 一个 PR 对应一个工作单元（见 docs/git-workflow.md 第 3 节），只暂存本单元涉及的文件。
2. CI（`contract-baseline.yml`）会跑：依赖锁一致性、ruff、全套 pytest（覆盖率门禁 `--cov-fail-under=70`）、Postgres 16 真库集成测试、compose smoke、前端 test/lint/typecheck/build 全链。
3. 提交信息 body 建议说明动机与验证方式，而不只是罗列改动。

## 测试约定

- 异步测试使用 `unittest.IsolatedAsyncioTestCase`（既有约定）。
- 仓储层关键行为补 `postgres_*_integration.py` 真库集成测试（CI 用 Postgres 16 service container 运行）。
- 前端优先测 composable / viewModel / store 逻辑层，而非 DOM 快照。

## 报告安全问题

请按 [SECURITY.md](SECURITY.md) 私下报告，不要开公开 Issue。

## 行为准则

参与本项目即表示同意遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。
