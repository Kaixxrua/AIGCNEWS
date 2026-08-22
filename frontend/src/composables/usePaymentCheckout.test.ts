import { describe, expect, it, vi } from 'vitest'
import {
  PAYMENT_POLL_INTERVAL,
  PAYMENT_POLL_MAX,
  usePaymentCheckout,
} from './usePaymentCheckout'
import type { PaymentApi } from '@/services/payments/paymentApi'
import type {
  CreatePaymentOrderResponse,
  PaymentOrder,
} from '@/features/payments/paymentModel'

const order = (overrides: Partial<PaymentOrder>): PaymentOrder => ({
  order_no: 'P202608190001AB12CD',
  plan_code: 'member_monthly',
  channel: 'wechat_native',
  amount_cents: 1900,
  currency: 'CNY',
  status: 'pending',
  channel_order_no: '',
  expires_at: '2026-08-19T12:30:00Z',
  paid_at: null,
  created_at: '2026-08-19T12:00:00Z',
  ...overrides,
})

const created = (orderOverrides: Partial<PaymentOrder>): CreatePaymentOrderResponse => ({
  order: order(orderOverrides),
  instruction: { kind: 'qr_code', content: 'weixin://pay/x' },
})

interface Harness {
  api: PaymentApi
  runPolls: (count: number) => Promise<void>
  checkout: ReturnType<typeof usePaymentCheckout>
}

/** 手动泵定时器的测试线束：schedule 只排队不执行，runPolls 逐轮驱动。 */
const makeHarness = (apiOverrides: Partial<PaymentApi>): Harness => {
  const queue: Array<() => void> = []
  const api: PaymentApi = {
    listPlans: vi.fn(),
    createOrder: vi.fn().mockResolvedValue(created({})),
    getOrder: vi.fn().mockResolvedValue(order({ status: 'paid' })),
    ...apiOverrides,
  }
  const checkout = usePaymentCheckout({
    api,
    schedule: (cb) => {
      queue.push(cb)
      return queue.length as unknown as ReturnType<typeof setTimeout>
    },
  })
  const runPolls = async (count: number) => {
    for (let i = 0; i < count; i += 1) {
      const cb = queue.shift()
      if (!cb) return
      cb()
      // 让 pollOrder 内的 await 链跑完再驱动下一轮
      await Promise.resolve()
      await Promise.resolve()
    }
  }
  return { api, runPolls, checkout }
}

describe('usePaymentCheckout', () => {
  it('creates an order with a stable idempotency key and starts polling', async () => {
    const { api, checkout } = makeHarness({})

    await checkout.beginCheckout('member_monthly', 'wechat_native')

    expect(checkout.phase.value).toBe('awaiting_payment')
    expect(checkout.order.value?.order_no).toBe('P202608190001AB12CD')
    expect(checkout.instruction.value?.kind).toBe('qr_code')
    const key = (api.createOrder as ReturnType<typeof vi.fn>).mock.calls[0][2]
    expect(typeof key).toBe('string')
    expect(key.length).toBeGreaterThan(8)

    // 重复提交（双击）被入口守卫拦截，不二次下单
    await checkout.beginCheckout('member_monthly', 'wechat_native')
    expect(api.createOrder).toHaveBeenCalledTimes(1)
  })

  it('reuses the same idempotency key across create retries after failure', async () => {
    const createOrder = vi
      .fn()
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValue(created({}))
    const { checkout } = makeHarness({ createOrder })

    await checkout.beginCheckout('member_monthly', 'wechat_native')
    expect(checkout.phase.value).toBe('create_failed')

    checkout.restartCheckout()
    // restart 视为新的支付尝试：换新幂等键口径之前先确认旧键只用过一次
    const firstKey = createOrder.mock.calls[0][2]
    await checkout.beginCheckout('member_monthly', 'wechat_native')
    expect(createOrder.mock.calls[1][2]).not.toBe(firstKey)
    expect(checkout.phase.value).toBe('awaiting_payment')
  })

  it('stops polling and lands on paid when the order turns paid', async () => {
    const getOrder = vi
      .fn()
      .mockResolvedValueOnce(order({ status: 'pending' }))
      .mockResolvedValueOnce(order({ status: 'paid', paid_at: '2026-08-19T12:05:00Z' }))
    const { runPolls, checkout } = makeHarness({ getOrder })

    await checkout.beginCheckout('member_monthly', 'wechat_native')
    await runPolls(2)

    expect(getOrder).toHaveBeenCalledTimes(2)
    expect(checkout.phase.value).toBe('paid')
    expect(checkout.order.value?.status).toBe('paid')

    // 终态后不再排新轮询
    await runPolls(3)
    expect(getOrder).toHaveBeenCalledTimes(2)
  })

  it('maps expired and closed to their own terminal phases', async () => {
    const expired = makeHarness({ getOrder: vi.fn().mockResolvedValue(order({ status: 'expired' })) })
    await expired.checkout.beginCheckout('member_monthly', 'wechat_native')
    await expired.runPolls(1)
    expect(expired.checkout.phase.value).toBe('expired')

    const closed = makeHarness({ getOrder: vi.fn().mockResolvedValue(order({ status: 'closed' })) })
    await closed.checkout.beginCheckout('member_monthly', 'wechat_native')
    await closed.runPolls(1)
    expect(closed.checkout.phase.value).toBe('closed')
  })

  it('tolerates transient poll errors and keeps the chain alive', async () => {
    const getOrder = vi
      .fn()
      .mockRejectedValueOnce(new Error('容器重启'))
      .mockResolvedValueOnce(order({ status: 'paid' }))
    const { runPolls, checkout } = makeHarness({ getOrder })

    await checkout.beginCheckout('member_monthly', 'wechat_native')
    await runPolls(2)

    expect(checkout.phase.value).toBe('paid')
  })

  it('caps polling at the ten-minute ceiling', async () => {
    const getOrder = vi.fn().mockResolvedValue(order({ status: 'pending' }))
    const { runPolls, checkout } = makeHarness({ getOrder })

    await checkout.beginCheckout('member_monthly', 'wechat_native')
    await runPolls(PAYMENT_POLL_MAX)

    expect(checkout.phase.value).toBe('poll_timeout')
    expect(getOrder).toHaveBeenCalledTimes(PAYMENT_POLL_MAX)
    expect(PAYMENT_POLL_INTERVAL * PAYMENT_POLL_MAX).toBe(600_000)
  })

  it('discards in-flight callbacks after dispose', async () => {
    let resolveGet: (value: PaymentOrder) => void = () => {}
    const getOrder = vi.fn().mockImplementation(
      () => new Promise<PaymentOrder>((resolve) => { resolveGet = resolve }),
    )
    const { runPolls, checkout } = makeHarness({ getOrder })

    await checkout.beginCheckout('member_monthly', 'wechat_native')
    const pollPromise = runPolls(1)
    checkout.disposeCheckout()
    resolveGet(order({ status: 'paid' }))
    await pollPromise

    // 卸载后到达的结果被丢弃：订单与阶段都不更新
    expect(checkout.phase.value).toBe('awaiting_payment')
    expect(checkout.order.value?.status).toBe('pending')
  })

  it('resumes a pending order from a return jump and restarts polling', async () => {
    const getOrder = vi.fn().mockResolvedValue(order({ status: 'pending' }))
    const { runPolls, checkout } = makeHarness({ getOrder })

    const ok = await checkout.resumeCheckout('P202608190001AB12CD')

    expect(ok).toBe(true)
    expect(checkout.phase.value).toBe('awaiting_payment')
    expect(checkout.order.value?.order_no).toBe('P202608190001AB12CD')
    // 续单不重建支付指令：回跳页不再渲染二维码/跳转区
    expect(checkout.instruction.value).toBeNull()

    await runPolls(1)
    // resume 查单 + 一轮轮询
    expect(getOrder).toHaveBeenCalledTimes(2)
    expect(checkout.phase.value).toBe('awaiting_payment')
  })

  it('resumes a paid order straight to the terminal phase without polling', async () => {
    const getOrder = vi
      .fn()
      .mockResolvedValue(order({ status: 'paid', paid_at: '2026-08-19T12:05:00Z' }))
    const { runPolls, checkout } = makeHarness({ getOrder })

    expect(await checkout.resumeCheckout('P202608190001AB12CD')).toBe(true)
    expect(checkout.phase.value).toBe('paid')

    await runPolls(2)
    expect(getOrder).toHaveBeenCalledTimes(1)
  })

  it('maps resumed expired/closed orders and fails soft on unknown order_no', async () => {
    const expired = makeHarness({ getOrder: vi.fn().mockResolvedValue(order({ status: 'expired' })) })
    expect(await expired.checkout.resumeCheckout('P1')).toBe(true)
    expect(expired.checkout.phase.value).toBe('expired')

    const closed = makeHarness({ getOrder: vi.fn().mockResolvedValue(order({ status: 'closed' })) })
    expect(await closed.checkout.resumeCheckout('P1')).toBe(true)
    expect(closed.checkout.phase.value).toBe('closed')

    // 查无此单（404）：返回 false，停留在 idle，视图回落全新收银台
    const missing = makeHarness({ getOrder: vi.fn().mockRejectedValue(new Error('404')) })
    expect(await missing.checkout.resumeCheckout('P404')).toBe(false)
    expect(missing.checkout.phase.value).toBe('idle')
    expect(missing.checkout.order.value).toBeNull()
  })
})
