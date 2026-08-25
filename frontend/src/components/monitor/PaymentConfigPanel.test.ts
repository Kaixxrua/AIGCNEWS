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
  overseas_configured: true,
  overseas_provider: 'paypal',
  overseas_sandbox: true,
  overseas_client_id: 'PAYPAL_CLIENT_ID',
  wechat_api_v3_key_configured: true,
  wechat_api_v3_key_masked: 'abcd****wxyz',
  wechat_private_key_pem_configured: true,
  wechat_private_key_pem_masked: '----****END ',
  wechat_public_key_id: 'PUB_KEY_ID_0114',
  wechat_public_key_pem_configured: true,
  wechat_public_key_pem_masked: '----****END ',
  alipay_private_key_pem_configured: false,
  alipay_private_key_pem_masked: null,
  alipay_public_key_pem_configured: false,
  alipay_public_key_pem_masked: null,
  overseas_client_secret_configured: true,
  overseas_client_secret_masked: 'clie****cret',
  overseas_webhook_secret_configured: true,
  overseas_webhook_secret_masked: 'whid****cret',
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
    expect(badges.some(text => text.includes('Overseas · 已配置'))).toBe(true)
    // 脱敏 badge 只显示 masked 值，绝不明文
    expect(wrapper.text()).toContain('clie****cret')
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
    form.overseas_client_secret = 'new_client_secret'
    form.clear_wechat_api_v3_key = true
    const payload = buildPaymentConfigPayload(form)
    expect(payload.enabled).toBe(true)
    expect(payload.wechat_api_v3_key).toBeNull()
    expect(payload.clear_wechat_api_v3_key).toBe(true)
    expect(payload.overseas_client_secret).toBe('new_client_secret')
    expect(payload.overseas_webhook_secret).toBeNull()
    expect(payload.alipay_private_key_pem).toBeNull()
    expect(payload.public_base_url).toBe('https://pay.example.com')
    // 海外文本字段透传：provider/sandbox/client_id 随配置回显、原样提交
    expect(payload.overseas_provider).toBe('paypal')
    expect(payload.overseas_sandbox).toBe(true)
    expect(payload.overseas_client_id).toBe('PAYPAL_CLIENT_ID')
    expect(payload.clear_overseas_client_secret).toBe(false)
    // 微信支付公钥：ID 是文本字段（随配置回显、trim 提交），PEM 走密文保留/擦除语义
    expect(payload.wechat_public_key_id).toBe('PUB_KEY_ID_0114')
    expect(payload.wechat_public_key_pem).toBeNull()
    expect(payload.clear_wechat_public_key_pem).toBe(false)
    form.wechat_public_key_pem = '-----BEGIN PUBLIC KEY-----\nnew\n-----END PUBLIC KEY-----'
    form.clear_wechat_public_key_pem = true
    const updated = buildPaymentConfigPayload(form)
    expect(updated.wechat_public_key_pem).toContain('BEGIN PUBLIC KEY')
    expect(updated.clear_wechat_public_key_pem).toBe(true)
  })

  it('writes overseas provider select and sandbox checkbox back to the form', async () => {
    const form = createPaymentConfigForm(null)
    const wrapper = mountPanel(null, form)
    const select = wrapper.find('select')
    expect(select.exists()).toBe(true)
    // 服务商选项是品牌字面量（不进 i18n）：未选/PayPal/PingPong
    const options = select.findAll('option').map(option => [option.attributes('value'), option.text()])
    expect(options[1]).toEqual(['paypal', 'PayPal'])
    expect(options[2]).toEqual(['pingpong', 'PingPong'])
    await select.setValue('pingpong')
    expect(form.overseas_provider).toBe('pingpong')

    const sandbox = wrapper.findAll('input[type="checkbox"]').find(
      input => input.element.parentElement?.textContent?.includes('沙箱模式'),
    )
    expect(sandbox).toBeTruthy()
    await sandbox!.setValue(true)
    expect(form.overseas_sandbox).toBe(true)
  })

  it('groups each channel secret field inside its own channel section', () => {
    // 渠道密钥各归各位的契约：微信/支付宝/海外 的密钥只出现在各自区块内，
    // 防回归回「三渠道混排在一个密文区」的旧布局
    const wrapper = mountPanel(buildConfig())
    const sectionText = (title: string) => {
      const h4 = wrapper.findAll('h4').find(node => node.text() === title)
      expect(h4, `section ${title}`).toBeTruthy()
      return (h4!.element.parentElement?.parentElement?.textContent) ?? ''
    }
    const wechat = sectionText('微信支付')
    expect(wechat).toContain('API v3 密钥')
    expect(wechat).toContain('商户私钥')
    expect(wechat).toContain('微信支付公钥 ID')
    expect(wechat).toContain('微信支付公钥（PEM）')
    expect(wechat).not.toContain('支付宝公钥')
    const alipay = sectionText('支付宝')
    expect(alipay).toContain('应用私钥')
    expect(alipay).toContain('支付宝公钥')
    expect(alipay).not.toContain('商户私钥')
    const overseas = sectionText('海外支付')
    expect(overseas).toContain('Client Secret')
    expect(overseas).toContain('Webhook 密钥')
    expect(overseas).toContain('服务商')
    expect(overseas).not.toContain('商户私钥')
  })
})
