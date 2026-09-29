import { describe, expect, it } from 'vitest'

import {
  DEFAULT_VISIT_STATS_WINDOW,
  DONUT_CIRCUMFERENCE,
  DONUT_SEGMENT_GAP_PX,
  PLATFORM_COLOR_SLOT,
  VISIT_PLATFORM_ORDER,
  automatedVisits,
  buildDonutSegments,
  computeShares,
  isEmptyStats,
  orderedPlatformShares,
  type VisitPlatformShare,
} from './visitStatsViewModel'

const row = (platform: VisitPlatformShare['platform'], visits: number): VisitPlatformShare => ({
  platform, visits, share: 0,
})

describe('orderedPlatformShares', () => {
  it('returns the frozen bucket order and zero-fills missing buckets', () => {
    const ordered = orderedPlatformShares([row('windows', 2), row('ios', 6)])
    expect(ordered.map((entry) => entry.platform)).toEqual([...VISIT_PLATFORM_ORDER])
    expect(ordered.map((entry) => entry.visits)).toEqual([6, 0, 2, 0, 0, 0])
  })

  it('tolerates nullish input and clamps negative visits', () => {
    expect(orderedPlatformShares(null).every((entry) => entry.visits === 0)).toBe(true)
    expect(orderedPlatformShares([row('ios', -3)])[0]!.visits).toBe(0)
  })
})

describe('computeShares', () => {
  it('always sums to exactly 100.0 via largest remainder (33.33% triple split)', () => {
    const shares = computeShares([row('ios', 1), row('android', 1), row('windows', 1)])
    // 整数刻度（0.1% 为单位）恒等于 1000——浮点累加的 1e-14 抖动只是 IEEE 表象
    const unitSum = Object.values(shares).reduce((a, b) => a + Math.round(b * 10), 0)
    expect(unitSum).toBe(1000)
    expect(Object.values(shares).reduce((a, b) => a + b, 0)).toBeCloseTo(100, 10)
    // 1/3 × 3：每桶 33.3，余量并列时按桶序补给靠前者，共补 1 个 0.1
    expect(shares.ios).toBe(33.4)
    expect(shares.android).toBe(33.3)
    expect(shares.windows).toBe(33.3)
  })

  it('keeps zero visits at exactly 0 and distributes proportionally', () => {
    const shares = computeShares([row('ios', 75), row('macos', 25)])
    expect(shares.ios).toBe(75)
    expect(shares.macos).toBe(25)
    expect(shares.other).toBe(0)
  })

  it('returns all-zero shares for an empty window without dividing by zero', () => {
    const shares = computeShares([])
    expect(Object.values(shares)).toEqual([0, 0, 0, 0, 0, 0])
  })
})

describe('buildDonutSegments', () => {
  it('splits the circumference by share with surface gaps between segments', () => {
    const segments = buildDonutSegments([row('ios', 50), row('android', 50)])
    const ios = segments[0]!
    const android = segments[1]!
    const half = DONUT_CIRCUMFERENCE / 2
    // 每桶可见弧长 = 半周长 - 间隙
    expect(ios.dasharray).toBe(`${(half - DONUT_SEGMENT_GAP_PX).toFixed(4)} ${(half + DONUT_SEGMENT_GAP_PX).toFixed(4)}`)
    expect(ios.dashoffset).toBe(-(DONUT_SEGMENT_GAP_PX / 2))
    expect(android.dashoffset).toBe(-(half + DONUT_SEGMENT_GAP_PX / 2))
    // 零值桶不占弧长
    expect(segments[2]!.dasharray.startsWith('0.0000')).toBe(true)
  })

  it('leaves no fake gap when a single bucket owns the whole ring', () => {
    const segments = buildDonutSegments([row('ios', 10)])
    const ios = segments[0]!
    expect(ios.dasharray).toBe(`${DONUT_CIRCUMFERENCE.toFixed(4)} ${(0).toFixed(4)}`)
    expect(ios.dashoffset).toBe(-0)
  })

  it('maps every bucket to a fixed color slot (color follows entity, never rank)', () => {
    expect(Object.keys(PLATFORM_COLOR_SLOT)).toEqual([...VISIT_PLATFORM_ORDER])
    expect(new Set(Object.values(PLATFORM_COLOR_SLOT)).size).toBe(6)
    // linux 后加取空槽位 6，既有桶不改色
    expect(PLATFORM_COLOR_SLOT.other).toBe(5)
    expect(PLATFORM_COLOR_SLOT.linux).toBe(6)
  })
})

describe('isEmptyStats / defaults', () => {
  it('treats missing or zero-total responses as empty', () => {
    expect(isEmptyStats(null)).toBe(true)
    expect(isEmptyStats(undefined)).toBe(true)
    expect(isEmptyStats({ window: '7d', start_date: '2026-08-16', end_date: '2026-08-22', total_visits: 0, platforms: [] })).toBe(true)
    expect(isEmptyStats({ window: '7d', start_date: '2026-08-16', end_date: '2026-08-22', total_visits: 3, platforms: [] })).toBe(false)
  })

  it('reads automated visits separately and treats missing or dirty values as zero', () => {
    const base = { window: '7d' as const, start_date: '2026-08-16', end_date: '2026-08-22', total_visits: 3, platforms: [] }
    expect(automatedVisits({ ...base, automated_visits: 48 })).toBe(48)
    expect(automatedVisits(base)).toBe(0)
    expect(automatedVisits({ ...base, automated_visits: -2 })).toBe(0)
    expect(automatedVisits(null)).toBe(0)
  })

  it('defaults to the 7d window', () => {
    expect(DEFAULT_VISIT_STATS_WINDOW).toBe('7d')
  })
})
