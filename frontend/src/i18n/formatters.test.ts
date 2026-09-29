import { describe, expect, it } from 'vitest'
import { formatLocaleNumber } from './formatters'

describe('formatLocaleNumber', () => {
  it('groups digits for either interface locale', () => {
    expect(formatLocaleNumber(48214, 'zh-CN')).toBe('48,214')
    expect(formatLocaleNumber(48214, 'en-US')).toBe('48,214')
    expect(formatLocaleNumber(36, 'zh-CN')).toBe('36')
  })

  it('treats missing or non-numeric values as zero', () => {
    expect(formatLocaleNumber(null, 'zh-CN')).toBe('0')
    expect(formatLocaleNumber(Number.NaN, 'en-US')).toBe('0')
  })
})
