import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PaymentConfigPanel from './PaymentConfigPanel.vue'
import i18n, { setAppLocale } from '@/i18n'
import { buildPaymentConfigPayload, createPaymentConfigForm, type PaymentConfig, type PaymentConfigForm } from '@/features/monitor/monitorModel'

const buildConfig = (overrides: Partial<PaymentConfig> = {}): PaymentConfig => ({
  enabled: true,
  order_ttl_minutes: 30,
  public_base_url: 'https://pay.example.com',
  wechat_appid: 'wx123',
  wechat_mchid: '1600000000',
  wechat_mch_serial_no: 'SERIAL',
  alipay_appid: '',
  source: 'database',
  updated_at: '2026-08-20T01:00:00+00:00',
  wechat_configured: true,
  alipay_configured: false,
  stripe_configured: true,
  wechat_api_v3_key_configured: true,
  wechat_api_v3_key_masked: 'abcd****wxyz',
  wechat_private_key_pem_configured: true,
  wechat_private_key_pem_masked: '----****END ',
  alipay_private_key_pem_configured: false,
  alipay_private_key_pem_masked: null,
  alipay_public_key_pem_configured: false,
  alipay_public_key_pem_masked: null,
  stripe_secret_key_configured: true,
  stripe_secret_key_masked: 'sk_l****cret',
  stripe_webhook_secret_configured: true,
  stripe_webhook_secret_masked: 'whse****cret',
  ...overrides,
})

const mountPanel = (config: PaymentConfig | null, form?: PaymentConfigForm) =>
  mount(PaymentConfigPanel, {
    global: { plugins: [i18n] },
    props: { config, form: form ?? createPaymentConfigForm(config), loading: false, saving: false, resetting: false },
  })

describe('PaymentConfigPanel', () => {
  beforeEach(() => {
    setAppLocale('zh-CN')
  })

  it('renders source and per-channel badges from the masked projection', () => {
    const wrapper = mountPanel(buildConfig())
    const badges = wrapper.findAll('.badge').map(badge => badge.text())
    expect(badges.some(text => text.includes('来源：数据库'))).toBe(true)
    expect(badges.some(text => text.includes('微信支付 · 已配置'))).toBe(true)
    expect(badges.some(text => text.includes('支付宝 · 未配置'))).toBe(true)
    expect(badges.some(text => text.includes('Stripe · 已配置'))).toBe(true)
    // 脱敏 badge 只显示 masked 值，绝不明文
    expect(wrapper.text()).toContain('sk_l****cret')
  })

  it('keeps secret inputs blank and never pre-fills masked values', () => {
    const form = createPaymentConfigForm(buildConfig())
    const wrapper = mountPanel(buildConfig(), form)
    const password = wrapper.find('input[type="password"]')
    expect((password.element as HTMLInputElement).value).toBe('')
    expect(password.attributes('placeholder')).toBe('留空则保留当前值')
    const textareas = wrapper.findAll('textarea')
    expect(textareas.length).toBeGreaterThan(0)
    expect((textareas[0]!.element as HTMLTextAreaElement).value).toBe('')
  })

  it('writes form fields back on input without mutating config', async () => {
    const form = createPaymentConfigForm(null)
    const wrapper = mountPanel(null, form)
    const toggle = wrapper.find('input[type="checkbox"]')
    await toggle.setValue(true)
    expect(form.enabled).toBe(true)
    const ttl = wrapper.find('input[type="number"]')
    await ttl.setValue(60)
    expect(form.order_ttl_minutes).toBe(60)
  })

  it('emits save and reset events from the action buttons', async () => {
    // 监听 prop 断言替代 emitted()：本环境 VTU 的 emitted 追踪不记录模板内 emit
    const events = { onSave: vi.fn(), onReset: vi.fn() }
    const wrapper = mount(PaymentConfigPanel, {
      global: { plugins: [i18n] },
      props: { config: buildConfig(), form: createPaymentConfigForm(null), loading: false, saving: false, resetting: false, ...events },
    })
    const buttons = wrapper.findAll('button')
    await buttons[0]!.trigger('click')
    await buttons[1]!.trigger('click')
    expect(events.onSave).toHaveBeenCalledTimes(1)
    expect(events.onReset).toHaveBeenCalledTimes(1)
  })

  it('builds payload with null secrets for retain semantics and clear flags', () => {
    const form = createPaymentConfigForm(buildConfig())
    form.stripe_secret_key = 'sk_live_new'
    form.clear_wechat_api_v3_key = true
    const payload = buildPaymentConfigPayload(form)
    expect(payload.enabled).toBe(true)
    expect(payload.wechat_api_v3_key).toBeNull()
    expect(payload.clear_wechat_api_v3_key).toBe(true)
    expect(payload.stripe_secret_key).toBe('sk_live_new')
    expect(payload.alipay_private_key_pem).toBeNull()
    expect(payload.public_base_url).toBe('https://pay.example.com')
  })
})
