import { describe, expect, it } from 'vitest'
import {
  PAYMENT_CHANNELS,
  formatAmountCents,
  isTerminalOrderStatus,
  periodForPlanCode,
  planCodeForPeriod,
  resolvePlan,
} from './paymentModel'
import type { PaymentPlan } from './paymentModel'

const plan = (overrides: Partial<PaymentPlan>): PaymentPlan => ({
  code: 'member_monthly',
  tier: 'member',
  amount_cents: 1900,
  currency: 'CNY',
  months: 1,
  ...overrides,
})

describe('planCodeForPeriod / periodForPlanCode', () => {
  it('maps billing periods to backend plan codes and back', () => {
    expect(planCodeForPeriod('monthly')).toBe('member_monthly')
    expect(planCodeForPeriod('yearly')).toBe('member_yearly')
    expect(periodForPlanCode('member_monthly')).toBe('monthly')
    expect(periodForPlanCode('member_yearly')).toBe('yearly')
  })

  it('is fail-closed for unknown plan codes', () => {
    expect(periodForPlanCode('member_lifetime')).toBeNull()
    expect(periodForPlanCode('')).toBeNull()
  })
})

describe('resolvePlan', () => {
  it('picks the plan matching the billing period', () => {
    const plans = [
      plan({ code: 'member_monthly', amount_cents: 1900, months: 1 }),
      plan({ code: 'member_yearly', amount_cents: 12900, months: 12 }),
    ]
    expect(resolvePlan(plans, 'monthly')?.amount_cents).toBe(1900)
    expect(resolvePlan(plans, 'yearly')?.amount_cents).toBe(12900)
  })

  it('returns null when the plan is missing from the API response', () => {
    expect(resolvePlan([plan({ code: 'member_monthly' })], 'yearly')).toBeNull()
    expect(resolvePlan([], 'monthly')).toBeNull()
  })
})

describe('formatAmountCents', () => {
  it('formats CNY amounts with the yuan sign and no trailing decimals', () => {
    expect(formatAmountCents(1900, 'CNY')).toBe('¥19')
    expect(formatAmountCents(12900, 'CNY')).toBe('¥129')
    expect(formatAmountCents(1990, 'CNY')).toBe('¥19.90')
    expect(formatAmountCents(5, 'CNY')).toBe('¥0.05')
  })

  it('prefixes the currency code for non-CNY amounts', () => {
    expect(formatAmountCents(500, 'USD')).toBe('USD 5')
  })
})

describe('isTerminalOrderStatus', () => {
  it('only pending is pollable', () => {
    expect(isTerminalOrderStatus('pending')).toBe(false)
    expect(isTerminalOrderStatus('paid')).toBe(true)
    expect(isTerminalOrderStatus('expired')).toBe(true)
    expect(isTerminalOrderStatus('closed')).toBe(true)
  })
})

describe('PAYMENT_CHANNELS', () => {
  it('lists the three skeleton channels in display order', () => {
    expect(PAYMENT_CHANNELS).toEqual(['wechat_native', 'alipay_page', 'stripe'])
  })
})
