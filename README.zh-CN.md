<div align="center">
  <img src="docs/assets/logo-4k.png" alt="AIGCNEWS" width="440">
</div>

<p align="center">
  <strong>简体中文</strong> | <a href="README.md">English</a>
</p>

<p align="center">
  <a href="https://aigcnews.cn/mcp?utm_source=github&utm_medium=readme"><img alt="在线使用" src="https://img.shields.io/badge/%E5%9C%A8%E7%BA%BF%E4%BD%BF%E7%94%A8-aigcnews.cn-blue"></a>
  <a href="https://cursor.com/en-US/install-mcp?name=aigc-radar&config=eyJ1cmwiOiJodHRwczovL2FpZ2NuZXdzLmNuL2FwaS9tY3AifQ=="><img alt="Install in Cursor" src="https://cursor.com/deeplink/mcp-install-dark.svg"></a>
  <a href="https://aigcnews.cn/mcp?utm_source=github&utm_medium=readme"><img alt="Install in VS Code" src="https://img.shields.io/badge/Install%20in-VS%20Code-007acc"></a>
</p>

# AIGCNEWS

AI 发现数据平台：持续索引 arXiv 论文、GitHub AI 项目、科技新闻、Product Hunt 与 Hacker News，产出每日榜单与研究简报。同一份数据通过两个入口对外提供：

- **AIGC Radar MCP** —— 面向 Agent 的 MCP 数据接口（旗舰）
- **Web 站点** —— 面向人类读者的榜单、项目库与简报界面

## 演示

![AIGCNEWS 演示：Dashboard 榜单切换、项目库检索](docs/assets/demo.gif)

| Dashboard 每日榜单 | GitHub AI 项目库 |
| --- | --- |
| ![Dashboard：多源榜单与趋势雷达](docs/assets/screenshot-dashboard.png) | ![项目库：18,000+ 精选 AI 项目](docs/assets/screenshot-projects.png) |

| 项目库语义检索（"mcp server"） |
| --- |
| ![项目检索：语义匹配 MCP 相关项目](docs/assets/screenshot-project-search.png) |

## AIGC Radar MCP（旗舰接口）

AIGC Radar 是本项目的旗舰入口：一个 Streamable HTTP MCP Server，让 Claude Code 等 MCP 客户端直接检索平台数据，并内置 MCP-first 的开源项目发现与复用策略（本地优先、500 Stars 准入、限量只读 GitHub fallback）。与通用舆情/热点聚合类 MCP 不同，它是一个 AI 垂直结构化索引：arXiv 论文、精选富化的 GitHub AI 项目库（分类体系、中英标签、星标增长快照）与多源日/周/月榜单，托管即连、公开只读。

```text
https://aigcnews.cn/api/mcp
```

接入 Claude Code：

```bash
claude mcp add --transport http aigc-radar https://aigcnews.cn/api/mcp
```

任何支持 Streamable HTTP 的 MCP 客户端都可以直接指向该 URL；Web 站点内置 9 类客户端（Cursor、Codex、VS Code、Windsurf 等）的一键导入配置；仅支持 stdio 的客户端可经 `npx mcp-remote https://aigcnews.cn/api/mcp` 桥接。自托管本地开发时 endpoint 为 `http://localhost:8000/api/mcp`。

公开工具（无需鉴权，全部只读）：

| 工具 | 用途 |
| --- | --- |
| `search_github_ai_projects` | local-first 搜索站内精选 GitHub AI 项目库（AI/Agent/MCP/RAG/LLM 工程产物） |
| `search_github_projects` | 搜索非 AI 的 GitHub 开源软件与组件 |
| `search_papers` | arXiv 论文专搜 |
| `search_documents` | 跨来源（arXiv / GitHub / news / Product Hunt / Hacker News）索引搜索 |
| `get_top_items` | 日 / 周 / 月榜单快照 |
| `get_paper_detail` | 单条索引文档详情 |
| `get_project_categories` | 项目分类与子类计数 |

携带 `Authorization: Bearer <MCP access token>` 时额外解锁 `search_my_project_favorites`（个人收藏检索）。

Context 侧提供 resources（`aigc-news://dashboard/summary`、`aigc-news://report/latest` 等）、resource templates 与 prompts（`daily_research_brief`、`project_discovery`）。完整的协议参数、MCP-first 策略与 fallback 语义见 [docs/mcp-server.md](docs/mcp-server.md)。

## Web 站点

同一份数据的人类可读界面：Dashboard 榜单与趋势雷达、GitHub AI 项目库（分类 / 筛选 / 收藏）、论文与跨来源索引、每日研究简报。前端 Vue 3 + Vite，后端 FastAPI，关系型数据存 PostgreSQL 16。

## 快速开始（Linux / WSL2）

### 前置要求

| 工具 | 版本 | 说明 |
| --- | --- | --- |
| Python | 3.12 | 后端运行时（镜像按 digest 锁定 `python:3.12-slim`） |
| Node.js | 22 | 前端构建与测试（与 CI 一致） |
| Docker + Compose | v2 | 基础设施与生产栈编排 |

### 1) 准备环境变量

```bash
cp .env.example .env
```

编辑 `.env` 填写本机参数。**`JWT_SECRET_KEY` 必须设置为强随机值**，缺失、等于示例值或长度不足 32 字符时应用拒绝启动（见 [docs/adr/0001](docs/adr/0001-jwt-secret-rotation-and-startup-guard.md)）：

```bash
openssl rand -hex 32
```

### 2) 安装依赖

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install --upgrade pip
backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt
cd frontend && npm ci && cd ..
```

`requirements-dev.txt` 在锁定的 `requirements.lock` 之上追加 pytest / pytest-cov / ruff，与 CI 使用同一份依赖基线。

### 3) 准备前端 TLS 证书（自签名即可）

`frontend-web` 的 nginx 以只读卷挂载 `frontend/ssl/`（已 gitignore，干净检出不存在），缺少证书会启动失败。本地部署生成自签名证书即可：

```bash
mkdir -p frontend/ssl
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout frontend/ssl/aigcnews.cn.key \
  -out frontend/ssl/aigcnews.cn_bundle.crt \
  -days 3650 -subj "/CN=aigcnews.cn"
# 加固后的 frontend-web 容器（cap_drop: ALL）要求私钥属主为 root
sudo chown root:root frontend/ssl/*.key && sudo chmod 600 frontend/ssl/*.key
```

### 4) 启动核心栈

```bash
scripts/manage_main_stack.sh up
```

该命令 reconcile 核心 Compose 栈（后端 API、前端、PostgreSQL、Redis、Milvus、MinIO 等）并等待健康检查通过，**干净检出即可运行**。常用子命令：`config`（校验编排，不打印秘密）、`status`、`logs`。

> 私有部署扩展（姊妹服务、外部编排网、私有 nginx server 等）不随仓库发布，以 overlay 形式注入：脚本探测到 `../aigcnews_private/deploy/docker-compose.private.yml`（可用 `AIGCNEWS_PRIVATE_COMPOSE` 覆盖）时自动并入；不存在时核心栈独立可用。机制详见 `docker/docker-compose.yml` 头部注释。

### 5) 本地开发（容器外热重载）

```bash
# 后端（读取 settings 中的 API_HOST / API_PORT，默认 8000）
backend/.venv/bin/python run_server.py

# 前端（Vite 开发服务器，默认 5173）
cd frontend && npm run dev
```

## 端口与健康检查

| 地址 | 用途 |
| --- | --- |
| `http://localhost`（80/443） | 前端站点（生产域名证书见 `frontend/ssl/`，key 必须 `root:root` 600） |
| `http://localhost:5173` | Vite 开发服务器 |
| `http://127.0.0.1:8000` | 后端 API（仅回环绑定；`/api/live`、`/api/ready` 健康检查） |
| `http://localhost:8000/api/mcp` | 本地 MCP endpoint |

基础设施（PostgreSQL / Redis / Milvus / MinIO / Attu）只在编排网络内部暴露，不向宿主机发布端口；后端通过服务名访问。宿主机侧临时调试用 `docker exec <容器> ...`，运维细节见 [docs/linux-server-boot.md](docs/linux-server-boot.md)。

## 测试与质量检查

```bash
# 后端全套件（必须从仓库根目录运行，与 CI 一致）
backend/.venv/bin/python -m pytest backend/tests -q

# 后端 lint
backend/.venv/bin/python -m ruff check backend/app backend/tests --config backend/pyproject.toml

# 前端：单元测试、类型检查、lint、构建
cd frontend
npm run test:unit
npm run typecheck
npm run lint
npm run build

# 编排校验
docker compose -f docker/docker-compose.yml config --quiet
```

提交信息遵循 Conventional Commits（`<type>(<scope>): <subject>`，scope 必填），细节见 [docs/git-workflow.md](docs/git-workflow.md)。

## 目录结构

```text
backend/            FastAPI 应用（app/）、测试（tests/）、迁移（migrations/）、依赖锁定
frontend/           Vue 3 + Vite 站点（src/）、nginx 配置、前端镜像
docker/             Compose 编排（核心栈）与备份演练编排（私有扩展经 overlay 注入）
docs/               项目文档（索引见 docs/README.md，决策记录见 docs/adr/）
scripts/            栈管理、迁移、备份与数据回填脚本
.github/workflows/  CI：后端测试、PostgreSQL 集成、前端构建与 lint、编排冒烟
.githooks/          commit-msg 提交信息校验（git config core.hooksPath .githooks）
```

## 架构与文档

- [docs/project-overview.md](docs/project-overview.md) —— 项目全景：产品、架构、数据、部署与工程状态
- [docs/architecture.md](docs/architecture.md) —— 功能架构当前态（PostgreSQL 16 为唯一关系型运行时）
- [docs/mcp-server.md](docs/mcp-server.md) —— AIGC Radar MCP 协议参数与策略
- [docs/README.md](docs/README.md) —— 全部文档索引（含历史归档标注）

## License

[MIT](LICENSE) © 2026 Kaixxrua
