# AIGC Radar MCP Server 协议与策略

AIGC Radar 是 AIGCNEWS 面向 Agent 的旗舰数据接口（MCP `serverInfo.name` 为 `aigc-radar`，版本见
[`mcp-go/internal/version/version.go`](../mcp-go/internal/version/version.go)）。
本文是协议参数、内置策略与鉴权语义的权威文档；README 仅保留接入概览。

> 命名说明：`serverInfo.name` 与 session id 前缀已随品牌更名迁移至 `aigc-radar`；
> `aigc-news://` 资源 URI 是稳定标识符，永久保持不变，客户端可安全存储。

## 客户端接入

- 生产 endpoint：`https://aigcnews.cn/api/mcp`（Streamable HTTP）；自托管本地开发为 `http://localhost:8000/api/mcp`
- Claude Code：`claude mcp add --transport http aigc-radar https://aigcnews.cn/api/mcp`
- 浏览器授权（OAuth）入口：`https://aigcnews.cn/api/mcp/oauth`。Claude Code 运行
  `claude mcp add --transport http aigc-radar https://aigcnews.cn/api/mcp/oauth` 后再运行
  `claude mcp login aigc-radar`（较旧的版本在 Claude Code 里输入 `/mcp`，选 Authenticate），
  浏览器里登录并点「同意」即可，不用复制 Token；流程见下文「浏览器授权（OAuth）」
- 站内 onboarding：Web 站点为 Claude Code、Cursor、Codex、OpenCode、Cline / Roo Code、Continue、
  Windsurf、VS Code 与通用 JSON 共 9 类客户端生成导入配置与命令。游客也能打开 `/mcp`：支持 OAuth 的
  Claude Code、Cursor、Codex、OpenCode、VS Code 默认给浏览器授权命令，免登录复制；改用手动 Token
  或选其余客户端时，生成含 Token 的命令前才弹出登录
- DSH：网站 `/dsh` 配置页同样必须登录；但从 npm 或 GitHub 安装 `dsh-aigc-radar` 插件本身不要求登录，
  省略 `mcpToken` 时仍可使用公开 runtime，登录后再按需把账号绑定的 DSH Token 写入本地 dsh profile
- 仅支持 stdio 的客户端：经社区标准桥 `npx mcp-remote https://aigcnews.cn/api/mcp` 接入；
  需要私有工具时追加 `--header "Authorization: Bearer <MCP access token>"`

网站登录只保护配置、Token 管理与账号级能力，不改变站外 `/api/mcp` runtime 的可选 Bearer 语义。

## 传输与协议

- 端点：`POST /api/mcp`（本地开发为 `http://localhost:8000/api/mcp`），Streamable HTTP 传输
- 协议版本：MCP `2025-06-18`，JSON-RPC 2.0 单请求（不支持 batch），请求体上限 64 KB
- 响应头携带 `MCP-Protocol-Version`；`initialize` 成功后下发 `Mcp-Session-Id`
- 单条工具结果与 resource 文本上限均为 100 KB，采用紧凑字段投影
- 所有公开能力均为只读数据

## 工具

公开工具（无需鉴权）：

| 工具 | 用途 |
| --- | --- |
| `search_github_ai_projects` | local-first 搜索站内精选 GitHub AI 项目库（AI/Agent/MCP/RAG/LLM 工程产物） |
| `search_github_projects` | 搜索非 AI 的 GitHub 开源软件与组件 |
| `get_github_project_detail` | 按需读取一个公开 GitHub 项目的资料与原始 README Markdown |
| `search_papers` | arXiv 论文专搜 |
| `search_documents` | 跨来源索引搜索（明确搜索站内新闻或跨来源索引时使用） |
| `get_top_items` | 日 / 周 / 月榜单快照 |
| `get_paper_detail` | 单条索引文档详情 |
| `get_project_categories` | 项目分类与子类计数 |

私有工具：

| 工具 | 用途 |
| --- | --- |
| `search_my_project_favorites` | 检索当前认证用户的个人项目收藏（需 Bearer Token） |
| `get_my_tracking` | 读当前认证用户的追踪规则与近 N 天追踪简报里命中的条目（需 Bearer Token 与 `tracking:read` scope；VIP 会员权益，免费账号得到升级提示） |

输入按发布的 JSON Schema 严格校验；日期参数必须是真实的 `YYYY-MM-DD` 日历日期。
项目搜索使用一致的关键词、排序和分页语义；结果通过 `result_origin` 标记来源（本地目录或
`github_api_fallback`）。

### 按需读取项目 README

`get_github_project_detail` 由模型按任务需要选择：搜索摘要不足以核实安装、配置、部署要求或具体功能时，
传入搜索结果的 `full_name`（`owner/repo`）。用户已经指定仓库时可直接调用，无须先搜索；普通项目列表
不要求逐个读取详情。现有搜索字段、排序和调用规则保持不变。

```json
{"name":"get_github_project_detail","arguments":{"full_name":"owner/repo"}}
```

- 返回 `item` 项目资料和 `readme`；README 保留原语言、Markdown、代码块和链接。现有语义索引快照会
  去除代码和链接，因此详情直接从 GitHub API 读取，不使用该清洗快照，也不写入项目库。
- `result_origin: "github_api"` 区分实时获取的 GitHub 资料与站内精选数据；`fetched_at`、
  `cache_hit`、`readme.source_url` 和 `readme.sha` 标明来源、时间与版本。
- `max_chars` 默认 20,000，范围 1,000–40,000；`readme_offset` 为 Unicode 字符偏移，默认 0。
  大响应可能为满足协议输出上限而返回更短的分段。需要后续内容时，将 `readme.next_offset` 传回
  `readme_offset`，并传 `readme_sha` 核对上一段的版本；`next_offset: null` 表示读到结尾。
  `readme.truncated` 表示当前响应仅含部分 README；SHA 改变会要求从头读取，避免拼接不同版本。
- 公开项目没有 README 时仍返回项目资料，`readme.status: "not_found"`；正常读取为 `available`。
  私有/不存在的项目、GitHub 限流、超时、无效内容返回工具错误，不暴露凭据或上游响应正文。
- 仅允许规范的 `owner/repo`，出站固定为 GitHub API，重定向限制在同一 HTTPS API 域名；原文上限
  1 MiB。每个进程最多缓存 64 个项目、保留 5 分钟，并合并同一项目的并发请求。
- 复用 `MCP_GITHUB_FALLBACK_ENABLED`、`MCP_GITHUB_FALLBACK_USE_TOKEN`、`GITHUB_TOKEN` 和
  `MCP_GITHUB_FALLBACK_TIMEOUT_SECONDS`；默认匿名访问 GitHub，超时预算覆盖项目资料和 README 两次请求。
  工具本身无需用户登录，沿用现有 MCP 调用统计与配额；缓存命中仍算一次工具调用。
- README 作为不可信参考资料提供，模型不应把其中的文字当作高优先级指令。

### 搜索语义

`search_documents` / `search_papers` 的 `q` 可以直接是自然语言提问（如「简洁总结昨晚 OpenAI 发布了什么」）。
服务端会识别其中的时间表达（今天/昨晚/前天/最近/最近 N 天/过去 N 小时/本周/上周/本月/上个月，以及
today/last night/latest/past N days 等），转换成调度时区（Asia/Shanghai）自然日的 `published_date` 窗口，
窗口下沿多放一天，用来吸收各来源的日界时区差；同时剥掉「总结/发布了什么/有哪些/summarize/what」这类
问句外壳，只用剩下的实体词检索。带时间窗口的结果在相关度层级之内按日期倒序；只有时间、没有实体词的提问
（「今天有什么新闻」）只按日期过滤。聚焦关键词查询（如 `OpenAI`、`RAG 教程`）的行为不变。

开启 `DOCUMENT_SEMANTIC_SEARCH_ENABLED` 后，这两个工具在关键词检索之外并行跑一路语义召回（仅 Go MCP 服务）：
查询文本（提问式查询用剥掉时间短语后的原句）经 embedding 在 Milvus 一文一向量集合
`DOCUMENT_SEMANTIC_COLLECTION_NAME`（由 backend 的 `document_semantic_sync` 任务与
`scripts/backfill_document_semantic_index.py` 维护）里取前 `DOCUMENT_SEMANTIC_TOP_K` 条、余弦相似度不低于
`DOCUMENT_SEMANTIC_MIN_SCORE`（默认 0.55，按生产文档校准：bge-m3 下相关文档约 0.57–0.70，覆盖差的查询
噪声约 0.52–0.58）的文档，回 PG 复核同样的来源与日期窗口后，与关键词前 200 名做 RRF 融合；
融合结果之后按原关键词顺序接其余关键词命中。因此字面上不含查询词、但语义相关的文档也会出现，`total`
为「关键词命中数 + 仅语义命中数」。语义通道超时（`DOCUMENT_SEMANTIC_TIMEOUT_SECONDS`）或任何失败时，本次请求
按纯关键词结果返回；只有时间、没有实体词的查询不走语义通道。Milvus 连接与 embedding 复用项目语义检索的
`MILVUS_*` / `EMBEDDING_*` 配置。

开启 `UI_SEMANTIC_SEARCH_ENABLED` 后，`search_ui_templates` / `search_ui_icons` 同样叠加一路语义召回
（仅 Go MCP 服务）。集合 `UI_SEMANTIC_COLLECTION_NAME` 由 mcp-go 自己维护：启动后在后台为模板（名称、描述、
分类、风格、别名）和图标（可读名、别名、分类）计算 embedding，只补写缺少的（条目, 文本指纹）行，不删旧行；
检索时只认当前内嵌目录里指纹一致的条目，套用同样的分类/框架/图标集/风格过滤后，与关键词结果做等权 RRF
融合。中文描述因此能召回只有英文元数据的图标。`search_mode` 保持关键词档位，仅当关键词两轮都为空、结果全部
来自语义通道时为 `semantic`。集合尚未建好、同步未完成、超时（`UI_SEMANTIC_TIMEOUT_SECONDS`）或任何失败时，
本次请求按纯关键词结果返回，响应字段不变。

开启 `PROJECT_FAVORITES_SEMANTIC_SEARCH_ENABLED` 后，`search_my_project_favorites` 的 `q` 也叠加一路语义召回
（仅 Go MCP 服务）：取调用者最近 1000 条 GitHub 收藏，在项目语义集合 `PROJECT_SEMANTIC_COLLECTION_NAME` 里只对这些
`repo_id` 做向量检索，相似度不低于 `PROJECT_FAVORITES_SEMANTIC_MIN_SCORE`（默认 0.55，按生产收藏校准：bge-m3 下
相关项约 0.56–0.67、无关项最高约 0.54）的收藏与关键词条件取并集（关键词全中 **或** 语义命中），分类、语言、
标签等其余过滤、排序与分页不变。语义命中只可能来自调用者自己的收藏。超时
（`PROJECT_FAVORITES_SEMANTIC_TIMEOUT_SECONDS`）或任何失败时按纯关键词过滤返回，响应字段不变；尚未进入项目语义
集合的收藏只能被关键词命中。

## MCP-first 项目发现与复用策略

MCP host 路由遵循明确的 **MCP-first 项目发现与复用策略**：只要用户要求寻找、搜索、推荐、比较或复用
project、repository、开源实现、SDK、framework、component、template、example 或 tutorial，即使没有
明确说 GitHub 或开源，也应先调用一个匹配工具；在实现具有自身架构、集成或长期维护边界的重大模块、
完整能力或独立子系统前，即使用户没有要求搜索，也先做一次开源复用检查。用户要求提升 AI 开发效率、
加速 AI 应用交付或减少 AI 工程重复工作时，优先使用 local-first 的 `search_github_ai_projects`；
AI/RAG/LLM/Agent/MCP 工程产物同样走该工具，非 AI 软件和组件使用 `search_github_projects`，主要交付物
明确为论文、文献、引用、学术评测或实验时才优先使用 `search_papers`。所有公开项目搜索统一要求至少
500 GitHub Stars；本地目录查询和直接 GitHub fallback 都执行该门槛，fallback 查询使用 `stars:>=500`，
并在限量和缓存前独立剔除 Stars 缺失、格式无效或低于门槛的响应。文案/样式、重命名、明确局部 bug、
测试/日志/类型、validation/字段调整、简单 CRUD 和孤立函数/组件/endpoint 修改不主动搜索。每个未变化
需求最多一次初始搜索，且不能与宿主 `WebSearch` / `WebFetch` / `Bash` 同批执行；等待并检查 MCP 结果后，
仅在调用失败、没有可用或相关结果、或缺少具体外部事实时才针对缺口顺序回退 Web。原生 `WebSearch` 不受
MCP 服务端控制，因此 host 必须核验其候选的当前 GitHub Stars，不得展示、推荐或比较无法核验或低于
500 Stars 的项目。500 Stars 只是准入门槛，不能替代维护状态、许可证、安全性和集成适配评估。若采用候选
会改变架构、部署、数据归属、许可证或长期维护，host 应列出直接复用、借鉴设计后自研和完全自研选项并
等待用户确认。

该策略以英文原文通过 `initialize` instructions、工具描述和 Prompt 发布（见
[`mcp-go/internal/mcpapp/catalog.go`](../mcp-go/internal/mcpapp/catalog.go) 的 `hostInstructions`），但服务端无法覆盖客户端自己的 system prompt 或原生工具优先级。策略依据的
实测对比见 [mcp-vs-websearch-agent-project-discovery.md](mcp-vs-websearch-agent-project-discovery.md)。

## 本地优先与 GitHub fallback

技术选型、架构建议以及库、框架、数据库或解析器推荐同样属于复用决策，即使用户没有使用“搜索”一词也必须先走对应的 AIGC_NEWS 搜索。项目 Codex hook 默认以 `enforce` 模式运行；`observe`/`off` 仅用于明确的本地排障，不能作为正常回答路径。

`search_github_ai_projects` / `search_github_projects` 均为 local-first：
只有本地第一页结果总数为 0，且过滤与排序可由 GitHub Search 等价表达时，才进行限量、只读 fallback。
fallback 不写库、不暴露 GitHub Token。

## Resources 与 Prompts

静态 resources：

| URI | 内容 |
| --- | --- |
| `aigc-news://dashboard/summary` | 最新公共 dashboard 上下文：榜单、趋势雷达与来源聚合统计（JSON） |
| `aigc-news://projects/categories` | 项目分类与子类计数（JSON） |
| `aigc-news://report/latest` | 最新生成的公共简报（Markdown，支持查询参数 source/period/date） |

Resource templates：

| URI 模板 | 内容 |
| --- | --- |
| `aigc-news://dashboard/top{?source,period,date,limit}` | 按来源、周期、日期与限量读取榜单（JSON） |
| `aigc-news://papers/{paper_id}` | 单条索引文档详情（JSON） |
| `aigc-news://projects/library{?q,category,subcategory,language,scope,sort,page,limit}` | 项目库切片（JSON） |
| `aigc-news://report/latest{?source,period,date}` | 按来源、周期与可选日期读取最新简报（Markdown） |

Prompts：

| Prompt | 用途 |
| --- | --- |
| `daily_research_brief` | 引导客户端用公开工具与 resources 汇总当日 AIGC 研究简报 |
| `project_discovery` | 引导客户端以 local-first 搜索发现、比较与评估可复用开源项目 |

## 鉴权

MCP 有两个相互独立的平面：网站配置与站外运行时。

### 网站配置平面

- 网站 `/mcp` 配置页对游客开放：可选客户端与终端、复制免登录的公开命令和浏览器授权命令；生成含手动 Token 的命令时，页面内弹出全局登录弹窗，登录后回到 `/mcp` 继续。Token API 仍由后端 401 兜底。站点没有独立 `/login` 页面。
- 网站 `/dsh` 配置页也必须登录；登录后才能取得或复用账号绑定的 DSH 专用 Token。
- generic MCP Token 的创建、查看脱敏 metadata、删除与轮换，以及网站生成的客户端配置，均由登录账号执行；客户端不能提交 membership、group、quota 或 VIP 作为权限依据。
- 登录 JWT 仅用于网站会话，不等于 MCP access token，也不会直接作为 `/api/mcp` runtime credential。
- generic Token 只保存 SHA-256 lookup digest、hint、scopes、有效期与撤销状态；DSH Token 通过独立 `purpose` 隔离，并保存服务端加密材料以支持跨刷新复用。Token 明文不会进入网站的普通 storage、URL、页面日志或 analytics；目标客户端、终端、剪贴板或环境变量仍可能自行保存它。

### MCP 运行平面

- 没有 `Authorization` 头：请求按 anonymous/guest 处理，公开工具、resources 与 prompts 继续可用，使用游客/IP 配额；不会投影为某个 Free 账号。
- 携带有效 `Authorization: Bearer <MCP access token>`：按 Token 所属用户、实时会员档位与 scope 鉴权，使用账号配额并解锁私有工具 `search_my_project_favorites`（scope `projects:favorites:read`）与 `get_my_tracking`（scope `tracking:read`，调用时再按实时会员档位放行）。网站 `/mcp` 与 DSH 向导签发的 Token 默认带这两个只读 scope。
- 只要显式提供了凭证但凭证为非 Bearer、格式错误、未知、过期、已撤销、已删除、所属用户已禁用或 scopes JSON 无效，均在 JSON-RPC 解析前返回 HTTP 401，并带 `WWW-Authenticate: Bearer`；绝不降级为游客，也不消耗游客配额。
- 认证顺序固定为：方法校验 → Bearer 认证 → JSON-RPC 解析 → 限流 → 分派。MCP access token 由站内账号体系签发与管理，与登录 JWT 相互独立。

### 浏览器授权（OAuth）

`https://aigcnews.cn/api/mcp/oauth` 给支持 MCP 授权规范的客户端用。它与 `/api/mcp` 共用同一套认证、解析、限流、分派与工具（Go `mcpapp.OAuthEntry`），区别只有一处：不收匿名请求。授权服务器在 Python 主后端（`backend/app/services/auth/mcp_oauth.py`、`backend/app/api/routes_mcp_oauth.py`）。

1. 客户端不带令牌请求入口，得到 HTTP 401 和 `WWW-Authenticate: Bearer resource_metadata="https://aigcnews.cn/.well-known/oauth-protected-resource/api/mcp/oauth"`（RFC 9728 §5.1）；带了无效凭证时，头里另有 RFC 6750 的 `error`（令牌无效为 `invalid_token`，凭证格式不对为 `invalid_request`）。
2. 客户端读受保护资源元数据，再读授权服务器元数据 `/.well-known/oauth-authorization-server`（RFC 8414）。两份 JSON 在 `frontend/public/.well-known/` 下，随前端发布包上两个边缘。只给 `/api/mcp/oauth` 发资源元数据：根路径若也有一份，连匿名 `/api/mcp` 的客户端也会去走登录。
3. 动态客户端注册 `POST /api/oauth/register`（RFC 7591）。公开客户端（`token_endpoint_auth_method=none`）不发密钥，只靠 PKCE；声明 `client_secret_post` / `client_secret_basic` 时才发密钥，库里只存 SHA-256 摘要。回调地址最多 10 个、每个不超过 2,000 字符，危险 scheme 拒收；本机回环地址匹配时不比端口（RFC 8252 §7.3）。从未完成授权、注册超过 30 天的客户端由注册接口顺手清理。
4. 浏览器打开授权页 `/oauth/authorize`（前端页面，未登录时页内弹出登录，不走路由守卫，以免丢掉客户端带来的授权参数）。只支持 `response_type=code` + PKCE `S256`；`resource` 可省略，给了就必须是 `https://aigcnews.cn/api/mcp/oauth`（末尾斜杠视为同一资源），否则 `invalid_target`（RFC 8707）。scope 取客户端请求与本站支持的交集，一个都不认识时按默认的两个只读 scope 授予。用户点「同意」后签发授权码：一次性（Redis `GETDEL` 原子消费），5 分钟过期。
5. 客户端在 `POST /api/oauth/token` 用授权码与 code_verifier 换令牌。令牌就是 `user_mcp_tokens` 里的普通行，另记 `oauth_client_id`（迁移 `0088_mcp_oauth_clients.sql`），Go 侧鉴权查询与手动 Token 完全相同；不设过期，不发 refresh_token。同一用户在同一客户端再次授权时，旧令牌在同一事务里吊销；每用户 20 个活跃令牌的上限照常生效。

限流（均为 10 分钟窗口）：注册每 IP 20 次、全站 200 次；授权预览每用户 60 次、同意或拒绝每用户 30 次；换令牌每 IP 60 次。

已知限制：

- 资源地址与签发方都绑定 `aigcnews.cn`。从备用域名 `aigcradar.online` 接入的客户端，改用手动 Token。
- 不支持 CIMD（Client ID Metadata Documents）。新版 MCP 授权规范推荐 CIMD、动态注册保留为兼容方式；授权服务器元数据不声明 `client_id_metadata_document_supported`，客户端据此回落到动态注册。
- 网站页面还没有令牌列表与吊销按钮。吊销走 `DELETE /api/auth/me/mcp-tokens/{token_id}`，或在同一客户端重新授权以替换旧令牌。

npm/GitHub 安装的 DSH 插件不要求网站登录。插件省略 `mcpToken` 时完全省略 `Authorization` header，因此可直接使用公开 runtime；只有明确配置 Token 时才进入账号渠道，个人收藏等私有能力需要有效 Token。

## 限流与调用额度

实现见 [`mcp-go/internal/ratelimit/ratelimit.go`](../mcp-go/internal/ratelimit/ratelimit.go)。协议请求先经过 Redis 60 秒固定窗口的突发限流：

| 调用方 | 协议方法（initialize / tools/list / resources / prompts） | tools/call |
| --- | --- | --- |
| 匿名（按客户端 IP，取可信代理 X-Forwarded-For 首跳） | 60 次/分 | 30 次/分 |
| 认证（按用户 id） | 240 次/分 | 120 次/分 |

只有 `tools/call` 继续进入商业调用额度。额度窗口从该身份首次调用起计时，不按自然日或自然月重置：

| 档位 | 身份分桶 | 固定 24 小时窗口 | 滚动 30 天窗口 |
| --- | --- | ---: | ---: |
| 匿名 | 客户端 IP | 10 次 | — |
| Free | 用户 id | 20 次 | 400 次 |
| VIP | 用户 id | 400 次 | 8,000 次 |
| 管理员 | 用户 id | 豁免 | 豁免 |

- 2026-10-08 起匿名与 Free 降为原来的三分之一（此前匿名 30 次；Free 60 次 + 1,200 次），VIP 不变；匿名每 24 小时用满、连用 30 天（300 次）仍低于 Free 的 30 天额度（400 次）。
- MCP 与程序化 REST `/api/v1/projects/search`、`/api/v1/projects/categories` 使用相同 Redis key，调用会消耗同一个共享池；网站浏览端点 `/api/projects` 不参与该额度。
- 登录档先检查 24 小时 pacing 桶，通过后才消耗滚动 30 天桶；被短窗口拒绝的请求不会消耗长窗口额度。
- 超限返回 HTTP 429，响应体为 JSON-RPC error（code `-32000`），并带与实际剩余窗口相符的 `Retry-After` 头；`error.data.quota_scope` 为兼容保留 `daily` / `monthly` 字面量，但用户文案使用“每 24 小时”与“滚动 30 天”。
- 解析失败的畸形请求直接返回 JSON-RPC 错误，不计入配额。
- Redis 不可用时放行（可用性优先于限流严格性），与认证端点限流策略一致。

## 每日用量汇总

实现见 [`mcp-go/internal/usage/usage.go`](../mcp-go/internal/usage/usage.go)，读取见 [`backend/app/monitoring/mcp_daily_usage.py`](../backend/app/monitoring/mcp_daily_usage.py)。管理员在监控页「MCP 调用」分区查看，接口为 `GET /api/monitor/mcp-usage?days=1..31`（默认 14，仅管理员）。

- 按北京时间计日，分匿名（未带令牌）/ 免费 / 会员（实时生效档位）三类；管理员请求与压测 UA 整体不记。
- 指标：去重客户端（HyperLogLog；登录用户按账号，匿名按「当天日期 + IP」的 SHA-256 摘要前 16 位，Redis 里不出现原始 IP；多天合计取并集，不是逐日相加）、连接次数（`initialize`）、放行的 `tools/call` 次数（按工具名，不在注册表的名字记 `__unknown__`）、429 次数（按分钟突发 / 24 小时 / 30 天分类，被拒请求不算调用）。
- 客户端名取 `initialize` 的 `params.clientInfo.name` 并小写；空名记 `__unknown__`，含非法字符或超过 48 个字符记 `__other__`；每天最多收 64 个名字（三类合计），之后的新名字并入 `__other__`。
- 键为 `mcpusage:{day}:*`，保留 400 天；`mcpusage:since` 记首次记录日，监控页据此不把开始统计前的日子显示成 0。写入是单次 Lua 原子执行、250 ms 超时且失败只记日志，不影响 MCP 响应；读取时 Redis 不可用返回 `available=false` 的同形零值。

## 与 `/api/ops/mcp-servers` 的区别

管理员页面中的 `/api/ops/mcp-servers` 是配置**外部** MCP Server 的出站管理能力（含连接测试），
与本文描述的入站 `/api/mcp` 服务不是同一条链路。

## 测评套件

`evals/mcp/` 提供本服务的端到端契约与场景测评（基于 mcp-eval，详见 `evals/mcp/README.md`）：

- 运行入口：`evals/mcp/run.sh`（全部用例；追加文件名可只跑契约层 `test_contract.py` 或场景层 `test_scenarios.py`）。
- 测评配置：`evals/mcp/mcpeval.yaml`（默认打本机 `http://127.0.0.1:8000/api/mcp`，改 `url` 可指向其他环境）。
- 凭据约定：Bearer 头存放于 `evals/mcp/mcpeval.secrets.yaml`（0600），由 `run.sh` 首次运行自动生成；
  该文件与 `test-reports/` 报告、缓存目录均被 `evals/mcp/.gitignore` 排除，一律不入库。
