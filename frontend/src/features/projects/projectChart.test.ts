import { describe, expect, it } from 'vitest'
import {
  formatSparkDate,
  formatStarDelta,
  projectChartRanked,
  projectChartShowsMovement,
  projectRankMovement,
  projectSparkDays,
  projectSparkSummary,
  projectTrendKey,
} from './projectChart'

describe('projectChart', () => {
  it('asks for trends with the repository key the backend accepts', () => {
    expect(projectTrendKey({ repo_id: 'microsoft/VibeVoice', full_name: 'microsoft/VibeVoice' })).toBe('microsoft/VibeVoice')
    expect(projectTrendKey({ repo_id: 42, full_name: 'acme/tool.js' })).toBe('acme/tool.js')
    expect(projectTrendKey({ full_name: ' acme/alpha ' })).toBe('acme/alpha')
    expect(projectTrendKey({ full_name: 'acme/alpha/extra' })).toBe('')
    expect(projectTrendKey({ full_name: 'Example Website', source: 'website', website_id: 3 })).toBe('')
    expect(projectTrendKey({ full_name: 'acme/alpha', website_id: 3 })).toBe('')
  })

  it('numbers rows only for ranking sorts and compares with yesterday only on the daily chart', () => {
    expect(projectChartRanked('hot')).toBe(true)
    expect(projectChartRanked('stars')).toBe(true)
    expect(['updated', 'recent', 'name', 'relevance'].map((sort) => projectChartRanked(sort as never))).toEqual([false, false, false, false])
    expect(projectChartShowsMovement('today')).toBe(true)
    expect(projectChartShowsMovement('all')).toBe(false)
    expect(projectChartShowsMovement('recommended')).toBe(false)
  })

  it('reads movement against yesterday and treats a missing rank as new', () => {
    expect(projectRankMovement(3, 7)).toEqual({ kind: 'up', steps: 4 })
    expect(projectRankMovement(9, 2)).toEqual({ kind: 'down', steps: 7 })
    expect(projectRankMovement(5, 5)).toEqual({ kind: 'same' })
    expect(projectRankMovement(1, null)).toEqual({ kind: 'new' })
    expect(projectRankMovement(1, 0)).toEqual({ kind: 'new' })
    expect(projectRankMovement(1, Number.NaN)).toEqual({ kind: 'new' })
  })

  it('lays the window out day by day and leaves uncounted days empty', () => {
    const days = projectSparkDays([
      { date: '2026-09-29', stars: 900, gain: 5 },
      { date: '2026-09-30', stars: 910, gain: null },
      { date: '2026-10-02', stars: 990, gain: 80 },
      { date: '2026-09-01', stars: 1, gain: 999 },
    ], '2026-10-02', 5)

    expect(days).toEqual([
      { date: '2026-09-28', gain: null },
      { date: '2026-09-29', gain: 5 },
      { date: '2026-09-30', gain: null },
      { date: '2026-10-01', gain: null },
      { date: '2026-10-02', gain: 80 },
    ])
    expect(projectSparkSummary(days)).toEqual({ total: 85, peak: { date: '2026-10-02', gain: 80 }, counted: 2 })
    expect(projectSparkDays([], 'not a date', 14)).toEqual([])
    expect(projectSparkSummary([{ date: '2026-10-02', gain: null }])).toEqual({ total: 0, peak: null, counted: 0 })
  })

  it('crosses month and year ends on the calendar, not the clock', () => {
    expect(projectSparkDays([], '2026-03-01', 3).map((day) => day.date)).toEqual(['2026-02-27', '2026-02-28', '2026-03-01'])
    expect(projectSparkDays([], '2027-01-01', 2).map((day) => day.date)).toEqual(['2026-12-31', '2027-01-01'])
  })

  it('formats signed deltas and day labels', () => {
    expect(formatStarDelta(1203, 'en-US')).toBe('+1,203')
    expect(formatStarDelta(0, 'en-US')).toBe('0')
    expect(formatStarDelta(-3, 'en-US')).toBe('−3')
    expect(formatSparkDate('2026-10-01', 'en-US')).toBe('Oct 1')
    expect(formatSparkDate('2026-10-01', 'zh-CN')).toBe('10月1日')
    expect(formatSparkDate('soon', 'en-US')).toBe('soon')
  })
})
