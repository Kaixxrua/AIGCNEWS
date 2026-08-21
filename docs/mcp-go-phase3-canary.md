# Go MCP Phase 3 金丝雀验证记录

日期：2026-08-21

## 范围

本次只验证隔离回环金丝雀，不切生产流量。Python MCP 作为控制组，Go MCP 作为候选组；不修改 DNS、边缘路由、生产 Compose、私有 overlay，也不下线 Python 服务。

- Python 控制组：`http://127.0.0.1:8003`（临时隔离容器；现有生产控制实例未触碰）
- Go 候选组：`http://127.0.0.1:8002`（临时隔离容器）
- 两者使用现有编排网络中的 Redis、Milvus、PostgreSQL 依赖。
- 临时容器均已停止并删除；共享依赖及其数据卷未删除。

## 静态门禁

以下检查通过：

- `go mod tidy`，且 `go.mod`/`go.sum` 无变化
- `go build ./...`
- `go vet ./...`
- `go test ./... -count=1`
- `backend/tests/parity/test_live_diff.py`：27 passed，1 个既有 Pydantic 弃用警告
- `live_diff.py --list --replay static`：列出 74 个冻结静态用例

Go 镜像首次构建使用默认 `proxy.golang.org` 时因网络超时失败；改用 Docker build arg `GOPROXY=https://goproxy.cn,direct` 后构建成功。该网络 workaround 未改 Dockerfile 或仓库配置。

## 探活证据

Go 镜像启动后：

- `/api/live`：HTTP 200，`{"status":"ok"}`
- `/api/version`：HTTP 200，版本 `1.2.0`
- `/api/ready`：HTTP 200，`runtime_ready=true`，configuration/postgres 检查通过
- 镜像 healthcheck：healthy
- 日志确认 Postgres 连接池、Redis 限流层和 HTTP listener 均成功启动

隔离 Python 控制容器也达到 healthy，`/api/live` 与 `/api/ready` 均返回 HTTP 200。其启动日志显示 Redis、语义检索 warmup 和 Milvus 初始化成功；其中 PyMilvus 发出既有弃用/代理 scheme 警告，但未阻止 readiness。

Go 当前 readiness 的直接检查是 Postgres Ping；Redis/Milvus 由 Compose 依赖健康条件覆盖，不能将该端点解释为完整的语义依赖诊断。

## Live differential 结果

命令：

```bash
python3 backend/tests/parity/live_diff.py \
  --python-mcp http://127.0.0.1:8003 \
  --go http://127.0.0.1:8002 \
  --replay static --timeout 15 --warmup 1 \
  --json-report /tmp/phase3-live-diff-isolated.json
```

报告：`/tmp/phase3-live-diff-isolated.json`（不进入仓库）。

结果：59 个用例执行，51 个一致，8 个差异，0 个请求错误。前四个 prompts/get 用例及其余协议/资源/错误用例已通过；差异为：

1. `tools-list`
2. `tools-list-id-null`
3. `tools-list-id-float`
4. `tools-list-id-bool`
5. `tools-list-id-zero`
6. `mcp-cors-preflight-allowed`
7. `mcp-cors-preflight-disallowed`
8. `mcp-post-with-origin`

`tools/list` 的差异是 Go 静态工具 schema 中 `search_github_projects` 的 `sort` enum 顺序与当前 Python 控制组不同（Python 以 `relevance` 开头，Go 语料生成版本以 `relevance` 结尾）；该差异会影响完整响应字节，但不是请求处理失败。

CORS 差异是 Go 当前手写 HTTP 层没有 Python FastAPI 的 CORS middleware：预检请求返回 405，而 Python 对允许 origin 返回 200、对不允许 origin 返回 400；带 origin 的 POST 也缺少 `access-control-*`/`vary` 响应头。该差异是实际 Phase 3 blocker，不能宣称全量 live parity 通过。

另一次直接复用现有 Python 生产控制容器的比较曾触发 Go 进程级 Redis 限流状态（429），因此没有将该结果计入最终报告；正式结果使用临时隔离 Python 控制容器，避免共享控制端点和限流状态造成混淆。

## 修复与重跑（2026-08-21 后续）

两个 blocker 均已修复：

1. **tools/list schema 顺序**：权威 Python 源 `backend/app/services/mcp/contracts.py` 的 `ProjectDiscoverySort` 改为 `hot, stars, updated, recent, name, relevance`（`relevance` 殿后），使 Pydantic 生成的 `inputSchema` enum 顺序与冻结语料/Go 静态 catalog 一致。未改生成的 `catalog_tools.go` 或冻结 corpus。
2. **CORS**：Go 手写 HTTP 层新增与 Python FastAPI/Starlette 等价的 CORS 包装层（`mcp-go/internal/probes/cors.go` + `CORS_ALLOWED_ORIGINS` 配置），覆盖允许的/拒绝的预检与带 origin 的简单响应头。

重跑命令同前，报告写入 `/tmp/phase3-live-diff-after-fixes.json`（不入库）。

**结果：59 个用例执行，59 个一致，0 个差异，0 个请求错误，exit 0。** 五个 tools/list 变体与三个 CORS 用例全部通过，live parity 现为通过。

## 结论与后续

Phase 3 的安全启动、探活和静态 live differential 已执行并通过。金丝雀可启动且 **live parity 通过**（59/59，0 差异）。

生产流量切换、DNS、边缘切换、生产 Compose 路由、观测 bake、回滚和 Python retirement 仍需单独设计、授权和验证；本记录不构成任何切换授权。

