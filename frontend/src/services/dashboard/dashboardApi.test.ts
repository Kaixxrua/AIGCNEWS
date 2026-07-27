import { beforeEach, describe, expect, it, vi } from 'vitest'

const transport = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../http/apiClient', () => ({ api: transport }))

import { dashboardApi } from './dashboardApi'

describe('Dashboard API contract', () => {
  beforeEach(() => transport.get.mockReset())

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
    await expect(dashboardApi.fetchTop({ source: 'arxiv', period: 'daily', date: '2026-07-27', signal })).resolves.toEqual({ items: [] })
    expect(transport.get).toHaveBeenLastCalledWith('/dashboard/top', {
      params: { limit: 10, source: 'arxiv', period: 'daily', date: '2026-07-27' }, signal,
    })
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
