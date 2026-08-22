import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MembershipCheckoutView from './MembershipCheckoutView.vue'
import type {
  CreatePaymentOrderResponse,
  PaymentOrder,
  PaymentPlansResponse,
} from '@/features/payments/paymentModel'

const apiBox = vi.hoisted(() => ({
  listPlans: vi.fn(),
  createOrder: vi.fn(),
  getOrder: vi.fn(),
}))

const redirectBox = vi.hoisted(() => ({ redirectToUrl: vi.fn() }))

vi.mock('@/services/payments/paymentApi', () => ({ paymentApi: apiBox }))
vi.mock('@/services/payments/redirect', () => redirectBox)

const plansResponse = (overrides: Partial<PaymentPlansResponse> = {}): PaymentPlansResponse => ({
  plans: [
    { code: 'member_monthly', tier: 'member', amount_cents: 1900, currency: 'CNY', months: 1 },
    { code: 'member_yearly', tier: 'member', amount_cents: 15900, currency: 'CNY', months: 12 },
  ],
  channels: [
    { channel: 'wechat_native', available: true },
    { channel: 'alipay_page', available: false },
    { channel: 'stripe', available: false },
  ],
  ...overrides,
})

const paidOrder: PaymentOrder = {
  order_no: 'P202608190001AB12CD',
  plan_code: 'member_monthly',
  channel: 'wechat_native',
  amount_cents: 1900,
  currency: 'CNY',
  status: 'paid',
  channel_order_no: 'ch-1',
  expires_at: '2026-08-19T12:30:00Z',
  paid_at: '2026-08-19T12:05:00Z',
  created_at: '2026-08-19T12:00:00Z',
}

const createResponse: CreatePaymentOrderResponse = {
  order: { ...paidOrder, status: 'pending', paid_at: null, channel_order_no: '' },
  instruction: { kind: 'qr_code', content: 'weixin://wxpay/bizpayurl?pr=abc' },
}

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      common: { loading: '加载中…' },
      membership: {
        checkout: {
          title: '开通 vip',
          subtitle: '选择支付方式完成开通。',
          planMonthly: 'vip · 按月付',
          planYearly: 'vip · 按年付',
          perMonth: '/ 月',
          perYear: '/ 年',
          channelTitle: '支付方式',
          channelWechat: '微信支付',
          channelAlipay: '支付宝',
          channelStripe: '银行卡（Stripe）',
          channelSoon: '即将开放',
          submit: '去支付',
          submitting: '创建订单中…',
          createFailed: '创建订单失败，请稍后重试。',
          qrPlaceholder: '支付二维码',
          scanHint: '请使用对应 App「扫一扫」完成支付',
          redirectHint: '正在跳转支付页，若未自动跳转请点击下方按钮',
          redirectAction: '前往支付',
          expireCountdown: '订单支付有效期剩余 {time}',
          awaiting: '等待支付结果…',
          orderNo: '订单号',
          paid: '支付成功，vip 已开通！',
          paidHint: '会员权益已生效，感谢支持。',
          expired: '订单已过期，请重新发起支付。',
          pollTimeout: '支付结果确认超时。',
          retry: '重新发起支付',
          loadFailed: '收银台暂不可用。',
          backToMembership: '返回会员页',
        },
      },
    },
  },
  missingWarn: false,
  fallbackWarn: false,
})

const mountView = async (query: Record<string, string> = { plan: 'monthly' }) => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/membership', name: 'membership', component: { template: '<div />' } },
      { path: '/membership/checkout', name: 'membership-checkout', component: MembershipCheckoutView },
    ],
  })
  await router.push({ path: '/membership/checkout', query })
  const wrapper = mount(MembershipCheckoutView, {
    global: { plugins: [i18n, router] },
  })
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  vi.useFakeTimers()
  apiBox.listPlans.mockReset().mockResolvedValue(plansResponse())
  apiBox.createOrder.mockReset().mockResolvedValue(createResponse)
  apiBox.getOrder.mockReset().mockResolvedValue(paidOrder)
  redirectBox.redirectToUrl.mockReset()
})

afterEach(() => {
  vi.useRealTimers()
})

import { afterEach } from 'vitest'

describe('MembershipCheckoutView', () => {
  it('renders the plan amount from the plans API, not from i18n literals', async () => {
    const { wrapper } = await mountView({ plan: 'yearly' })

    expect(wrapper.find('.checkout-amount').text()).toContain('¥159')
    expect(wrapper.find('.checkout-amount').text()).toContain('/ 年')
    expect(wrapper.find('.checkout-plan-name').text()).toBe('vip · 按年付')
    expect(apiBox.listPlans).toHaveBeenCalledTimes(1)
  })

  it('greys out unavailable channels and selects the first available one', async () => {
    const { wrapper } = await mountView()
    const channels = wrapper.findAll('.checkout-channel')

    expect(channels).toHaveLength(3)
    expect(channels[0].text()).toContain('微信支付')
    expect(channels[0].classes()).toContain('checkout-channel--selected')
    expect(channels[1].attributes('disabled')).toBeDefined()
    expect(channels[1].text()).toContain('即将开放')
    expect(channels[2].attributes('disabled')).toBeDefined()
  })

  it('creates an order on submit and renders the qr placeholder with raw content', async () => {
    const { wrapper } = await mountView()

    await wrapper.find('.checkout-submit').trigger('click')
    await flushPromises()

    expect(apiBox.createOrder).toHaveBeenCalledWith(
      'member_monthly',
      'wechat_native',
      expect.any(String),
    )
    expect(wrapper.find('.checkout-qr').exists()).toBe(true)
    expect(wrapper.find('.checkout-instruction-raw').text()).toBe(
      'weixin://wxpay/bizpayurl?pr=abc',
    )
    expect(wrapper.text()).toContain('等待支付结果…')
    expect(wrapper.text()).toContain('P202608190001AB12CD')
  })

  it('auto-redirects redirect_url instructions after a short delay and keeps a manual link', async () => {
    apiBox.listPlans.mockResolvedValue(
      plansResponse({
        channels: [
          { channel: 'wechat_native', available: false },
          { channel: 'alipay_page', available: true },
          { channel: 'stripe', available: false },
        ],
      }),
    )
    const gatewayUrl = 'https://openapi.alipay.com/gateway.do?app_id=x&sign=y'
    apiBox.createOrder.mockResolvedValue({
      order: {
        ...paidOrder,
        status: 'pending',
        paid_at: null,
        channel_order_no: '',
        channel: 'alipay_page',
      },
      instruction: { kind: 'redirect_url', content: gatewayUrl },
    })
    const { wrapper } = await mountView()

    await wrapper.find('.checkout-submit').trigger('click')
    await flushPromises()

    // 延迟窗口内不跳，先渲染提示与手动兜底链接
    expect(redirectBox.redirectToUrl).not.toHaveBeenCalled()
    expect(wrapper.find('a.checkout-redirect').attributes('href')).toBe(gatewayUrl)
    expect(wrapper.text()).toContain('正在跳转支付页')

    await vi.advanceTimersByTimeAsync(600)
    expect(redirectBox.redirectToUrl).toHaveBeenCalledTimes(1)
    expect(redirectBox.redirectToUrl).toHaveBeenCalledWith(gatewayUrl)
  })

  it('never auto-redirects qr_code instructions', async () => {
    const { wrapper } = await mountView()
    await wrapper.find('.checkout-submit').trigger('click')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(5000)
    expect(redirectBox.redirectToUrl).not.toHaveBeenCalled()
  })

  it('ticks a live countdown from the backend expires_at while awaiting payment', async () => {
    vi.setSystemTime(new Date('2026-08-19T12:00:00Z'))
    // 全程保持 pending：隔离倒计时展示与轮询状态翻转两条链路；
    // TTL 缩到 2 分钟，避免快进越过 PAYMENT_POLL_MAX 触发 poll_timeout
    apiBox.createOrder.mockResolvedValue({
      order: {
        ...paidOrder,
        status: 'pending',
        paid_at: null,
        channel_order_no: '',
        expires_at: '2026-08-19T12:02:00Z',
      },
      instruction: { kind: 'qr_code', content: 'weixin://wxpay/bizpayurl?pr=abc' },
    })
    apiBox.getOrder.mockResolvedValue({
      ...paidOrder,
      status: 'pending',
      paid_at: null,
      expires_at: '2026-08-19T12:02:00Z',
    })
    const { wrapper } = await mountView()
    await wrapper.find('.checkout-submit').trigger('click')
    await flushPromises()

    // 订单 12:02 过期 → 创建时刻剩 02:00
    expect(wrapper.text()).toContain('订单支付有效期剩余 02:00')
    await vi.advanceTimersByTimeAsync(1000)
    expect(wrapper.text()).toContain('订单支付有效期剩余 01:59')
    // 到期后钳在 00:00，状态翻转仍由后端轮询裁决
    await vi.advanceTimersByTimeAsync(2 * 60 * 1000)
    expect(wrapper.text()).toContain('订单支付有效期剩余 00:00')
  })

  it('stops showing the countdown once the order reaches a terminal state', async () => {
    vi.setSystemTime(new Date('2026-08-19T12:00:00Z'))
    const { wrapper } = await mountView()
    await wrapper.find('.checkout-submit').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('订单支付有效期剩余')

    await vi.advanceTimersByTimeAsync(3000)
    await flushPromises()
    expect(wrapper.text()).toContain('支付成功')
    expect(wrapper.text()).not.toContain('订单支付有效期剩余')
  })

  it('lands on the paid state when polling observes the paid status', async () => {
    const { wrapper } = await mountView()
    await wrapper.find('.checkout-submit').trigger('click')
    await flushPromises()

    await vi.advanceTimersByTimeAsync(3000)
    await flushPromises()

    expect(apiBox.getOrder).toHaveBeenCalledWith('P202608190001AB12CD')
    expect(wrapper.text()).toContain('支付成功，vip 已开通！')
  })

  it('shows the expired state with a restart action when the order expires', async () => {
    apiBox.getOrder.mockResolvedValue({ ...paidOrder, status: 'expired' })
    const { wrapper } = await mountView()
    await wrapper.find('.checkout-submit').trigger('click')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(3000)
    await flushPromises()

    expect(wrapper.text()).toContain('订单已过期，请重新发起支付。')
    await wrapper.find('.checkout-submit').trigger('click')
    await flushPromises()
    // 重新发起回到待支付（新的支付尝试）
    expect(wrapper.text()).toContain('去支付')
    expect(apiBox.createOrder).toHaveBeenCalledTimes(1)
  })

  it('redirects back to the membership page when the plan is missing', async () => {
    apiBox.listPlans.mockResolvedValue(plansResponse({ plans: [] }))
    const { router } = await mountView()

    expect(router.currentRoute.value.name).toBe('membership')
  })

  it('shows the fallback notice when plans fail to load', async () => {
    apiBox.listPlans.mockRejectedValue(new Error('404'))
    const { wrapper } = await mountView()

    expect(wrapper.text()).toContain('收银台暂不可用。')
    expect(wrapper.find('.checkout-submit').exists()).toBe(false)
  })

  it('shows create_failed when order creation rejects with a 503', async () => {
    apiBox.createOrder.mockRejectedValue({
      response: { status: 503, data: { detail: 'payment_channel_not_configured' } },
    })
    const { wrapper } = await mountView()
    await wrapper.find('.checkout-submit').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('创建订单失败，请稍后重试。')
  })
})
