import { describe, expect, it } from 'vitest'
import {
  DOMESTIC_CHANNELS,
  OVERSEAS_CHANNELS,
  PAYMENT_CHANNELS,
  computeYearlyDiscountPercent,
  computeYearlySavingsCents,
  formatAmountCents,
  formatCountdownMs,
  isTerminalOrderStatus,
  periodForPlanCode,
  planCodeForPeriod,
  planCurrencyForLocale,
  resolvePlan,
  visibleChannelsForLocale,
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

  it('maps USD variants for the overseas catalog', () => {
    expect(planCodeForPeriod('monthly', 'USD')).toBe('member_monthly_usd')
    expect(planCodeForPeriod('yearly', 'USD')).toBe('member_yearly_usd')
    expect(periodForPlanCode('member_monthly_usd')).toBe('monthly')
    expect(periodForPlanCode('member_yearly_usd')).toBe('yearly')
  })

  it('is fail-closed for unknown plan codes', () => {
    expect(periodForPlanCode('member_lifetime')).toBeNull()
    expect(periodForPlanCode('')).toBeNull()
  })
})

describe('planCurrencyForLocale', () => {
  it('gates the plan currency by locale: zh buys CNY, other locales buy USD', () => {
    expect(planCurrencyForLocale('zh-CN')).toBe('CNY')
    expect(planCurrencyForLocale('zh-TW')).toBe('CNY')
    expect(planCurrencyForLocale('en-US')).toBe('USD')
    expect(planCurrencyForLocale('')).toBe('USD')
    expect(planCurrencyForLocale('fr-FR')).toBe('USD')
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

  it('picks the USD variant when the locale currency is USD', () => {
    const plans = [
      plan({ code: 'member_monthly', amount_cents: 1900, currency: 'CNY', months: 1 }),
      plan({ code: 'member_monthly_usd', amount_cents: 490, currency: 'USD', months: 1 }),
    ]
    expect(resolvePlan(plans, 'monthly', 'USD')?.code).toBe('member_monthly_usd')
    expect(resolvePlan(plans, 'monthly', 'USD')?.amount_cents).toBe(490)
    expect(resolvePlan(plans, 'monthly', 'CNY')?.code).toBe('member_monthly')
  })

  it('returns null when the plan is missing from the API response', () => {
    expect(resolvePlan([plan({ code: 'member_monthly' })], 'yearly')).toBeNull()
    expect(resolvePlan([], 'monthly')).toBeNull()
    expect(resolvePlan([plan({ code: 'member_monthly' })], 'monthly', 'USD')).toBeNull()
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

  it('formats USD amounts with the dollar sign', () => {
    expect(formatAmountCents(490, 'USD')).toBe('$4.9')
    expect(formatAmountCents(3900, 'USD')).toBe('$39')
    expect(formatAmountCents(1490, 'USD')).toBe('$14.9')
    expect(formatAmountCents(499, 'USD')).toBe('$4.99')
  })

  it('prefixes the currency code for other non-CNY amounts', () => {
    expect(formatAmountCents(500, 'EUR')).toBe('EUR 5')
    expect(formatAmountCents(550, 'EUR')).toBe('EUR 5.5')
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
  it('lists the three channels in display order', () => {
    expect(PAYMENT_CHANNELS).toEqual(['wechat_native', 'alipay_page', 'overseas_redirect'])
  })
})

describe('visibleChannelsForLocale', () => {
  it('gates channels by locale: zh sees domestic only, other locales see overseas only', () => {
    expect(DOMESTIC_CHANNELS).toEqual(['wechat_native', 'alipay_page'])
    expect(OVERSEAS_CHANNELS).toEqual(['overseas_redirect'])
    expect(visibleChannelsForLocale('zh-CN')).toEqual(['wechat_native', 'alipay_page'])
    expect(visibleChannelsForLocale('zh-TW')).toEqual(['wechat_native', 'alipay_page'])
    expect(visibleChannelsForLocale('en-US')).toEqual(['overseas_redirect'])
  })

  it('treats empty and unknown locales as overseas (English is the default foreign UI)', () => {
    expect(visibleChannelsForLocale('')).toEqual(['overseas_redirect'])
    expect(visibleChannelsForLocale('fr-FR')).toEqual(['overseas_redirect'])
  })
})

describe('computeYearlySavingsCents', () => {
  it('computes monthly×12 − yearly for the default catalog', () => {
    expect(computeYearlySavingsCents(1900, 15900)).toBe(6900)
    // 美元目录：$4.9 × 12 − $14.9 = $43.9
    expect(computeYearlySavingsCents(490, 1490)).toBe(4390)
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
    // 美元目录：1 − 14.9/58.8 = 74.66…% → 74
    expect(computeYearlyDiscountPercent(490, 1490)).toBe(74)
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
