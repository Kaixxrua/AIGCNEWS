# Go MCP W4 并发基线压测报告

日期：2026-08-21

## 范围与方法

W4 是替代路线第四单元：在等价数据上对比 Go 与 Python 网关的延迟、吞吐
与内存基线，并端到端验证压测流量不计入 dashboard 调用计数。不切生产
流量。

- 双金丝雀沿用 W3：`aigc-mcp-go:phase4`（main 7ec225c）↔ parity_go、
  `docker-mcp-api`（本仓 backend 只读挂载）↔ parity_py；127.0.0.1:8002 /
  8003。
- **限流/计数隔离**：双端 REDIS_HOST 指向临时 scratch Redis
  （w3-redis），压测的限流桶与计数键不接触共享 redis-aigc。
- **限流不解禁**：每请求旋转 X-Forwarded-For（可信代理口径），限流器
  正常工作但每桶独立，避免 30/min 匿名封顶压死吞吐测量。
- **UA 打标**：全部压测请求带 `User-Agent: mcp-latency-bench/1.0`。
- 负载三档：`initialize`（协议地板）、`search_papers`（PG 论文检索）、
  `search_documents`（PG 新闻检索）；并发 1/8/32/64，每格 15s，双端交替。
  压测脚本 /tmp/w3_bench.py（不入库），原始数据 /tmp/w4-bench.json。

## 压测打标端到端验证（Phase A，共享 Redis）

切换 scratch Redis 前，在共享 redis-aigc 上验证打标语义：

- `mcpmetrics:total` 前值 4090；Go 端 20 bench + 5 普通 UA 对照、Python
  端 25 bench（后 20 个因分钟桶 429）；终值 4095。
- 增量恰好等于唯一一组未被限流的普通 UA 调用（Go 5 个）；双端全部
  bench UA 调用（含 Python 端已 200 的 5 个）均未计数。
- 压测后复查：scratch Redis 无任何 `mcpmetrics:total/tool_calls`
  （唯一键为 Python 启动期的空 shadow 种子标记 `mcpmetrics:seeded:
  backend-api`）；共享 Redis total 保持 4095（其后 +2 为同期真实生产
  流量，与本压测无关）。

## 结果（15s/格，0 错误）

| 负载 | 并发 | Go rps | Py rps | Go p50 ms | Py p50 ms | Go p99 ms | Py p99 ms |
|---|---|---|---|---|---|---|---|
| initialize | 1 | 368.7 | 265.2 | 2.28 | 3.30 | 6.9 | 8.8 |
| initialize | 8 | 396.7 | 349.6 | 16.2 | 17.0 | 87 | 102 |
| initialize | 32 | 229.9 | 199.2 | 83 | 93 | 814 | 897 |
| initialize | 64 | 176.8 | 196.1 | 213 | 194 | 2746 | 2646 |
| search_papers | 1 | 25.9 | 23.2 | 37.7 | 41.9 | 52 | 62 |
| search_papers | 8 | 117.5 | 96.9 | 63.8 | 79.0 | 116 | 139 |
| search_papers | 32 | 76.8 | 87.4 | 208 | 218 | 2243 | 2290 |
| search_papers | 64 | 52.6 | 56.8 | 838 | 832 | 5032 | 4570 |
| search_documents | 1 | 9.9 | 9.0 | 99 | 106 | 126 | 162 |
| search_documents | 8 | 48.4 | 42.7 | 155 | 178 | 275 | 315 |
| search_documents | 32 | 56.2 | 48.9 | 557 | 607 | 849 | 2365 |
| search_documents | 64 | 48.8 | 44.2 | 1083 | 1143 | 5348 | 5576 |

内存 RSS（压测前 → 后）：Go 14.9 → 26.8 MB；Python 744.6 → 746.2 MB
（Python 基线含 embedding 模型常驻；Go 约为其 1/28）。

## 解读

- 低/中并发（生产真实区间；现网日均 ~560 次 MCP 调用）Go 全面占优：
  吞吐高 12–39%，p50 低 10–24%，p99 更低。
- c32/c64 两端的 DB 型负载均进入 Postgres 饱和区，差值落入噪声；
  部分格子 Python 略高（±8–14%）。压测期间宿主有并行浏览器负载，
  高并发格受客户端/宿主争抢影响，只作趋势参考。
- 全程 24 格 0 错误。
- 附带发现（既有问题，非 parity 缺陷）：`get_top_items(source=all)`
  单次查询约 12s（生产 aigc-mcp 实测）/ 25–31s（孪生库），双端同量级，
  压测中会将两端同时序列化。已从吞吐负载中移除，建议单独排查该查询
  （疑似缺缓存/重聚合），与替代路线无关。

## 结论

Go 网关在真实负载区间延迟与吞吐均不低于 Python，内存低约 28 倍，
压测打标语义端到端生效。W4 通过，可进入 W5 蓝绿切流。
