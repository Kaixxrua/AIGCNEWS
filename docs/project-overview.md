# AIGCNEWS 项目全景

> 最后更新：2026-08-13
> 文档定位：产品与功能走查 —— 平台上有什么、给谁用、入口在哪、哪些能力开放。代码级分层与实现细节见 [architecture.md](architecture.md)；部署与自托管见 [self-hosting.zh-CN.md](self-hosting.zh-CN.md)。

## 一、项目定位

AIGCNEWS 是面向 AI 工程师、研究者与 AI Agent 的垂直情报平台：持续采集 AI 领域的论文、开源项目、行业新闻、新产品与社区热点，加工为**可浏览的榜单、可检索的项目库、可订阅的简报**，并通过两个入口对外提供同一份数据资产：

- **AIGC Radar MCP** —— 面向 Agent 的 MCP 数据接口（旗舰，`/api/mcp`）
- **Web 站点** —— 面向人类读者的榜单、项目库与简报界面

平台沉淀的是经过加工的结构化情报（正文/PDF 补全、评分、分类、中英标签、榜单快照、增长与热度、向量索引），而不是书签集合。

## 二、数据源全景

| 来源 | 周期 | 采集通道 | 说明 |
|---|---|---|---|
| HuggingFace Papers / arXiv | 日 / 周 / 月 | 每小时 :01 | 论文榜单；摘要先入库，PDF 后台异步补全全文 |
| GitHub Trending | 日 / 周 / 月 | 每小时 :02 | 趋势仓库，喂给项目库候选池与热度榜 |
| Techmeme | 日 | 每小时 :03 + 00:36 关榜补采 | 科技新闻 RSS + HTML 双通道 |
| Product Hunt | 日 | 每小时 :04 | 新产品发布（Apollo SSR 解析） |
| Hacker News | 日 | 每小时 :05 + 00:35 关榜补采 | Firebase API Top-30 |
| DailyHot 聚合热榜 | 日 | 每小时 :07 | 自托管 DailyHotApi（profile-gated 容器），见 [dailyhot-source.md](dailyhot-source.md) |
| X / Twitter Watchlist | 日 | 每 2 小时 :06 + 00:31 关榜补采 | **可插拔源**：实现位于私有插件包，开关 `x_source_enabled` |
| 微信公众号 | 关注制 | 按账号同步 | **可插拔源**：开关 `wechat_source_enabled`，自有路由不经采集注册表 |

关键机制：

- **榜单快照制**：榜单读 `document_rank_snapshots` 历史快照而非实时重算，任意日期可稳定回看。
- **关榜（closing）契约**：每日 00:31–00:36 的关榜任务补采"昨日"切片，配合 Dashboard 静默期策略（读侧 embargo），保证定榜前数据完整、定榜后不再抖动。
- **错误隔离**：单源失败只产生 error 结果，不阻断其他源。
- **插件边界**：X 与微信的敏感抓取实现不在公共仓；插件缺席时对应路由 404、调度任务不注册，其余功能不受影响（契约见 `backend/app/services/source_plugins/`）。

## 三、功能走查

### 3.1 Dashboard 多源榜单（`/`）

公共首页，无需登录：

- 六源同板切换（论文 / GitHub / 新闻 / Product Hunt / Hacker News / X），日 / 周 / 月周期
- 榜单状态机：采集中 / 静默期 / 已定稿 / 无数据，读侧由 dashboard policy 统一裁决
- 日历组件按快照日期回看历史榜单；分类雷达图、综合统计卡片（注册用户数、今日新增文档、今日独立访客）
- `/dashboard/live-stats` 实时统计与 `/dashboard/visitor-count`（Redis SET 按 CST 日去重，48h TTL）
- 全部端点 Redis 缓存（`aigc-cache:` 前缀），采集完成后自动失效并预热首屏请求

### 3.2 GitHub AI 项目库（`/projects`）

当前完成度最高的模块，平台核心亮点：

- **规模与门槛**：18,000+ 精选项目与工具站；公共 GitHub 项目执行 **≥500 Stars 准入**（`PUBLIC_PROJECT_MIN_STARS`），低信号仓库不进库
- **检索**：PostgreSQL 关键词候选 × Milvus 语义候选（独立 collection，README 分块索引）融合，回库水合后按分类/语言/门槛过滤；本地零结果且满足严格条件时才走限量只读 GitHub fallback
- **排序**：相关性 / 热度 / Stars / 更新时间 / 收录时间 / 名称；`sort=hot` 走每日 `daily_hot_v5` 热度分（规模校正增长 × 增长加速度 × 维护活跃 × 社区参与，含置信度折减）
- **增长展示**：卡片展示今日 +N Stars（连续自然日快照差值；缺昨日快照时仅对同日 Trending 日榜项目采用页面 `stars today`，来源可区分）
- **筛选即 URL**：分类 / 子分类 / 语言 / 标签 / 排序 / 分页全部同步 query string，刷新可恢复、可复制分享
- **站长推荐**：管理员可将项目加入推荐位（`github_repo_recommendations`）

### 3.3 收藏与私人工具书架

登录用户在项目库内：

- **收藏**：跨设备同步，前端乐观更新、失败回滚；公共库与私人数据严格隔离
- **私人工具书架**：提交 URL 自动抓取富化（标题 / 中英描述 / 分类 / 标签 / 图片），失败可手工填写；支持编辑与删除；个人站点不会自动混入公共目录
- **私人覆盖**：`user_tool_website_overrides` 让同一条目对不同用户呈现不同标题/描述/标签

### 3.4 论文发现与阅读（`/papers/:id/read`）

- 发现：全局搜索（300ms 防抖，空查询展示当日热门）、`/papers/top10-today` 冷启动榜单、全文检索
- 阅读：站内 PDF 阅读器（pdfjs 分页渲染 + 进度显示），桌面双栏 / 移动单栏，原始 PDF 下载，**区域框选截图**可直接向 AI 提问
- 两阶段入库：摘要先行（尽快可搜），后台低频下载 PDF（3–5s 间隔防封）、PyMuPDF 解析、切片写入 Milvus
- 游客可读；论文 AI 对话当前跟随对话链路的开放状态（见 3.8）

### 3.5 X 动态板（`/x`，插件门控）

- 精选时间线瀑布流（图片 / 视频 / 引用卡片），按日期窗口回看
- 推文中文翻译完整补回 @ 提及；媒体经 `/api/media/x/*` 代理（twimg 流式转发、mp4 首帧 ffmpeg 封面）
- 归属规则：纯转贴按原贴日期归属；每日 00:31 关榜任务补采昨日遗漏
- 已删推文清理由 `x_deleted_janitor` 每 6 小时执行（失败即中止、零写入的 fail-closed 设计）

### 3.6 微信公众号（`/wechat`，插件门控 + 管理员）

- 管理员扫码登录（QR 会话加密入库）、搜索并添加公众号、触发同步
- 用户侧：关注目录、按关注生成阅读 Feed；文章全文仅管理员可见
- mmbiz 图片经 `/api/media/wechat/proxy` 代理（头像落盘缓存、正文流式直转）

### 3.7 简报与订阅推送（`/report`、`/subscriptions`）

- **8 个维度**（综合 / arxiv / github / news / producthunt / hackernews / x / dailyhot）× **3 种周期**（日 / 周 / 月），中英双语
- 生成：管理员 SSE 流式生成（截断自动续写最多 5 轮），结果按日期持久化缓存；每天 08:00 全维度自动生成
- 阅读：公共端点按日期读历史简报，无需登录
- **订阅推送**（`/subscriptions`，登录）：用户自建投递渠道 —— 邮箱（OTP 验证）或 webhook（企业微信 / 钉钉 / 飞书 / 自定义，带 SSRF 防护的连通性验证）；按来源 × 频率订阅；调度器每 30 分钟幂等投递（`push_deliveries` 按 issue 去重，只读缓存不触发生成）；支持"立即发送"到邮箱
- 部分来源只有日度采集，其周报/月报受底层数据周期限制

### 3.8 RAG 对话（能力完整，Web 入口维护中）

后端具备完整混合检索问答链路（文档 ID 精确召回 → 标题召回 → Milvus 向量 → Neo4j 图谱 → 来源均衡去重 → 硅基流动 bge-reranker 精排 → 可选 Kimi 联网搜索 → 流式生成），多会话、附件（图片零落盘 / PDF 解析）、视觉问答、思维链分阶段展示、每日消息配额均已实现。

**当前状态**：`/chat` 路由为 `requiresAdmin` 且有 `CHAT_SERVICE_ENABLED` 总开关 —— 属于已实现但暂停开放的能力，重开与否是产品决策，不是技术缺口。

### 3.9 AIGC Radar MCP（`/api/mcp`，旗舰）

面向 Claude Code / Cursor / Codex / VS Code 等 9 类 MCP 客户端的 Streamable HTTP 数据接口，公开只读、免鉴权：

| 工具 | 用途 |
|---|---|
| `search_github_ai_projects` | local-first 检索精选 GitHub AI 项目库 |
| `search_github_projects` | 非 AI 开源软件与组件检索 |
| `search_papers` | arXiv 论文专搜 |
| `search_documents` | 跨来源索引搜索 |
| `get_top_items` | 日 / 周 / 月榜单快照 |
| `get_paper_detail` | 单条索引文档详情 |
| `get_project_categories` | 项目分类与子类计数 |

- 携带 `Authorization: Bearer <MCP token>` 解锁 `search_my_project_favorites`（scope `projects:favorites:read`）
- 另提供 3 个 resources、4 个 resource templates、2 个 prompts；`initialize` 响应的 `instructions` 字段发布 MCP-first 路由策略
- 登录用户在 `/mcp` 页自助签发 token：SHA-256 摘要存储、明文仅展示一次、设备标签、有效期、可撤销、每用户上限 20 个
- 限流：匿名按 IP 60/30 req-min，认证按用户 240/120 req-min（Redis 固定窗口，故障时放行）
- 协议参数与策略全文见 [mcp-server.md](mcp-server.md)

### 3.10 账号体系

- 邮箱验证码注册 / 登录 / 忘记密码重置，JWT（HS256，默认 7 天）
- **空库首个注册用户自动成为管理员**，之后均为普通用户；注册依赖邮件通道（SMTP 或 dev 模式日志打印验证码），见 [self-hosting.zh-CN.md](self-hosting.zh-CN.md)
- 防刷：OTP 5 分钟有效 + 60s 发送冷却 + 5 次尝试上限；登录 / 注册按 IP 固定窗口限流

### 3.11 管理后台（`/monitor`，管理员）

单页运维中心，12+ 面板：

- 采集任务记录与手动触发（智能 / 按日期 / 按源），数据清理
- 调度器状态、手动触发、**逐任务窗口配置**（开始-结束时段 × 间隔分钟 × 启用开关，DB 覆盖默认 cron）
- 模型 Provider 配置与**真实连接测试**；SMTP 配置（入库即生效、优先于环境变量、脱敏展示、测试邮件）
- 外部 MCP Server 配置（出站，token 脱敏、安全测试仅 initialize/tools/list）
- X 凭据池 / watchlist 管理与测活；GitHub 项目爬取、富化（含取消与状态轮询）、推荐位、指标刷新 / 重算
- 简报批量生成、Dashboard 缓存清理、RAG 评估记录

## 四、用户角色与权限

| 能力 | 游客 | 注册用户 | 管理员 |
|---|---|---|---|
| Dashboard / 项目库 / 论文阅读 / 简报阅读 / X 板（若开启） | ✓ | ✓ | ✓ |
| MCP 公开工具 | ✓（按 IP 限流） | ✓ | ✓ |
| 收藏 / 私人书架 / 订阅推送 / MCP token 签发 | — | ✓ | ✓ |
| RAG 对话（当前维护中） | — | — | ✓（开关控制） |
| 公众号关注 Feed | — | ✓（插件开启时） | ✓ |
| 管理后台 / 采集与调度 / Provider / SMTP / 爬取富化 | — | — | ✓ |

鉴权依赖：`RequireUser` / `RequireAdmin`（JWT Bearer）、`OptionalUser`（登录增强）、`OptionalMcpUser`（MCP token，无效 token 一律 401 而非降级匿名）。

## 五、当前开放状态一览

| 模块 | 状态 |
|---|---|
| Dashboard 榜单 / 项目库 / 论文阅读 / 简报 / 订阅推送 | 稳定开放 |
| AIGC Radar MCP | 稳定开放（旗舰，公开只读） |
| X 动态板 | 私有部署开启（依赖插件与凭据） |
| 微信公众号 | 管理员可见（插件门控） |
| RAG 对话 / 论文 AI 对话 | 实现完整，Web 入口维护中（requiresAdmin + 总开关） |
