import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PaymentPricingPanel from './PaymentPricingPanel.vue'
import i18n, { setAppLocale } from '@/i18n'
import {
  createPaymentPlanPricingForm,
  type PaymentPlanPricing,
} from '@/features/monitor/monitorModel'

const plansFixture = (
  monthlyOverride: number | null,
  yearlyOverride: number | null,
  monthlyUsdOverride: number | null = null,
  yearlyUsdOverride: number | null = null,
): PaymentPlanPricing[] => [
  {
    code: 'member_monthly', tier: 'member', currency: 'CNY', months: 1,
    default_amount_cents: 1900, override_amount_cents: monthlyOverride,
    amount_cents: monthlyOverride ?? 1900,
    updated_at: monthlyOverride === null ? null : '2026-08-24T10:00:00+00:00',
  },
  {
    code: 'member_yearly', tier: 'member', currency: 'CNY', months: 12,
    default_amount_cents: 15900, override_amount_cents: yearlyOverride,
    amount_cents: yearlyOverride ?? 15900,
    updated_at: yearlyOverride === null ? null : '2026-08-24T10:00:00+00:00',
  },
  {
    code: 'member_monthly_usd', tier: 'member', currency: 'USD', months: 1,
    default_amount_cents: 490, override_amount_cents: monthlyUsdOverride,
    amount_cents: monthlyUsdOverride ?? 490,
    updated_at: monthlyUsdOverride === null ? null : '2026-08-24T10:00:00+00:00',
  },
  {
    code: 'member_yearly_usd', tier: 'member', currency: 'USD', months: 12,
    default_amount_cents: 3900, override_amount_cents: yearlyUsdOverride,
    amount_cents: yearlyUsdOverride ?? 3900,
    updated_at: yearlyUsdOverride === null ? null : '2026-08-24T10:00:00+00:00',
  },
]

const mountPanel = (props: { plans?: PaymentPlanPricing[]; loading?: boolean; saving?: boolean } = {}) => {
  const form = createPaymentPlanPricingForm(props.plans ?? null)
  const wrapper = mount(PaymentPricingPanel, {
    global: { plugins: [i18n] },
    props: { plans: [], loading: false, saving: false, form, ...props },
  })
  return { wrapper, form }
}

describe('PaymentPricingPanel', () => {
  beforeEach(() => {
    setAppLocale('zh-CN')
  })

  it('renders all four plan rows with default prices as placeholders', () => {
    const { wrapper } = mountPanel({ plans: plansFixture(null, null) })
    expect(wrapper.find('h3').text()).toBe('会员套餐定价')
    const inputs = wrapper.findAll('input')
    expect(inputs).toHaveLength(4)
    // 默认价行进 placeholder，输入框留空（空 = 恢复默认语义）
    expect(inputs[0]!.attributes('placeholder')).toBe('19')
    expect(inputs[1]!.attributes('placeholder')).toBe('159')
    expect(inputs[2]!.attributes('placeholder')).toBe('4.9')
    expect(inputs[3]!.attributes('placeholder')).toBe('39')
    const text = wrapper.text()
    expect(text).toContain('月付（¥/月）')
    expect(text).toContain('年付（¥/年）')
    expect(text).toContain('月付（$/月）')
    expect(text).toContain('年付（$/年）')
    expect(text).toContain('默认 ¥19')
    expect(text).toContain('生效 ¥19')
    expect(text).toContain('默认 ¥159')
    expect(text).toContain('生效 ¥159')
    expect(text).toContain('默认 $4.9')
    expect(text).toContain('生效 $39')
    expect(text).toContain('默认价')
  })

  it('marks overridden plans and shows the effective price', () => {
    const { wrapper, form } = mountPanel({ plans: plansFixture(2500, null) })
    expect(form).toEqual({ monthly_yuan: '25', yearly_yuan: '', monthly_usd: '', yearly_usd: '' })
    const text = wrapper.text()
    expect(text).toContain('生效 ¥25')
    expect(text).toContain('已覆盖')
    // 恢复默认按钮只在有覆盖或表单非空时出现：月付行有、其余三行无
    const restoreButtons = wrapper.findAll('button[type="button"]')
    expect(restoreButtons).toHaveLength(1)
    expect(restoreButtons[0]!.text()).toBe('恢复默认')
  })

  it('writes yuan input back into the form draft and restores defaults', async () => {
    const { wrapper, form } = mountPanel({ plans: plansFixture(2500, 20000) })
    const inputs = wrapper.findAll('input')
    await inputs[0]!.setValue('29.9')
    expect(form.monthly_yuan).toBe('29.9')

    // 恢复默认按钮把字段清回空串（null 语义）
    const restoreButtons = wrapper.findAll('button[type="button"]')
    expect(restoreButtons).toHaveLength(2)
    await restoreButtons[0]!.trigger('click')
    expect(form.monthly_yuan).toBe('')
    expect(form.yearly_yuan).toBe('200')
  })

  it('tracks USD overrides in the form and shows the effective dollar price', async () => {
    const { wrapper, form } = mountPanel({ plans: plansFixture(null, null, 550, 4200) })
    expect(form).toEqual({ monthly_yuan: '', yearly_yuan: '', monthly_usd: '5.5', yearly_usd: '42' })
    const text = wrapper.text()
    expect(text).toContain('生效 $5.5')
    expect(text).toContain('生效 $42')

    // 美元行复用同一回写通道
    const inputs = wrapper.findAll('input')
    await inputs[2]!.setValue('4.99')
    expect(form.monthly_usd).toBe('4.99')
  })

  it('emits save on submit and locks inputs while saving', async () => {
    const onSave = vi.fn()
    const form = createPaymentPlanPricingForm()
    const wrapper = mount(PaymentPricingPanel, {
      global: { plugins: [i18n] },
      props: { plans: [], form, loading: false, saving: false, onSave },
    })
    await wrapper.find('button.monitor-btn-primary').trigger('click')
    expect(onSave).toHaveBeenCalledTimes(1)

    const { wrapper: locking } = mountPanel({ plans: plansFixture(null, null), saving: true })
    expect(locking.find('button.monitor-btn-primary').attributes('disabled')).toBeDefined()
    expect(locking.find('button.monitor-btn-primary').text()).toContain('保存中')
    for (const input of locking.findAll('input')) {
      expect(input.attributes('disabled')).toBeDefined()
    }
  })

  it('shows the loading hint while pricing is being fetched', () => {
    const { wrapper } = mountPanel({ loading: true })
    expect(wrapper.text()).toContain('加载中')
    expect(wrapper.find('button.monitor-btn-primary').attributes('disabled')).toBeDefined()
  })
})
