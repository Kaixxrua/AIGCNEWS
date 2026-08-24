import { describe, expect, it } from 'vitest'
import {
  FALLBACK_MEMBER_MONTHLY_CENTS,
  FALLBACK_MEMBER_YEARLY_CENTS,
  PAYMENT_CHANNELS,
  computeYearlyDiscountPercent,
  computeYearlySavingsCents,
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
  it('formats CNY amounts with the yuan sign and trims insignificant trailing zeros', () => {
    expect(formatAmountCents(1900, 'CNY')).toBe('¥19')
    expect(formatAmountCents(15900, 'CNY')).toBe('¥159')
    // 角去尾零：¥19.9 而不是 ¥19.90；分位非零时保留两位
    expect(formatAmountCents(1990, 'CNY')).toBe('¥19.9')
    expect(formatAmountCents(1999, 'CNY')).toBe('¥19.99')
    expect(formatAmountCents(1901, 'CNY')).toBe('¥19.01')
    expect(formatAmountCents(5, 'CNY')).toBe('¥0.05')
    expect(formatAmountCents(1000000, 'CNY')).toBe('¥10000')
  })

  it('prefixes the currency code for non-CNY amounts', () => {
    expect(formatAmountCents(500, 'USD')).toBe('USD 5')
    expect(formatAmountCents(550, 'USD')).toBe('USD 5.5')
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

describe('fallback plan price constants', () => {
  // 与 backend/app/services/payments/plans.py 常量跨侧钉死：plans 探测失败时
  // 会员卡按兜底价渲染，漂移必须改两侧测试。
  it('pins the fallback prices to the backend default catalog', () => {
    expect(FALLBACK_MEMBER_MONTHLY_CENTS).toBe(1900)
    expect(FALLBACK_MEMBER_YEARLY_CENTS).toBe(15900)
  })
})

describe('computeYearlySavingsCents', () => {
  it('computes monthly×12 − yearly for the default catalog', () => {
    expect(computeYearlySavingsCents(1900, 15900)).toBe(6900)
  })

  it('tracks runtime overrides', () => {
    expect(computeYearlySavingsCents(2500, 20000)).toBe(10000)
  })

  it('goes non-positive when yearly is not cheaper (pill hides)', () => {
    expect(computeYearlySavingsCents(1900, 22800)).toBe(0)
    expect(computeYearlySavingsCents(1900, 30000)).toBeLessThan(0)
  })
})

describe('computeYearlyDiscountPercent', () => {
  it('computes floor((1 − yearly/(monthly×12)) × 100) for the default catalog', () => {
    expect(computeYearlyDiscountPercent(1900, 15900)).toBe(30)
  })

  it('floors odd ratios instead of rounding up', () => {
    // 1 − 20000/30000 = 33.33…% → 33
    expect(computeYearlyDiscountPercent(2500, 20000)).toBe(33)
  })

  it('clamps to 0 when yearly is not cheaper (badge hides)', () => {
    expect(computeYearlyDiscountPercent(1900, 22800)).toBe(0)
    expect(computeYearlyDiscountPercent(1900, 30000)).toBe(0)
  })

  it('returns 0 for a non-positive baseline instead of dividing by zero', () => {
    expect(computeYearlyDiscountPercent(0, 15900)).toBe(0)
  })
})
