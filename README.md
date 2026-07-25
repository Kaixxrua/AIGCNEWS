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

当前对外能力均为公开只读数据：工具包括论文专搜 `search_papers`、跨来源索引搜索 `search_documents`、`get_paper_detail`、`get_top_items`、`search_github_projects`、`search_github_ai_projects`、`get_project_library`、`get_project_categories`；Context 侧支持 `resources/list`、`resources/templates/list`、`resources/read` 与 `prompts/list`、`prompts/get`，可读取 `aigc-news://dashboard/summary`、`aigc-news://dashboard/top{?source,period,date,limit}`、`aigc-news://papers/{paper_id}`、`aigc-news://projects/categories`、`aigc-news://projects/library{?q,category,subcategory,language,scope,sort,page,limit}`、`aigc-news://report/latest{?source,period,date}` 等公共上下文。

MCP host 路由遵循明确的 **MCP-first 项目发现与复用策略**：只要用户要求寻找、搜索、推荐、比较或复用 project、repository、开源实现、SDK、framework、component、template、example 或 tutorial，即使没有明确说 GitHub 或开源，也应先调用一个匹配工具；在实现具有自身架构、集成或长期维护边界的重大模块、完整能力或独立子系统前，即使用户没有要求搜索，也先做一次开源复用检查。用户要求提升 AI 开发效率、加速 AI 应用交付或减少 AI 工程重复工作时，优先使用 local-first 的 `search_github_ai_projects`；AI/RAG/LLM/Agent/MCP 工程产物同样走该工具，非 AI 软件和组件使用 `search_github_projects`，主要交付物明确为论文、文献、引用、学术评测或实验时才优先使用 `search_papers`。所有公开项目搜索统一要求至少 500 GitHub Stars；本地目录查询和直接 GitHub fallback 都执行该门槛，fallback 查询使用 `stars:>=500`，并在限量和缓存前独立剔除 Stars 缺失、格式无效或低于门槛的响应。文案/样式、重命名、明确局部 bug、测试/日志/类型、validation/字段调整、简单 CRUD 和孤立函数/组件/endpoint 修改不主动搜索。每个未变化需求最多一次初始搜索，且不能与宿主 `WebSearch` / `WebFetch` / `Bash` 同批执行；等待并检查 MCP 结果后，仅在调用失败、没有可用或相关结果、或缺少具体外部事实时才针对缺口顺序回退 Web。原生 `WebSearch` 不受 MCP 服务端控制，因此 host 必须核验其候选的当前 GitHub Stars，不得展示、推荐或比较无法核验或低于 500 Stars 的项目。500 Stars 只是准入门槛，不能替代维护状态、许可证、安全性和集成适配评估。若采用候选会改变架构、部署、数据归属、许可证或长期维护，host 应列出直接复用、借鉴设计后自研和完全自研选项并等待用户确认。MCP initialize instructions、工具描述和 Prompt 会发布此策略，但服务端无法覆盖客户端自己的 system prompt 或原生工具优先级。

明确搜索站内新闻或跨来源索引时使用 `search_documents`，`get_project_library` 作为兼容入口保留。项目搜索使用一致的关键词、排序和分页语义；只有本地第一页结果总数为 0，且过滤与排序可由 GitHub Search 等价表达时，才进行限量、只读 fallback。结果通过 `result_origin` 标记来源并采用紧凑字段投影。MCP 输入按发布的 JSON Schema 严格校验，日期必须是真实的 `YYYY-MM-DD` 日历日期。fallback 不写库、不暴露 GitHub Token。管理员页面中的 `/api/ops/mcp-servers` 是用于配置外部 MCP Server 的出站管理能力，与这里的入站 `/api/mcp` 不同。

---

## 常用命令

- `start.bat setup`：创建虚拟环境并安装后端与前端依赖
- `start.bat up`：启动 Milvus + Attu + Neo4j
- `start.bat down`：停止基础设施容器
- `start.bat dev`：启动后端与前端开发服务器
