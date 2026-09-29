import { describe, expect, it } from 'vitest'
import { parseReportDateQuery, todayInReportTimeZone } from './reportViewModel'

describe('parseReportDateQuery', () => {
  it('accepts a past or current calendar date from the RSS briefing link', () => {
    expect(parseReportDateQuery('2026-09-27', '2026-09-29')).toBe('2026-09-27')
    expect(parseReportDateQuery('2026-09-29', '2026-09-29')).toBe('2026-09-29')
  })

  it('falls back to the default date for missing, repeated, malformed or future values', () => {
    expect(parseReportDateQuery(undefined, '2026-09-29')).toBeNull()
    expect(parseReportDateQuery(['2026-09-27', '2026-09-28'], '2026-09-29')).toBeNull()
    expect(parseReportDateQuery('2026-9-27', '2026-09-29')).toBeNull()
    expect(parseReportDateQuery('2026-02-30', '2026-09-29')).toBeNull()
    expect(parseReportDateQuery('2026-09-30', '2026-09-29')).toBeNull()
  })
})

describe('todayInReportTimeZone', () => {
  it('returns the CST calendar date even when UTC is still on the previous day', () => {
    // UTC 17:00 = 次日 01:00 CST；简报缓存键按 CST 日期生成。
    expect(todayInReportTimeZone(new Date('2026-08-08T17:00:00Z'))).toBe('2026-08-09')
  })

  it('stays on the same date before the CST midnight boundary', () => {
    // UTC 15:59:59 = 当天 23:59:59 CST。
    expect(todayInReportTimeZone(new Date('2026-08-08T15:59:59Z'))).toBe('2026-08-08')
  })

  it('zero-pads month and day for single-digit values', () => {
    // UTC 2026-01-02 20:00 = CST 2026-01-03 04:00。
    expect(todayInReportTimeZone(new Date('2026-01-02T20:00:00Z'))).toBe('2026-01-03')
  })
})
