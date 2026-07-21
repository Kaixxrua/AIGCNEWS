# RAG AIGC Agent

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

默认访问地址：
- Milvus gRPC: `localhost:19530`
- Milvus HTTP: `localhost:9091`
- Attu 管理界面: `http://localhost:8000`
- Neo4j Browser: `http://localhost:7475`
- Neo4j Bolt: `bolt://localhost:7688`

默认账号与密码：
- Neo4j: `neo4j / your_password`（请在 `.env` 中修改）
- MinIO: `minioadmin / minioadmin`

### 4) 启动开发服务

```bash
start.bat dev
```

启动后：
- 后端 FastAPI: `http://localhost:8000`
- 前端 Vite: `http://localhost:5173`

### MCP Server

AIGC_NEWS 对外暴露一个 Streamable HTTP MCP Server：

```text
http://localhost:8000/api/mcp
```

当前对外能力均为公开只读数据：工具包括论文专搜 `search_papers`、跨来源索引搜索 `search_documents`、`get_paper_detail`、`get_top_items`、`search_github_projects`、`search_github_ai_projects`、`get_project_library`、`get_project_categories`；Context 侧支持 `resources/list`、`resources/templates/list`、`resources/read` 与 `prompts/list`、`prompts/get`，可读取 `aigc-news://dashboard/summary`、`aigc-news://dashboard/top{?source,period,date,limit}`、`aigc-news://papers/{paper_id}`、`aigc-news://projects/categories`、`aigc-news://projects/library{?q,category,subcategory,language,scope,sort,page,limit}`、`aigc-news://report/latest{?source,period,date}` 等公共上下文。任意领域 GitHub/开源软件推荐（包括 Windows/macOS/Linux 桌面、截图与效率工具）优先使用 `search_github_projects`；AI/RAG/LLM/Agent/MCP 请求默认优先使用 local-first 的 `search_github_ai_projects`，包括学习资料、教程、示例和实现；只有明确要求论文、文献、survey、引用、benchmark、实验或研究结果时才优先使用仅返回 arXiv 论文的 `search_papers`；明确搜索站内新闻或跨来源索引时使用 `search_documents`，`get_project_library` 作为兼容入口保留。项目搜索使用一致的关键词、排序和分页语义；只有本地第一页结果总数为 0，且过滤与排序可由 GitHub Search 等价表达时，才进行限量、只读 fallback。结果通过 `result_origin` 标记来源并采用紧凑字段投影。MCP 输入按发布的 JSON Schema 严格校验，日期必须是真实的 `YYYY-MM-DD` 日历日期。fallback 不写库、不暴露 GitHub Token。管理员页面中的 `/api/ops/mcp-servers` 是用于配置外部 MCP Server 的出站管理能力，与这里的入站 `/api/mcp` 不同。

---

## 常用命令

- `start.bat setup`：创建虚拟环境并安装后端与前端依赖
- `start.bat up`：启动 Milvus + Attu + Neo4j
- `start.bat down`：停止基础设施容器
- `start.bat dev`：启动后端与前端开发服务器
