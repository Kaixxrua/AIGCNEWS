# AIGC Radar MCP — Go 实现（生产承载）

Python MCP 入站（`backend/app/services/mcp/inbound/*` 与独立进程
`mcp_main.py`，均已随 W6 退役删除）的全量 Go 重写，现为生产 `/api/mcp`
的唯一承载：抗高并发、单容器静态二进制、与 Python 版**逐字节**线格式
一致（冻结语料回放门禁常驻）。

## 当前状态（生产承载中）

- ✅ 生产流量：W5 蓝绿切流完成，frontend nginx `location = /api/mcp`
  直连本服务；W6 已删除 Python 网关层（main `4289909`：入站工具栈、
  独立进程与回放线束全删）

- ✅ 配置装载（环境变量与 Python `config.py` 同名同默认值）
- ✅ Postgres 连接池与仓储适配器（pgx/v5，DSN/超时/statement_timeout 对齐 psycopg 口径）
- ✅ `/api/live`、`/api/version`、`/api/ready` 三端点字节对齐
  （404/405/307 形状按 mcp_main.app 实测复刻；语料用例直接回放比对）
- ✅ Dockerfile（静态二进制 → alpine，uid 1000）与 compose 服务 `mcp-api-go`
- ✅ `/api/mcp` 协议面：解析/校验（wire）、有序紧凑 JSON（jsonx）、
  Bearer token 认证（authn，SQL 与 Python 仓储逐字同义）、无状态分派
  （mcpapp：initialize/通知/未知方法/tools/call、resources、prompts）；非 POST 405、
  panic → 500 纯文本均按 Starlette 口径复刻
- ✅ `/api/mcp/oauth` OAuth 入口（`mcpapp.OAuthEntry`）：与 `/api/mcp` 共用 App、认证器、
  限流器与用量记录，只是不收匿名请求；401 质询带 RFC 9728 `resource_metadata`，
  授权服务器在 Python 主后端（流程见 `docs/mcp-server.md`「浏览器授权（OAuth）」）
- ✅ Redis 固定窗口限流：分钟突发桶 + tools/call 分层配额、TTL 自愈、
  Redis 故障 fail-open、可信代理 XFF 首跳归因；限流缝严格位于解析之后、
  分派之前，429 JSON-RPC 投影与 Python 逐字节一致
- ✅ 工具目录与已迁移工具：文档/论文详情、官方榜单、资源、项目分类、
  GitHub 项目搜索（AI 与非 AI）、收藏夹、采纳回执及 prompts/get
- ✅ 回放门禁 `internal/replay`：protocol、surface、tools、resources 与 prompts
  语料逐字节回放；包含 miniredis + warmup 的 `rate-limited-429` 场景
- ✅ Python-vs-Go 静态 live-diff helper 与 CI gate 已加入；运行时依赖服务可用时
  可执行等价服务回放对照

Python 网关层已删除：配额桶/版本名等跨语言契约由冻结字面量与
`internal/version` 常量双向钉住（见 backend 侧契约测试）。回滚 =
revert W6 提交 + 重启 aigc-backend；nginx 路由回滚镜像 tag
`docker-frontend-web:pre-mcpgo-rollback` 仍保留。

## 设计要点

- **不用任何 MCP SDK**：语料冻结了多处刻意非标准行为（无 id 通知 204、
  协议错误走 HTTP 200 + JSON-RPC 信封、429 + `-32000` + Retry-After 等），
  手写 net/http 逐字复刻比对抗 SDK 抽象更短、可回放验证。
- **回放门禁**：`internal/probes` 的测试直接消费
  `backend/tests/parity/corpus/surface.jsonl`；后续每个包都以语料为硬门禁。
- **版本同源**：`internal/version` 读仓库根 `server.json`，容器内回退常量
  （与 `catalog.py MCP_SERVER_VERSION` 同步；测试钉住防漂移）。
- **连接池 fail-fast**：启动即 Ping，DB 不可达拒启动（对齐 Python
  lifespan `pool.open()` 语义），拒绝半就绪服务。

## 本地开发

```bash
cd mcp-go
go build ./... && go vet ./... && go test ./... -count=1
```

运行（需要可达的 PostgreSQL；变量名与 Python 完全一致）：

```bash
POSTGRES_HOST=127.0.0.1 POSTGRES_USER=... POSTGRES_PASSWORD=... \
POSTGRES_DATABASE=... POSTGRES_SSLMODE=disable \
go run ./cmd/mcp-server
# → :8000 上提供 /api/live /api/version /api/ready /api/mcp
```

## 容器

```bash
docker build -f mcp-go/Dockerfile -t aigc-mcp-go:dev .
docker compose -f docker/docker-compose.yml up -d mcp-api-go   # 127.0.0.1:8002
```

金丝雀期与 Python `mcp-api`（8001）并存；生产切换由边缘层决定（Phase 3）。
