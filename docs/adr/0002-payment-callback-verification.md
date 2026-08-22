# ADR 0002：支付回调验签与幂等发权益

- 状态：Accepted（收费骨架阶段）
- 日期：2026-08-19
- 范围：微信 Native、支付宝电脑网站支付、Stripe 会员订阅

## 决策

支付回调必须经过统一的 provider 适配层，再进入订单校验和发权益事务。provider 接收**原始 request bytes**与请求头；不得先解析 JSON、重新序列化或使用表单字段替代原文后再验签。provider 必须校验渠道时间戳并拒绝重放，且将金额归一为整数分、币种归一为大写 ISO 代码。

provider 验证成功后，API 仍需校验订单存在、渠道、渠道订单号、金额和币种。金额或币种不一致时 fail-closed：记录 error event，返回失败 ACK/422，订单状态和会员权益均不改变。

订单状态与会员权益在同一个数据库事务内条件更新：仅 `pending` 或 `expired` 可转为 `paid`。条件更新影响行数为零时视为幂等重放，不再次延长会员期限。`expired → paid` 是有意保留的迟到支付边；`closed` 是吸收态，回调拒绝并交人工处理。

## ACK 契约

- 微信 Native 成功：`{"code":"SUCCESS"}`；失败使用渠道要求的失败 JSON。
- 支付宝电脑网站支付成功：纯文本 `success`；失败返回非成功 ACK。
- Stripe webhook：成功 HTTP 200 空 JSON；验证或处理失败返回非 2xx/失败 JSON。

ACK 只表示回调处理结果，不代替订单状态查询。已支付订单的重复回调仍返回成功 ACK，但不重复发权益。

## 端点与开关

`payments_enabled=False` 时，用户支付路由表现为 404 `payments_disabled`，保持支付功能暗栈。开关开启但对应 provider 凭证缺失时，创建订单返回 503 `payment_channel_not_configured`。Ops 订单端点不受用户支付开关隐藏，管理员仍可查询和处理台账。

套餐为 `member_monthly`（1900 CNY cents，1 个日历月）和 `member_yearly`（15900 CNY cents，12 个月）。

## 限流

套餐公开读取和回调端点使用 Redis 固定窗口键 `ratelimit:payments.plans:{client_ip}`、`ratelimit:payments.callback:{client_ip}`。Redis 不可用时限流 fail-open，以避免支付成功回调因限流基础设施故障丢失；签名、金额和状态校验仍 fail-closed。

## 被拒绝的替代方案

1. **先解析 JSON 再验签**：会改变空白、字段顺序或编码，导致签名语义漂移。
2. **订单状态与会员更新使用两个事务**：可能出现已标记支付但未发权益，或已发权益但订单仍 pending。
3. **回调前先关闭订单**：会把迟到支付错误地变成人工退款；订单自然过期只转为 `expired`。
4. **新增事件表作为本阶段必选依赖**：当前以回调原文、订单状态和 error events 提供审计，避免扩大迁移面；未来可独立引入事件账本。
5. **把 callback payload 返回普通用户接口**：回调内容可能包含敏感元数据，只允许管理员详情投影查看。

## 后续实施

营业执照和商户凭证就绪后，逐渠道实现 provider 的真实创建支付与验签方法，补充渠道官方测试向量，再单独打开 `payments_enabled`。每个渠道单独验证金额、时间戳、重放和 ACK 行为。
