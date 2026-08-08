import { beforeEach, describe, expect, it, vi } from 'vitest'

const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../http/apiClient', () => ({ api: transport }))

import { dashboardApi } from './dashboardApi'

describe('Dashboard API contract', () => {
  beforeEach(() => {
    transport.get.mockReset()
    transport.post.mockReset()
  })

  it('normalizes summary and top responses at the transport edge', async () => {
    const signal = new AbortController().signal
    transport.get.mockResolvedValueOnce({ data: { stats: null, is_finalized: null, is_embargoed: true } })
    await expect(dashboardApi.fetchSummary({ period: 'daily', date: '2026-07-27', signal })).resolves.toEqual({
      stats: {}, isFinalized: false, isEmbargoed: true,
    })
    expect(transport.get).toHaveBeenLastCalledWith('/dashboard/summary', {
      params: { period: 'daily', date: '2026-07-27' }, signal,
    })

    transport.get.mockResolvedValueOnce({ data: { items: null } })
    await expect(dashboardApi.fetchTop({ source: 'arxiv', period: 'daily', date: '2026-07-27', signal })).resolves.toEqual({ items: [], isEmbargoed: false })
    expect(transport.get).toHaveBeenLastCalledWith('/dashboard/top', {
      params: { limit: 10, source: 'arxiv', period: 'daily', date: '2026-07-27' }, signal,
    })
  })

  it('surfaces the embargo flag from top responses for embargo-aware empty states', async () => {
    transport.get.mockResolvedValueOnce({ data: { items: [], is_embargoed: true } })
    await expect(dashboardApi.fetchTop({ source: 'x', period: 'daily', date: '2026-08-07' })).resolves.toEqual({
      items: [], isEmbargoed: true,
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
    await expect(dashboardApi.fetchSnapshotDates({ limit: 90, source: 'github', period: 'weekly', signal })).resolves.toEqual([])
    expect(transport.get).toHaveBeenLastCalledWith('/dashboard/snapshot-dates', {
      params: { limit: 90, source: 'github', period: 'weekly' }, signal,
    })

    transport.get.mockResolvedValueOnce({ data: { registered_users: 4 } })
    await expect(dashboardApi.fetchVisitorCount(signal)).resolves.toEqual({
      registeredUsers: 4, todayRegisteredUsers: 0, userCount: 0,
    })
    expect(transport.get).toHaveBeenLastCalledWith('/dashboard/visitor-count', { signal })
  })

  it('normalizes GitHub hot data and preserves its compatibility defaults', async () => {
    transport.get.mockResolvedValueOnce({ data: { period: '', items: null, total: 0 } })
    await expect(dashboardApi.fetchGitHubHotRepos('weekly', 8)).resolves.toEqual({
      period: '', window_days: undefined, items: [], total: 0, snapshot_count: undefined,
    })
    expect(transport.get).toHaveBeenLastCalledWith('/dashboard/github-hot', { params: { period: 'weekly', limit: 8 } })
  })
})
