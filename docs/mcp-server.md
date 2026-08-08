# AIGC Radar MCP Server 协议与策略

AIGC Radar 是 AIGCNEWS 面向 Agent 的旗舰数据接口（MCP `serverInfo.name` 为 `aigc-radar`，版本见
[`backend/app/services/mcp/inbound/catalog.py`](../backend/app/services/mcp/inbound/catalog.py)）。
本文是协议参数、内置策略与鉴权语义的权威文档；README 仅保留接入概览。

> 命名说明：`serverInfo.name` 与 session id 前缀已随品牌更名迁移至 `aigc-radar`；
> `aigc-news://` 资源 URI 是稳定标识符，永久保持不变，客户端可安全存储。

## 客户端接入

- 生产 endpoint：`https://aigcnews.cn/api/mcp`（Streamable HTTP）；自托管本地开发为 `http://localhost:8000/api/mcp`
- Claude Code：`claude mcp add --transport http aigc-radar https://aigcnews.cn/api/mcp`
- 站内 onboarding：Web 站点为 Claude Code、Cursor、Codex、OpenCode、Cline / Roo Code、Continue、
  Windsurf、VS Code 与通用 JSON 共 9 类客户端生成导入配置与命令
- 仅支持 stdio 的客户端：经社区标准桥 `npx mcp-remote https://aigcnews.cn/api/mcp` 接入；
  需要私有工具时追加 `--header "Authorization: Bearer <MCP access token>"`

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
| `search_papers` | arXiv 论文专搜 |
| `search_documents` | 跨来源索引搜索（明确搜索站内新闻或跨来源索引时使用） |
| `get_top_items` | 日 / 周 / 月榜单快照 |
| `get_paper_detail` | 单条索引文档详情 |
| `get_project_categories` | 项目分类与子类计数 |

私有工具：

| 工具 | 用途 |
| --- | --- |
| `search_my_project_favorites` | 检索当前认证用户的个人项目收藏（需 Bearer Token） |

输入按发布的 JSON Schema 严格校验；日期参数必须是真实的 `YYYY-MM-DD` 日历日期。
项目搜索使用一致的关键词、排序和分页语义；结果通过 `result_origin` 标记来源（本地目录或
`github_api_fallback`）。

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

该策略以英文原文通过 `initialize` instructions、工具描述和 Prompt 发布（见 catalog.py 的
`MCP_HOST_INSTRUCTIONS`），但服务端无法覆盖客户端自己的 system prompt 或原生工具优先级。策略依据的
实测对比见 [mcp-vs-websearch-agent-project-discovery.md](mcp-vs-websearch-agent-project-discovery.md)。

## 本地优先与 GitHub fallback

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

- 公开工具与公开 resources 无需鉴权。
- 携带 `Authorization: Bearer <MCP access token>` 的请求按 token 对应的用户与 scope 鉴权，
  解锁私有工具 `search_my_project_favorites`；token 无效返回 401。
- MCP access token 由站内账号体系签发与管理，与登录 JWT 相互独立。

## 限流

端点按 Redis 固定窗口限流（窗口 60 秒，实现见 `backend/app/services/mcp/inbound/rate_limit.py`）：

| 调用方 | 协议方法（initialize / tools/list / resources / prompts） | tools/call |
| --- | --- | --- |
| 匿名（按客户端 IP，取 X-Forwarded-For 首跳） | 60 次/分 | 30 次/分 |
| 认证（按用户 id） | 240 次/分 | 120 次/分 |

- 超限返回 HTTP 429，响应体为 JSON-RPC error（code `-32000`），并带 `Retry-After: 60` 头。
- 解析失败的畸形请求直接返回 JSON-RPC 错误，不计入配额。
- Redis 不可用时放行（可用性优先于限流严格性），与认证端点限流策略一致。

## 与 `/api/ops/mcp-servers` 的区别

管理员页面中的 `/api/ops/mcp-servers` 是配置**外部** MCP Server 的出站管理能力（含连接测试），
与本文描述的入站 `/api/mcp` 服务不是同一条链路。

## 测评套件

`evals/mcp/` 提供本服务的端到端契约与场景测评（基于 mcp-eval，详见 `evals/mcp/README.md`）：

- 运行入口：`evals/mcp/run.sh`（全部用例；追加文件名可只跑契约层 `test_contract.py` 或场景层 `test_scenarios.py`）。
- 测评配置：`evals/mcp/mcpeval.yaml`（默认打本机 `http://127.0.0.1:8000/api/mcp`，改 `url` 可指向其他环境）。
- 凭据约定：Bearer 头存放于 `evals/mcp/mcpeval.secrets.yaml`（0600），由 `run.sh` 首次运行自动生成；
  该文件与 `test-reports/` 报告、缓存目录均被 `evals/mcp/.gitignore` 排除，一律不入库。
