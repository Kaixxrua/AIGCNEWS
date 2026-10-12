# DailyHot 聚合热榜源（自托管 DailyHotApi）

站点第 8 个内容源 `dailyhot`：聚合中文互联网各站热榜（默认 36氪、IT之家、
少数派、掘金、知乎、虎嗅、极客公园、爱范儿），上游为编排内网自托管的
[imsyy/DailyHotApi](https://github.com/imsyy/DailyHotApi)（MIT）。
采集 → 简报生成 → 订阅派发全部复用既有管线，无 schema migration。

## 架构位置

```
scheduler(dailyhot_hotlists, 每小时 :07)
  → DailyHotCrawler → http://dailyhot:6688/<endpoint>（编排内网，不经代理）
  → documents(source='dailyhot', source_channel='dailyhot_daily')
  → 8:00 简报生成（_PROMPT_DAILYHOT，缓存 key 后缀 _dailyhot）
  → subscription_dispatch 派发（source='dailyhot' 订阅）
```

- 端点级失败只跳过该端点；所有已配置端点均失败（包括 HTTP 500、
  连接失败或业务错误）时，本次采集返回 `dailyhot_all_endpoints_failed`，
  单源任务记为失败。上游成功但榜单为空仍视为正常零产出，
  不影响其他源；热榜条目的跨站 hot 量级不可比（知乎千万级、少数派十几、
  虎嗅/爱范儿恒为 0），hot 只用于端点内取 Top-N，`score` 与 `raw_score`
  同为端点内名次分（榜首 100 逐名递减）。入库 Top-N、日榜快照与简报选稿都按
  `raw_score` 优先排序，存原始 hot 会让知乎与极客公园包揽每轮 Top-10。
- MCP `SourceChoice` 枚举刻意未扩展（wire-format Red 变更，随 B 路线单独评估）。

## 部署（一次性）

`manage_main_stack.sh` 以 `--no-build` 启动，镜像必须预构建；DailyHotApi
源码不进本仓库，按 PriceAI 先例在部署主机同级检出：

```bash
cd /home/<user>                 # 与 AIGCNEWS 检出同级
git clone --depth 1 https://github.com/imsyy/DailyHotApi.git
cd AIGCNEWS
docker compose -f docker/docker-compose.yml --profile dailyhot build dailyhot
```

随后在 `.env` 追加 `COMPOSE_PROFILES=dailyhot`（systemd EnvironmentFile 会
传给 compose CLI），`systemctl restart aigcnews-compose@<user>` 或
`scripts/manage_main_stack.sh up` 拉起。服务仅 `expose 6688`（编排内网），
backend 的 `NO_PROXY` 已含 `dailyhot` 服务名。

## 配置（.env）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `DAILYHOT_API_BASE_URL` | `http://dailyhot:6688` | 上游地址（编排服务名） |
| `DAILYHOT_ENDPOINTS` | `36kr,ithome,sspai,juejin,zhihu,huxiu,geekpark,ifanr` | 端点路由名，可选值见 DailyHotApi `src/routes/`（约 60 个） |
| `DAILYHOT_PER_ENDPOINT_LIMIT` | `5` | 每端点按 hot 降序保留条数 |
| `DAILYHOT_REQUEST_TIMEOUT_SECONDS` | `8.0` | 单端点请求超时 |
| `DAILYHOT_OUTBOUND_PROXY` | 空（直连） | DailyHotApi 出站 HTTP 代理，如 `http://host.docker.internal:7897`；代理需为各热榜站点配置可用出口 |

`DAILYHOT_OUTBOUND_PROXY` 注入 DailyHotApi 容器的 `HTTP_PROXY` 和
`HTTPS_PROXY`，不改变 backend 到 `dailyhot:6688` 的内网请求。修改后需
仅重建 DailyHot 容器（无需重建镜像）才能生效。健康检查只检测本地 HTTP
服务，不能证明上游热榜可达；应逐端点确认 HTTP 200 和非空 `data`。

## 验证

```bash
docker exec aigc-backend python -c \
  "import asyncio; from backend.app.services.ingestion.source_dailyhot import fetch_dailyhot_items; \
   print(len(asyncio.run(fetch_dailyhot_items(base_url='http://dailyhot:6688', endpoints=['ithome']))))"
```

非 0 即链路通；随后监控页手动触发 `dailyhot_hotlists` 或等整点 :07。
