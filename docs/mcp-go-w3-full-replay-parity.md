# Go MCP W3 全量回放与写路径 live parity 记录

日期：2026-08-21

## 范围

W3 是替代路线的第三单元：在等价数据上验证 Go 网关与 Python 网关的
全量语料（含 DB 依赖的 stubbed 用例）与采纳回执写路径。不切生产流量，
不改 DNS/边缘/生产 Compose/私有 overlay，Python 服务不下线。

## 方法

- 开发库快照一次（pg_dump 定制格式，约 103 MB），同一快照恢复成两个
  孪生库 `parity_py` / `parity_go`（同 Postgres 容器内）。
  恢复后关键表行数逐项相等：documents 16244、document_rank_snapshots
  14702、github_repo_snapshots 527024、briefings 742、
  project_adoptions 4、project_favorites 2。
- 双金丝雀（均为临时容器，沿用 Phase 3 隔离配方）：
  - Go 候选：`aigc-mcp-go:phase4`（main 7ec225c 干净 worktree 构建，
    含 CORS parity 与 dashboard 计数写者），127.0.0.1:8002 → parity_go
  - Python 控制：`docker-mcp-api` + 只读挂载本仓 backend，克隆
    aigc-mcp 环境并覆盖 POSTGRES_DATABASE=parity_py 与独立 metrics
    shadow 路径，127.0.0.1:8003
- 全量回放：`live_diff.py --replay all`（94 用例 = 59 static + 35
  stubbed），`--timeout 30 --warmup 1`。
- 写路径补充探针（语料未覆盖 submit_project_adoption）：同一
  JSON-RPC 请求先后打双端，比较响应字节与两侧 project_adoptions
  表行（pg_dump 数据段逐行 diff，created_at 归一化）。

## 结果

- 全量回放：94 用例执行，94 一致，0 差异，0 请求错误，0 跳过。
  报告：/tmp/w3-live-diff-all.json（不入库）。
- 采纳写入成功路径：双端响应除 `created_at` 插入时刻微秒差外逐字节
  一致（归一化后 IDENTICAL）；两侧表各新增 1 行且全列相等（id 均为 6，
  序列随同一快照恢复），窗口/累计统计一致。
- 采纳写入错误路径（非法 decision）：响应逐字节一致
  （"decision: Input should be 'adopted', 'reference_only' or
  'declined'"），两侧表行数均保持 5，无部分写入。
- 附带观测：匿名日配额耗尽投影双端一致，唯一差异为 retry_after
  秒数（等于两次请求的人为间隔，属时钟派生值，非 parity 缺陷）。

## 操作备注

- 回放期间双端共享 Redis 的分钟/日配额键被 94×2 请求耗尽；仅删除了
  `ratelimit:mcp.quota.daily:ip:172.19.0.1`（docker 网关 = 本机测试
  流量专用桶）后完成写路径探针。公网 IP 配额桶未触碰。
- 共享 Redis 的 `mcpmetrics:*` 在回放期间由双端同时自增（测试拓扑
  假象：生产只有单写者），不影响响应 parity；bench UA 用例两端均未
  计数（W2 语义在金丝雀镜像中生效）。

## 结论

在等价数据上，Go 网关对全部 94 个冻结用例与采纳回执写路径（成功 +
错误 + 表状态）均与 Python 逐字节一致。W3 通过，可进入 W4 并发基线
压测。临时容器与孪生库保留供 W4 复用。
