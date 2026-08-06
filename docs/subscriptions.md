# 订阅推送（用户订阅与推送渠道）

用户域的订阅推送基础层：用户在站点上绑定推送渠道（当前仅 email），再按
「来源 × 频率 × 渠道」创建订阅。本文是数据模型、API 与策略的权威文档。

> 当前状态：基础层已上线（渠道绑定、订阅 CRUD、测试邮件）。定时调度投递
> （push_deliveries 幂等表 + APScheduler 频率枚举批量派发）属于后续工作单元；
> 与既有 `briefing_subscriptions`（简报邮件订阅）的合并走
> Contract → Extract → Adapt → Switch → Delete，本层上线前不影响其行为。

## 数据模型（迁移 0018）

- `push_channels`：`(id, user_id, channel_type, target, encrypted_config, verified, status)`，
  唯一约束 `(user_id, channel_type, target)`；`channel_type` 当前仅 `email`（CHECK 约束，
  未来渠道类型需新迁移扩展）。`target` 为投递地址（email 渠道无凭据，`encrypted_config` 为 NULL）。
- `user_subscriptions`：`(id, user_id, channel_id, source, frequency, status)`，
  唯一约束 `(user_id, channel_id, source, frequency)`；`frequency ∈ {daily, weekly, monthly}`，
  `status ∈ {active, paused}`。两表均 `ON DELETE CASCADE`：删渠道连带删订阅，删用户连带清空。

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

`source` 词汇表与简报管线一致：`all / arxiv / github / news / producthunt / hackernews / x`。

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

- 服务层：`backend/app/services/push/`（`channel_service.py`、`subscription_service.py`、`secrets.py`、`errors.py`）
- 仓储：`backend/app/repositories/{push_channel,user_subscription}_repository.py` + `postgres_*` 实现
- 路由：`backend/app/api/routes_push.py`；契约测试：`backend/tests/test_push_channels.py`
