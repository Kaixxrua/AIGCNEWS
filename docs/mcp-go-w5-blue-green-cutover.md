# Go MCP W5 蓝绿切流执行记录

日期：2026-08-21

## 范围

W5 把生产 `/api/mcp` 从 Python 主后端切到 Go 网关，业务零中断、秒级可回滚。
Python 服务全程在线；本单元不改 DNS/边缘（CN Caddy 无 MCP 专属路由，
`@api → 127.0.0.1:18443` 直连本机 frontend），只动编排内两层：
Go 容器入栈 + frontend nginx 精确路由。

## 生产路由事实（切流前）

- 广告端点 `https://aigcnews.cn/api/mcp` 由 aigc-frontend 的
  `location /api/` 前缀块代理到 `aigc-backend:8000`——**主后端进程
  （main.py:487 同样挂载 routes_mcp）在服务 MCP**，独立
  aigc-mcp:8001 长期空闲（24h 内 286 次 POST 全部是 Phase 3 测试）。
- `frontend/nginx.conf` 烘焙进 docker-frontend-web 镜像（byte 级一致
  已验证），私有 overlay 仅注入 ssl + private incs，无 MCP 引用。
- TRUSTED_PROXY_IPS=127.0.0.1,::1,172.16.0.0/12 覆盖 frontend
  （172.19.0.12）；Go clientip 支持 CIDR 口径。

## W5a：Go 容器入生产栈（零流量变更）

- 镜像 `aigc-mcp-go:phase4`（W2 门禁全绿位）tag 为
  `docker-mcp-api-go:latest`，按 manage_main_stack.sh 的正典调用
  （双 env-file + 私有 overlay + --profile mcp-go）
  `up -d --no-deps mcp-api-go` 启动。
- **坑**：首次启动因 8002 被 W3 金丝雀 w3-go 占用失败，残留坏网络端点
  → 容器内 /etc/resolv.conf 异常、纯 Go resolver 直询 8.8.8.8 报
  network unreachable 崩溃循环。修法：移除已完成的 W3/W4 金丝雀
  w3-go + `--force-recreate` 重建，端点正常（172.19.0.14/16）。
- 验证：ready/live 200；env 钉死 REDIS_HOST=redis-aigc、
  POSTGRES_DATABASE=aigcnews_catalog（生产库）、TRUSTED_PROXY_IPS
  与 Python 同口径；bench UA 前缀为双端硬编码常量
  （`mcp-latency-bench/`，metrics.go:40 ↔ mcp_tools.py:45），无需配置；
  真实 JSON-RPC（search_papers）对生产库正常返回；**其他容器零重建**
  （uptime 全部不变）。

## W5b：nginx 精确路由切流

- 提交 ee4e9f5：`location = /api/mcp` 变量化 proxy_pass 至
  `aigc-mcp-go:8000`（$request_uri 恒等映射，与 /api/ 块同口径；
  经 http 级 resolver 127.0.0.11 动态解析容器 IP），
  限流（api_general burst=50）/转发头（XFF=$remote_addr 还原口径）/
  SSE（buffering off、300s 超时）逐条对齐 /api/ 块。
  仅精确路径——其余 /api/* 仍由 Python 主后端服务。
- 门禁：pin 产线基镜像 nginx:alpine@sha256:4a73073… nginx -t 通过；
  CSP 哈希契约 5/5 绿（未触 CSP 行）。
- 部署：frontend 容器 rootfs 只读（docker cp 不可写）→ 单层镜像 delta
  （FROM 运行中镜像 + COPY 新 conf，SPA 层字节不变）→
  `up -d --no-deps --force-recreate frontend-web`，中断约 3s。
  旧镜像保留 `docker-frontend-web:pre-mcpgo-rollback`。

## 切流验证证据

1. **在途连接实锤**：get_top_items（~12s 慢查询）请求中途抓 frontend
   网络命名空间 /proc/net/tcp：到 `0E0013AC:1F40`（172.19.0.14:8000 =
   aigc-mcp-go）的连接 **ESTABLISHED**；到 aigc-backend:8000 的全部为
   TIME_WAIT 残留。生产 /api/mcp 确由 Go 服务。
2. 公网边缘 e2e（bench UA，不进 dashboard 计数）：initialize、
   tools/list（8 工具）、search_github_ai_projects、get_top_items、
   非法 method（-32601）全部符合冻结契约。
3. CORS 经边缘一致：允许源 preflight 200 + allow-origin 回显 +
   max-age 600 + Vary: Origin；非法源 400 无 allow-origin。
4. 普通 REST（/api/live 等）仍 200——Python 主后端正常服务其余 API。

## 回滚程序（两级）

- **路由级（秒级）**：旧 conf 已在 git（c3a6062:frontend/nginx.conf）；
  重建单层镜像指向旧 conf 或直接 `docker tag
  docker-frontend-web:pre-mcpgo-rollback docker-frontend-web:latest`
  + `up -d --no-deps --force-recreate frontend-web`，/api/mcp 自动
  回落 /api/ 块 → Python。
- **Go 服务级**：`docker stop aigc-mcp-go` 后路由级回滚。
- Python 侧全程未动，天然兜底。

## 烘焙期监控项

- aigc-mcp-go：重启次数、RSS（基线 ~15MB，上限 512m）、ERROR 日志。
- redis-aigc `mcpmetrics:total` 随真实流量自然自增（Go 为唯一写者后
  双写影子文件不再更新——生产 backend 本无 MCP_TOOL_CALL_METRICS_PATH）。
- 429 行为：公网 IP 限流桶照常累积。
- 注意：本镜像 delta 仅在 latest tag；main 已含新 conf，下次常规前端
  发布烘焙后无漂移。

## 追加：健康检查代理坑（同日修复 3a0e88c）

切流后发现 aigc-mcp-go 报 unhealthy：compose 注入的 socks5h 出站代理
变量被镜像内 busybox wget 探针继承——wget 不支持 socks5h 且不读
NO_PROXY，探针全挂但服务本身正常（Python 镜像探针用 python/curl 故
同 env 下无恙）。修复 = Dockerfile HEALTHCHECK 命令加进程级空代理
前缀；一次性容器共享网络命名空间复现（exit=1）并验证（exit=0）。
生产用单层 delta 镜像（二进制不变）+ force-recreate 落地，容器
healthy，边缘 200。教训：凡注入代理变量的容器，探针/内部回环调用
必须进程内清代理。

## 结论

生产 MCP 流量已由 Go 网关服务，行为与 Python 逐字节等价（W3 94/94 +
写路径），性能基线占优（W4）。进入烘焙期；金丝雀健康后执行 W6
（删除 Python 网关层：main.py routes_mcp 挂载、mcp-api 服务、
mcp_main.py 与工具处理器）。

**2026-08-22 更新**：烘焙通过，W6 已执行完毕——U1–U3（指标播种解耦、
挂载摘除、独立进程与回放线束删除：`16244f3` / `645a053` / `852a3da`）
与 U4（入站工具栈删除，`4289909`）全部落地；U5 收口复核零残留，
U6 运行侧清理完成（aigc-mcp / w3-python / w3-redis 容器移除，
parity_py / parity_go 孪生库已 drop）。回滚姿态变化：nginx 路由
回滚镜像 tag 仍有效；Python 侧代码已不存在，回退 Python 承载需
revert W6 提交并重启 aigc-backend。
