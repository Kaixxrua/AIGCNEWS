# AIGC Radar MCP — Go 实现（金丝雀阶段）

Python MCP 入站（`backend/app/services/mcp/inbound/*`，独立进程 `mcp_main.py`）
的全量 Go 重写。目标：抗高并发、单容器静态二进制、与 Python 版**逐字节**
线格式一致。

## 当前状态（PR 1.2）

- ✅ 配置装载（环境变量与 Python `config.py` 同名同默认值）
- ✅ Postgres 连接池（pgx/v5，DSN/超时/statement_timeout 对齐 psycopg 口径）
- ✅ `/api/live`、`/api/version`、`/api/ready` 三端点字节对齐
  （404/405/307 形状按 mcp_main.app 实测复刻；语料用例直接回放比对）
- ✅ Dockerfile（静态二进制 → alpine，uid 1000）与 compose 服务 `mcp-api-go`
- ✅ `/api/mcp` 协议面：解析/校验（wire）、有序紧凑 JSON（jsonx）、
  Bearer token 认证（authn，SQL 与 Python 仓储逐字同义）、无状态分派
  （mcpapp：initialize/通知/未知方法/tools/call 错误面）；非 POST 405、
  panic → 500 纯文本均按 Starlette 口径复刻
- ✅ 回放门禁 `internal/replay`：protocol.jsonl 28 例逐字节通过；
  限流（PR 1.3）与静态清单（PR 1.4）用例显式登记跳过，语料新增即红
- ⬜ 限流（PR 1.3）、工具目录/资源/prompts（PR 1.4）、逐工具移植（Phase 2）

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
