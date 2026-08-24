import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PaymentPricingPanel from './PaymentPricingPanel.vue'
import i18n, { setAppLocale } from '@/i18n'
import {
  createPaymentPlanPricingForm,
  type PaymentPlanPricing,
} from '@/features/monitor/monitorModel'

const plansFixture = (monthlyOverride: number | null, yearlyOverride: number | null): PaymentPlanPricing[] => [
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

  it('renders both plan rows with default prices as placeholders', () => {
    const { wrapper } = mountPanel({ plans: plansFixture(null, null) })
    expect(wrapper.find('h3').text()).toBe('会员套餐定价')
    const inputs = wrapper.findAll('input')
    expect(inputs).toHaveLength(2)
    // 默认价行进 placeholder，输入框留空（空 = 恢复默认语义）
    expect(inputs[0]!.attributes('placeholder')).toBe('19')
    expect(inputs[1]!.attributes('placeholder')).toBe('159')
    const text = wrapper.text()
    expect(text).toContain('月付')
    expect(text).toContain('年付')
    expect(text).toContain('默认 ¥19')
    expect(text).toContain('生效 ¥19')
    expect(text).toContain('默认 ¥159')
    expect(text).toContain('生效 ¥159')
    expect(text).toContain('默认价')
  })

  it('marks overridden plans and shows the effective price', () => {
    const { wrapper, form } = mountPanel({ plans: plansFixture(2500, null) })
    expect(form).toEqual({ monthly_yuan: '25', yearly_yuan: '' })
    const text = wrapper.text()
    expect(text).toContain('生效 ¥25')
    expect(text).toContain('已覆盖')
    // 恢复默认按钮只在有覆盖或表单非空时出现：月付行有、年付行无
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
