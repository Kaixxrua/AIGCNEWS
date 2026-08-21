# Go MCP W6 Python 网关层退役清单与预案

日期：2026-08-21（烘焙期评估产物；执行须等收尾检查全绿后逐单元落地）

## 前置状态

- 生产 `/api/mcp` 已由 aigc-mcp-go 服务（W5，main ee4e9f5），烘焙中；
  回滚 = `docker tag docker-frontend-web:pre-mcpgo-rollback
  docker-frontend-web:latest` + force-recreate frontend-web。
- Go 语义搜索经 EMBEDDING_PROVIDER/API_KEY/BASE_URL/MODEL_NAME 直连
  托管 embedding 端点（与 Python 同 env），**不回调任何 Python 进程**
  ——删除 Python MCP 层不影响 Go 语义搜索。
- 注意：W6 合并到 main 后，生产生效时点 = 下一次 aigc-backend 重启
  （bind mount）。重启后路由级回滚（回落 Python）不复存在，回滚变为
  revert W6 提交 + 重启 backend；但 nginx 已把 /api/mcp 钉给 Go，
  意外重启不会断 MCP。

## import 闭包分析（2026-08-21 实测）

外部对 `backend/app/services/mcp/` 的引用（删除红线）：

| 消费方 | 引用 | 处置 |
|---|---|---|
| app/main.py:76,299 | `inbound.tools.MCP_TOOL_REGISTRY`（启动播种指标） | 改为冻结的 8 工具名常量表 |
| app/main.py:487 | `routes_mcp` 挂载 | 删除挂载 + import |
| app/mcp_main.py | 整个独立入口 | 整文件删除 |
| app/api/dependencies.py:92 | `admin_service.McpAdminService` | **保留** |
| app/api/routes_ops_mcp.py:14 | `admin_service`（ops 后台 MCP 管理） | **保留**（路由不动） |
| app/api/routes_projects_api.py:31 | `inbound.context.McpAuthorizationContext` | **保留** context.py |
| app/services/mcp_connection_tester.py:8,20 | `protocol` + `transport.StreamableHttpTransport`（用户侧 MCP 连通性测试，客户端角色） | **保留** protocol.py / transport.py |
| app/core/app_version.py:24 | `inbound.catalog.MCP_SERVER_VERSION` | 常量内联后删除 catalog.py |
| app/services/api_access/quota.py | 无直接引用 | — |
| app/monitoring/* | 无 services/mcp 引用（dashboard 计数读 Redis/JSON，Go 已是唯一写者） | — |

## 执行单元（每单元独立提交 + 落地，顺序执行）

1. **U1 解耦播种**：main.py 的 MCP_TOOL_REGISTRY 播种改为冻结常量表
   （8 个工具名即契约），同时内联 app_version 的 MCP_SERVER_VERSION。
   门禁：backend 相关单测（metrics 播种、version）。
2. **U2 摘除挂载**：main.py 删 routes_mcp 挂载/import；删
   app/api/routes_mcp.py。门禁：启动冒烟（import main 成功、
   /api/live 就绪）、ops 路由回归。
3. **U3 删独立服务**：删 app/mcp_main.py + docker-compose.yml 的
   mcp-api 服务块（100–160 行区，含 mem_limit/HF 缓存/独立
   metrics 目录注释）；同步 NO_PROXY 列表可保留别名（无害）。
   门禁：compose config 校验；生产侧 aigc-mcp 容器已空闲，
   落地后 `docker rm -f aigc-mcp`（运行侧清理，不入提交）。
4. **U4 删入站工具栈**：services/mcp/inbound/ 下除 context.py
   （及 catalog.py 已于 U1 摘除引用）外的 handler/tools 栈；
   services/mcp 保留下属白名单：admin_service.py、protocol.py、
   transport.py、inbound/context.py。逐文件删前重跑 import 闭包
   grep 复核。门禁：backend 全量单测（-p no:mcp_eval）。
5. **U5 测试/语料收口**：删 tests/parity/{live_diff,recorder}.py 与
   test_corpus_parity.py、test_live_diff.py（失去 Python 腿）；
   corpus/ + manifest **保留**为冻结契约文档（Go 侧生成物
   catalog_tools.go 的来源）；删针对 Python handler 的
   test_mcp_*.py，保留针对保留模块（admin_service/protocol/
   transport/context）的用例。门禁：backend 全量单测。
6. **U6 运行侧收尾**（不入提交）：确认无 w3-python/w3-redis 残留
   容器；删 parity_py/parity_go 孪生库；frontend 镜像从 main 干净
   重建一次消除 delta tag 漂移（conf 与 main 一致，可择机）。
7. **U7 文档**：更新 docs/mcp-go-w5-blue-green-cutover.md 结论与
   本文件状态；memory 收尾。

## 风险与红线

- U1–U5 任一门禁失败即停，不得带失败落地。
- 全程不动 aigc-mcp-go 运行实例；不动 frontend 路由（已指向 Go）。
- 删除 admin_service/protocol/transport/context 之外任何被引用文件
  前必须重跑闭包 grep 证明无引用。
- shared redis-aigc 的公网限流键一律不动。
