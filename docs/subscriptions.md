# 订阅推送（用户订阅与推送渠道）

用户域的订阅推送基础层：用户在站点上绑定推送渠道（当前仅 email），再按
「来源 × 频率 × 渠道」创建订阅。本文是数据模型、API 与策略的权威文档。

> 当前状态：渠道绑定、订阅 CRUD、测试邮件与定时派发均已上线。
> 派发（迁移 0019 `push_deliveries` + `subscription_dispatch` 调度任务，默认每
> 半小时一轮）只读简报缓存做幂等投递，不触发简报生成。
> 与既有 `briefing_subscriptions`（简报邮件订阅）的合并走
> Contract → Extract → Adapt → Switch → Delete，本层上线前不影响其行为。

## 数据模型（迁移 0018）

- `push_channels`：`(id, user_id, channel_type, target, encrypted_config, verified, status)`，
  唯一约束 `(user_id, channel_type, target)`；`channel_type` 当前仅 `email`（CHECK 约束，
  未来渠道类型需新迁移扩展）。`target` 为投递地址（email 渠道无凭据，`encrypted_config` 为 NULL）。
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
| `POST /api/push/me/channels` | 创建 email 渠道（201）并向目标邮箱发绑定验证码；已验证邮箱重复绑定返回 409；未验证重复提交重发验证码（不产生重复行） |
| `POST /api/push/me/channels/{id}/verify` | 校验 6 位验证码，置 `verified=true`；验证码错误返回 400 |
| `PATCH /api/push/me/channels/{id}` | 启用/停用渠道（`status: active\|disabled`） |
| `DELETE /api/push/me/channels/{id}` | 删除渠道（级联删除其订阅） |
| `POST /api/push/me/channels/{id}/test` | 经真实 SMTP 管线发送测试简报邮件 |
| `GET /api/push/me/subscriptions` | 列出订阅（联表携带渠道类型与目标） |
| `POST /api/push/me/subscriptions` | 创建订阅（201）；渠道须已验证且启用，否则 400；重复订阅 409 |
| `PATCH /api/push/me/subscriptions/{id}` | 暂停/恢复（`status: active\|paused`） |
| `DELETE /api/push/me/subscriptions/{id}` | 删除订阅 |

`source` 词汇表与简报管线一致：`all / arxiv / github / news / producthunt / hackernews / x / dailyhot`
（`dailyhot` 为聚合热榜源，部署与配置见 [dailyhot-source.md](dailyhot-source.md)）。

## 验证码与限流

- 渠道绑定验证码复用邮件 OTP 设施，专用 purpose `push_channel_verify`（Redis 前缀
  `email:push:code|lock|attempts:`），300 秒有效、60 秒发送冷却、5 次尝试上限。
- IP 级固定窗口限速（600 秒窗口）：创建渠道（含验证码签发）5 次、测试邮件 5 次；
  Redis 不可用时放行（可用性优先）。

## 凭据加密

`push_channels.encrypted_config` 供含凭据的渠道类型（webhook secret、bot token 等）
静态加密使用：AES-256-GCM（复用微信 secret box 模式，信封含密钥版本号支持轮换），
密钥来自环境变量 `PUSH_CHANNEL_ENCRYPTION_KEY`（32 字节随机值的 URL-safe Base64）与
`PUSH_CHANNEL_ENCRYPTION_KEY_VERSION`。密钥缺失或非法时含凭据的渠道类型拒绝处理
secret，绝不降级为明文；email 渠道无凭据不受影响。生成方式见 `.env.example`。

## 代码位置

- 服务层：`backend/app/services/push/`（`channel_service.py`、`subscription_service.py`、`dispatch_service.py`、`secrets.py`、`errors.py`）
- 仓储：`backend/app/repositories/{push_channel,user_subscription,push_delivery}_repository.py` + `postgres_*` 实现
- 路由：`backend/app/api/routes_push.py`；契约测试：`backend/tests/test_push_channels.py`、`backend/tests/test_push_dispatch.py`
