# 订阅推送（用户订阅与推送渠道）

用户域的订阅推送基础层：用户在站点上绑定推送渠道（当前仅 email），再按
「来源 × 频率 × 渠道」创建订阅。本文是数据模型、API 与策略的权威文档。

> 当前状态：渠道绑定、订阅 CRUD、测试邮件与定时派发均已上线。
> 派发（迁移 0019 `push_deliveries` + `subscription_dispatch` 调度任务，默认每
> 半小时一轮）只读简报缓存做幂等投递，不触发简报生成。
> 与既有 `briefing_subscriptions`（简报邮件订阅）的合并走
> Contract → Extract → Adapt → Switch → Delete，本层上线前不影响其行为。

## 数据模型（迁移 0018 / 0022）

- `push_channels`：`(id, user_id, channel_type, target, encrypted_config, verified, status)`，
  唯一约束 `(user_id, channel_type, target)`；`channel_type ∈ {email, webhook}`（0022 扩展
  CHECK）。`target` 为投递地址：email 渠道无凭据（`encrypted_config` 为 NULL）；
  webhook 渠道的 `target` 存完整 URL（唯一约束与用户可见地址），`encrypted_config`
  存密封后的 `{"url": ...}` 作为投递凭据。
- `user_subscriptions`：`(id, user_id, channel_id, source, frequency, status)`，
  唯一约束 `(user_id, channel_id, source, frequency)`；`frequency ∈ {daily, weekly, monthly}`，
  `status ∈ {active, paused}`。两表均 `ON DELETE CASCADE`：删渠道连带删订阅，删用户连带清空。

## 派发模型（迁移 0019）

- `push_deliveries`：`(id, subscription_id, item_key, status, attempts, last_error, sent_at)`，
  唯一约束 `(subscription_id, item_key)` 保证同一订阅同一期次至多一条投递记录；
  `status ∈ {pending, sent, failed}`，尝试上限 3 次，用尽后置 `failed` 终态不再重试。
  `item_key` 即简报缓存 key（`{期次日期}_{来源?}_{频率}`，周报锚定周一、月报锚定 1 号）。
- `subscription_dispatch` 调度任务（监控页可配起止与轮询）枚举全部频率 × 来源：
  先读 `briefings` 缓存（daily 由 8:00 生成任务填充，weekly/monthly 依赖按需生成），
  缓存缺失直接跳过；命中后对每条「订阅启用 + 渠道已验证启用」的订阅执行一次投递，
  单订阅失败不影响其他订阅。新订阅在下一轮派发即可收到当前期次。

## API（均需登录，响应带 no-store）

| 端点 | 语义 |
| --- | --- |
| `GET /api/push/me/channels` | 列出当前用户的渠道 |
| `POST /api/push/me/channels` | 创建渠道（201）。`channel_type=email`（默认）：向目标邮箱发绑定验证码，已验证重复 409、未验证重发验证码；`channel_type=webhook`：校验 URL 后先做一次真实探测投递，成功才落库且落库即 `verified=true`（webhook 无 OTP 通道，探测即验证），探测失败 400 且不留行 |
| `POST /api/push/me/channels/{id}/verify` | 校验 6 位验证码，置 `verified=true`；验证码错误返回 400 |
| `PATCH /api/push/me/channels/{id}` | 启用/停用渠道（`status: active\|disabled`） |
| `DELETE /api/push/me/channels/{id}` | 删除渠道（级联删除其订阅） |
| `POST /api/push/me/channels/{id}/test` | 按渠道类型发送测试投递（email 走真实 SMTP；webhook 走平台载荷，平台侧拒绝返回 502） |
| `GET /api/push/me/subscriptions` | 列出订阅（联表携带渠道类型与目标） |
| `POST /api/push/me/subscriptions` | 创建订阅（201）；渠道须已验证且启用，否则 400；重复订阅 409 |
| `PATCH /api/push/me/subscriptions/{id}` | 暂停/恢复（`status: active\|paused`） |
| `DELETE /api/push/me/subscriptions/{id}` | 删除订阅 |

`source` 词汇表与简报管线一致：`all / arxiv / github / news / producthunt / hackernews / x / dailyhot`
（`dailyhot` 为聚合热榜源，部署与配置见 [dailyhot-source.md](dailyhot-source.md)）。

## 验证码与限流

- 渠道绑定验证码复用邮件 OTP 设施，专用 purpose `push_channel_verify`（Redis 前缀
  `email:push:code|lock|attempts:`），300 秒有效、60 秒发送冷却、5 次尝试上限。
- IP 级固定窗口限速（600 秒窗口）：创建 email 渠道（含验证码签发）5 次、创建 webhook
  渠道（含探测投递）5 次、测试投递 5 次；Redis 不可用时放行（可用性优先）。

## Webhook 渠道（迁移 0022）

- **URL 要求**：仅 https、不允许 userinfo、长度 ≤ 2048；主机名做 IP 字面量与 DNS 解析
  双重检查，任一解析结果非公网地址（私网/回环/链路本地/保留段）即拒绝（SSRF 防护），
  创建时与每次投递前都会校验。请求不跟随重定向，超时 5 秒。
- **平台自动识别**（按主机名，未知主机按通用 JSON 投递）：

  | 平台 | 主机 | 载荷 |
  | --- | --- | --- |
  | 企业微信群机器人 | `qyapi.weixin.qq.com` | `markdown` 消息 |
  | 钉钉自定义机器人 | `oapi.dingtalk.com` | `markdown` 消息 |
  | 飞书自定义机器人 | `open.feishu.cn` / `open.larksuite.com` | `text` 消息 |
  | 通用 | 其他 | `{"title","text","source":"aigcnews.cn"}` JSON |

  企业微信/钉钉/飞书 HTTP 200 也可能在响应体报错（`errcode`/`code` 非 0），视为投递失败。
- **分块**：按平台单条字节预算在段落边界分块（企业微信 3500B/钉钉 18000B/其他 28000B），
  单段超预算按字符边界硬切；最多 6 块，超出末块截断并附「完整报告见 aigcnews.cn」。
- **验证模型**：无验证码邮件可发，创建时先向 URL 真实投递一条绑定提示（探测即验证），
  成功才落库；重复绑定同一 URL 返回 409。
- **投递凭据**：派发只读 `encrypted_config` 解封出的 URL；密钥缺失时创建返回 503、
  派发计入失败尝试，绝不降级为明文。

## 凭据加密

`push_channels.encrypted_config` 为含凭据渠道类型的静态加密存储（webhook 渠道密封
`{"url": ...}`）：AES-256-GCM（复用微信 secret box 模式，信封含密钥版本号支持轮换），
密钥来自环境变量 `PUSH_CHANNEL_ENCRYPTION_KEY`（32 字节随机值的 URL-safe Base64）与
`PUSH_CHANNEL_ENCRYPTION_KEY_VERSION`。密钥缺失或非法时含凭据的渠道类型拒绝处理
secret，绝不降级为明文；email 渠道无凭据不受影响。生成方式见 `.env.example`。

## RSS feed token（迁移 0063）

RSS 的 canonical 内容是综合简报，而不是 source documents。公开完整简报使用 `GET /api/feeds/briefing.xml`，无需登录，最多返回最近 7 期，响应为 `Cache-Control: public, max-age=900`。会员简报速览使用 `GET /api/feeds/briefing-digest.xml?token=…`，最多返回最近 7 期且不返回按来源的原始条目；缺失或无效 token 返回 401，免费用户、过期会员或不满足有效会员条件返回 403，响应为 `Cache-Control: private, no-store` 和 `X-Robots-Tag: noindex`。

会员 digest 使用独立于 JWT、MCP token、membership token 和推送凭据的凭据域
`user_feed_tokens`：每用户至多一个活跃 token（partial unique index 强制），永不过期、
无 scopes；访问控制完全在请求时判定（token 未吊销 + 用户未禁用 + 生效会员档位），
免费用户可先持证、升级后同一链接即刻生效。明文以 AES-256-GCM 密封落库供随时回显
（库里永不出现明文），密钥来自独立密钥域 `FEED_TOKEN_ENCRYPTION_KEY` /
`FEED_TOKEN_ENCRYPTION_KEY_VERSION`（不复用推送渠道密钥）。

| 端点 | 语义 |
| --- | --- |
| `GET /api/auth/me/feed-token` | 获取（或首次签发）当前用户的 feed token，幂等返回同一枚 |
| `POST /api/auth/me/feed-token/rotate` | 重新生成：单事务吊销旧 token 并签发新 token，旧 RSS 链接即刻失效；IP 限速 5 次/600 秒 |

token 仍使用独立于其他凭据域的 feed token：每用户至多一个活跃 token（partial unique index 强制），无 scopes；访问控制在请求时判定。明文以 AES-256-GCM 密封落库，库里永不出现明文，密钥使用独立的 `FEED_TOKEN_ENCRYPTION_KEY` / `FEED_TOKEN_ENCRYPTION_KEY_VERSION`。前端仅在当前 composable 生命周期的内存中使用 token，不写入 localStorage、DOM 或日志；轮换会吊销旧 token 并使旧 digest 链接立即失效。

订阅仍使用 `feed=briefing`。来源选择只控制接收的简报模块，不改变 RSS payload，也不产生 source-specific RSS 的数据模型或持久化结构。前端「我的订阅」页提供两个 canonical 链接：公开完整简报和带 token 的会员 digest；卡片级另有「重置 RSS 链接」入口。所有 RSS 的 link、description 和 HTML 内容都拒绝服务器本地路径、危险 scheme、协议相对 URL 与非公开资源 URL。

`/api/feed.xml`、`/api/feeds/member.xml` 和 `/api/feeds/{source}.xml` 保留为 legacy 兼容路由，但均 deprecated、非 canonical，也不再作为前端入口或文档主宣传入口；新订阅请使用上述两个 briefing endpoints。

## 代码位置

- 服务层：`backend/app/services/push/`（`channel_service.py`、`subscription_service.py`、`dispatch_service.py`、`webhook_service.py`、`secrets.py`、`errors.py`）
- 仓储：`backend/app/repositories/{push_channel,user_subscription,push_delivery}_repository.py` + `postgres_*` 实现
- 路由：`backend/app/api/routes_push.py`；契约测试：`backend/tests/test_push_channels.py`、`backend/tests/test_push_dispatch.py`、`backend/tests/test_push_webhook.py`
- 前端：`/subscriptions`「我的订阅」页（`frontend/src/views/SubscriptionsView.vue` + `composables/useSubscriptionsController.ts` + `services/subscriptions/` + `features/subscriptions/`），渠道绑定（邮箱验证码 / webhook 探测）与订阅 CRUD，登录可见
