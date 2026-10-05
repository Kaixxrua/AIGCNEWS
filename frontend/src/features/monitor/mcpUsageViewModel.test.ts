import { describe, expect, it } from 'vitest'
import type { McpDailyUsageResponse, McpUsageAudienceStats, McpUsageDay } from './monitorModel'
import {
  barPercent,
  dailyMax,
  hasUsage,
  limitKindKey,
  nonZeroAudiences,
  specialClientNameKey,
  specialToolKey,
  trackedDays,
  trackingStartsInWindow,
} from './mcpUsageViewModel'

const zeroStats = (): McpUsageAudienceStats => ({
  anonymous: { clients: 0, connections: 0, calls: 0, limited: 0 },
  free: { clients: 0, connections: 0, calls: 0, limited: 0 },
  member: { clients: 0, connections: 0, calls: 0, limited: 0 },
  total: { clients: 0, connections: 0, calls: 0, limited: 0 },
})

const day = (date: string, tracked: boolean, calls = 0): McpUsageDay => {
  const stats = zeroStats()
  stats.total.calls = calls
  stats.anonymous.calls = calls
  return { date, tracked, ...stats }
}

const usage = (overrides: Partial<McpDailyUsageResponse> = {}): McpDailyUsageResponse => ({
  available: true,
  timezone: 'Asia/Shanghai',
  days: 7,
  start_date: '2026-09-29',
  end_date: '2026-10-05',
  since: '2026-10-04',
  summary: zeroStats(),
  daily: [],
  tools: [],
  client_names: [],
  client_names_truncated: false,
  limited: [],
  ...overrides,
})

describe('mcpUsageViewModel', () => {
  it('maps the Go fallback buckets and limit kinds to i18n keys and leaves real names alone', () => {
    expect(specialToolKey('__unknown__')).toBe('mcpUsage.unknownTool')
    expect(specialToolKey('search_papers')).toBeNull()
    expect(specialClientNameKey('__unknown__')).toBe('mcpUsage.unnamedClient')
    expect(specialClientNameKey('__other__')).toBe('mcpUsage.otherClients')
    expect(specialClientNameKey('cursor')).toBeNull()
    expect(limitKindKey('burst')).toBe('mcpUsage.limitKind.burst')
    expect(limitKindKey('daily')).toBe('mcpUsage.limitKind.daily')
    expect(limitKindKey('monthly')).toBe('mcpUsage.limitKind.monthly')
    expect(limitKindKey('weekly')).toBeNull()
  })

  it('drops days before tracking started and keeps the newest-first order', () => {
    const rows = [day('2026-10-05', true, 3), day('2026-10-04', true, 1), day('2026-10-03', false)]
    expect(trackedDays(usage({ daily: rows })).map((row) => row.date)).toEqual(['2026-10-05', '2026-10-04'])
    expect(trackedDays(null)).toEqual([])
  })

  it('reports usage only when some counter in the window is non-zero', () => {
    expect(hasUsage(null)).toBe(false)
    expect(hasUsage(usage())).toBe(false)
    const limitedOnly = zeroStats()
    limitedOnly.total.limited = 1
    expect(hasUsage(usage({ summary: limitedOnly }))).toBe(true)
  })

  it('flags a tracking start inside the window but not at or before its first day', () => {
    expect(trackingStartsInWindow(usage())).toBe(true)
    expect(trackingStartsInWindow(usage({ since: '2026-09-29' }))).toBe(false)
    expect(trackingStartsInWindow(usage({ since: '2026-09-01' }))).toBe(false)
    expect(trackingStartsInWindow(usage({ since: null }))).toBe(false)
    expect(trackingStartsInWindow(undefined)).toBe(false)
  })

  it('lists non-zero audiences in column order', () => {
    expect(nonZeroAudiences({ anonymous: 0, free: 2, member: 1, total: 3 })).toEqual([
      { audience: 'free', count: 2 },
      { audience: 'member', count: 1 },
    ])
    expect(nonZeroAudiences({ anonymous: 0, free: 0, member: 0, total: 0 })).toEqual([])
  })

  it('scales the daily bar to the window peak and draws nothing for an all-zero metric', () => {
    const rows = [day('2026-10-05', true, 4), day('2026-10-04', true, 1)]
    expect(dailyMax(rows, 'calls')).toBe(4)
    expect(dailyMax(rows, 'clients')).toBe(0)
    expect(barPercent(4, 4)).toBe(100)
    expect(barPercent(1, 3)).toBe(33)
    expect(barPercent(0, 0)).toBe(0)
    expect(barPercent(-2, 4)).toBe(0)
  })
})
