import { describe, expect, it } from 'vitest'
import { formatLocaleDate, formatLocaleNumber, parseImplicitUtc } from './formatters'

describe('calendar dates and timestamps', () => {
  it('keeps publication dates on their stated day in negative-offset timezones', () => {
    expect(formatLocaleDate('2026-01-02', { timeZone: 'America/Los_Angeles' }, 'en-US')).toBe('1/2/2026')
  })

  it('converts full timestamps using the requested timezone', () => {
    expect(formatLocaleDate('2026-01-02T03:04:05Z', { timeZone: 'America/Los_Angeles' }, 'en-US')).toBe('1/1/2026')
  })

  it.each(['2026-01-02T03:00:00-07:00', '2026-01-02T03:00:00-0700'])('respects negative offsets in %s', (value) => {
    expect(parseImplicitUtc(value).toISOString()).toBe('2026-01-02T10:00:00.000Z')
  })

  it('treats timezone-less database timestamps as UTC', () => {
    expect(parseImplicitUtc('2026-01-02T03:00:00').toISOString()).toBe('2026-01-02T03:00:00.000Z')
  })
})

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
