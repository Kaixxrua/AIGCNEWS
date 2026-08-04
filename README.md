# AIGCNEWS

AI 发现数据平台：持续索引 arXiv 论文、GitHub AI 项目、科技新闻、Product Hunt 与 Hacker News，产出每日榜单与研究简报。同一份数据通过两个入口对外提供：

- **AIGC Radar MCP** —— 面向 Agent 的 MCP 数据接口（旗舰）
- **Web 站点** —— 面向人类读者的榜单、项目库与简报界面

## AIGC Radar MCP（旗舰接口）

AIGC Radar 是本项目的旗舰入口：一个 Streamable HTTP MCP Server，让 Claude Code 等 MCP 客户端直接检索平台数据，并内置 MCP-first 的开源项目发现与复用策略（本地优先、500 Stars 准入、限量只读 GitHub fallback）。

```text
http://localhost:8000/api/mcp
```

接入 Claude Code：

```bash
claude mcp add --transport http aigc-radar http://localhost:8000/api/mcp
```

任何支持 Streamable HTTP 的 MCP 客户端都可以直接指向该 URL；生产环境把主机替换为部署域名即可。

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
| `get_project_library` | 兼容入口（新客户端请改用上面两个搜索工具） |

携带 `Authorization: Bearer <MCP access token>` 时额外解锁 `search_my_project_favorites`（个人收藏检索）。

Context 侧提供 resources（`aigc-news://dashboard/summary`、`aigc-news://report/latest` 等）、resource templates 与 prompts（`daily_research_brief`、`project_discovery`）。完整的协议参数、MCP-first 策略与 fallback 语义见 [docs/mcp-server.md](docs/mcp-server.md)。

## Web 站点

同一份数据的人类可读界面：Dashboard 榜单与趋势雷达、GitHub AI 项目库（分类 / 筛选 / 收藏）、论文与跨来源索引、每日研究简报。前端 Vue 3 + Vite，后端 FastAPI，关系型数据存 PostgreSQL。

## 快速开始 (Quick Start)

### 1) 准备环境变量
1. 复制示例文件并重命名为 `.env`：
   ```bash
   copy .env.example .env
   ```
2. 编辑 `.env`，根据本机环境填写参数。

### 2) 安装依赖
在 Windows 下建议直接使用启动脚本：

```bash
start.bat setup
```

等价的手动命令：

```bash
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r backend\requirements.txt
cd frontend
npm install
```

### 3) 启动基础设施（Milvus + Attu + Neo4j）

```bash
start.bat up
```

默认访问地址（应用服务）：
- 后端 API: `http://localhost:8000`（`/api/live`、`/api/ready` 健康检查）
- 前端: `http://localhost`（80/443，生产域名证书见 `frontend/ssl/`）

基础设施（Milvus / MinIO / Attu / Neo4j / Redis）只在编排网络内部暴露，
不再向宿主机发布端口；后端通过服务名访问（`milvus:19530`、`neo4j:7687`、
`redis:6379`）。宿主机侧临时调试用 `docker exec <容器> ...`，运维细节见
[`docs/linux-server-boot.md`](docs/linux-server-boot.md)。

默认账号与密码（可用 `.env` 中的 `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` /
`NEO4J_PASSWORD` 覆盖）：
- Neo4j: `neo4j / 12345678`（请在 `.env` 中修改）
- MinIO: `minioadmin / minioadmin`

### 4) 启动开发服务

```bash
start.bat dev
```

启动后：
- 后端 FastAPI: `http://localhost:8000`
- 前端 Vite: `http://localhost:5173`

---

## 常用命令

- `start.bat setup`：创建虚拟环境并安装后端与前端依赖
- `start.bat up`：启动 Milvus + Attu + Neo4j
- `start.bat down`：停止基础设施容器
- `start.bat dev`：启动后端与前端开发服务器
