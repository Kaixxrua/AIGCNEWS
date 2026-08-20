# 会员订阅与在线支付

> 本文描述会员订阅收费能力（2026-08-20）。支付默认关闭；营业执照、商户号和 provider 凭证就绪后，配置凭证并单独打开 `payments_enabled`。

## 商品

后端 `backend/app/services/payments/plans.py` 是商品与金额唯一来源：

| code | 权益 | 金额 | 周期 |
|---|---|---:|---:|
| `member_monthly` | member | ¥19（1900 cents） | 1 个日历月 |
| `member_yearly` | member | ¥129（12900 cents） | 12 个月 |

金额始终以整数分存储。月末续费按日历月扩展并钳制到目标月份最后一天；有效期内的 member 从现有到期时间顺延，free 或已过期用户从当前时间起算。

## 支付渠道

- 微信支付 Native 扫码
- 支付宝电脑网站支付
- Stripe 国际卡

provider 位于 `backend/app/services/payments/providers/`。Stripe Checkout 与支付宝电脑网站支付已接入真实下单和回调验签；微信 Native 扫码仍按接入 PR 启用。三渠道共用 CNY 单一商品金额源，不引入官方 SDK。支付开关保持 `payments_enabled=False` 时，用户支付路由返回 404 `payments_disabled`；开关打开但渠道缺凭证时，创建订单返回 503 `payment_channel_not_configured`；渠道远端返回错误时返回 502 `payment_channel_upstream_error`。

## 订单与状态

`payment_orders`（迁移 0051）记录订单号、用户、套餐、渠道、金额/币种、幂等键、渠道订单号、回调原文、支付时间、权益到期时间和订单过期时间。

状态为：

- `pending → paid`：回调或 Ops 补单成功。
- `pending → expired`：每 5 分钟调度任务处理超时订单。
- `expired → paid`：允许迟到支付，钱已收则发放权益。
- `pending → closed`：管理员人工关单。
- `closed`：吸收态，不接受回调发权益。

回调与 Ops 补单共用唯一发权益入口。数据库事务先条件更新订单，再更新用户会员等级和到期时间；重复回调影响行数为零，不重复延长会员期限。永久会员只标记订单已支付，不增加期限。

## API

用户端（受 `payments_enabled` 门控）：

| 端点 | 语义 |
|---|---|
| `GET /api/payments/plans` | 匿名读取套餐与渠道可用性；按 IP 限流 |
| `POST /api/payments/orders` | 登录用户按幂等键创建订单并获得二维码/跳转指令 |
| `GET /api/payments/orders` | 当前用户订单列表，不返回 `callback_payload` |
| `GET /api/payments/orders/{order_no}` | 当前用户自己的订单详情，不返回 `callback_payload` |
| `POST /api/payments/callback/{channel}` | provider 回调；原始 bytes 验签、时间戳防重放、金额/币种校验后发权益 |

管理员端（`RequireAdmin`，不受用户支付开关隐藏）：

- `GET /api/ops/payments/orders`：按状态、渠道、套餐、邮箱和时间分页筛选。
- `GET /api/ops/payments/orders/{order_no}`：管理员详情，包含回调载荷和审计字段。
- `POST /api/ops/payments/orders/{order_no}/mark-paid`：人工补单，复用恰好一次发权益事务。
- `POST /api/ops/payments/orders/{order_no}/close`：人工关闭 pending 订单。

## 回调安全与限流

签名必须作用于原始请求字节；provider 还必须检查渠道时间戳和 replay protection。订单金额、币种和渠道订单号必须与本地订单一致；不一致时 fail-closed，记录 error event，零状态变更。公开套餐和回调限流键为 `ratelimit:payments.plans:{client_ip}` 与 `ratelimit:payments.callback:{client_ip}`。Redis 故障时限流 fail-open，但验签、金额和状态校验不会放宽。

### Stripe Checkout 配置

在 monitor 支付配置面板填写 `stripe_secret_key` 与 `stripe_webhook_secret`，保存后运行时立即生效。Stripe Dashboard 新建 webhook endpoint：

```text
https://<public-base-url>/api/payments/callback/stripe
```

只订阅 `checkout.session.completed` 事件，并将 endpoint signing secret 填入 `stripe_webhook_secret`。success/cancel URL 会回到收银台并携带 `order_no`，前端可继续轮询订单状态；Stripe `query_order` 暂不启用，支付结果以验签 webhook 为准。

### 支付宝电脑网站支付配置

在 monitor 支付配置面板填写支付宝 AppID、应用私钥和支付宝公钥。`alipay.trade.page.pay` 会生成带 RSA2 签名的支付跳转 URL；在支付宝开放平台将异步通知地址设为：

```text
https://<public-base-url>/api/payments/callback/alipay_page
```

支付宝回调只接受 `TRADE_SUCCESS` 或 `TRADE_FINISHED`，并用支付宝公钥验证 `sign`；回调中的 `total_amount` 元串必须能严格表示为整数分。订单对账/人工补单查单使用 `alipay.trade.query`。

provider ACK 形状见 [ADR 0002](adr/0002-payment-callback-verification.md)。

## 前端收银台

路由为 `/membership/checkout?plan=monthly|yearly`，由 `MembershipCheckoutView.vue` 懒加载。金额只取 `GET /api/payments/plans`；不可用渠道置灰并显示“即将开放”。Native 渠道显示二维码占位与原始支付指令，网页/Stripe 渠道显示跳转指令。创建订单后每 3 秒轮询一次，最多 200 次或 10 分钟；`paid`、`expired`、`closed` 终止，组件卸载会清理计时器并丢弃在途响应。

## 代码位置

- 领域：`backend/app/services/payments/`
- 用户路由：`backend/app/api/routes_payments.py`
- Ops 路由：`backend/app/api/routes_ops_payments.py`
- 存储契约与实现：`backend/app/repositories/payment_order_repository.py`、`postgres_payment_order_repository.py`
- 前端 API/模型：`frontend/src/services/payments/`、`frontend/src/features/payments/`
- 前端收银台：`frontend/src/views/MembershipCheckoutView.vue`、`frontend/src/composables/usePaymentCheckout.ts`
- Ops 面板：`frontend/src/components/monitor/PaymentOrdersPanel.vue`
