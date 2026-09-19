import { beforeEach, describe, expect, it, vi } from 'vitest'

const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../http/apiClient', () => ({ api: transport }))

import { dashboardApi } from './dashboardApi'

describe('Dashboard API contract', () => {
  it('keeps the persistent watchlist when the recent window has no tweets', async () => {
    const accounts = [{ handle: 'thsottiaux', displayName: 'Tibo' }]
    transport.get.mockResolvedValueOnce({ data: { items: [], accounts } })
    expect((await dashboardApi.fetchRecentX({})).accounts).toEqual(accounts)
  })
  beforeEach(() => {
    transport.get.mockReset()
    transport.post.mockReset()
  })

  it('normalizes summary and top responses at the transport edge', async () => {
    const signal = new AbortController().signal
    transport.get.mockResolvedValueOnce({ data: { stats: null, is_finalized: null, is_embargoed: true } })
    await expect(dashboardApi.fetchSummary({ date: '2026-07-27', signal })).resolves.toEqual({
      stats: {}, isFinalized: false, isEmbargoed: true,
    })
    expect(transport.get).toHaveBeenLastCalledWith('/dashboard/summary', {
      params: { date: '2026-07-27' }, signal,
    })

    transport.get.mockResolvedValueOnce({ data: { is_finalized: true, is_embargoed: false } })
    await expect(dashboardApi.fetchSummaryStatic!({ date: '2026-07-27', signal })).resolves.toEqual({
      isFinalized: true, isEmbargoed: false,
    })
    expect(transport.get).toHaveBeenLastCalledWith('/dashboard/summary-static', {
      params: { date: '2026-07-27' }, signal,
    })

    transport.get.mockResolvedValueOnce({ data: { items: null } })
    await expect(dashboardApi.fetchTop({ source: 'arxiv', date: '2026-07-27', signal })).resolves.toEqual({ items: [], isEmbargoed: false, sourceStatus: {} })
    expect(transport.get).toHaveBeenLastCalledWith('/dashboard/top', {
      params: { limit: 10, source: 'arxiv', date: '2026-07-27' }, signal,
    })
  })

  it('surfaces the embargo flag from top responses for embargo-aware empty states', async () => {
    transport.get.mockResolvedValueOnce({ data: { items: [], is_embargoed: true } })
    await expect(dashboardApi.fetchTop({ source: 'x', date: '2026-08-07' })).resolves.toEqual({
      items: [], isEmbargoed: true, sourceStatus: {},
    })
  })

  it('maps per-source board status from top responses for tab badges', async () => {
    transport.get.mockResolvedValueOnce({
      data: {
        items: [{ id: 1, title: 'Synthetic' }],
        is_embargoed: false,
        source_status: {
          arxiv: { is_finalized: false, is_embargoed: true, day_boundary: 'PT', finalize_hour: 17 },
          github: { is_finalized: true, is_embargoed: false, day_boundary: 'CST', finalize_hour: 1 },
        },
      },
    })
    await expect(dashboardApi.fetchTop({ source: 'arxiv', date: '2026-08-10' })).resolves.toEqual({
      items: [{ id: 1, title: 'Synthetic' }],
      isEmbargoed: false,
      sourceStatus: {
        arxiv: { is_finalized: false, is_embargoed: true, day_boundary: 'PT', finalize_hour: 17 },
        github: { is_finalized: true, is_embargoed: false, day_boundary: 'CST', finalize_hour: 1 },
      },
    })
  })

  it('posts x snapshot rebuild with an optional target date', async () => {
    transport.post.mockResolvedValueOnce({
      data: { status: 'succeeded', message: 'done', results: [{ date: '2026-07-30', upserted: 6 }], skipped_no_date: 0 },
    })
    await expect(dashboardApi.rebuildXSnapshot('2026-07-30')).resolves.toEqual({
      status: 'succeeded', message: 'done', results: [{ date: '2026-07-30', upserted: 6 }], skipped_no_date: 0,
    })
    expect(transport.post).toHaveBeenLastCalledWith('/ops/x/snapshots/rebuild', { target_date: '2026-07-30' })

    transport.post.mockResolvedValueOnce({ data: { status: 'succeeded', message: 'empty', results: [], skipped_no_date: 0 } })
    await dashboardApi.rebuildXSnapshot()
    expect(transport.post).toHaveBeenLastCalledWith('/ops/x/snapshots/rebuild', { target_date: null })
  })

  it('preserves snapshot and visitor request shapes and defaults', async () => {
    const signal = new AbortController().signal
    transport.get.mockResolvedValueOnce({ data: { dates: null } })
    await expect(dashboardApi.fetchSnapshotDates({ limit: 90, source: 'github', signal })).resolves.toEqual([])
    expect(transport.get).toHaveBeenLastCalledWith('/dashboard/snapshot-dates', {
      params: { limit: 90, source: 'github' }, signal,
    })

    transport.get.mockResolvedValueOnce({ data: { registered_users: 4, today_visits: 9, total_visits: 101 } })
    await expect(dashboardApi.fetchVisitorCount(signal)).resolves.toEqual({
      registeredUsers: 4, todayRegisteredUsers: 0, userCount: 0, todayVisits: 9, totalVisits: 101,
    })
    expect(transport.get).toHaveBeenLastCalledWith('/dashboard/visitor-count', { signal })
  })
})
