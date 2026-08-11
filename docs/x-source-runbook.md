# X/Twitter 信息源运维 Runbook

> **可插拔源**：X 采集实现（传输层、spike 脚本）位于仓库外私有插件包
> `aigcnews_private`（`scripts/x_ingestion_spike.py` 亦在该仓 `scripts/` 下），
> 经 `x_source_enabled` 开关与部署 overlay 注入。开源检出中本链路不可用，
> 对应路由 404、采集轮自动跳过。本文档面向已部署私有插件的运维方。

X 源通过 `twitter-cli`（X 内部 GraphQL + TLS 指纹）以**主账号 cookie** 抓取关注
账号推文。本文档覆盖：cookie 提取、配置、验收、失效重配与节奏调整。

> ⚠️ **风险声明**：cookie 抓取属于 X 未授权访问方式，主账号存在被限流、
> 冻结甚至封号的风险。接入即表示接受该风险。系统已内置缓释措施
> （见下文「节奏与风控缓释」），但不能消除风险。

## 凭据与配置项

| 环境变量 | 说明 | 默认 |
| --- | --- | --- |
| `TWITTER_AUTH_TOKEN` | x.com 登录 cookie `auth_token` | （必填） |
| `TWITTER_CT0` | x.com 登录 cookie `ct0`（CSRF token） | （必填） |
| `TWITTER_WATCH_HANDLES` | 关注账号 watchlist，逗号分隔（@ 可选，大小写不敏感） | 空 |
| `TWITTER_TWEETS_PER_ACCOUNT` | 每账号每轮抓取条数 | 20 |
| `TWITTER_INTER_ACCOUNT_DELAY_SECONDS` | 账号间隔基线秒数（实际延迟带 [0.8, 1.6) 抖动） | 5.0 |

## 首次配置

### 1. 提取 cookie

1. 浏览器（Chrome/Edge/Firefox）登录 **x.com**（用主账号）。
2. 打开开发者工具（F12）→ **Application/存储** → **Cookies** → `https://x.com`。
3. 复制两条 cookie 的值：
   - `auth_token`（40 位十六进制，登录态凭证）
   - `ct0`（160 位十六进制，CSRF token）
4. 备选路径：开发者工具 → **Network** → 刷新页面 → 任意 `x.com` 请求 →
   请求头 `cookie:` 中找 `auth_token=...; ct0=...`。

> 提取后**不要在该浏览器上退出登录**——退出会立即吊销 cookie。
> 如需日常浏览，用另一个浏览器/隐身窗口操作账号。

### 2. 写入 .env

```bash
TWITTER_AUTH_TOKEN=<40位hex>
TWITTER_CT0=<160位hex>
TWITTER_WATCH_HANDLES=openai,anthropic,karpathy
```

### 3. 重启后端

docker-compose 透传整个 .env，无需改 compose：

```bash
docker compose restart backend   # 或本地开发：重启 uvicorn
```

### 4. spike 验收（必做）

```bash
python scripts/x_ingestion_spike.py                      # 在私有插件仓 scripts/ 下运行
python scripts/x_ingestion_spike.py --handle openai --count 5
```

- **退出码 0** 且打印推文列表 → 凭据有效，链路通。
- 打印 `x_auth_not_configured` → .env 未生效（检查变量名、是否重启）。
- 打印 `x_auth_expired` → cookie 失效，走「失效重配」。
- 打印 `x_rate_limited` → 触发限流，等待 1–2 小时后重试；频繁出现则
  调大 `TWITTER_INTER_ACCOUNT_DELAY_SECONDS`。

### 5. 触发一次真实采集（可选）

```bash
curl -X POST "http://localhost:8000/api/ops/ingest-source?source=x" \
  -H "Authorization: Bearer <admin_token>"
```

随后确认入库：`documents` 表出现 `source='x'` 的行（频道 `x_daily_watchlist`）。

> **注意**：spike 未通过前不要在生产启用定时任务（`x_watchlist`，
> 每 2 小时一轮，注册于 `scheduler_registry.py`）。

## 失效重配

### 症状

- `ingestion_tasks` 表中 x 源任务连续失败，错误信息含 `x_auth_expired`。
- spike 脚本退出码 1，输出 `x_auth_expired`。
- 监控页（ingestion 任务面板）x 行持续红色失败。

认证失效时采集器会**立即中止整轮**（不会拿死 cookie 锤其余账号），
因此失效期间的每轮调度都会快速失败，不会加剧风控。

### 重配步骤

1. 按「首次配置 → 1」重新提取 `auth_token` + `ct0`。
2. 更新 .env 两个变量。
3. 重启后端。
4. 跑 spike 验收（退出码 0 即恢复）。
5. 下一轮定时任务自动恢复；也可手动 `POST /ops/ingest-source?source=x`。

cookie 典型寿命数周至数月；账号改密、退出登录、X 侧风控重置都会立即失效。

## 节奏与风控缓释

内置缓释（默认值即推荐值，非必要不调）：

- **降频调度**：每 2 小时一轮（其余信息源每小时），`coalesce=True` 错过合并。
- **顺序抓取 + 抖动延迟**：账号间基线 5s × [0.8, 1.6) 随机抖动，不并发。
- **user_id 24h 缓存**：screen_name → user_id 解析结果缓存 24 小时，
  请求量减半。
- **失败即止**：认证失效/限流立即中止整轮；单账号 NotFound/异常仅跳过。
- **过滤广告**：policy 层强制丢弃 `is_promoted` / 转推 / 订阅专属推文。

应急旋钮（改 .env 后重启生效）：

| 场景 | 调整 |
| --- | --- |
| 疑似被限流（`x_rate_limited` 偶发） | `TWITTER_INTER_ACCOUNT_DELAY_SECONDS=10` 或更高 |
| 账号很多（>20 个）轮次过长 | 精简 watchlist，不要盲目调小延迟 |
| 想进一步降频 | 改 `scheduler_registry.py` 中 `x_watchlist` 的 `CronSchedule(hour="*/4", ...)`，需过 scheduler 契约测试 |

## 故障排查速查

| 现象 | 可能原因 | 处理 |
| --- | --- | --- |
| 每轮 0 条、日志「watchlist 为空」 | `TWITTER_WATCH_HANDLES` 未配/全被禁用 | 配 .env 并重启 |
| `x_auth_not_configured` | 凭据缺失或 .env 未加载 | 检查变量名、重启、重跑 spike |
| `x_auth_expired` | cookie 失效 | 走「失效重配」 |
| `x_rate_limited` | 触发 X 限流 | 等 1–2h；调大间隔基线 |
| 某账号持续缺失、日志「不存在/已注销/已改名」 | 账号改名/注销/被封 | 从 watchlist 移除或更新 handle |
| 推文日期全部为空 | X 返回格式漂移 | 提 issue；`parse_tweet_date` 解析失败不阻断入库 |
