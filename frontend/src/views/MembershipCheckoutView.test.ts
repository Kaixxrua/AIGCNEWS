import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MembershipCheckoutView from './MembershipCheckoutView.vue'
import { useAuthStore } from '@/stores/authStore'
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

const redirectBox = vi.hoisted(() => ({ openPaymentPageInNewTab: vi.fn() }))

vi.mock('@/services/payments/paymentApi', () => ({ paymentApi: apiBox }))
vi.mock('@/services/payments/redirect', () => redirectBox)

const plansResponse = (overrides: Partial<PaymentPlansResponse> = {}): PaymentPlansResponse => ({
  plans: [
    { code: 'member_monthly', tier: 'member', amount_cents: 1900, currency: 'CNY', months: 1 },
    { code: 'member_yearly', tier: 'member', amount_cents: 15900, currency: 'CNY', months: 12 },
    { code: 'member_monthly_usd', tier: 'member', amount_cents: 490, currency: 'USD', months: 1 },
    { code: 'member_yearly_usd', tier: 'member', amount_cents: 3900, currency: 'USD', months: 12 },
  ],
  channels: [
    { channel: 'wechat_native', available: true },
    { channel: 'alipay_page', available: false },
    { channel: 'overseas_redirect', available: false },
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
          channelOverseas: '海外支付（银行卡 / PayPal）',
          channelSoon: '即将开放',
          submit: '去支付',
          submitting: '创建订单中…',
          createFailed: '创建订单失败，请稍后重试。',
          qrPlaceholder: '支付二维码',
          scanHint: '请使用对应 App「扫一扫」完成支付',
          redirectHint: '正在新标签页打开支付页，若未自动打开请点击下方按钮',
          redirectAction: '前往支付',
          expireCountdown: '订单支付有效期剩余 {time}',
          resumeHint: '已恢复待支付订单：如未完成支付，请在支付页继续；订单过期后可重新发起。',
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
    'en-US': {
      common: { loading: 'Loading…' },
      membership: {
        checkout: {
          title: 'Subscribe to vip',
          subtitle: 'Pick a payment method to finish.',
          planMonthly: 'vip · Monthly',
          planYearly: 'vip · Annual',
          perMonth: '/ month',
          perYear: '/ year',
          channelTitle: 'Payment method',
          channelWechat: 'WeChat Pay',
          channelAlipay: 'Alipay',
          channelOverseas: 'Card / PayPal',
          channelSoon: 'Coming soon',
          submit: 'Pay now',
          submitting: 'Creating order…',
          createFailed: 'Could not create the order. Please try again.',
          qrPlaceholder: 'Payment QR code',
          scanHint: 'Scan with the corresponding app to pay',
          redirectHint: 'Opening the payment page in a new tab…',
          redirectAction: 'Continue to payment',
          expireCountdown: 'Time left to pay: {time}',
          resumeHint: 'Pending order restored.',
          awaiting: 'Waiting for payment…',
          orderNo: 'Order no.',
          paid: 'Payment received — vip is active!',
          paidHint: 'Your membership is live.',
          expired: 'This order has expired. Please start a new payment.',
          pollTimeout: 'Payment confirmation timed out.',
          retry: 'Start a new payment',
          loadFailed: 'Checkout is unavailable right now.',
          backToMembership: 'Back to membership',
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
  // 收银台在支付到账后调 authStore.fetchMe 刷新顶栏档位/到期时间：挂真实 store，
  // fetchMe 桩成 resolved 空值，避免测试环境真的打 /auth/me
  const pinia = setActivePinia(createPinia())
  const authStore = useAuthStore()
  authStore.fetchMe = vi.fn().mockResolvedValue(undefined)
  const wrapper = mount(MembershipCheckoutView, {
    global: { plugins: [i18n, router, pinia] },
  })
  await flushPromises()
  return { wrapper, router, authStore }
}

beforeEach(() => {
  vi.useFakeTimers()
  i18n.global.locale.value = 'zh-CN'
  apiBox.listPlans.mockReset().mockResolvedValue(plansResponse())
  apiBox.createOrder.mockReset().mockResolvedValue(createResponse)
  apiBox.getOrder.mockReset().mockResolvedValue(paidOrder)
  redirectBox.openPaymentPageInNewTab.mockReset()
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

  it('renders the USD yearly plan in English', async () => {
    i18n.global.locale.value = 'en-US'
    const { wrapper } = await mountView({ plan: 'yearly' })

    expect(wrapper.find('.checkout-amount').text()).toContain('$39')
    expect(wrapper.find('.checkout-amount').text()).toContain('/ year')
    expect(wrapper.find('.checkout-plan-name').text()).toBe('vip · Annual')
  })

  it('greys out unavailable channels and selects the first available one', async () => {
    const { wrapper } = await mountView()
    const channels = wrapper.findAll('.checkout-channel')

    // 中文界面只出国内渠道集（微信/支付宝），海外槽不渲染
    expect(channels).toHaveLength(2)
    expect(channels[0]!.text()).toContain('微信支付')
    expect(channels[0]!.classes()).toContain('checkout-channel--selected')
    expect(channels[1]!.text()).toContain('支付宝')
    expect(channels[1]!.attributes('disabled')).toBeDefined()
    expect(channels[1]!.text()).toContain('即将开放')
  })

  it('renders each channel brand icon with its locked brand color', async () => {
    const { wrapper } = await mountView()
    const channels = wrapper.findAll('.checkout-channel')

    // 微信绿 / 支付宝蓝：品牌图标随渠道渲染，颜色由图标组件锁官方品牌色
    expect(channels[0]!.find('svg.checkout-channel-icon').exists()).toBe(true)
    expect(channels[0]!.find('svg.checkout-channel-icon').attributes('fill')).toBe('#07C160')
    expect(channels[1]!.find('svg.checkout-channel-icon').attributes('fill')).toBe('#1677FF')

    // 英文界面海外槽 → PayPal 蓝
    i18n.global.locale.value = 'en-US'
    await flushPromises()
    const overseas = wrapper.find('.checkout-channel svg.checkout-channel-icon')
    expect(overseas.exists()).toBe(true)
    expect(overseas.attributes('fill')).toBe('#003087')
  })

  it('shows only the overseas channel in English, greyed out when unconfigured', async () => {
    i18n.global.locale.value = 'en-US'
    const { wrapper } = await mountView()
    const channels = wrapper.findAll('.checkout-channel')

    expect(channels).toHaveLength(1)
    expect(channels[0]!.text()).toContain('Card / PayPal')
    expect(channels[0]!.attributes('disabled')).toBeDefined()
    expect(channels[0]!.text()).toContain('Coming soon')
    expect(wrapper.text()).not.toContain('WeChat Pay')
    // 英文界面按 USD 套餐目录渲染金额
    expect(wrapper.find('.checkout-amount').text()).toContain('$4.9')
    expect(wrapper.find('.checkout-amount').text()).toContain('/ month')
    // 无可选渠道 → 提交按钮禁用
    expect(wrapper.find('.checkout-submit').attributes('disabled')).toBeDefined()
  })

  it('auto-selects the overseas channel in English when available and submits with it', async () => {
    i18n.global.locale.value = 'en-US'
    apiBox.listPlans.mockResolvedValue(
      plansResponse({
        channels: [
          { channel: 'wechat_native', available: true },
          { channel: 'alipay_page', available: true },
          { channel: 'overseas_redirect', available: true },
        ],
      }),
    )
    apiBox.createOrder.mockResolvedValue({
      order: {
        ...paidOrder,
        status: 'pending',
        paid_at: null,
        channel_order_no: '',
        channel: 'overseas_redirect',
        plan_code: 'member_monthly_usd',
        amount_cents: 490,
        currency: 'USD',
      },
      instruction: { kind: 'redirect_url', content: 'https://www.sandbox.paypal.com/checkoutnow?token=x' },
    })
    const { wrapper } = await mountView()
    const channels = wrapper.findAll('.checkout-channel')

    expect(channels).toHaveLength(1)
    expect(channels[0]!.classes()).toContain('checkout-channel--selected')

    await wrapper.find('.checkout-submit').trigger('click')
    await flushPromises()
    expect(apiBox.createOrder).toHaveBeenCalledWith(
      'member_monthly_usd',
      'overseas_redirect',
      expect.any(String),
    )
  })

  it('re-selects the channel when the locale switches mid-session', async () => {
    apiBox.listPlans.mockResolvedValue(
      plansResponse({
        channels: [
          { channel: 'wechat_native', available: true },
          { channel: 'alipay_page', available: true },
          { channel: 'overseas_redirect', available: true },
        ],
      }),
    )
    const { wrapper } = await mountView()

    // zh-CN：默认选中微信支付，金额为 CNY 目录
    expect(wrapper.find('.checkout-channel').text()).toContain('微信支付')
    expect(wrapper.find('.checkout-channel').classes()).toContain('checkout-channel--selected')
    expect(wrapper.find('.checkout-amount').text()).toContain('¥19')

    // 切英文：可见集变为海外槽，选中态与金额（USD 目录）随之迁移
    i18n.global.locale.value = 'en-US'
    await flushPromises()
    const channels = wrapper.findAll('.checkout-channel')
    expect(channels).toHaveLength(1)
    expect(channels[0]!.text()).toContain('Card / PayPal')
    expect(channels[0]!.classes()).toContain('checkout-channel--selected')
    expect(wrapper.find('.checkout-amount').text()).toContain('$4.9')

    await wrapper.find('.checkout-submit').trigger('click')
    await flushPromises()
    expect(apiBox.createOrder).toHaveBeenCalledWith(
      'member_monthly_usd',
      'overseas_redirect',
      expect.any(String),
    )
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

  it('auto-opens redirect_url instructions in a new tab after a short delay and keeps a manual link', async () => {
    apiBox.listPlans.mockResolvedValue(
      plansResponse({
        channels: [
          { channel: 'wechat_native', available: false },
          { channel: 'alipay_page', available: true },
          { channel: 'overseas_redirect', available: false },
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

    // 延迟窗口内不跳，先渲染提示与新标签页兜底链接
    expect(redirectBox.openPaymentPageInNewTab).not.toHaveBeenCalled()
    const fallback = wrapper.find('a.checkout-redirect')
    expect(fallback.attributes('href')).toBe(gatewayUrl)
    expect(fallback.attributes('target')).toBe('_blank')
    expect(wrapper.text()).toContain('正在新标签页打开支付页')

    await vi.advanceTimersByTimeAsync(600)
    expect(redirectBox.openPaymentPageInNewTab).toHaveBeenCalledTimes(1)
    expect(redirectBox.openPaymentPageInNewTab).toHaveBeenCalledWith(gatewayUrl)
  })

  it('never auto-opens qr_code instructions', async () => {
    const { wrapper } = await mountView()
    await wrapper.find('.checkout-submit').trigger('click')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(5000)
    expect(redirectBox.openPaymentPageInNewTab).not.toHaveBeenCalled()
  })

  it('resumes the return-url order straight into the paid state', async () => {
    apiBox.getOrder.mockResolvedValue(paidOrder)
    const { wrapper } = await mountView({ plan: 'monthly', order_no: paidOrder.order_no })

    expect(apiBox.getOrder).toHaveBeenCalledWith(paidOrder.order_no)
    expect(wrapper.text()).toContain('支付成功')
    expect(apiBox.createOrder).not.toHaveBeenCalled()
  })

  it('resumes a still-pending return-url order into awaiting with countdown and polling', async () => {
    vi.setSystemTime(new Date('2026-08-19T12:00:00Z'))
    apiBox.getOrder.mockResolvedValue({ ...paidOrder, status: 'pending', paid_at: null })
    const { wrapper } = await mountView({ plan: 'monthly', order_no: paidOrder.order_no })

    expect(wrapper.text()).toContain('等待支付结果…')
    expect(wrapper.text()).toContain('已恢复待支付订单')
    expect(wrapper.text()).toContain('订单支付有效期剩余 30:00')
    expect(wrapper.text()).toContain(paidOrder.order_no)
    // 回跳页不再出现下单按钮（防重复发起）
    expect(wrapper.find('.checkout-submit').exists()).toBe(false)
    expect(apiBox.createOrder).not.toHaveBeenCalled()

    // 轮询续上：3 秒后再查一次单
    await vi.advanceTimersByTimeAsync(3000)
    await flushPromises()
    expect(apiBox.getOrder.mock.calls.length).toBeGreaterThanOrEqual(2)
  })

  it('falls back to a fresh checkout when the return-url order_no is unknown', async () => {
    apiBox.getOrder.mockRejectedValue({ response: { status: 404 } })
    const { wrapper } = await mountView({ plan: 'monthly', order_no: 'P404UNKNOWN' })

    expect(wrapper.find('.checkout-submit').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('等待支付结果…')
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

  it('refreshes the user identity once polling observes the paid status', async () => {
    const { wrapper, authStore } = await mountView()
    await wrapper.find('.checkout-submit').trigger('click')
    await flushPromises()

    expect(authStore.fetchMe).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(3000)
    await flushPromises()

    // 到账后自动拉一次 /auth/me：顶栏用户组与到期时间无需手动刷新页面即更新
    expect(wrapper.text()).toContain('支付成功，vip 已开通！')
    expect(authStore.fetchMe).toHaveBeenCalledTimes(1)
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
