import { ref } from 'vue'
import type {
  CreatePaymentOrderResponse,
  PaymentOrder,
} from '@/features/payments/paymentModel'
import { isTerminalOrderStatus } from '@/features/payments/paymentModel'
import type { PaymentApi } from '@/services/payments/paymentApi'

export const PAYMENT_POLL_INTERVAL = 3000
// 3s × 200 = 10 分钟上限：支付页挂起时兜底断链，渠道回调链路独立兜底到账
export const PAYMENT_POLL_MAX = 200

export type CheckoutPhase =
  | 'idle'
  | 'creating'
  | 'awaiting_payment'
  | 'paid'
  | 'expired'
  | 'closed'
  | 'create_failed'
  | 'poll_timeout'

interface UsePaymentCheckoutOptions {
  api: PaymentApi
  schedule?: (callback: () => void, delay: number) => ReturnType<typeof setTimeout>
  /** 订单落 paid 终态时触发（轮询/幂等命中/回跳续单三条路径都会到）：
      调用方借此刷新用户会员身份，支付成功后右上角档位无需手动刷新页面 */
  onOrderPaid?: () => void
}

/** 幂等键：同一次收银台会话内重复提交（双击/重试）命中后端既有订单。 */
const newIdempotencyKey = (): string =>
  globalThis.crypto?.randomUUID?.() ??
  `checkout-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`

export const usePaymentCheckout = ({ api, schedule, onOrderPaid }: UsePaymentCheckoutOptions) => {
  const schedulePoll = schedule ?? ((cb: () => void, delay: number) => setTimeout(cb, delay))

  const phase = ref<CheckoutPhase>('idle')
  const order = ref<PaymentOrder | null>(null)
  const instruction = ref<CreatePaymentOrderResponse['instruction'] | null>(null)
  const errorDetail = ref('')

  let pollCount = 0
  let pollTimer: ReturnType<typeof setTimeout> | null = null
  let idempotencyKey = ''
  let disposed = false

  const clearPollTimer = () => {
    if (pollTimer) {
      clearTimeout(pollTimer)
      pollTimer = null
    }
  }
  // 卸载/离页兜底：停表断链并丢弃在途回调
  const disposeCheckout = () => {
    disposed = true
    clearPollTimer()
  }

  /** 落终态：paid 额外触发 onOrderPaid（会员身份刷新钩子） */
  const landTerminalPhase = (status: 'paid' | 'expired' | 'closed') => {
    phase.value = status
    if (status === 'paid') onOrderPaid?.()
  }

  const pollOrder = async () => {
    const current = order.value
    if (disposed || !current) return
    pollCount += 1
    let latest: PaymentOrder
    try {
      latest = await api.getOrder(current.order_no)
    } catch (error) {
      // 轮询错误容忍：容器重启等瞬态故障不断链
      console.error('Failed to poll payment order', error)
      if (pollCount >= PAYMENT_POLL_MAX) {
        phase.value = 'poll_timeout'
        return
      }
      pollTimer = schedulePoll(() => { void pollOrder() }, PAYMENT_POLL_INTERVAL)
      return
    }
    if (disposed) return
    order.value = latest
    if (isTerminalOrderStatus(latest.status)) {
      landTerminalPhase(latest.status as 'paid' | 'expired' | 'closed')
      return
    }
    if (pollCount >= PAYMENT_POLL_MAX) {
      phase.value = 'poll_timeout'
      return
    }
    pollTimer = schedulePoll(() => { void pollOrder() }, PAYMENT_POLL_INTERVAL)
  }

  /** 下单并开始轮询；channel 可用性由调用方（收银台视图）先行拦截。 */
  const beginCheckout = async (planCode: string, channel: string) => {
    if (phase.value === 'creating' || phase.value === 'awaiting_payment') return
    disposed = false
    phase.value = 'creating'
    errorDetail.value = ''
    if (!idempotencyKey) idempotencyKey = newIdempotencyKey()
    try {
      const created = await api.createOrder(planCode, channel, idempotencyKey)
      if (disposed) return
      order.value = created.order
      instruction.value = created.instruction
      if (isTerminalOrderStatus(created.order.status)) {
        // 幂等命中既有单：直接落到对应终态（paid/expired/closed），不轮询
        landTerminalPhase(created.order.status as 'paid' | 'expired' | 'closed')
        return
      }
      phase.value = 'awaiting_payment'
      pollCount = 0
      pollTimer = schedulePoll(() => { void pollOrder() }, PAYMENT_POLL_INTERVAL)
    } catch (error) {
      if (disposed) return
      phase.value = 'create_failed'
      const detail = (error as { response?: { data?: { detail?: unknown } } })
        ?.response?.data?.detail
      errorDetail.value = typeof detail === 'string' ? detail : ''
    }
  }

  /** 订单过期/失败后重新发起：换单不换幂等键口径——新支付尝试用新键。 */
  const restartCheckout = () => {
    clearPollTimer()
    order.value = null
    instruction.value = null
    idempotencyKey = ''
    phase.value = 'idle'
  }

  /**
   * 回跳续单：支付页 return_url 带回 order_no 时按它恢复订单——
   * 终态直接落对应阶段（不轮询），pending 续上轮询；查单失败返回 false，
   * 调用方（收银台视图）静默回落到全新收银台。
   */
  const resumeCheckout = async (orderNo: string): Promise<boolean> => {
    let latest: PaymentOrder
    try {
      latest = await api.getOrder(orderNo)
    } catch (error) {
      console.error('Failed to resume payment order', error)
      return false
    }
    if (disposed) return false
    clearPollTimer()
    order.value = latest
    instruction.value = null
    if (isTerminalOrderStatus(latest.status)) {
      landTerminalPhase(latest.status as 'paid' | 'expired' | 'closed')
      return true
    }
    phase.value = 'awaiting_payment'
    pollCount = 0
    pollTimer = schedulePoll(() => { void pollOrder() }, PAYMENT_POLL_INTERVAL)
    return true
  }

  return { phase, order, instruction, errorDetail, beginCheckout, restartCheckout, resumeCheckout, disposeCheckout }
}
