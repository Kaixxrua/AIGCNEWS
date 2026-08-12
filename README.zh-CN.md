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

面向工程师、研究者与 AI Agent 的 AI 发现与情报平台：持续索引 arXiv / HuggingFace 论文、GitHub AI 项目、科技新闻、Product Hunt、Hacker News、X（Twitter）热点与微信公众号文章，加工为可浏览的榜单、可检索的项目库与可订阅的简报。同一份数据通过两个入口对外提供：

- **AIGC Radar MCP** —— 面向 Agent 的 MCP 数据接口（旗舰）
- **Web 站点** —— 面向人类读者的榜单、项目库与简报界面（[aigcnews.cn](https://aigcnews.cn)）

## 演示

![AIGCNEWS 演示：Dashboard 榜单切换、项目库检索](docs/assets/demo.gif)

| Dashboard 每日榜单 | GitHub AI 项目库 |
| --- | --- |
| ![Dashboard：多源榜单与趋势雷达](docs/assets/screenshot-dashboard.png) | ![项目库：18,000+ 精选 AI 项目](docs/assets/screenshot-projects.png) |

| 项目库语义检索（"mcp server"） |
| --- |
| ![项目检索：语义匹配 MCP 相关项目](docs/assets/screenshot-project-search.png) |

## 功能一览

### 多源榜单 Dashboard

- 一块看板聚合六大来源榜单 —— **论文、GitHub、新闻、Product Hunt、Hacker News、X** —— 支持日 / 周 / 月周期切换
- 基于快照的榜单：日历回看任意历史日期；已定稿榜单永久归档，实时初榜展示仍在采集的数据，昨日榜单定稿前处于静默期（北京时间揭榜）
- GitHub 热度分综合星标增速、项目体量、维护活跃度、社区参与度、项目年龄与近期更新 —— 而非只看总 Stars
- 趋势雷达、今日新增 / 用户 / 访客统计，以及 MCP 实时调用计数

### GitHub AI 项目库

- **18,000+ 精选 AI 项目与工具网站**，两级分类体系、编程语言筛选、中英双语描述与标签
- 混合检索：PostgreSQL 关键词候选 × Milvus 语义召回融合，回库水合完整数据，准入过滤（公网 GitHub fallback ≥ 500 Stars），再按相关性 / 热度 / Stars / 更新时间 / 收录时间 / 名称排序
- 每张卡片展示增长指标（今日 +N Stars）与可用状态，另有今日热门与站长推荐合集
- 筛选状态同步到 URL —— 刷新不丢、可复制分享、支持浏览器前进后退

### 论文发现与阅读

- arXiv 与 HuggingFace 每日热门论文，支持标题 / 摘要检索
- 站内 PDF 阅读器：分页渲染与进度显示、原始文件下载、桌面双栏 / 移动单栏布局、区域框选截图
- 两阶段采集：摘要先入库保证立即可搜；后台再下载 PDF、解析全文、切片并建立向量索引

### X 动态（Twitter）

- 精选 AI 账号时间线，图片 / 视频瀑布流，按互动分排序
- 最近 24 小时流 + 按日期快照，静默期机制（北京时间 15:00 定稿后公开）
- 推文中文翻译，@ 提及与链接完整补回
- 管理员工具：监控账号管理、按需拉取、快照重建 / 补拉

### 微信公众号

- 关注公众号，在统一 Feed 中阅读最新文章，站内全文阅读（展开 / 收起过渡、回到顶部 / 跳到底部导航）
- 平台侧微信连接器：扫码登录，会话加密持久化在服务端；支持搜索公众号、保存账号与后台文章同步

### 智能简报与订阅

- 综合 / 论文 / GitHub / 新闻 / Product Hunt / Hacker News 等方向的日报、周报、月报，中英双语
- SSE 流式生成，带缓存、可重新生成、可按日期阅读历史简报
- 按来源与频率订阅邮件推送，支持立即送达，在订阅页统一管理

### 收藏与私人书架

- 收藏项目乐观更新（失败自动回滚），支持个人标签与跨设备同步
- 私人工具书架：提交 URL 自动抓取 metadata 并由 AI 富化卡片，失败可切换手动模式；标题 / 描述 / 分类 / 标签 / 图标随时可改
- 个人网站绝不混入公共项目库 —— 公共与私人数据严格隔离

### 账号与管理后台

- 邮箱注册、登录、验证码找回密码；JWT 会话
- 运维监控：一键 / 按源 / 按日期触发或强制采集、生成每日简报、刷新 Dashboard 缓存
- 模型 Provider 管理（Base URL / Key / 模型 / 推理强度，真实连接测试）与外部 MCP Server 注册（握手 + 工具清单探测）
- X 采集运维：凭证池、监控账号、按需拉取、快照重建
- GitHub 爬取任务（Stars / 日期窗口、dry-run、自动富化）与富化队列管理（重试 / 补跑 / 终止、并发控制与熔断）

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

携带 `Authorization: Bearer <MCP access token>` 时额外解锁 `search_my_project_favorites`（个人收藏检索）。登录用户可签发最小权限、可撤销的只读 Token，支持设备标签与有效期 —— 明文仅在创建时展示一次，服务端只保存摘要。

Context 侧提供 resources（`aigc-news://dashboard/summary`、`aigc-news://report/latest` 等）、resource templates 与 prompts（`daily_research_brief`、`project_discovery`）。完整的协议参数、MCP-first 策略与 fallback 语义见 [docs/mcp-server.md](docs/mcp-server.md)。

### 性能实测

服务端延迟，测于 2026-08-11，可用 [scripts/benchmark_mcp_latency.py](scripts/benchmark_mcp_latency.py) 复现（Streamable HTTP JSON-RPC，6 个代表性工具 × 3 轮，共 18 次 `tools/call` 计时）：

| Endpoint | p50 | p95 | 说明 |
| --- | --- | --- | --- |
| 自托管 `http://localhost:8000/api/mcp` | 0.36 s | 0.71 s | 后端查询处理本身为亚秒级 |

Agent 端到端对比 WebSearch，测于 2026-08-11，可用 [scripts/benchmark_agent_tool_latency.py](scripts/benchmark_agent_tool_latency.py) 复现：headless `claude -p`（claude-opus-4-8，effort low），MCP 指向 `http://127.0.0.1:8000/api/mcp`，wall-clock 从进程启动计到产出完整回答，两侧均要求用不超过两句话作答，10 组不同查询 × 每条路径各 1 次：

| 查询 | AIGC Radar MCP | WebSearch |
| --- | --- | --- |
| self-hosted LLM observability platform open source | 9.6 s | 13.4 s |
| open source screenshot tool for Windows with rounded corners | 7.7 s | 38.8 s |
| mixture of experts load balancing paper | 6.7 s | 19.8 s |
| Sora video generation model | 6.2 s | 42.4 s |
| trending GitHub repositories this week | 9.4 s | 10.7 s |
| MCP server for database access | 8.7 s | 10.0 s |
| self-hosted photo management like Google Photos | 32.9 s | 31.8 s |
| RLHF reward model overoptimization paper | 7.0 s | 17.4 s |
| top Hacker News stories this month | 6.8 s | 52.2 s |
| Claude Code agent skills | 6.7 s | 54.8 s |
| **中位数** | **7.4 s** | **25.8 s** |

MCP 在 10 组中有 9 组低于 10 秒，WebSearch 从未低于 9.9 秒——**中位口径快 3.5 倍**。纯 MCP 工具执行（`tool_use` → `tool_result`）中位数 0.16 s（0.03–0.80 s）；WebSearch 的搜索在 API 回合内部执行（server-side 工具），客户端无法观测到等价窗口。32.9 s 的 MCP 离群值是模型 API 停顿而非工具耗时（该次工具调用仅 0.041 s）——中位数口径天然排除此类波动。

工具选用准确率，测于 2026-08-12，可用 [scripts/eval_mcp_tool_selection.py](scripts/eval_mcp_tool_selection.py) 复现：headless `claude -p`（claude-opus-4-8，effort high），宿主工具与全部 7 个 MCP 工具同时可用；仅当**首个**工具调用命中预期的 AIGC Radar 工具且全程无宿主工具绕行时记为通过：

| 探针组 | 准确率 |
| --- | --- |
| 9 个意图明确探针（各 10 + 5 次试验） | **98%**（49/50） |
| 2 个混合意图探针（各 5 次试验） | **90%**（9/10） |
| **总计（11 个探针，60 次试验）** | **96.7%**（58/60） |

混合意图提示词明确邀请两类交付物（"以项目为主、论文为辅"）。早期试验中模型会把两个候选工具并行都调；工具描述中的路由规则已彻底消除这一模式——剩余两次未命中分别是碎片式提示词下的凭记忆作答（零工具调用）与一次宿主 Bash 绕行，而非竞争工具并行。

LLM-as-judge 质量评分，测于 2026-08-12，使用 [Salesforce MCPEval](https://github.com/SalesforceAIResearch/MCPEval)：9 个自动生成的任务在自托管 endpoint 上执行（agent 模型 gpt-5.4-mini），由 gpt-5.4 对照 ground-truth 轨迹与参考答案打分，0–1 量表：

| 维度 | 平均分 |
| --- | --- |
| **工具使用轨迹**（7 个子维度） | **0.71** |
| — adaptability（应变） | 0.83 |
| — tool_selection（工具选择） | 0.72 |
| — planning（规划） | 0.69 |
| **任务完成度**（4 个子维度） | **0.54** |
| — accuracy（准确性） | 0.61 |
| — requirement_coverage（需求覆盖） | 0.52 |
| 任务成功率 | 9/9 |

轨迹分衡量 agent 驱动工具的过程质量，完成分衡量 agent 最终回答对照任务要求的达成度。对同一轨迹重复打分会漂移 ±0.02–0.08（其中一次评分遭遇 judge 解析失败，把健康轨迹记为 0.0），±0.05 以内应视为评测噪音。论文载荷现已全链路携带作者与 arXiv ID（持久化 + 全量回填 + 所有论文工具透出），judge 评语不再报告归因数据缺失——剩余完成分差距来自 agent 模型的答案组织（对可用归因信息引用不一致），而非工具能力。

复现：

```bash
python3 scripts/benchmark_mcp_latency.py --url http://localhost:8000/api/mcp --trials 3
python3 scripts/benchmark_agent_tool_latency.py  # 需要 claude CLI
python3 scripts/eval_mcp_tool_selection.py       # 需要 claude CLI
```

### 结构化 JSON 响应

WebSearch 给你链接，AIGC Radar 给你可直接消费的数据。`search_github_ai_projects` 单条记录节选：

```json
{
  "full_name": "rag-web-ui/rag-web-ui",
  "url": "https://github.com/rag-web-ui/rag-web-ui",
  "description_zh": "基于 RAG 的智能对话 Web UI，适合搭建私有知识库问答与文档检索助手。",
  "category_name_zh": "RAG / 知识库",
  "subcategory_name_zh": "文档问答",
  "tags_zh": ["文档问答", "检索增强生成", "知识库", "Web 界面"],
  "tags_en": ["Document Q&A", "RAG", "Knowledge base", "Web UI"],
  "language": "TypeScript",
  "stars": 3257,
  "daily_star_growth": 1,
  "hot_score": 2.5899,
  "pushed_at": "2026-04-06T14:22:58Z",
  "detail_url": "https://aigcnews.cn/projects?q=rag-web-ui%2Frag-web-ui&utm_source=mcp&utm_medium=tool"
}
```

- 中英双语字段：`description_zh` / `tags_zh` / `tags_en` 与双语分类体系，同一索引同时服务中英文检索。
- 质量信号随响应直达：`stars` / `forks` / `daily_star_growth` / `hot_score` / `pushed_at`，无需再调 GitHub API。
- 准入与溯源透明：500 Stars 准入（`min_stars`）、`result_origin` / `fallback_used` 标明结果来源、`attribution` 与 `detail_url` 可回链详情页。

### 高质量精选索引

项目库中的每个 GitHub 项目都通过了 **500 Stars 准入门槛**（`min_stars`）才会进入精选环节——玩具项目、停更 fork、低信号仓库从未入库，搜索结果天然高质量，Agent 无需再做二次过滤。WebSearch 没有这道闸门：它按公开网页排名返回，可能混入无人维护或琐碎的仓库，质量判断全部留给使用者。

- 全链路强制：500 Stars 下限同时作用于入库采集与限量只读 GitHub fallback，低于门槛的结果在到达 Agent 之前就被排除。
- 精选而非简单爬取：入库项目附带分类体系、中英双语标签与星标增长快照，排序信号保持新鲜。

## 架构

```text
数据源（arXiv/HF · GitHub · Techmeme · Product Hunt · HN · X · 微信公众号）
  → 抓取与标准化 → 富化（README / PDF 补全、AI 评分、打标、中文描述）
  → PostgreSQL 主写 → 排行快照
  → Milvus 向量索引 · Neo4j 论文图谱 → 缓存失效
  → Dashboard · 项目检索 · 简报 · MCP
```

| 层 | 技术 |
| --- | --- |
| 前端 | Vue 3 + TypeScript + Vite + Pinia + Tailwind CSS + Vue I18n（zh-CN / en-US），新粗野主义设计 |
| 后端 | FastAPI 单体，分层：传输层（REST / SSE / MCP）→ 应用服务 → Repository Protocol → 基础设施适配器 |
| 关系型 | PostgreSQL 16（唯一关系型运行时） |
| 向量 / 图 | Milvus（+ MinIO / etcd）、Neo4j 论文实体图谱 |
| 缓存 | Redis（API 缓存、邮箱验证码、防刷、访客去重） |
| 运维 | 进程内调度器（Asia/Shanghai）、单机 Docker Compose、restart policy + systemd 恢复 |

后端另内置完整混合 RAG 对话链路（PostgreSQL + Milvus + Neo4j 召回、精排、流式输出、多会话、图片 / PDF 附件）；其 Web 入口目前暂停开放维护中。

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

## 文档索引

- [docs/project-overview.md](docs/project-overview.md) —— 项目全景：产品、架构、数据、部署与工程状态
- [docs/architecture.md](docs/architecture.md) —— 功能架构当前态（PostgreSQL 16 为唯一关系型运行时）
- [docs/mcp-server.md](docs/mcp-server.md) —— AIGC Radar MCP 协议参数与策略
- [docs/README.md](docs/README.md) —— 全部文档索引（含历史归档标注）

## 数据归属与合规

- **聚合内容不归本项目所有。** 管线呈现的论文、仓库元数据、新闻、Product Hunt / Hacker News 条目、X 推文与微信公众号文章，其权利归原作者与平台所有。AIGCNEWS 仅为运行阅读界面存储元数据、摘要与缩略图，不主张任何所有权。参考部署的数据库转储、采集快照与媒体缓存不属于本仓库，亦不许可再分发。
- **抓取链路只发布接口。** X（Twitter）与微信采集实现**不包含在本仓库内**——它们经 `x_source_enabled` / `wechat_source_enabled` 特性开关从私有插件包可选加载（见 `backend/app/services/source_plugins/`）。插件缺席时对应路由返回 404、采集轮自动跳过，其余功能不受影响。
- **自建实例的运营者责任**：启用此类插件须自行遵守源平台服务条款、robots 协议与适用法律，并妥善保管配置的凭据（cookie/token）。
- **商标。** X、Twitter、WeChat、Product Hunt、Hacker News、arXiv、GitHub、Hugging Face 等名称与标志归各自所有者；本项目仅为指称性使用，不存在隶属或背书关系。
- **内容移除请求**：请提 issue 或联系维护者。完整归属声明见 [NOTICE](NOTICE)。

## License

[Business Source License 1.1](LICENSE) © 2026 Kaixxrua —— 非生产使用与内部非商业使用免费；商业使用与公网部署需获得作者事先书面授权；每个版本首次公开发行满四年后自动转为 Apache-2.0。
