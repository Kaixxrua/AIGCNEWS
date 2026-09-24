# AIGCNEWS 架构（当前态）

> 最后更新：2026-08-19
> 文档定位：开发者向的具体架构 —— 分层、路由、服务域、存储、调度、部署。功能与产品视角见 [project-overview.md](project-overview.md)。本文只描述当前事实，不记录历史方案；退役事项见各专项 runbook。

## 一、技术栈

| 层次 | 选型 |
|---|---|
| 后端 | FastAPI + Uvicorn（Python 3.12），pydantic Settings 单例配置 |
| 前端 | Vue 3 + TypeScript + Vite 7 + Pinia 3 + Vue Router 5 + TailwindCSS 3 + vue-i18n 11（无组件库、无 ECharts，可视化全部自绘） |
| 关系数据库 | **PostgreSQL 16 —— 唯一关系型运行时**（psycopg_pool 连接池） |
| 向量 | Milvus 2.4（HNSW + COSINE，1024 维；依赖 etcd + MinIO） |
| 图 | Neo4j 5.18（论文实体图谱） |
| 缓存 / 限流 | Redis 7（FastAPICache、OTP、访客去重、固定窗口限流） |
| 调度 | APScheduler AsyncIOScheduler（进程内，Asia/Shanghai） |
| LLM | OpenAI 兼容端点（chat / embedding 可切换 provider）；硅基流动 bge-reranker-v2-m3 精排；Kimi `$web_search` 联网；SiliconFlow Kimi-K2.5 视觉 |
| 部署 | 单机 Docker Compose + nginx（前端 TLS 边缘）；systemd + restart policy 开机恢复 |

## 二、系统全景

```text
数据源（HF/arXiv · GitHub Trending · Techmeme · Product Hunt · HN · DailyHot · X* · 微信*）
  → 采集与标准化（crawlers，单源失败隔离）
  → 富化（README / PDF 补全、LLM 分类打标、中英描述、指标快照与热度分）
  → PostgreSQL 主写（幂等 upsert）→ 榜单快照（document_rank_snapshots）
  → 派生索引：Milvus 向量 × 2（文档 / 项目）· Neo4j 论文图谱
  → Redis 缓存失效 + 首屏预热
  → 消费面：Dashboard · 项目库 · 论文阅读 · 简报/订阅推送 · AIGC Radar MCP · RAG 对话（维护中）

* X / 微信为可插拔私有源（source_plugins + 特性开关门控）
```

一致性模型：PostgreSQL 是结构化事实主库；Milvus / Neo4j / Redis 是可重建派生能力，跨存储采用最终一致（重试 + backfill + 关榜补采），无分布式事务。

## 三、后端架构

### 3.1 分层与组合根

```text
Transport   api/routes_*.py        REST + SSE 入口，DTO 与鉴权（MCP 入站为独立 Go 服务 mcp-go/）
Service     services/*             领域逻辑（采集、RAG、简报、项目搜索、推送、MCP…）
Repository  repositories/*_repository.py   按能力拆分的 Protocol（端口）
Infra       repositories/postgres_*.py / milvus_repo.py / graph_repo.py …  适配器
```

- **组合根** = `main.py` lifespan：`create_application_repositories(postgres)` 构造 30 字段的冻结 dataclass `ApplicationRepositories`，将每个 Protocol 绑到 PostgreSQL 实现，注入 `app.state`；`application_repository_context.py` 持进程级单例供少量边界场景读取。
- 架构测试以 AST 扫描固化：生产代码仅 `main.py` 允许装配仓储；服务层一律显式注入，无隐式回退。
- 项目库读路径例外：`project_catalog_factory.get_project_catalog_repository()` 每次调用解析（大表查询汇聚在 `postgres_project_catalog.py`）。

**lifespan 启动顺序**：JWT 密钥校验（弱/缺即拒启）→ PG 连接池 + 迁移账本检查（pending 仅告警）→ 监控运行时 → 仓储组装（含 runtime provider / SMTP 读取器绑定）→ 附件孤儿对账 → operations 运行时 → 模型 Provider 运行时 → 项目搜索运行时 + RAG provider → 语义预热任务（开关门控）→ Redis + FastAPICache（失败降级不致命）→ 调度器（读 DB 任务配置后注册）。关闭按相反顺序，调度器与运行时各有优雅退出宽限。

### 3.2 API 路由总表

全部挂在 `/api` 前缀下。鉴权：`RequireUser` / `RequireAdmin`（JWT）、`OptionalUser`、`OptionalMcpUser`（MCP token）。

| 文件 | 鉴权 | 内容 |
|---|---|---|
| `routes_auth.py` | 公开 + RequireUser | 邮箱 OTP 注册 / 登录 / 忘记密码重置；`/auth/me`；`/auth/me/mcp-tokens` CRUD（IP 与账号双维限流） |
| `routes_dashboard.py` | 公开，Redis 缓存 | top / radar / summary / live-stats / snapshot-dates / visitor-count / x/recent；静默期读侧拦截 |
| `routes_github_projects.py` | OptionalUser / RequireUser | 公共项目库检索、分类、taxonomy；我的收藏、工具书架 CRUD |
| `routes_papers.py` | 公开 | 论文搜索、top10-today、详情（PDF 仅供后台处理） |
| `routes_report.py` | 公开 + RequireUser + RequireAdmin | 简报读取（公开）；订阅 / 立即发送（用户）；SSE 生成、评估记录（管理员） |
| `routes_push.py` | RequireUser | 推送渠道（邮箱 OTP / webhook 验证、测试）与订阅 CRUD |
| `routes_chat.py` / `routes_attachments.py` / `routes_vision.py` | RequireUser | 对话 SSE、会话与消息管理、图片附件（零落盘）、视觉问答 |
| —（独立 Go 服务 `mcp-go/`，nginx `location = /api/mcp` 直达） | MCP token | **POST `/api/mcp` 单端点**，JSON-RPC 全协议（见第七节；Python 入站已随 W6 退役删除） |
| `routes_monitor.py` | 公开 + RequireAdmin | `/live` `/ready` 健康探针（公开）；health / metrics / tasks（管理员） |
| `routes_ops.py` + 子路由 | RequireAdmin | 采集触发 / 数据清理 / 调度器状态与配置 / Provider 配置与测试 / 简报批量 / 缓存清理 / 项目运维；`routes_ops_github.py`（爬取、富化、推荐、指标）、`routes_ops_mcp.py`（出站 MCP 配置）、`routes_ops_smtp.py`（SMTP 面板）、`routes_ops_x.py`（见下行）、`routes_ops_payments.py`（支付订单列表、详情、补单、关单） |
| `routes_ops_x.py` | RequireAdmin | X watchlist / 凭据池 CRUD 与测活、日榜快照回填 |
| `routes_wechat.py` / `routes_wechat_media.py` | 插件门控 + 角色 | 公众号扫码登录、账号与文章同步（管理员）；关注目录与 Feed（用户）；mmbiz 媒体代理（公开但 IP 限流） |
| `routes_x_media.py` | 插件门控，公开 | twimg 图片代理、mp4 首帧封面（IP 限流；`<img>` 无法带 Authorization 故公开） |
| `routes_features.py` / `routes_sitemap.py` | 公开 | 特性开关播报；近 90 天论文页 sitemap |
| `routes_payments.py` | payments_enabled + RequireUser（回调按 provider 验签） | 套餐、创建订单、我的订单、订单状态、微信/支付宝/海外跳转回调；关闭时用户侧 404，渠道未配置时创建返回 503 |

特性开关：`x_source_enabled` / `wechat_source_enabled` 以 router 级依赖实现"关闭即 404，等同未部署"；`chat` 另有 `CHAT_SERVICE_ENABLED` 总开关。

### 3.3 核心服务域（`backend/app/services/`）

| 域 | 职责要点 |
|---|---|
| `ingestion/` | 7 源爬虫编排（`pipeline.py`）；内容富化；**项目库管线**：候选池、每日指标快照与 `daily_hot_v7` 热度、LLM 分类打标（中英）、README 语义索引源；arXiv PDF 异步下载切片；采集后缓存失效 + 首屏预热 |
| `project_catalog/` + `project_discovery.py` / `project_search_runtime.py` / `project_semantic_search.py` / `project_reranker.py` | 项目检索分层：PG 关键词候选 × Milvus 语义候选 → 融合 → 回库水合 → 门槛/分类过滤 → 排序；本地零结果时限量只读 GitHub fallback；legacy/v2 影子对比用于验证切换 |
| `rag/` | ChatService：混合召回（文档 ID 精确 → 标题 → Milvus → Neo4j → 来源均衡）→ reranker 精排（COSINE>0.6 智能跳过）→ 可选 Kimi 联网 → 两轮 LLM（工具判断 + 流式生成）；直连 OpenAI 兼容 API 保留 reasoning 字段 |
| `briefing/` | 8 维度 × 3 周期简报生成（快照优先、截断续写 ≤5 轮、按日期持久化）；订阅派发编排 |
| `chat/` | 会话 CRUD 与 LRU 裁剪（每用户 10 会话 × 每会话 10 消息）、附件生命周期、每日消息配额 |
| `dashboard/` | 快照日期解析、榜单装配、雷达类目与静默期 policy（读侧 embargo） |
| `push/` | 渠道服务（邮箱 OTP / webhook 探测验证、SSRF 防护、密钥封缄）；订阅 CRUD；`dispatch_service` 幂等投递（`push_deliveries` 按 issue 去重） |
| `mcp/` | 见第七节（入站 Server）；另有出站方向：外部 MCP Server 配置 CRUD + 安全连接测试（token 脱敏投影、协议 2025-06-18、5s/10s 超时、钉住目标防 SSRF） |
| `email/` + `email_service.py` | OTP 存储（注册 / 重置 / 推送验证三套键）、SMTP 发送、`smtp_config_provider` DB 覆盖 env 的热配置（60s TTL） |
| `runtime_provider/` | 应用级模型 Provider 池（管理面板可改、300s 延迟关闭旧客户端）；chat/embedding 工厂 |
| `vision/` | SiliconFlow Kimi-K2.5 视觉问答；截图进程内缓存 TTL 300s，零落盘 |
| `x_watch/` `x_credentials/` `x_janitor/` | X watchlist 管理；凭据池 CRUD + 测活；已删推文清理（fail-closed） |
| `payments/` | 会员套餐、订单状态机、provider registry、回调验签结果与恰好一次发权益；provider 当前为凭证未配置桩 |
| `source_plugins/` | 私有插件加载器：X 传输层与微信门面的公共契约 + fail-closed 加载；开关关或包缺失即 404 / 跳过 |
| `media_cache.py` | 微信 / X 媒体共享磁盘缓存（LRU + TTL，默认 512MiB / 7 天） |
| `*_admin.py` | 运维面服务（采集、爬取、富化、调度配置、SMTP、快照回填、数据清理…），全部仅管理员 |
| `evaluation/` | RAG 评估（token 级召回 / 引用覆盖），结果入 `rag_evaluations` |

### 3.4 关键横切机制

- **出站安全**：`outbound_target_policy.py` 对 webhook / 媒体代理等用户可控 URL 做公网 IP 策略（SSRF 防护）；GitHub fallback 不写库、不暴露 token。
- **密钥封缄**：微信会话、X 凭据、推送渠道、外部 MCP token 均以 base64-32B 主密钥加密入库（`CHANGEME` 拒启；缺失即拒绝存取，绝不落明文）。
- **限流**：Redis 固定窗口 `ratelimit:{action}:{identity}`，覆盖注册/登录/OTP/推送/媒体代理/MCP。
- **访客统计**：中间件按 CST 日写 `visitor:{date}` SET（48h TTL），`SCARD` 即独立访客数。

## 四、数据存储

### 4.1 PostgreSQL 16（43 张表 + 迁移账本）

连接：`psycopg_pool`（min 2 / max 20，statement_timeout 15s，sslmode 默认 require）；事务借出失败时显式废弃连接，防止脏连接回池。

迁移：`backend/migrations/postgres/NNNN_*.sql`（当前 0001–0036，编号必须连续）；账本表 `app_schema_migrations` 记录 version/filename/sha256/时间；全程持 advisory lock；逐迁移单事务；**启动不自动 apply**，由 `scripts/migrate_postgres.py` 执行，启动仅打印 pending 告警。

表分组（括号内为引入迁移号）：

| 分组 | 表 |
|---|---|
| 用户与会话 | `users`、`conversations`、`chat_messages`、`chat_attachments`、`chat_attachment_meta`(0026) |
| 内容与榜单 | `documents`、`document_rank_snapshots`、`ingestion_tasks`、`briefings`、`briefing_subscriptions`、`rag_evaluations` |
| 项目库 | `github_repo_candidates`、`github_repo_snapshots`、`github_repo_daily_metrics`、`github_trending_hits`、`github_repo_enrichments`、`github_repo_aliases`、`github_repo_recommendations`、`github_project_semantic_sources`、`project_favorites`、`tool_websites`、`tool_website_enrichments`、`user_tool_websites`、`user_tool_website_overrides`、catalog 迁移工具表 ×3、`project_catalog_applied_events`(outbox 去重) |
| 订阅推送 | `push_channels`、`user_subscriptions`、`push_deliveries` |
| MCP | `user_mcp_tokens`（SHA-256 摘要 + hint + scopes + 有效期 + 撤销，明文不落库）、`mcp_server_configs`（出站配置） |
| 支付订单 | `payment_orders`（订单号、用户、套餐、渠道、金额分、状态、幂等键、渠道回调原文、支付与权益时间）；迁移 0051 |
| 运行配置 | `runtime_provider_settings`（单行）、`smtp_settings`(0036，单行)、`scheduler_job_config`(0016) |
| X（插件） | `x_watch_accounts`、`x_credentials`、`x_credentials_bootstrap_state` |
| 微信（插件） | `wechat_official_accounts`、`wechat_articles`、`wechat_sessions`、`wechat_login_attempts`、`wechat_account_follows` |

### 4.2 Milvus（两个 collection）

| Collection | 内容 | 切片 | 检索参数 |
|---|---|---|---|
| `aigc_docs` | 采集文档 + arXiv PDF 全文 | 文档 800/100；PDF 3000/200 | HNSW，COSINE，ef=max(k,64)；支持按 source 过滤保底各源覆盖 |
| `aigc_github_projects_v1` | 项目语义索引：1 个 profile 块 + 至多 12 个 README 块（README 上限 40k 字符） | 1200 步进 1080（重叠 120） | min_score 0.45，chunk_limit 800，repo_limit 200；索引按 source_fingerprint 增量 |

开关：`project_semantic_search_enabled` / `_indexing_enabled`（默认关）；维度变更即 schema 校验报错。

### 4.3 Neo4j

仅对 arXiv 新文档抽取：`LLMGraphTransformer`，节点 `Paper / Author / Concept`，关系自由文本归一化为大写（fallback `RELATED_TO`），MERGE 幂等写入；读侧按关键词匹配节点 + 一跳邻居，渲染为 `Paper(x) -[REL]-> Concept(y)` 注入 RAG 上下文。

### 4.4 Redis 键位

| 用途 | 键模式 | TTL / 窗口 |
|---|---|---|
| API 缓存（FastAPICache） | `aigc-cache:*` | 10s–1h |
| 独立访客 | `visitor:{YYYY-MM-DD}`（SET） | 48h |
| OTP（注册 / 重置 / 推送验证） | `email:{code,lock,attempts}:…` 三套前缀 | 300s / 60s / 300s |
| 固定窗口限流 | `ratelimit:{action}:{identity}` | 按动作；MCP 60s；支付套餐/回调使用 `ratelimit:payments.plans:*`、`ratelimit:payments.callback:*` |
| 支付匿名访问 | `ratelimit:payments.plans:{client_ip}` / `ratelimit:payments.callback:{client_ip}` | 固定窗口；Redis 故障 fail-open |
| MCP 限流分桶 | `mcp.protocol` / `mcp.tool_call` | 匿名 60/30、认证 240/120 req-min，故障放行 |

## 五、定时调度

进程内 APScheduler（Asia/Shanghai，`max_instances=1`）。19 个任务分四组：

| 组 | 任务（时间） |
|---|---|
| 逐源采集 | arxiv :01 · github :02 · techmeme :03 · producthunt :04 · hackernews :05 · dailyhot :07（每小时）；x_watchlist 每 2h :06 |
| 关榜补采（昨日切片定稿） | x_closing 00:31 · metrics_closing 00:33 · hackernews_closing 00:35 · news_closing 00:36 |
| 项目库 | daily_pipeline 02:00（入库/快照/打分/富化）· metrics_refresh 每 2h :17 · semantic_warmup 每 30min（开关门控） |
| 运维 | daily_briefing 08:00 · subscription_dispatch 每 30min（只读缓存幂等投递）· x_credentials_probe 每 2h :08 · x_deleted_janitor 每 6h :11 · conversation_cleanup 每 7 天 03:30 · payment_order_closing 每 5min（payments_enabled 门控，pending → expired） |

- **DB 覆盖**：`scheduler_job_config` 可将任意任务改为"每日窗口 × 间隔分钟"或停用，经 `/ops/scheduler/config` 热生效。
- **互斥**：`github_job_lock` / `x_operation_lock` 串行化手动运维与调度运行。
- **告警**：连续失败（默认 3 次）与零入库（默认 3 轮，watch 5 源）经 `scripts/notify_ops_alert.py` 外发。
- **启动对账**：补采近 2 天缺失的 arxiv 快照、刷新当日 GitHub 指标。
- X 链任务在 `x_source_enabled=False` 时不注册。单实例假设：横向扩容需保证调度器单活。

## 六、前端架构

### 6.1 分层约定

```text
views/        页面：布局与装配，不写业务逻辑
features/     领域纯逻辑：model / viewModel / presentation（大量 colocated *.test.ts）
composables/  页面状态与异步编排（数据控制器）
services/     HTTP 层（axios 实例 + 每域 API 模块）
stores/       Pinia：仅跨页共享状态（auth、chat、enrichment 红点）
```

### 6.2 路由与守卫（`router/index.ts`，视图全部懒加载）

| 路径 | 页面 | 守卫 |
|---|---|---|
| `/` | DashboardView | 公开 |
| `/projects` | GitHubProjectsView（826 行，逻辑委派 controller + presentation） | 公开 |
| `/report` · `/papers/:id/read` · `/disclaimer` · `/privacy` | 简报 · 论文阅读 · 法务 | 公开（论文对话游客降级为登录引导） |
| `/mcp` | McpConnectView | `requiresAuth`（网站客户端配置与 Token 管理） |
| `/dsh` | DshView | `requiresAuth`（网站 DSH 配置与账号 Token） |
| `/x` | XBoardView（828 行瀑布流） | 特性开关 `xSource` |
| `/subscriptions` | SubscriptionsView | requiresAuth |
| `/chat` | ChatView | requiresAdmin + `CHAT_SERVICE_ENABLED` |
| `/wechat` | WechatView | requiresAdmin + `wechatSource` |
| `/monitor` | MonitorView（12+ 面板编排，含支付订单详情与回调载荷管理员投影） | requiresAdmin |
| `/membership/checkout?plan=monthly|yearly` | MembershipCheckoutView（套餐金额来自支付 API，二维码/跳转指令与支付轮询） | requiresAuth + payments_enabled |
| `/register` · `/forgot-password` | 注册与密码重置页（登录由全局弹窗承载，无独立 `/login`） | guestOnly |

守卫为纯函数（`features/navigation/routePolicy.ts`）：匿名访问受保护页 → 拒绝本次导航（首次深链落到安全路由 `/`），记录完整目标并打开全局登录弹窗；登录成功后恢复目标。非管理员 → `/`；特性关闭 → `/`。

### 6.3 关键机制

- **SSE**：`useEventSource` 基于 fetch ReadableStream（非原生 EventSource），自动带 Bearer，解析 `data:` 帧与 `[DONE]`，429 映射为配额提示。
- **聊天**：`chatStore` + `ChatLifecycleCoordinator`（会话生命周期状态机）+ SSE 事件 reducer + 16ms 帧打字机引擎（与 Pinia 解耦）。
- **HTTP**：axios 实例（baseURL `/api`，60s）；401 单 flight 处理 —— 清 token、强制 anonymous、toast、打开全局登录弹窗；若会话在受保护页失效，先回安全路由并保留目标，登录成功后恢复。MCP token 接口响应体脱敏。
- **i18n**：vue-i18n，`en-US.ts` 为完整基线树，`zh-CN.ts` 深合并补丁（每 key 必有英文）；默认中文，浏览器语言探测。
- **设计系统**：编辑部纸张风 —— 暖白纸面 `#f7f5ee` / 近黑墨色 / 荧光黄绿 `#d8f14b` 强调 / 硬边框硬阴影 / Playfair Display + DM Sans + JetBrains Mono；明暗双主题 CSS 变量；旧 glassmorphism `tech-*` token 仅个别组件残留。
- **构建/质量**：`dev / build / typecheck(vue-tsc) / lint(eslint) / test:unit(vitest, jsdom)`；契约测试含 CSP hash 与认证架构。

## 七、AIGC Radar MCP 服务（入站）

`POST /api/mcp` 单端点，Streamable HTTP（纯 POST 请求/响应，无 GET 流）。
自 W5 起由独立 Go 服务（`mcp-go/`，compose 服务 `mcp-api-go`）承载，
frontend nginx `location = /api/mcp` 直接路由；Python 入站实现已随 W6
全部退役删除。

Go 侧布局：

| 包 | 职责 |
|---|---|
| `internal/mcpapp` | JSON-RPC 分发：initialize / tools/list / tools/call / resources/* / prompts/*；通知（无 id）→ 204；8 工具 handler；静态注册表（serverInfo `aigc-radar`，3 resources + 4 templates + 2 prompts，`MCP_HOST_INSTRUCTIONS` 路由策略）；结果序列化（100k 字符截断为 preview）与品牌归因 `detail_url` UTM 回链 |
| `internal/ratelimit` | Redis 固定窗口（见 4.4），超限 429 + `Retry-After` + JSON-RPC `-32000`；桶字符串/额度与 REST 共享配额池同值同池 |
| `internal/version` | serverInfo 名与版本回退常量（server.json 优先），与 Python 侧契约测试双向钉住 |
| `internal/replay` | 冻结语料（`backend/tests/parity/corpus/`）逐字节回放门禁 |

Python 侧保留（`services/mcp/`）：`contracts.py`（工具输入模型，REST/测试
复用）、`admin_service.py`（ops 后台 MCP 管理）、`protocol.py` /
`transport.py`（出站客户端，供 mcp_connection_tester）、
`inbound/context.py`（`McpAuthorizationContext`，REST 侧 token 身份投影）。

语义要点（Go 逐字节对齐，冻结语料守护）：

- 工具错误一律以 `isError: true` 的工具结果返回（非协议错误）；未知方法 `-32601`、参数 `-32602`、内部 `-32603`，协议错误 HTTP 200。
- `search_my_project_favorites` 需 scope `projects:favorites:read`，匿名调用短路为"需要认证"工具错误；base64 游标分页。
- 工具与 REST 共用同一套数据端口（同一 Postgres 仓储语义）。
- token 模型：SHA-256 摘要 + 展示 hint、scopes、client_type/label、有效期、撤销、每用户活跃上限 20（事务内软淘汰最旧）。

## 八、部署形态

### 8.1 Compose 服务（`docker/docker-compose.yml`）

| 服务 | 镜像 | 端口 | 加固 |
|---|---|---|---|
| `frontend-web` | 本地构建（nginx） | `80/443` 唯一公网口 | `read_only` + tmpfs、`cap_drop: ALL` + 最小 cap_add、SSL 证书只读挂载（key 须 root:root 600） |
| `backend-api` | 本地构建 | `127.0.0.1:8000` 仅回环 | `cap_drop: ALL`、no-new-privileges、mem 4g |
| `project-catalog-postgres` | `postgres:16-alpine`（sha256 钉） | `127.0.0.1:5432`（供宿主机备份） | oom_score_adj -500 |
| `redis` / `milvus` / `etcd` / `minio` / `attu` / `neo4j` | 官方镜像（全部 sha256 钉） | **不发布**，仅编排网内 expose | — |
| `project-catalog-ops` | 本地构建 | 无 | profile `project-catalog-ops`，一次性运维容器 |
| `dailyhot` | 本地构建 DailyHotApi | 无（expose 6688） | profile `dailyhot`，内网热榜上游 |

私有扩展（姊妹服务、外部编排网、私有 nginx server）以 overlay 注入：`scripts/manage_main_stack.sh` 探测 `AIGCNEWS_PRIVATE_COMPOSE`（默认 `../aigcnews_private/deploy/docker-compose.private.yml`），存在即并入并自动启用 dailyhot profile；不存在则核心栈独立可用。

### 8.2 nginx 边缘（`frontend/nginx.conf`）

80→443 跳转、TLS1.2/1.3、HSTS；`resolver 127.0.0.11` + 变量化 upstream 免疫后端容器 IP 漂移；SPA fallback；`/api/` 反代（edge XFF 不可信，以 `$remote_addr` 重写）；双限流区（auth 10r/m、general 20r/s，429）；SSE 关缓冲 + 300s 超时；静态资产 1 年 immutable 缓存；安全头 +  enforcing CSP（inline 主题脚本走 sha256 白名单，前端有契约测试守护）；`client_max_body_size 60m`；私有 vhost 经 `.inc` 占位文件 + overlay bind-mount 注入。

### 8.3 CI（`.github/workflows/`）

- `contract-baseline.yml`（push/PR）：backend-tests（锁一致性 + ruff + pytest）、postgres-integration（PG16 服务跑迁移 + 集成套件）、compose-smoke（compose config + 干净检出前端构建）、frontend-build
- `evals-contract.yml`（定时/手动）：MCP 契约评测（8 工具，无 LLM），产物上传 artifact

## 九、外部契约边界

REST、MCP、SSE 为稳定契约，内部重构不得改变外部行为：

- **REST**：路由、字段、分页排序、错误状态、权限、Stars 门槛与 fallback 来源标注。
- **MCP**：JSON-RPC envelope、initialize 行为、工具/资源/prompt 定义、结构化结果、工具级错误、token scope 与私人数据隔离。
- **SSE**：事件名、`data:` 分隔、sources/thinking/content/conversation/error/heartbeat 序列、`[DONE]`、断开后持久化语义；代理层不得缓冲。

数据库历史：MySQL 已退役并从仓库移除（最终操作见 [mysql-retirement-runbook.md](mysql-retirement-runbook.md)）；任何新增持久化先定义 repository Protocol，再由组合根组装 PostgreSQL 实现。
