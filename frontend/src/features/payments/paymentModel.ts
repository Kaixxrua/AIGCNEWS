// 支付收费骨架（用户域）：套餐/订单/渠道的视图模型与纯函数助手。
// 词汇表与后端 schema_payments / services/payments 保持一致：
// 金额一律整数分，权威金额来源是 GET /api/payments/plans 响应。
// 营销卡金额/折扣由前端用 plans 数据自算；plans 探测失败时用下方
// 兜底常量渲染（与后端 plans.py 默认价由两侧测试钉住防漂移）。

export type PaymentPlanCode =
  | 'member_monthly'
  | 'member_yearly'
  | 'member_monthly_usd'
  | 'member_yearly_usd'
export type BillingPeriod = 'monthly' | 'yearly'
// 海外渠道是单槽多商（PayPal/PingPong 由 Monitor 选配），前端只见统一槽 id
export type PaymentChannel = 'wechat_native' | 'alipay_page' | 'overseas_redirect'

export type PaymentOrderStatus = 'pending' | 'paid' | 'expired' | 'closed'

export interface PaymentPlan {
  code: string
  tier: string
  amount_cents: number
  currency: string
  months: number
}

export interface PaymentChannelAvailability {
  channel: string
  available: boolean
}

export interface PaymentPlansResponse {
  plans: PaymentPlan[]
  channels: PaymentChannelAvailability[]
}

export interface PaymentOrder {
  order_no: string
  plan_code: string
  channel: string
  amount_cents: number
  currency: string
  status: string
  channel_order_no: string
  expires_at: string
  paid_at: string | null
  created_at: string
}

export interface PaymentInstruction {
  kind: string // "qr_code" | "redirect_url" | "client_secret"
  content: string
}

export interface CreatePaymentOrderResponse {
  order: PaymentOrder
  instruction: PaymentInstruction
}

export const PAYMENT_CHANNELS: readonly PaymentChannel[] = [
  'wechat_native',
  'alipay_page',
  'overseas_redirect',
]

// 收银台渠道按界面语言门控（纯展示层，服务端不感知语言）：
// 中文界面只出国内扫码/跳转渠道，其他语言只出海外跳转槽。
// zh-CN/zh-TW 等一律按前缀 zh 判定；空串与未知语言一律落海外集（英文为默认外语）。
export const DOMESTIC_CHANNELS: readonly PaymentChannel[] = ['wechat_native', 'alipay_page']
export const OVERSEAS_CHANNELS: readonly PaymentChannel[] = ['overseas_redirect']

export const visibleChannelsForLocale = (locale: string): readonly PaymentChannel[] =>
  locale.toLowerCase().startsWith('zh') ? DOMESTIC_CHANNELS : OVERSEAS_CHANNELS

// 套餐币种按界面语言门控（与渠道门控同一判定）：中文界面买 CNY 套餐，
// 其他语言买 USD 套餐（PayPal 不收 CNY；PingPong 跨境以 USD 计价）。
// 服务端另以 plans.py 的 CHANNEL_CURRENCIES 矩阵收口，前端只做展示层拣选。
export const planCurrencyForLocale = (locale: string): 'CNY' | 'USD' =>
  locale.toLowerCase().startsWith('zh') ? 'CNY' : 'USD'

// 套餐码 ↔ 计费周期 + 币种：收银台 query 参数（?plan=monthly|yearly）与后端
// plan_code 的唯一换算口；未知值一律 null（fail-closed，不落单）。
export const planCodeForPeriod = (
  period: BillingPeriod,
  currency: 'CNY' | 'USD' = 'CNY',
): PaymentPlanCode =>
  period === 'yearly'
    ? currency === 'USD'
      ? 'member_yearly_usd'
      : 'member_yearly'
    : currency === 'USD'
      ? 'member_monthly_usd'
      : 'member_monthly'

export const periodForPlanCode = (code: string): BillingPeriod | null => {
  if (code === 'member_monthly' || code === 'member_monthly_usd') return 'monthly'
  if (code === 'member_yearly' || code === 'member_yearly_usd') return 'yearly'
  return null
}

/** 从 plans 响应解析当前计费周期 + 币种的套餐；缺套餐即收银台不可用（null）。 */
export const resolvePlan = (
  plans: PaymentPlan[],
  period: BillingPeriod,
  currency: 'CNY' | 'USD' = 'CNY',
): PaymentPlan | null =>
  plans.find((plan) => plan.code === planCodeForPeriod(period, currency)) ?? null

/** 分 → 展示金额：CNY 用 ¥、USD 用 $，其余原样带币种码；整元不补小数，角去尾零（19.90 → 19.9，19.99 保留）。 */
export const formatAmountCents = (amountCents: number, currency: string): string => {
  const digits = (amountCents / 100).toFixed(2).replace(/\.?0+$/, '')
  if (currency === 'CNY') return `¥${digits}`
  if (currency === 'USD') return `$${digits}`
  return `${currency} ${digits}`
}

// 营销卡兜底价：plans 探测失败时按默认商业承诺渲染，与后端 plans.py
// 常量钉住（backend/tests/test_payment_plans.py ↔ paymentModel.test.ts）。
export const FALLBACK_MEMBER_MONTHLY_CENTS = 1900
export const FALLBACK_MEMBER_YEARLY_CENTS = 15900
export const FALLBACK_MEMBER_MONTHLY_USD_CENTS = 490
export const FALLBACK_MEMBER_YEARLY_USD_CENTS = 3900

/** 年付相对月付 ×12 的省钱额（分）；非正即无优惠（调用方据此隐藏 pill）。 */
export const computeYearlySavingsCents = (
  monthlyCents: number,
  yearlyCents: number,
): number => monthlyCents * 12 - yearlyCents

/** 年付折扣百分比（向下取整，钳 ≥0）；非正即无折扣（调用方据此隐藏 badge）。 */
export const computeYearlyDiscountPercent = (
  monthlyCents: number,
  yearlyCents: number,
): number => {
  const baseline = monthlyCents * 12
  if (baseline <= 0) return 0
  return Math.max(0, Math.floor((1 - yearlyCents / baseline) * 100))
}

/** 剩余毫秒 → 倒计时文本：MM:SS，超过一小时 H:MM:SS；负值钳到 00:00。 */
export const formatCountdownMs = (ms: number): string => {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000))
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  const mm = String(minutes).padStart(2, '0')
  const ss = String(seconds).padStart(2, '0')
  return hours > 0 ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`
}

/** 轮询终止态：只有 pending 值得继续轮询；expired/closed 不再变化。 */
export const isTerminalOrderStatus = (status: string): boolean =>
  status === 'paid' || status === 'expired' || status === 'closed'
