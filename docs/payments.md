# 会员订阅与在线支付

> 本文描述会员订阅收费能力（2026-08-20）。支付默认关闭；营业执照、商户号和 provider 凭证就绪后，配置凭证并单独打开 `payments_enabled`。

## 商品

后端 `backend/app/services/payments/plans.py` 是商品与**默认金额**唯一来源：

| code | 权益 | 默认金额 | 周期 |
|---|---|---:|---:|
| `member_monthly` | member | ¥19（1900 cents） | 1 个日历月 |
| `member_yearly` | member | ¥159（15900 cents） | 12 个月 |

金额始终以整数分存储。月末续费按日历月扩展并钳制到目标月份最后一天；有效期内的 member 从现有到期时间顺延，free 或已过期用户从当前时间起算。

### 运行时调价（监控页入口）

管理员可在监控页「支付配置」分组的**会员套餐定价**面板（`PaymentPricingPanel.vue`）调整月付/年付价格，无需改代码发布：

- 覆盖行存于 `payment_plan_overrides`（迁移 0056，`plan_code` 主键 + `amount_cents` 整数分，CHECK 约束 100–1,000,000 分拦截「把分当元」录错）；**缺行即按 plans.py 默认价生效**。
- Ops API：`GET/PUT /api/ops/payments/plans`（`RequireAdmin`，刻意不挂 `payments_enabled` 门——可先调价再开支付）。PUT 为整体聚合语义：`{monthly_amount_cents, yearly_amount_cents}` 整数 = upsert 覆盖，`null`/缺省 = 删除覆盖恢复默认价；越界返回 400 中文 detail。
- 读路径：`plan_overrides.py` 以 60 秒 TTL 缓存合并默认目录与覆盖行；面板保存即失效缓存（本实例即时生效），其余实例最迟 60 秒内跟随；读库异常按默认价降级，绝不影响下单。
- **在途订单快照语义**：调价只影响新订单。`GET /api/payments/plans` 与创建订单走生效价；在途 pending 订单仍以 `payment_orders` 行内金额快照收款，回调验款也对快照校验，天然免疫运行时调价。回调发放只取静态 `get_plan` 的 months/tier。
- 前端会员卡（`MembershipView.vue`）的金额、年付锚定、「年付省 ¥N」与「-N%」折扣标全部由 plans 接口数据自算（`paymentModel.ts` 纯函数，向下取整、非正隐藏）；plans 探测失败按兜底常量渲染，兜底常量与 plans.py 默认价跨侧钉死。

## 支付渠道

- 微信支付 Native 扫码
- 支付宝电脑网站支付
- 海外跳转渠道 `overseas_redirect`（单槽多商：PayPal 或 PingPong，由监控页选配）

provider 位于 `backend/app/services/payments/providers/`。三渠道均已接入真实下单和回调验签，不引入官方 SDK。收银台按界面语言门控渠道（纯展示层，服务端不感知语言）：中文界面只显示微信/支付宝，其他语言只显示海外渠道。支付开关保持 `payments_enabled=False` 时，用户支付路由返回 404 `payments_disabled`；开关打开但渠道缺凭证时，创建订单返回 503 `payment_channel_not_configured`；渠道远端返回错误时返回 502 `payment_channel_upstream_error`。

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
- `GET /api/ops/payments/plans`：套餐定价投影（默认价/覆盖价/生效价/更新时间）。
- `PUT /api/ops/payments/plans`：整体聚合调价（整数分 = 覆盖，`null` = 恢复默认），越界 400。

## 回调安全与限流

签名必须作用于原始请求字节；provider 还必须检查渠道时间戳和 replay protection。订单金额、币种和渠道订单号必须与本地订单一致；不一致时 fail-closed，记录 error event，零状态变更。公开套餐和回调限流键为 `ratelimit:payments.plans:{client_ip}` 与 `ratelimit:payments.callback:{client_ip}`。Redis 故障时限流 fail-open，但验签、金额和状态校验不会放宽。

### 海外跳转渠道配置（PayPal / PingPong）

海外渠道是**单槽多商**：监控页支付配置面板的「海外支付」区选择服务商（PayPal / PingPong），填入三个通用凭证槽，保存后运行时立即生效；切换服务商无需改代码。槽位语义按服务商映射：

| 通用槽 | PayPal | PingPong |
|---|---|---|
| `overseas_client_id` | Client ID | clientId（商户号） |
| `overseas_client_secret` | Client Secret | 签名盐 salt（下单加签与回调验签共用） |
| `overseas_webhook_secret` | Webhook ID | accId（门店号，回调归属钉死） |

`overseas_sandbox` 勾选后两家都走各自沙箱端点（PayPal `api-m.sandbox.paypal.com`，PingPong `sandbox-acquirer-payment.pingpongx.com`）。未选择服务商时渠道 fail-closed（前端显示「即将开放」）。注意：**面板徽标「已配置」≠ 收银台可用**——徽标只看凭证齐全，收银台可用性还受 `payments_enabled` 总开关门控，两者刻意解耦。

两家回调共用同一个渠道地址：

```text
https://<public-base-url>/api/payments/callback/overseas_redirect
```

**PayPal**：纯跳转链路（无 JS SDK）。下单走 `POST /v2/checkout/orders`（intent=CAPTURE，`reference_id`/`custom_id`/`PayPal-Request-Id` 均为本站订单号保证幂等），取 `rel=approve` 链接跳转；在 Developer Console 为该应用创建 webhook，订阅 `CHECKOUT.ORDER.APPROVED` 与 `PAYMENT.CAPTURE.COMPLETED`，把 Webhook ID 填入 `overseas_webhook_secret`。回调先经 `/v1/notifications/verify-webhook-signature` 在线验签；收到 `CHECKOUT.ORDER.APPROVED` 时服务端自动调用 capture API 并直接 ACK（零状态变更），`PAYMENT.CAPTURE.COMPLETED` 才发权益（金额从 `custom_id` 找回订单并归一到分校验）。**注意**：当前套餐为 CNY 定价，PayPal 跨境账户能否收 CNY 取决于商户协议——正式上线前需要美元套餐 PR（下一工作单元）并实测一笔沙箱单。

**PingPong**：信封式签名（顶层 `{accId, clientId, signType, version, bizContent, sign}`，`sign = SHA256(salt + 全部非 sign 字段键升序 key=value&…)` 大写 hex）。下单走 `POST /v4/payment/prePay`（`merchantTransactionId`=本站订单号天然幂等），应答 `code=="000000"` 且含 `paymentUrl` 时跳转。回调按官方 PHP 参考实现验签（原始文本转义归一后解析），钉死 `clientId`/`accId` 归属；仅 `code=="000000"` + `notifyType=="RECHARGE"` + `status=="SUCCESS"` 发权益，其余状态与非 RECHARGE 通知一律 ACK 200 零状态变更（关单交给既有到期关单任务）。ACK 为纯文本 `OK` / `FAIL`。

**风险提示**：两家 provider 均按官方文档 + mock 测试实现，接入时商户号尚在审核、未经真实沙箱联调；上线前务必以一笔沙箱单走通「下单 → 跳转 → 回调 → 发权益」全链路。

### 支付宝电脑网站支付配置

在 monitor 支付配置面板填写支付宝 AppID、应用私钥和支付宝公钥。`alipay.trade.page.pay` 会生成带 RSA2 签名的支付跳转 URL；在支付宝开放平台将异步通知地址设为：

```text
https://<public-base-url>/api/payments/callback/alipay_page
```

支付宝回调只接受 `TRADE_SUCCESS` 或 `TRADE_FINISHED`，并用支付宝公钥验证 `sign`；回调中的 `total_amount` 元串必须能严格表示为整数分。订单对账/人工补单查单使用 `alipay.trade.query`。

### 微信支付 Native 配置

微信侧需要普通商户号 + Native 产品 + 一个已绑定的 AppID（已认证服务号或开放平台「网站应用」）。在 monitor 支付配置面板填写七项：AppID、商户号 mchid、商户 API 证书序列号、API v3 密钥、商户 API 证书私钥（PEM）、微信支付公钥 ID、微信支付公钥（PEM）；七项齐全渠道才判定为已配置（fail-closed）。

验签采用**微信支付公钥模式**（不做平台证书自动下载轮换）：商户平台「账户中心 → API 安全」页可申请「微信支付公钥」，一次性复制公钥 ID（`PUB_KEY_ID_...`）并下载公钥 PEM 静态配置；回调验签时 `Wechatpay-Serial` 头必须等于该公钥 ID。下单与查单请求用商户 API 证书私钥按 v3 规程加签（`WECHATPAY2-SHA256-RSA2048`）。

回调通知地址（商户平台 Native 产品配置或下单 `notify_url` 均为此值）：

```text
https://<public-base-url>/api/payments/callback/wechat_native
```

回调只接受 `event_type=TRANSACTION.SUCCESS` 且解密后 `trade_state=SUCCESS`；`resource` 为 `AEAD_AES_256_GCM`，用 API v3 密钥（必须 32 字节）解密；`amount.total` 单位为分、币种必须 CNY；时间戳超出 ±5 分钟即拒绝。关单对账/人工补单查单走 `GET /v3/pay/transactions/out-trade-no/{order_no}`。Native 扫码在微信侧完成支付，无前台回跳，下单不使用 `return_url`。

provider ACK 形状见 [ADR 0002](adr/0002-payment-callback-verification.md)。

## 前端收银台

路由为 `/membership/checkout?plan=monthly|yearly`，由 `MembershipCheckoutView.vue` 懒加载。金额只取 `GET /api/payments/plans`；渠道按界面语言门控（`visibleChannelsForLocale`：zh 前缀出微信/支付宝，其余语言出海外跳转槽），不可用渠道置灰并显示“即将开放”；会话中切换语言会按新可见集重选渠道。Native 渠道显示二维码占位与原始支付指令，支付宝/海外渠道显示跳转指令。创建订单后每 3 秒轮询一次，最多 200 次或 10 分钟；`paid`、`expired`、`closed` 终止，组件卸载会清理计时器并丢弃在途响应。

## 代码位置

- 领域：`backend/app/services/payments/`
- 用户路由：`backend/app/api/routes_payments.py`
- Ops 路由：`backend/app/api/routes_ops_payments.py`
- 存储契约与实现：`backend/app/repositories/payment_order_repository.py`、`postgres_payment_order_repository.py`
- 前端 API/模型：`frontend/src/services/payments/`、`frontend/src/features/payments/`
- 前端收银台：`frontend/src/views/MembershipCheckoutView.vue`、`frontend/src/composables/usePaymentCheckout.ts`
- Ops 面板：`frontend/src/components/monitor/PaymentOrdersPanel.vue`
