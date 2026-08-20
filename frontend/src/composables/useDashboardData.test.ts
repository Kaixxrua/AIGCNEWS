import { createApp, defineComponent, h, KeepAlive, nextTick, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const defaultDashboardApi = vi.hoisted(() => ({
  fetchSummary: vi.fn(),
  fetchSummaryStatic: vi.fn(),
  fetchTop: vi.fn(),
  fetchSnapshotDates: vi.fn(),
  fetchVisitorCount: vi.fn(),
  fetchGitHubHotRepos: vi.fn(),
}))
vi.mock('../services/dashboard/dashboardApi', () => ({ dashboardApi: defaultDashboardApi }))

const liveStatsApi = vi.hoisted(() => ({
  fetchLiveStats: vi.fn(),
}))
vi.mock('../services/dashboard/dashboardLiveApi', () => liveStatsApi)

import type { DashboardApi } from '@/services/dashboard/dashboardApi'
import { useDashboardData } from './useDashboardData'

type DashboardData = ReturnType<typeof useDashboardData>
type DashboardOverrides = Partial<Pick<Parameters<typeof useDashboardData>[0], 'dashboardApi' | 'now' | 'createAbortController'>>

const flush = async () => {
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
  await nextTick()
}

const mountDashboard = (overrides: DashboardOverrides = {}) => {
  let dashboard!: DashboardData
  const updateStatSources = vi.fn()
  const updateVisitorSources = vi.fn()
  const visible = ref(true)
  const DashboardHarness = defineComponent({
    name: 'DashboardHarness',
    setup() {
      dashboard = useDashboardData({ updateStatSources, updateVisitorSources, ...overrides })
      return () => h('div')
    },
  })
  const Root = defineComponent({
    setup() {
      return () => h(KeepAlive, null, () => visible.value ? h(DashboardHarness) : null)
    },
  })
  const element = document.createElement('div')
  const app = createApp(Root)
  app.mount(element)
  return { app, dashboard, visible, updateStatSources, updateVisitorSources }
}

describe('Dashboard request lifecycle contract', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 6, 27, 12))
    Object.values(defaultDashboardApi).forEach(mock => mock.mockReset())
    liveStatsApi.fetchLiveStats.mockReset()
    defaultDashboardApi.fetchSummary.mockResolvedValue({ stats: { total_documents: 3 }, isFinalized: true, isEmbargoed: false })
    defaultDashboardApi.fetchSummaryStatic.mockResolvedValue({ isFinalized: true, isEmbargoed: false })
    liveStatsApi.fetchLiveStats.mockResolvedValue({ total_documents: 3 })
    defaultDashboardApi.fetchTop.mockResolvedValue({
      items: [{ id: 1, title: 'Top' }],
      sourceStatus: { arxiv: { is_finalized: false, is_embargoed: false, day_boundary: 'PT', finalize_hour: 17 } },
    })
    defaultDashboardApi.fetchSnapshotDates.mockResolvedValue(['2026-07-27'])
    defaultDashboardApi.fetchVisitorCount.mockResolvedValue({ registeredUsers: 7, todayRegisteredUsers: 2, userCount: 9, todayVisits: 21, totalVisits: 365 })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('loads static summary, live counters, top ten, and snapshot availability with shared date defaults', async () => {
    liveStatsApi.fetchLiveStats.mockResolvedValue({
      total_documents: 3,
      registered_users: 7,
      user_count: 9,
      today_visits: 21,
      total_visits: 365,
    })
    const mounted = mountDashboard()
    await flush()

    expect(mounted.dashboard.activeTab.value).toBe('github')
    expect(defaultDashboardApi.fetchSummaryStatic).toHaveBeenCalledWith({ period: 'daily', date: '2026-07-27', signal: expect.any(AbortSignal) })
    expect(defaultDashboardApi.fetchTop).toHaveBeenCalledWith({
      limit: 10, source: 'github', period: 'daily', date: '2026-07-27', signal: expect.any(AbortSignal),
    })
    expect(defaultDashboardApi.fetchSnapshotDates).toHaveBeenCalledWith({ limit: 90, source: 'github', period: 'daily', signal: expect.any(AbortSignal) })
    expect(liveStatsApi.fetchLiveStats).toHaveBeenCalledWith(expect.any(AbortSignal))
    expect(defaultDashboardApi.fetchVisitorCount).not.toHaveBeenCalled()
    expect(mounted.dashboard.stats.value).toMatchObject({ total_documents: 3, registered_users: 7, user_count: 9, today_visits: 21, total_visits: 365 })
    expect(mounted.dashboard.tabList.value).toEqual([{ id: 1, title: 'Top' }])
    expect(mounted.dashboard.isFinalized.value).toBe(true)
    expect(mounted.dashboard.isEmbargoed.value).toBe(false)
    // 分源定稿状态透出（PR6）：tab 级徽章的数据源
    expect(mounted.dashboard.sourceStatus.value).toEqual({
      arxiv: { is_finalized: false, is_embargoed: false, day_boundary: 'PT', finalize_hour: 17 },
    })
    expect(mounted.dashboard.hasData.value).toBe(true)
    expect(mounted.updateStatSources).toHaveBeenCalled()
    mounted.app.unmount()
  })

  it('keeps loading domains independent when switching tabs', async () => {
    const mounted = mountDashboard()
    await flush()
    mounted.dashboard.activeTab.value = 'news'
    await flush()

    expect(defaultDashboardApi.fetchTop).toHaveBeenLastCalledWith({
      limit: 10, source: 'news', period: 'daily', date: '2026-07-27', signal: expect.any(AbortSignal),
    })
    expect(mounted.dashboard.loading.value).toBe(false)
    await vi.waitFor(() => expect(mounted.dashboard.tabLoading.value).toBe(false))
    mounted.app.unmount()
  })

  it('uses the selected date, clears the list, and refreshes the stats', async () => {
    const mounted = mountDashboard()
    await flush()
    mounted.updateStatSources.mockClear()
    const pending = mounted.dashboard.onDateChange('2026-07-20')
    expect(mounted.dashboard.tabList.value).toEqual([])
    await pending

    expect(defaultDashboardApi.fetchSummaryStatic).toHaveBeenCalledWith({ period: 'daily', date: '2026-07-20', signal: expect.any(AbortSignal) })
    expect(mounted.updateStatSources).toHaveBeenCalledOnce()
    expect(mounted.dashboard.isViewingHistory.value).toBe(true)
    mounted.app.unmount()
  })

  it('merges live counters on refreshLiveStats and skips while viewing history', async () => {
    liveStatsApi.fetchLiveStats.mockResolvedValue({ total_documents: 99, mcp_total_calls: 5, mcp_dsh_calls: 2, source_counts: { arxiv: 4 } })
    const mounted = mountDashboard()
    await flush()
    mounted.updateStatSources.mockClear()

    await mounted.dashboard.refreshLiveStats()
    expect(mounted.dashboard.stats.value).toMatchObject({ total_documents: 99, mcp_total_calls: 5, mcp_dsh_calls: 2 })
    expect(mounted.updateStatSources).toHaveBeenCalledOnce()

    liveStatsApi.fetchLiveStats.mockClear()
    await mounted.dashboard.onDateChange('2026-07-20')
    liveStatsApi.fetchLiveStats.mockClear()
    mounted.updateStatSources.mockClear()
    await mounted.dashboard.refreshLiveStats()
    expect(liveStatsApi.fetchLiveStats).not.toHaveBeenCalled()
    expect(mounted.updateStatSources).not.toHaveBeenCalled()
    mounted.app.unmount()
  })

  it('keeps fresh live counters when a slower legacy summary resolves last on first load', async () => {
    // 兼容旧注入端：summary 带着较旧的动态计数到达时，不能覆盖首屏 live-stats。
    type Summary = Awaited<ReturnType<DashboardApi['fetchSummary']>>
    let resolveSummary!: (value: Summary) => void
    defaultDashboardApi.fetchSummaryStatic.mockImplementation(() => new Promise((resolve) => {
      resolveSummary = resolve as (value: Summary) => void
    }))
    liveStatsApi.fetchLiveStats.mockResolvedValue({
      total_documents: 3, today_visits: 9, total_visits: 100,
    })
    const mounted = mountDashboard()
    await flush()
    expect(mounted.dashboard.stats.value).toEqual({})

    resolveSummary({
      stats: { total_documents: 3, today_visits: 6, total_visits: 97, mcp_total_calls: 1232 },
      isFinalized: true, isEmbargoed: false,
    })
    await flush()

    expect(mounted.dashboard.stats.value.today_visits).toBe(9)
    expect(mounted.dashboard.stats.value.total_visits).toBe(100)
    expect(mounted.dashboard.stats.value.total_documents).toBe(3)
    expect(mounted.dashboard.stats.value.mcp_total_calls).toBe(1232)
    mounted.app.unmount()
  })

  it('keeps fresher live counters when a stale cached summary is re-applied', async () => {
    // summary 走 3600s 缓存：首次加载含 mcp_total_calls=1232，live 轮询前进到 1233 后，
    // 切 tab 重新应用同一份陈旧 summary 不得让计数回退（回归：首页 MCP 调用数 1233→1232）
    defaultDashboardApi.fetchSummaryStatic.mockResolvedValue({
      stats: { total_documents: 3, mcp_total_calls: 1232, mcp_dsh_calls: 40, source_counts: { arxiv: 3 } },
      isFinalized: true, isEmbargoed: false,
    })
    liveStatsApi.fetchLiveStats.mockResolvedValue({ total_documents: 5, mcp_total_calls: 1233, mcp_dsh_calls: 41, source_counts: { arxiv: 5 } })
    const mounted = mountDashboard()
    await flush()

    await mounted.dashboard.refreshLiveStats()
    expect(mounted.dashboard.stats.value.mcp_total_calls).toBe(1233)
    expect(mounted.dashboard.stats.value.mcp_dsh_calls).toBe(41)

    mounted.dashboard.activeTab.value = 'github'
    await flush()

    expect(mounted.dashboard.stats.value.mcp_total_calls).toBe(1233)
    expect(mounted.dashboard.stats.value.mcp_dsh_calls).toBe(41)
    expect(mounted.dashboard.stats.value.total_documents).toBe(5)
    expect(mounted.dashboard.stats.value.source_counts).toEqual({ arxiv: 5 })
    mounted.app.unmount()
  })

  it('applies cached summary counters before the first live poll succeeds', async () => {
    defaultDashboardApi.fetchSummaryStatic.mockResolvedValue({
      stats: { total_documents: 3, mcp_total_calls: 1232 },
      isFinalized: true, isEmbargoed: false,
    })
    const mounted = mountDashboard()
    await flush()
    expect(mounted.dashboard.stats.value.mcp_total_calls).toBe(1232)

    mounted.dashboard.activeTab.value = 'github'
    await flush()
    expect(mounted.dashboard.stats.value.mcp_total_calls).toBe(1232)
    mounted.app.unmount()
  })

  it('aborts dashboard and availability requests on replacement and deactivation', async () => {
    const dashboardSignals: AbortSignal[] = []
    defaultDashboardApi.fetchSummaryStatic.mockImplementation(async ({ signal }) => {
      dashboardSignals.push(signal!)
      return { stats: { total_documents: 3 }, isFinalized: true, isEmbargoed: false }
    })
    const availabilitySignals: AbortSignal[] = []
    defaultDashboardApi.fetchSnapshotDates.mockImplementation(async ({ signal }: { signal: AbortSignal }) => {
      availabilitySignals.push(signal)
      return []
    })
    const mounted = mountDashboard()
    await flush()
    mounted.dashboard.activeTab.value = 'arxiv'
    await flush()

    expect(dashboardSignals[0]?.aborted).toBe(true)
    expect(availabilitySignals[0]?.aborted).toBe(true)
    mounted.visible.value = false
    await nextTick()
    expect(dashboardSignals[dashboardSignals.length - 1]?.aborted).toBe(true)
    expect(availabilitySignals[availabilitySignals.length - 1]?.aborted).toBe(true)
    mounted.app.unmount()
  })

  it('ignores a late dashboard response even when its transport does not reject on abort', async () => {
    type Summary = Awaited<ReturnType<DashboardApi['fetchSummary']>>
    const deferred: Array<{ resolve: (value: Summary) => void }> = []
    const injectedApi: DashboardApi = {
      fetchSummary: vi.fn(async () => ({ stats: {}, isFinalized: true, isEmbargoed: false })),
      fetchSummaryStatic: vi.fn(() => new Promise<Summary>((resolve) => deferred.push({ resolve }))),
      fetchTop: vi.fn(async () => ({ items: [], isEmbargoed: false, sourceStatus: {} })),
      fetchSnapshotDates: vi.fn(async () => []),
      fetchVisitorCount: vi.fn(async () => ({ registeredUsers: 0, todayRegisteredUsers: 0, userCount: 0, todayVisits: 0, totalVisits: 0 })),
      fetchGitHubHotRepos: vi.fn(async () => ({ period: 'daily', items: [] })),
      fetchRecentX: vi.fn(async () => ({ items: [], total: 0, windowHours: 24 })),
      deleteDocument: vi.fn(async () => ({ status: 'ok', message: 'deleted', doc_id: 'x:1', deleted: true })),
      bulkDeleteDocuments: vi.fn(async () => ({ status: 'ok', message: 'deleted', doc_ids: ['x:1'], deleted_count: 1, not_found_count: 0 })),
      rebuildXSnapshot: vi.fn(async () => ({ status: 'succeeded', message: 'ok', results: [], skipped_no_date: 0 })),
    }
    liveStatsApi.fetchLiveStats.mockResolvedValue({})
    const mounted = mountDashboard({ dashboardApi: injectedApi, now: () => new Date(2026, 6, 27, 12).getTime() })
    await flush()
    mounted.dashboard.activeTab.value = 'arxiv'
    await flush()
    deferred[1]!.resolve({ stats: { total_documents: 2 }, isFinalized: false, isEmbargoed: false })
    await flush()
    expect(mounted.dashboard.stats.value.total_documents).toBe(2)
    deferred[0]!.resolve({ stats: { total_documents: 1 }, isFinalized: true, isEmbargoed: true })
    await flush()
    expect(mounted.dashboard.stats.value.total_documents).toBe(2)
    expect(mounted.dashboard.isFinalized.value).toBe(false)
    mounted.app.unmount()
  })

  it('skips first activation refresh and refreshes a kept-alive view after 60 seconds', async () => {
    const mounted = mountDashboard()
    await flush()
    expect(defaultDashboardApi.fetchSummaryStatic).toHaveBeenCalledTimes(1)

    mounted.visible.value = false
    await nextTick()
    mounted.visible.value = true
    await flush()
    expect(defaultDashboardApi.fetchSummaryStatic).toHaveBeenCalledTimes(1)

    mounted.visible.value = false
    await nextTick()
    vi.advanceTimersByTime(60_000)
    mounted.visible.value = true
    await flush()
    expect(defaultDashboardApi.fetchSummaryStatic).toHaveBeenCalledTimes(2)
    mounted.app.unmount()
  })
})
