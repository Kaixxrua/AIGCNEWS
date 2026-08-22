// 支付收费骨架（用户域）：套餐/订单/渠道的视图模型与纯函数助手。
// 词汇表与后端 schema_payments / services/payments 保持一致：
// 金额一律整数分，权威金额来源是 GET /api/payments/plans 响应，
// 前端营销卡的 i18n 价格字面量由 locale.test.ts 钉住防漂移。

export type PaymentPlanCode = 'member_monthly' | 'member_yearly'
export type BillingPeriod = 'monthly' | 'yearly'
export type PaymentChannel = 'wechat_native' | 'alipay_page' | 'stripe'

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
  'stripe',
]

// 套餐码 ↔ 计费周期：收银台 query 参数（?plan=monthly|yearly）与后端
// plan_code 的唯一换算口；未知值一律 null（fail-closed，不落单）。
export const planCodeForPeriod = (period: BillingPeriod): PaymentPlanCode =>
  period === 'yearly' ? 'member_yearly' : 'member_monthly'

export const periodForPlanCode = (code: string): BillingPeriod | null => {
  if (code === 'member_monthly') return 'monthly'
  if (code === 'member_yearly') return 'yearly'
  return null
}

/** 从 plans 响应解析当前计费周期的套餐；缺套餐即收银台不可用（null）。 */
export const resolvePlan = (
  plans: PaymentPlan[],
  period: BillingPeriod,
): PaymentPlan | null =>
  plans.find((plan) => plan.code === planCodeForPeriod(period)) ?? null

/** 分 → 展示金额：CNY 用 ¥，其余原样带币种码；整元不补小数。 */
export const formatAmountCents = (amountCents: number, currency: string): string => {
  const yuan = amountCents / 100
  const digits = Number.isInteger(yuan) ? String(yuan) : yuan.toFixed(2)
  return currency === 'CNY' ? `¥${digits}` : `${currency} ${digits}`
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
