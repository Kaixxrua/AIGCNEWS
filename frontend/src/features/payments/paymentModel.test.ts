import { describe, expect, it } from 'vitest'
import {
  PAYMENT_CHANNELS,
  formatAmountCents,
  formatCountdownMs,
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
      plan({ code: 'member_yearly', amount_cents: 15900, months: 12 }),
    ]
    expect(resolvePlan(plans, 'monthly')?.amount_cents).toBe(1900)
    expect(resolvePlan(plans, 'yearly')?.amount_cents).toBe(15900)
  })

  it('returns null when the plan is missing from the API response', () => {
    expect(resolvePlan([plan({ code: 'member_monthly' })], 'yearly')).toBeNull()
    expect(resolvePlan([], 'monthly')).toBeNull()
  })
})

describe('formatAmountCents', () => {
  it('formats CNY amounts with the yuan sign and no trailing decimals', () => {
    expect(formatAmountCents(1900, 'CNY')).toBe('¥19')
    expect(formatAmountCents(15900, 'CNY')).toBe('¥159')
    expect(formatAmountCents(1990, 'CNY')).toBe('¥19.90')
    expect(formatAmountCents(5, 'CNY')).toBe('¥0.05')
  })

  it('prefixes the currency code for non-CNY amounts', () => {
    expect(formatAmountCents(500, 'USD')).toBe('USD 5')
  })
})

describe('formatCountdownMs', () => {
  it('formats sub-hour remainders as MM:SS', () => {
    expect(formatCountdownMs(30 * 60 * 1000)).toBe('30:00')
    expect(formatCountdownMs(59_000)).toBe('00:59')
    expect(formatCountdownMs(59_999)).toBe('00:59')
  })

  it('formats hour-plus remainders as H:MM:SS', () => {
    expect(formatCountdownMs(3600 * 1000)).toBe('1:00:00')
    expect(formatCountdownMs((23 * 3600 + 59 * 60 + 59) * 1000)).toBe('23:59:59')
  })

  it('clamps negative remainders to 00:00', () => {
    expect(formatCountdownMs(0)).toBe('00:00')
    expect(formatCountdownMs(-1)).toBe('00:00')
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
