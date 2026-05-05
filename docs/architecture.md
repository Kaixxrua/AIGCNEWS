# AIGC_NEWS 项目功能架构

> 最后更新：2026-03-19（联网搜索后端重构：弃用三方搜索源（Tavily/Brave/DuckDuckGo），改为使用 Kimi 内置 $web_search builtin_function，通过两轮 tool_calls 循环实现联网搜索，无需额外 API Key）

---

## 一、项目总览

### 1.1 项目定位

**AIGC_NEWS** 是一个 **AIGC（AI 生成内容）技术资讯聚合与智能问答平台**，集成了五大数据源的自动化采集、RAG（检索增强生成）智能问答、每日简报自动生成、论文阅读等功能。面向 AI 技术从业者、研究人员和产品经理，提供一站式的 AI 领域资讯追踪与深度分析服务。

### 1.2 技术栈

| 层次 | 技术选型 |
|------|---------|
| **后端框架** | FastAPI (Python) + Uvicorn |
| **前端框架** | Vue 3 + TypeScript + Vite + Pinia + TailwindCSS |
| **LLM 引擎** | OpenAI / Anthropic / Ollama（通过 LangChain 抽象） |
| **向量数据库** | Milvus 2.4（HNSW 索引 + COSINE 度量） |
| **图数据库** | Neo4j 5.18（知识图谱） |
| **关系数据库** | MySQL 8.0（主存储） + SQLite（遗留备用） |
| **缓存** | Redis 7（API 缓存 + Email OTP 验证码 + 防刷） |
| **对象存储** | MinIO（Milvus 依赖） |
| **定时调度** | APScheduler（AsyncIOScheduler） |
| **Embedding** | OpenAI / HuggingFace / Ollama（可切换） |
| **Reranker** | Pro/BAAI/bge-reranker-v2-m3（硅基流动 /v1/rerank API，远程精排） |
| **容器化** | Docker Compose（9 个服务） |
| **反向代理** | Nginx（前端 SPA） |

### 1.3 整体架构

```
┌─────────────────────── 前端 (Vue3 + Vite) ───────────────────────┐
│  Dashboard 仪表盘 │ RAG 智能问答 │ 简报中心 │ 运维监控 │ 论文阅读器 │
└──────────────────────────────┬────────────────────────────────────┘
                               │ HTTP / SSE
┌──────────────────────────────▼────────────────────────────────────┐
│                      后端 (FastAPI)                                │
│  ┌─────────┐ ┌──────────┐ ┌───────────┐ ┌────────┐ ┌──────────┐ │
│  │ API 路由 │ │ RAG 服务 │ │ 简报生成   │ │ 评分   │ │ 认证鉴权 │ │
│  └─────────┘ └──────────┘ └───────────┘ └────────┘ └──────────┘ │
│  ┌───────────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ 数据采集 Pipeline  │  │ 定时调度器    │  │ 监控与评估       │   │
│  └───────────────────┘  └──────────────┘  └──────────────────┘   │
└──────────────────────────────┬────────────────────────────────────┘
                               │
┌──────────────────────────────▼────────────────────────────────────┐
│                        数据存储层                                  │
│  ┌────────┐  ┌──────────┐  ┌───────┐  ┌───────┐  ┌───────────┐  │
│  │ MySQL  │  │ Milvus   │  │ Neo4j │  │ Redis │  │ PDF 存储  │  │
│  │ 8.0    │  │ 2.4      │  │ 5.18  │  │ 7     │  │ (本地)    │  │
│  └────────┘  └──────────┘  └───────┘  └───────┘  └───────────┘  │
└──────────────────────────────────────────────────────────────────-┘
                               │
┌──────────────────────────────▼────────────────────────────────────┐
│                       五大数据源                                   │
│  HuggingFace Papers │ GitHub Trending │ Techmeme RSS              │
│  Product Hunt       │ Hacker News                                 │
└───────────────────────────────────────────────────────────────────┘
```

---

## 二、后端 API 层

所有路由在 `backend/app/main.py` 中挂载，统一前缀 `/api`。

### 2.1 认证路由 — `routes_auth.py`

| 方法 | 端点 | 鉴权 | 功能 |
|------|------|------|------|
| POST | `/api/auth/send-email-otp` | 无 | 发送邮箱验证码（60s 防刷） |
| POST | `/api/auth/register` | 无 | 用户注册（邮箱 + 验证码 + 邀请码 + 密码） |
| POST | `/api/auth/login` | 无 | 用户登录（邮箱 + 密码），返回 JWT |
| GET | `/api/auth/me` | RequireUser | 获取当前用户信息 |

### 2.2 聊天路由 — `routes_chat.py`

| 方法 | 端点 | 鉴权 | 功能 |
|------|------|------|------|
| POST | `/api/chat/stream` | RequireUser | RAG 流式问答（SSE）+ 会话持久化落盘 |
| POST | `/api/chat/conversations/ensure` | RequireUser | 按 `scope/scope_key` 获取或创建会话 |
| POST | `/api/chat/conversations/create` | RequireUser | 强制创建新会话（不复用已有会话） |
| GET | `/api/chat/conversations` | RequireUser | 分页获取当前用户会话列表 |
| GET | `/api/chat/conversations/{conversation_id}` | RequireUser | 获取指定会话详情与历史消息 |
| DELETE | `/api/chat/conversations/{conversation_id}` | RequireUser | 删除指定会话及其所有消息 |
| DELETE | `/api/chat/messages/{message_id}` | RequireUser | 删除指定消息及其后续分支 |
| POST | `/api/chat/messages/{message_id}/regenerate` | RequireUser | 裁剪消息树后重新生成回复 |

请求体：`{message, history[], temperature?, conversation_id?, attachment_ids?, paper_id?, scope?, web_search?}`
SSE 事件流：`status → sources → thinking → content → conversation → [DONE]`

- **普通用户每日消息限额**：`/chat/stream` 和 `/chat/messages/{id}/regenerate` 在流式开始前检查当日已发送消息数（`count_user_messages_today()`），超过 `USER_DAILY_MESSAGE_LIMIT`（默认 20 条）时返回 HTTP 429，`detail` 包含 `error: "message_limit_exceeded"` + 友好提示。admin 用户不受限。

- **真流式架构**：`_stream_persisted_chat` 直接遍历 `stream_chat()` 的 AsyncGenerator，每收到一个 payload 立即 `yield` 给前端（边收边发），消除原有"先收完再发"的 60s 阻塞。持久化（MySQL 落盘）改为 SSE 流结束后才执行。
- `web_search=true` 时，后端并发执行 RAG 检索 + 联网搜索，搜索结果作为额外上下文注入 Prompt，搜索结果来源以 `source="web"` 包含在 sources 事件中

### 2.3 视觉问答路由 — `routes_vision.py`

| 方法 | 端点 | 鉴权 | 功能 |
|------|------|------|------|
| POST | `/api/chat/upload-screenshot` | RequireUser | 上传截图 base64 到内存缓存（TTL 5min） |
| POST | `/api/chat/vision-relay` | RequireUser | 流式视觉问答（SiliconFlow Kimi-K2.5） |

Zero-Disk 设计：图片 base64 只存内存，绝不写盘。

### 2.4 论文路由 — `routes_papers.py`

| 方法 | 端点 | 鉴权 | 功能 |
|------|------|------|------|
| GET | `/api/papers/search?q=&limit=` | 无 | 全文搜索（title + summary 模糊匹配） |
| GET | `/api/papers/top10-today` | 无 | 今日高分 ArXiv 论文 Top10（冷启动推荐） |
| GET | `/api/papers/{paper_id}` | 无 | 论文详情（含 pdf_media_url） |
| GET | `/api/papers/{paper_id}/pdf` | 无 | ArXiv PDF 代理（解决 CORS） |

### 2.5 仪表盘路由 — `routes_dashboard.py`

| 方法 | 端点 | 鉴权 | 功能 |
|------|------|------|------|
| GET | `/api/dashboard/top` | 无 | 热门文档排行（支持 source/period/date 过滤） |
| GET | `/api/dashboard/radar` | 无 | 趋势雷达图数据（5 大类目：大模型/智能体/多模态/数据评测/系统部署） |
| GET | `/api/dashboard/summary` | 无 | 综合仪表盘（Top10 + 雷达 + 统计卡片 + 来源分布） |
| GET | `/api/dashboard/visitor-count` | 无 | 今日独立访客数（**不缓存**，实时读取 Redis SCARD） |
| GET | `/api/dashboard/snapshot-dates` | 无 | 有快照数据的日期列表（日历组件用） |
| GET | `/api/dashboard/github-hot` | 无 | GitHub 热度排行（增长 + 基线 + 年龄修正） |

所有 Dashboard 端点均使用 Redis 缓存（TTL 1h），支持定榜/静默期机制（15:00 CST 定榜）。

**`/api/dashboard/summary` 统计卡片**：`stats` 字段包含以下真实数据：
- `registered_users`：调用 `db.get_user_count()` 返回注册用户总数（查 users 表）
- `today_new_documents`：调用 `db.get_today_document_count()` 返回 CST 今日新增文档数
- `today_unique_visitors`：调用 Redis `SCARD visitor:{YYYY-MM-DD}` 返回今日独立访客 IP 数

**今日独立访客统计机制**（`VisitorTrackingMiddleware`）：
- 在 `backend/app/main.py` 注册 `VisitorTrackingMiddleware`（Starlette BaseHTTPMiddleware）
- 每次 HTTP 请求（排除 `/api/media/` 静态文件）提取来源 IP（优先读 `X-Forwarded-For`）
- 将 IP 写入 Redis SET，Key 格式：`visitor:{YYYY-MM-DD}`（CST 时区），TTL 48 小时
- Redis SET 天然去重，`SCARD` 即为今日独立访客数，O(1) 性能无副作用

### 2.6 简报路由 — `routes_report.py`

| 方法 | 端点 | 鉴权 | 功能 |
|------|------|------|------|
| POST | `/api/report/daily/stream` | RequireAdmin | 流式生成简报（SSE） |
| GET | `/api/report/latest` | 无 | 获取指定类型/周期的简报缓存 |
| GET | `/api/report/history` | 无 | 简报历史列表 |
| GET | `/api/report/{briefing_id}` | 无 | 简报详情 |
| POST | `/api/report/subscribe` | RequireUser | 订阅简报邮件推送 |
| POST | `/api/report/unsubscribe` | RequireUser | 取消简报邮件订阅 |
| GET | `/api/report/subscriptions` | RequireUser | 获取当前用户的活跃订阅列表 |
| POST | `/api/report/send-to-email` | RequireUser | 将当前简报一次性发送到用户邮箱 |
| GET | `/api/report/eval/summary` | 无 | RAG 评估统计汇总 |
| GET | `/api/report/eval/list` | 无 | RAG 评估记录列表 |

### 2.7 运维路由 — `routes_ops.py`

| 方法 | 端点 | 鉴权 | 功能 |
|------|------|------|------|
| POST | `/api/ops/ingest` | RequireAdmin | 触发数据采集（智能/强制模式） |
| POST | `/api/ops/ingest-by-date` | RequireAdmin | 按指定日期采集 |
| POST | `/api/ops/ingest-source` | RequireAdmin | 按数据源独立采集 |
| GET | `/api/ops/ingest-source/list` | RequireAdmin | 可用数据源列表 |
| POST | `/api/ops/clear-data` | RequireAdmin | 清空所有数据（不可逆） |
| POST | `/api/ops/github-hot/refresh` | RequireAdmin | 刷新 GitHub 热榜 |
| GET | `/api/ops/scheduler/status` | RequireAdmin | 调度器状态查询 |
| POST | `/api/ops/scheduler/trigger` | RequireAdmin | 手动触发定时任务 |
| POST | `/api/ops/briefing/generate-all` | RequireAdmin | 全维度简报批量生成 |
| POST | `/api/ops/cache/clear-dashboard` | RequireAdmin | 清除 Dashboard 缓存 |

### 2.8 监控路由 — `routes_monitor.py`

| 方法 | 端点 | 鉴权 | 功能 |
|------|------|------|------|
| GET | `/api/monitor/health` | RequireUser | 全服务健康检查 |
| GET | `/api/monitor/metrics` | RequireUser | 运行时指标收集 |
| GET | `/api/monitor/tasks` | RequireAdmin | 分页采集任务记录 |

### 2.9 静态文件

| 路径 | 功能 |
|------|------|
| `/api/media/papers/{filename}.pdf` | PDF 文件静态服务（挂载 `storage/papers` 目录） |

---

## 三、核心服务层

### 3.1 RAG 服务 — `backend/app/services/rag/`

#### `chat_service.py`
- **核心类**: `ChatService`
- **功能**: RAG 流式问答服务（支持 Tool Use / Function Calling + 联网搜索 + 思维链）
- **架构**: 两轮 LLM 调用——第一轮非流式（带 tools 让 LLM 判断是否需要查数据库）+ 第二轮流式（根据工具结果 + RAG 上下文生成最终回答）
- **Tool Use 工具**:
  - `query_ranking`: 查询排行榜数据（支持 source/period/limit 参数），从 `documents` 表按 CST 日期过滤
  - `query_knowledge_stats`: 查询知识库统计和文档列表（支持 source/limit 参数），调用 `get_source_counts()` 获取各来源总量
- **流程**: 并发执行 RAG 检索 + LLM 工具判断 + 可选联网搜索 → 如有 tool_calls 则执行工具 → 智能精排 → 构建上下文（工具结果 + RAG + 联网搜索） → LLM 流式生成
- **LLM 调用**: 绕过 LangChain，使用 `raw_openai_streamer.py` 中的 `chat_completions()`（非流式，带 tools）和 `stream_chat_completions()`（流式）
- **推理模型配置**: 通过 `THINKING_MODEL_NAME` 环境变量指定支持思维链的模型，留空则复用 `CHAT_MODEL_NAME`
- **思维链格式**: Cherry Studio 风格流式增量推送，前端累积显示
- **多轮对话**: 保留最近 5 轮历史（可配置）
- **上下文模板**: 包含 `[arxiv]`、`[github]`、`[news]`、`[producthunt]`、`[hackernews]`、`[neo4j]`、`[web-N]`、`[db-query]` 八类来源标注
- **联网搜索集成**: `web_search_enabled=True` 时与 RAG 检索并发执行，结果追加到上下文末尾
- **GitHub 结构化字段（Bug1 修复）**: `_build_context()` 对 `source=github` 的文档额外追加 `[GitHub 数据] Stars: {n} | Forks: {n} | Language: {lang} | URL: {url}` 行

#### `raw_openai_streamer.py`
- **功能**: 直接调用 OpenAI 兼容 API 的流式 / 非流式客户端
- **两个入口函数**:
  - `stream_chat_completions()`: 流式 SSE 调用，逐事件 yield `StreamDelta(reasoning, content)`
  - `chat_completions()`: **非流式调用，支持 `tools` 参数**，返回 `ChatCompletionResult(content, reasoning, tool_calls, finish_reason)`，用于 Tool Use 第一轮判断
- **数据类**: `StreamDelta`（流式增量）、`ToolCallResult`（单个工具调用：id/name/arguments）、`ChatCompletionResult`（非流式返回）
- **背景**: LangChain `ChatOpenAI` 丢弃 `reasoning_content` 扩展字段
- **配置**: 复用 `settings.openai_api_key`、`settings.openai_base_url`
- **超时**: 流式 180s + 非流式 60s

#### `web_search_service.py`
- **功能**: 联网搜索统一入口，使用 Kimi 内置 `$web_search` builtin_function 实现联网搜索
- **实现**: 两轮 tool_calls 循环——Round 1 发送带 `$web_search` 工具声明的请求，收到 `finish_reason=tool_calls` 后，将 `arguments` 原封不动提交给 Kimi（role=tool 消息）；Round 2 Kimi 执行搜索并返回结果文本
- **配置项**: 复用 `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `CHAT_MODEL_NAME`，无需额外配置
- **结果解析**: `_parse_kimi_search_response()` 从 Kimi 返回的 Markdown 文本中提取结构化链接和摘要
- **返回格式**: `List[WebSearchResult]`（title/url/snippet/content），统一转换为 `source="web"` 的来源格式
- **异常策略**: 任何后端失败自动切换，全部失败时返回空列表，不中断主流程

#### `retriever.py`
- **核心类**: `HybridRetriever`
- **混合检索策略**:
  1. **Milvus 向量检索**: 按 query embedding 相似度搜索，HNSW 索引
  2. **Neo4j 图检索**: 按关键词匹配知识图谱实体和关系
  3. **MySQL Fallback**: 当 Milvus 不可用时，关键词匹配 MySQL 文档
  4. **Source Fallback**: 每个来源（arxiv/news/github）额外取 3-5 条保证覆盖
- **去重合并**: Round-Robin 均衡各来源文档，ID/URL/标题去重
- **关键词提取**: 简单 token 化 + 停用词过滤

#### `reranker.py`
- **模型**: Pro/BAAI/bge-reranker-v2-m3（调用硅基流动 `POST https://api.siliconflow.cn/v1/rerank`）
- **策略**: 仅对 vector/hybrid 来源文档调用 API 精排，fallback 文档直接透传
- **智能跳过**: `stream_chat` 中检查 vector 文档的 Milvus COSINE 距离分数，若最佳分数 > 0.6（全部不太相关），直接跳过 reranker API 调用，节省 2-5 秒网络延迟
- **阈值**: `RELEVANCE_THRESHOLD = 0.7`（relevance_score，0-1 范围；从 0.5 提高到 0.7 以减少不相关参考来源数量）
- **最大文档数**: 一次精排最多 5 篇
- **分数转换**: relevance_score × 10 → 0-10 显示分
- **配置项**: `SILICONFLOW_API_KEY`、`RERANKER_MODEL_NAME`（均在 `.env` 中配置）
- **无本地模型**：不再依赖 sentence-transformers / 本地 GPU，冷启动即用

#### `generator.py` / `citation_mapper.py`
- 均为 `# TODO: placeholder`，功能已内联到 `chat_service.py`

### 3.2 简报生成服务 — `backend/app/services/briefing/`

#### `daily_briefing.py`
- **核心类**: `DailyBriefingService`
- **功能**: 生成并持久化日/周/月简报
- **6 种简报模板**: all（综合）、arxiv（学术）、github（工程）、news（行业）、producthunt（产品）、hackernews（社区）
- **3 种周期**: daily / weekly / monthly
- **数据来源优先级**: 快照表 → documents 表 + channel 过滤 → 最新文档兜底
- **截断续写**: 检测 LLM 输出是否被截断，最多自动续写 5 轮
- **缓存策略**: 按 `{date}_{source}_{period}` 作为 key 持久化到 MySQL briefings 表
- **SSE 流式输出**: `start → content(多次) → done`
- **Tag 标签（Bug3 修复 + 优化）**: 所有 6 个 Prompt 模板均已升级为细粒度领域标签系统——每个一级/二级标题后必须附加 `\`#来源\` \`#领域\``，来源标签（必选1个，如 `#arxiv` `#github`）+ 领域标签（必选1-2个，如 `#LLM` `#Agent` `#RAG` `#推理优化` `#模型压缩` 等），每个源类型有独立的领域标签候选列表，**禁止使用过于宽泛的 #ai #tool #trending**

#### `podcast_adapter.py`
- `# TODO: placeholder`（播客适配器，待实现）

### 3.3 数据采集服务 — `backend/app/services/ingestion/`

#### `pipeline.py`（核心编排器）
- **核心类**: `IngestionOrchestrator`
- **架构**: 5 个独立爬虫 → 内容丰富 → 三库写入（MySQL + Milvus + Neo4j）
- **入口函数**:
  - `run_ingestion_pipeline()`: 全量采集
  - `run_single_source_pipeline()`: 单源采集
  - `run_smart_ingestion()`: 智能补录
- **关键流程**:
  1. 爬虫采集（fetch_all_periods）
  2. 已有 summary 短路复用（避免重复 LLM 调用）
  3. 内容丰富（enrich_papers）
  4. Top-N 筛选（按 raw_score 排序）
  5. 三库写入（MySQL upsert + Milvus 向量索引 + Neo4j 图谱抽取）
  6. 排行快照写入（document_rank_snapshots 表）
  7. 后台 PDF 补全（ArXiv 论文异步下载 + 解析）
  8. Dashboard 缓存清理

#### `base_crawler.py`（爬虫基类）
- **抽象基类**: `BaseCrawler`
- **标准化结果**: `CrawlResult`（source、channel、snapshot_date、period、items、error）
- **异常安全**: 任何异常都被捕获，返回 error CrawlResult，不影响其他源
- **并发调度**: `fetch_all_periods()` 使用 `asyncio.gather()` 并发采集所有周期

#### 爬虫实现（`crawlers/`）

| 爬虫文件 | 数据源 | 周期 | Channel |
|---------|--------|------|---------|
| `arxiv_crawler.py` | HuggingFace Papers | daily/weekly/monthly | `huggingface_{period}_html` |
| `github_crawler.py` | GitHub Trending | daily/weekly/monthly | `github_trending_{period}` |
| `news_crawler.py` | Techmeme RSS + HTML | daily only | `techmeme_daily_rss` |
| `producthunt_crawler.py` | Product Hunt Apollo SSR | daily only | `producthunt_daily_html` |
| `hackernews_crawler.py` | HN Firebase API Top-30 | daily only | `hn_daily_html` |

#### 底层数据获取库（`source_*.py`）

| 文件 | 功能 |
|------|------|
| `source_arxiv_mcp.py` | 爬取 HuggingFace Papers 页面获取 ArXiv 论文列表 |
| `source_github_trending.py` | 爬取 github.com/trending 页面 |
| `source_github.py` | GitHub API 获取仓库信息 |
| `source_github_mcp.py` | GitHub MCP 协议接口 |
| `source_news.py` | Techmeme RSS + HTML 双通道采集 |
| `source_producthunt.py` | Product Hunt 主页 Apollo SSR Transport 解析 |
| `source_hackernews.py` | Hacker News Firebase API |
| `source_huggingface.py` | HuggingFace API（已禁用） |

#### `content_enricher.py`（内容丰富器）
- **ArXiv**: 两阶段策略 — 先用摘要快速入库，后台异步下载 PDF 补全全文
- **GitHub**: 抓取仓库 README（GitHub API base64 解码）
- **News**: httpx 抓详情页 → BeautifulSoup 提取正文
- **HackerNews**: httpx 抓外链详情页 → BS4 提取正文
- **ProductHunt**: 保持 tagline + description（已足够）

#### `arxiv_pdf_downloader.py`（PDF 下载器）
- ArXiv XML API 批量拉取元数据
- 低频慢速 PDF 落盘（每次 sleep 3-5s 防封杀）
- PyMuPDF (fitz) 解析 PDF 全文
- RecursiveCharacterTextSplitter 切片写入 Milvus
- 更新 MySQL `documents.local_pdf_path` 字段

#### `graph_extractor.py`（图谱抽取器）
- 使用 LangChain `LLMGraphTransformer` 从论文中提取实体和关系
- 允许的节点类型：`Paper`、`Author`、`Concept`
- 仅对 ArXiv 源执行图谱抽取

#### `github_hot_service.py`（GitHub 热度服务）
- 维护 GitHub 候选池（`github_repo_candidates` 表）
- 周期性快照（`github_repo_snapshots` 表）
- 基于增长 + 基线 + 年龄修正的热度排名算法

### 3.4 评分服务 — `backend/app/services/scoring/`

#### `value_scorer.py`
- LLM 价值评分器（创新性 1-10 + 实用性 1-10）
- 带 429 指数退避重试
- 用于 pipeline 入库前过滤低质量论文

#### `llm_scorer.py`
- LLM 异步批量评分器
- Semaphore 并发控制（默认 1 并发）
- 对 Document 列表打分（技术创新性 + 社区影响力，0-10 分）

### 3.5 评估服务 — `backend/app/services/evaluation/`

#### `rag_metrics.py`
- **recall_score**: 基于 Jaccard 的 token 级别召回率
- **citation_score**: 答案中引用来源的覆盖率
- **subjective_score**: 主观评分（占位，默认 0）
- 评估结果持久化到 MySQL `rag_evaluations` 表

### 3.6 邮件服务 — `email_service.py`

- **OTP 验证码**: Redis 存储邮箱 OTP 验证码（TTL 5min）+ 防刷锁（TTL 60s）
- **简报邮件推送**: `send_briefing()` 方法将 Markdown 简报内容转换为精美 HTML 邮件，支持标题/粗体/链接/列表/引用的 Markdown→HTML 转换
- Dev 模式（`SMTP_HOST` 为空）：OTP 和简报邮件均打印到控制台日志，不发送真实邮件
- 生产模式：通过 `aiosmtplib` 异步发送 SMTP 邮件（支持 STARTTLS / SSL）
- `_send_email()` 发送纯文本邮件（OTP），`_send_html_email()` 发送 HTML 邮件（简报推送）
- Key 前缀：`email:code:{email}` / `email:lock:{email}`
- 保留 `sms_service.py`：兼容旧代码引用，但新注册流程不再使用

### 3.7 会话服务 — `backend/app/services/chat/`

#### `conversation_service.py`
- **核心类**: `ConversationService`
- **功能**: 服务端会话创建、消息落盘、消息树裁剪、LRU 清理
- **作用域模型**: `scope=global|paper`，论文阅读通过 `scope_key=paper_id` 绑定专属会话
- **持久化策略**: 在 `/api/chat/stream` 完成后同时写入 `user` 与 `assistant` 两条消息，并刷新会话统计
- **裁剪策略**:
  - 每用户最多保留 10 个会话
  - 每会话最多保留 10 条消息
  - `regenerate` 时删除目标消息之后的派生消息，再用同一会话重新生成
- **清理策略**: 暴露 `cleanup_stale_conversations()` 供调度器每 7 天批量清理 5 条过期会话

### 3.8 索引服务 — `backend/app/services/indexing/`

- `chunker.py`、`embedder.py`、`vector_store.py` 均为 `# TODO: placeholder`
- 实际切片/嵌入/向量存储功能分散在 `milvus_repo.py` 和 `arxiv_pdf_downloader.py` 中

---

## 四、数据存储层

### 4.1 MySQL 8.0 — `mysql_repo.py`

**核心类**: `MySQLRepository`（连接池：PooledDB，最大 20 连接）

**数据库表结构**:

| 表名 | 功能 | 关键字段 |
|------|------|---------|
| `documents` | 文档元数据主表 | id(md5), source, source_channel, title, url, summary, score, raw_score, rank_in_period, in_daily/weekly/monthly, local_pdf_path |
| `document_rank_snapshots` | 每日排行快照（历史记录） | doc_id, snapshot_date, source_channel, rank_in_period, raw_score |
| `ingestion_tasks` | 采集任务记录 | task_name, status, started_at, finished_at, item_count |
| `briefings` | 简报缓存 | date(含 source+period 后缀), content |
| `briefing_subscriptions` | 简报邮件订阅 | user_id, email, source, period, is_active, UNIQUE(user_id,source,period) |
| `rag_evaluations` | RAG 评估记录 | query, answer, sources_json, recall_score, citation_score |
| `users` | 用户表 | id, phone(可空/兼容旧数据), email(UNIQUE), email_verified, invite_code_used, username, hashed_password, role(user/admin) |
| `conversations` | 会话主表 | user_id, scope, scope_key, title, last_message_preview, message_count, last_accessed_at, updated_at |
| `chat_messages` | 聊天消息表 | conversation_id, role, content, thinking, sources_json, attachments_json, parent_message_id |
| `chat_attachments` | 聊天附件表 | user_id, conversation_id, file_name, mime_type, modality, parse_status, meta_json |
| `github_repo_candidates` | GitHub 候选池 | repo_id, full_name, stars, forks, watchers |
| `github_repo_snapshots` | GitHub 快照 | repo_id, snapshot_date, stars, forks |
| `github_trending_hits` | GitHub Trending 命中记录 | repo_id, period, rank, observed_date |

**关键操作**:
- `upsert_document()`: ON DUPLICATE KEY UPDATE，GREATEST() 语义确保多周期 upsert 不丢失
- `upsert_rank_snapshot()`: 排行快照 UPSERT，跨 channel 分数同步
- `get_snapshot_documents()`: JOIN 快照表查询指定日期的文档排行
- `get_or_create_conversation()`: 按 `scope/scope_key` 获取或创建会话
- `create_chat_message()`: 写入聊天消息并自动序列化 `sources/attachments`
- `trim_conversation_messages()`: 每会话 LRU 保留最近 10 条消息
- `trim_user_conversations()`: 每用户 LRU 保留最近 10 个会话
- `cleanup_stale_conversations()`: 删除最近 7 天未访问队列中最旧的 5 条会话
- `get_user_count()`: 返回 users 表已注册用户总数（Bug2 新增）
- `get_today_document_count()`: 返回 CST 今日新增文档数（Bug2 新增，按 created_at 前 10 字符过滤）
- `count_user_messages_today()`: 统计指定用户今日（CST）发送的消息数（JOIN conversations + chat_messages，role='user'，CONVERT_TZ 转 CST），用于每日消息限额检查

### 4.2 Milvus 2.4 — `milvus_repo.py`

**核心类**: `MilvusRepository`

| 功能 | 说明 |
|------|------|
| `add_documents()` | GitHub 结构化字段增强 → 文档切片（800 字符/100 重叠）→ Embedding → 写入 Milvus |
| `_enrich_github_content()` | 对 `source=github` 文档在切片前追加 `Stars: n \| Forks: n \| Language: lang`（Bug1 修复） |
| `search()` | 向量相似度搜索（HNSW，ef ≥ k 且 ≥ 64） |
| `search_by_source()` | 按 source 字段过滤查询（保证每源有代表） |
| `drop_collection()` | 删除整个 Collection |

**配置**: Collection `aigc_docs`，维度 1024，HNSW 索引，COSINE 度量。

### 4.3 Neo4j 5.18 — `graph_repo.py`

**核心类**: `GraphRepository`

| 功能 | 说明 |
|------|------|
| `search()` | 按关键词匹配图谱节点及其邻居，返回 `Entity(name) -[REL]-> Entity(name)` 格式文档 |
| `add_graph_documents()` | 写入节点（Paper/Author/Concept）和关系（MERGE 幂等） |

### 4.4 SQLite — `sqlite_repo.py`

- 遗留备用存储，表结构与 MySQL 类似
- 当前项目已全面切换到 MySQL，SQLite 代码保留但不再是主路径

### 4.5 Redis 7

| 用途 | Key 前缀 | TTL |
|------|---------|-----|
| API 缓存 | `aigc-cache:` | 1 小时 |
| Email OTP 验证码 | `email:code:{email}` | 5 分钟 |
| Email OTP 防刷锁 | `email:lock:{email}` | 60 秒 |

---

## 五、认证鉴权

### `auth.py`

| 组件 | 说明 |
|------|------|
| **密码哈希** | bcrypt（直接使用 bcrypt 库，不依赖 passlib） |
| **JWT** | python-jose，HS256 算法，默认 7 天过期，payload 含 `user_id`、`role`、`email` |
| **依赖注入** | `RequireUser` — 需要有效 Bearer JWT |
| | `RequireAdmin` — 需要 role='admin' |

### 注册 / 登录流程（Phase 4 邮箱机制）

| 步骤 | 说明 |
|------|------|
| 发送验证码 | `POST /api/auth/send-email-otp { email }` → Redis OTP TTL 5min + 防刷锁 60s |
| 注册 | `POST /api/auth/register { email, email_code, invite_code, password }` → 校验邀请码 `internal_testing` → 校验 OTP → 写库 |
| 登录 | `POST /api/auth/login { email, password }` → 返回 JWT |
| 获取信息 | `GET /api/auth/me` → `{ user_id, email, role }` |

### 权限模型

```
游客 ──POST /auth/register──▶ 普通用户（需邀请码）
游客 ──POST /auth/login────▶ 普通用户

普通用户 (RequireUser):
  ├── RAG 问答 (/chat/stream)        ← 每日限 20 条消息（USER_DAILY_MESSAGE_LIMIT）
  ├── 视觉问答 (/chat/vision-relay)
  ├── 健康检查 (/monitor/health)
  ├── 论文阅读 (/papers/:id/read)
  ├── 简报订阅 (/report/subscribe, /report/unsubscribe)
  ├── 查看订阅 (/report/subscriptions)
  └── 发送简报到邮箱 (/report/send-to-email)

管理员 (RequireAdmin):
  ├── 运维操作 (/ops/*)
  ├── 监控面板 (/monitor/tasks)
  ├── 简报生成 (/report/daily/stream)
  └── RAG 问答不受每日消息限额限制
```

---

## 六、定时任务

### `scheduler.py`

| Job ID | 调度频率 | 功能 |
|--------|---------|------|
| `arxiv_papers` | 每小时 :01 | HuggingFace Papers 论文采集 |
| `github_trending` | 每小时 :02 | GitHub Trending 热榜采集 |
| `news_techmeme` | 每小时 :03 | Techmeme 科技新闻采集 |
| `producthunt` | 每小时 :04 | Product Hunt 新品采集 |
| `hackernews` | 每小时 :05 | Hacker News AI 热帖采集 |
| `github_hot_refresh` | 每天 02:00 | GitHub 热度快照刷新 |
| `daily_briefing` | 每天 08:00 | 全维度简报自动生成（6 个维度 × daily） |
| `conversation_cleanup` | 每 7 天 03:30 | 清理 5 条 7 天未访问的旧会话 |

**设计原则**:
- 五源各错开 1 分钟避免同时触发
- `max_instances=1` 防止同源 Job 重叠
- `misfire_grace_time=7200` 确保重启后追赶执行
- 会话历史由调度器与服务层触发式 LRU 双层清理协同完成

---

## 七、前端架构

### 7.1 技术栈

- **框架**: Vue 3 (Composition API) + TypeScript
- **路由**: Vue Router 5（History 模式）
- **状态管理**: Pinia 3
- **样式**: TailwindCSS 3 + Glassmorphism 2.0 科技主题（Cyan/Violet 双色调）
- **HTTP**: Axios（REST）+ Fetch API（SSE 流）
- **图表**: ECharts 6
- **PDF**: pdfjs-dist 5.5（含实时渲染进度追踪）
- **Markdown**: markdown-it + KaTeX（公式渲染）+ highlight.js（代码高亮）
- **3D 效果**: Three.js + Vanta.js
- **设计系统**: 科技感 Token（`tech.primary` Cyan / `tech.secondary` Violet / `tech.glow`），来源徽章分色（`source.arxiv` / `source.github` / `source.news` / `source.neo4j` / `source.milvus`）

### 7.2 路由结构 — `router/index.ts`

| 路径 | 组件 | 权限 | 功能 |
|------|------|------|------|
| `/login` | `LoginView` | guestOnly | 登录页 |
| `/register` | `RegisterView` | guestOnly | 注册页（含用户协议勾选，不默认勾选） |
| `/` | `DashboardView` | 无 | 仪表盘（统计卡片缩小至 h-44px，日历宽度210px） |
| `/chat` | `ChatView` | 无 | RAG 智能问答 |
| `/report` | `ReportView` | 无 | 简报中心 |
| `/monitor` | `MonitorView` | requiresAdmin | 运维监控 |
| `/papers/:id/read` | `PaperReadView` | requiresAuth | 论文阅读器 |
| `/disclaimer` | `DisclaimerView` | 无 | 用户协议与免责声明（五侧重：AI免责/用户行为/版权/服务变更/账号安全） |
| `/privacy` | `PrivacyView` | 无 | 隐私政策 |

**LayoutView 布局变更**：
- 右上角 Auth Island 浮岛已移除
- Dock 导航栏末尾新增登录/登出按钮（竖线分隔），样式区分：登录按钮绿色 (`dock-item--login`)，登出按钮红色 (`dock-item--logout`)
- Dock 下方背景层新增 `dock-footer` 小字（版权/免责/隐私/生态合作联系邮箱）

**路由守卫**: 全局 `beforeEach` 检查 `requiresAuth`、`requiresAdmin`、`guestOnly`。

### 7.3 状态管理

#### `authStore.ts`
- **状态**: token、user（AuthUser）、pendingChatMessage
- **AuthUser 接口**: `{ user_id: number, email: string, role: 'user'|'admin', email_verified?: boolean }`
- **操作**: `login(email, password)`、logout、fetchMe、initFromStorage
- **Getters**: isLoggedIn、isAdmin
- **持久化**: localStorage 存储 token

#### `chatStore.ts`
- **状态树**:
  - `activeConversationId` / `activeScope`
  - `conversationMap: Record<string, ConversationSummary>`
  - `messageMap: Record<string, ChatMessage[]>`
  - `pendingAttachments: ChatAttachmentRef[]`
  - `loadingHistory` / `isStreaming` / `streamPhase`
  - `settings(maxHistoryTurns, temperature)`
- **消息模型**: `ChatMessage` 统一包含 `conversationId`、`thinking`、`thinkingPreview`、`hasThinking`、`isStreaming`、`attachments`
- **会话能力**: `loadConversations()`、`openConversation()`、`ensureGlobalConversation()`、`createNewConversation()`（强制新建会话）、`deleteActiveConversation()`（删除当前会话并切换）、`ensurePaperConversation()`、`fetchPaperConversation()`（不影响 activeConversationId）、`loadPaperConversations(paperId)`（加载某论文的所有历史会话列表）
- **交互控制**: `abortGeneration()`、`regenerateMessage()`、`deleteMessage()`
- **打字机效果**: 逐字符队列 + 16ms 定时器（content 3字符/帧 ≈ 180字/秒，thinking 12字符/帧 ≈ 720字/秒）
- **服务端同步**: SSE 完成后根据 `conversation` 事件与会话详情接口回填最终持久化结果

### 7.4 关键 Composable

#### `useEventSource.ts`
- 基于 Fetch API 的 SSE 客户端
- 自动附加 Bearer Token
- 支持 `\n\n` 和 `\r\n\r\n` 两种 SSE 分隔符
- 将 `[DONE]` 规范化为 `{ type: 'done' }` 事件，并在连接完成时触发 `onDone`
- 兼容 JSON 事件与纯文本 content 片段，供 [`chatStore.ts`](frontend/src/stores/chatStore.ts) 与 [`PaperReadView.vue`](frontend/src/views/PaperReadView.vue) 复用

### 7.5 页面与组件协作

#### `ChatView.vue`
- 通用 RAG 对话页，消费 [`chatStore.ts`](frontend/src/stores/chatStore.ts) 的 `messages` getter 与消息控制能力
- **多会话初始化（Bug4 修复）**：`onMounted` 现在在登录状态下自动调用 `store.loadConversations('global')` + `store.ensureGlobalConversation()`，解决首次进入页面时无会话导致消息被吞的问题
- **历史会话侧边栏（Bug4 修复）**：新增左侧会话列表面板（宽 220px），展示所有 `scope=global` 的会话，支持点击切换、新建对话、折叠/展开，活跃会话高亮显示
- **新建会话（Bug8 修复）**：`+` 按钮调用 `createNewConversation()` 强制创建新会话（而非 `ensureGlobalConversation` 复用已有会话）
- **清空会话（Bug8 修复）**：清空按钮调用 `deleteActiveConversation()` 真正删除当前会话及消息（不再仅清空前端内存）
- **附件按钮**：改为回形针（Paperclip）SVG 矢量图标，上传中显示旋转动画
- **发送/停止按钮**：AI 生成时发送按钮变为圆角正方形停止图标（可中止生成），空闲时恢复为发送箭头图标
- **标题栏**：实时显示当前活跃会话标题（fallback 为 "RAG 智能助手"），移除了顶部终止按钮（停止功能已整合到发送按钮位置）

#### `PaperReadView.vue`
- **共用全局会话（Bug5 最终方案）**：`currentConversationId` 直接映射为 `chatStore.activeConversationId`，与 ChatView 完全共享同一会话状态
- 进入论文页时不再创建 `scope=paper` 专属会话；若无活跃会话则调用 `ensureGlobalConversation()`
- 发送消息透传 `paper_id` 供后端 RAG 检索论文内容，`scope` 字段由会话自身决定（非 paperId 硬编码）
- **历史会话面板**：左上角按钮展开全局会话列表（与 ChatView 一致），显示当前会话标题，支持切换和新建
- 切换会话调用 `chatStore.openConversation()`，完全同步 `activeConversationId`
- 页面消息区由 `chatStore.messageMap[currentConversationId]` 驱动，视觉问答消息仍以页面临时态补充展示
- 视觉问答请求已透传 `conversation_id` 与 `paper_id`，为后续多模态会话统一持久化预留接口

---

## 八、关键业务流

### 8.1 通用聊天流

1. 前端 [`chatStore.ts`](frontend/src/stores/chatStore.ts) 先通过 `/api/chat/conversations/ensure` 确保会话存在
2. 前端向 `/api/chat/stream` 发送 `message/history/conversation_id/scope/paper_id/attachment_ids`
3. 后端 [`routes_chat.py`](backend/app/api/routes_chat.py) 调用 RAG 流式生成，累计 `sources/thinking/content`
4. SSE 完成后由 [`conversation_service.py`](backend/app/services/chat/conversation_service.py) 一次性落盘用户消息与助手消息
5. 前端收到 `conversation` 事件后刷新会话详情，确保本地状态与数据库一致

### 8.2 Paper 阅读会话共享流（Bug5 重构后）

1. 用户进入 [`PaperReadView.vue`](frontend/src/views/PaperReadView.vue)
2. 页面**共用** ChatView 的全局会话（`scope=global`），不再创建独立的 `scope=paper` 专属会话
3. 若当前无活跃会话，则调用 `ensureGlobalConversation()` 确保存在一个全局会话
4. 发送消息时携带 `paper_id` 作为 RAG 上下文，`scope` 字段跟随当前会话本身的 scope
5. 左侧历史会话面板展示与 ChatView 相同的全局会话列表，支持切换和新建
6. 切换会话调用 `openConversation(convId)`，与 ChatView 的切换逻辑完全一致

### 8.3 会话清理流

1. 每次消息写入后，服务层调用会话级与用户级 LRU 裁剪
2. [`scheduler.py`](backend/app/core/scheduler.py) 每 7 天执行一次 `conversation_cleanup`
3. [`mysql_repo.py`](backend/app/repositories/mysql_repo.py) 删除 7 天未访问的最旧 5 条会话及其级联消息
4. 前端按需重新拉取列表，不依赖本地永久缓存

---

## 九、文件索引（核心实现）

| 路径 | 作用 |
|------|------|
| `backend/app/main.py` | FastAPI 应用入口，挂载全部路由并接入 lifespan / scheduler |
| `backend/app/api/routes_auth.py` | 认证路由：发送邮箱OTP、邮箱注册（含邀请码校验）、邮箱登录、获取用户信息 |
| `backend/app/api/routes_chat.py` | 聊天 SSE、会话列表/详情、删除、重生成功能 |
| `backend/app/api/routes_vision.py` | 视觉问答中转与截图上传 |
| `backend/app/api/routes_attachments.py` | 图片/PDF 附件上传与状态查询 |
| `backend/app/services/email_service.py` | 邮件OTP服务（aiosmtplib + Redis防刷 + dev模式日志降级） |
| `backend/app/services/chat/conversation_service.py` | 会话持久化、裁剪、重生成、清理 |
| `backend/app/services/chat/attachment_service.py` | 聊天附件元数据与 PDF 文本提取 |
| `backend/app/repositories/mysql_repo.py` | MySQL 表初始化、文档/任务/评估/会话/用户数据读写 |
| `backend/app/core/config.py` | 应用配置（含 SMTP_HOST/PORT/USERNAME/PASSWORD/FROM_EMAIL 等邮件配置项） |
| `backend/app/core/scheduler.py` | 定时采集、简报生成、会话清理调度 |
| `frontend/src/stores/authStore.ts` | 认证状态（AuthUser.email 为主标识）、login/logout/fetchMe |
| `frontend/src/views/LoginView.vue` | 登录页（邮箱 + 密码） |
| `frontend/src/views/RegisterView.vue` | 注册页（邮箱 + OTP验证码 + 邀请码 + 密码） |
| `frontend/src/stores/chatStore.ts` | 多会话状态树、流式消费、消息控制 |
| `frontend/src/views/ChatView.vue` | 通用聊天页 |
| `frontend/src/views/PaperReadView.vue` | 论文阅读器 + 论文专属会话 |
| `frontend/src/composables/useEventSource.ts` | 基于 Fetch 的 SSE 客户端 |
| `frontend/src/services/api.ts` | 前端 REST API 类型与请求封装 |
| `frontend/src/views/DisclaimerView.vue` | 免责声明页面（平台性质、版权、AI内容不构成专业建议声明） |
| `frontend/src/views/PrivacyView.vue` | 隐私政策页面（数据收集最小化、对话匿名化处理说明） |

---

## 十、当前已知限制

1. [`routes_vision.py`](backend/app/api/routes_vision.py) 当前仍以临时视觉消息流为主，尚未将视觉问答结果正式持久化进 `conversations/chat_messages`。
2. 索引服务目录中的 `chunker.py`、`embedder.py`、`vector_store.py` 仍为占位实现。

> **已解决（2026-03-17）**：
> - [`ChatView.vue`](frontend/src/views/ChatView.vue) 已新增历史会话侧边栏（Bug4），并在 `onMounted` 时自动初始化会话，消息被吞问题已修复。
> - GitHub stars/forks/language 字段现已写入 Milvus 向量内容并在 LLM 上下文中显示（Bug1）。
> - Dashboard summary 端点现返回真实注册用户数和今日新增文档数（Bug2）。
> - 所有简报 Prompt 已强制要求每个标题后追加来源 Tag 标签（Bug3）。
>
> **已解决（2026-03-18）**：
> - **Bug5（最终方案）**：彻底重构论文阅读会话架构。论文页不再使用 `scope=paper` 专属会话，改为与 ChatView **共用全局会话**（`scope=global`）。`currentConversationId` 直接映射 `chatStore.activeConversationId`，切换论文不再修改 active 状态。`_streamToAssistant` 的 `scope` 字段改为从 `conversationMap[conversationId].scope` 读取，而非依赖 paperId 硬编码。论文页历史会话面板展示全局会话列表，与 ChatView 完全一致，支持切换和新建。
> - **Bug6（RAG 不感知今日榜单）**：用户问"今天 github top10"等排行类问题时，RAG 仅通过向量检索无法获取排行信息。修复方案：在 [`chat_service.py`](backend/app/services/rag/chat_service.py) 中新增 `_detect_ranking_query()` 关键词检测（匹配"今天/今日"+"top/排行/榜单"等），命中时与 RAG 检索并发直接查询 `documents` 表（使用 CST 日期与 Dashboard 对齐，按 `LEFT(created_at, 10)` 过滤 + `source` 过滤 + `raw_score DESC` 排序），以 `[today-ranking]` 标签注入 LLM 上下文开头，并将排行文档作为参考来源推送给前端。新增 `_detect_ranking_period()` 支持日/周/月榜识别，`_detect_ranking_limit()` 支持动态 topN 提取（如 "top10"→10、"前20"→20）。
> - **Bug7（参考来源过多）**：[`reranker.py`](backend/app/services/rag/reranker.py) 的 `RELEVANCE_THRESHOLD` 从 0.5 提高到 0.7，过滤掉相关性不足的文档，减少不相关参考来源数量。
> - **简报订阅功能**：新增 `briefing_subscriptions` 表和 4 个 API（subscribe/unsubscribe/subscriptions/send-to-email），用户可一键订阅简报邮件推送或立即发送到注册邮箱。[`email_service.py`](backend/app/services/email_service.py) 新增 `send_briefing()` / `_send_html_email()` 方法，支持 Markdown→HTML 邮件模板。
> - **简报 Tag 优化**：6 个 Prompt 模板的标签系统从宽泛的 `#ai #tool #trending` 升级为细粒度领域标签（如 `#LLM` `#Agent` `#RAG` `#推理优化` `#模型压缩` `#商业化` 等），每个源类型有独立的领域标签候选列表。
> - **普通用户 Report 页面增强**：[`ReportView.vue`](frontend/src/views/ReportView.vue) 现在对所有登录用户展示源类型选择按钮（6 种）和周期选择按钮（日报/周报/月报），新增「订阅到邮箱」和「发送到邮箱」按钮。生成按钮仅 Admin 可见。
>
> **已解决（2026-03-19）**：
> - **Bug8（Chat 页面新建会话）**：`+` 按钮原调用 `ensureGlobalConversation()` 只返回已有会话，现改为调用新增的 `POST /api/chat/conversations/create` API（`createNewConversation()`），强制创建新会话。
> - **Bug8（清空按钮无法真正清除）**：清空按钮原调用 `clearMessages()` 仅清空前端内存，刷新后记录恢复。现改为调用新增的 `DELETE /api/chat/conversations/{id}` API（`deleteActiveConversation()`），真正删除当前会话及其所有消息，然后自动切换到下一个全局会话或创建新会话。
> - **Bug8（附件按钮矢量化）**：附件按钮从文字"附件"改为回形针（Paperclip）SVG 矢量图标，上传中显示旋转加载动画。
> - **Bug8（发送/停止按钮合一）**：AI 消息生成时，发送按钮位置自动切换为圆角正方形停止图标（`■`），点击可中止生成；空闲时恢复为发送箭头图标。顶部标题栏的"终止"按钮已删除。
> - **普通用户每日消息限额**：新增 `USER_DAILY_MESSAGE_LIMIT` 配置项（默认 20，0=不限制），普通用户（role='user'）每天最多发送 20 条消息，admin 不受限。后端 [`routes_chat.py`](backend/app/api/routes_chat.py) 在 `/chat/stream` 和 `/chat/messages/{id}/regenerate` 前调用 `_check_user_message_limit()` 检查限额，超限返回 HTTP 429（`message_limit_exceeded`）。[`mysql_repo.py`](backend/app/repositories/mysql_repo.py) 新增 `count_user_messages_today()` 统计 CST 当日用户消息数。前端 [`useEventSource.ts`](frontend/src/composables/useEventSource.ts) 增强 HTTP 错误解析，[`chatStore.ts`](frontend/src/stores/chatStore.ts) 对 429 错误显示友好的 `⚠️ 今日消息已达上限` 提示。
