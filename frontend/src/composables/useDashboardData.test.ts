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
    expect(defaultDashboardApi.fetchSummaryStatic).toHaveBeenCalledWith({ period: 'daily', date: undefined, signal: expect.any(AbortSignal) })
    expect(defaultDashboardApi.fetchTop).toHaveBeenCalledWith({
      limit: 10, source: 'github', period: 'daily', date: undefined, signal: expect.any(AbortSignal),
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

  it('selects the latest ten X posts before displaying them, regardless of likes', async () => {
    const mounted = mountDashboard()
    await flush()
    const items = Array.from({ length: 12 }, (_, i) => ({
      id: i, source: 'x', score: 1000 - i, likes: 1000 - i,
      published_at: `2026-09-20T${String(i).padStart(2, '0')}:00:00Z`,
      translation_zh: `译文 ${i}`,
    }))
    defaultDashboardApi.fetchTop.mockResolvedValue({ items, sourceStatus: {} })
    mounted.dashboard.activeTab.value = 'x'
    await flush()
    expect(defaultDashboardApi.fetchTop).toHaveBeenLastCalledWith({
      limit: 500, source: 'x', period: 'daily', date: undefined, signal: expect.any(AbortSignal),
    })
    expect(mounted.dashboard.tabList.value.map(doc => doc.id)).toEqual([11, 10, 9, 8, 7, 6, 5, 4, 3, 2])
    expect(mounted.dashboard.tabList.value[0]?.translation_zh).toBe('译文 11')
    expect(items[0]?.id).toBe(0)
    mounted.app.unmount()
  })

  it('keeps loading domains independent when switching tabs', async () => {
    const mounted = mountDashboard()
    await flush()
    mounted.dashboard.activeTab.value = 'news'
    await flush()

    expect(defaultDashboardApi.fetchTop).toHaveBeenLastCalledWith({
      limit: 10, source: 'news', period: 'daily', date: undefined, signal: expect.any(AbortSignal),
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
    expect(mounted.updateStatSources).toHaveBeenCalled()
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
    expect(mounted.dashboard.stats.value.today_visits).toBe(9)

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
      fetchRecentX: vi.fn(async () => ({ items: [], total: 0, windowHours: 24, hasMore: false, nextCursor: null })),
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
    expect(mounted.dashboard.loading.value).toBe(false)
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

  it('shows rankings while statistics and available dates are still pending', async () => {
    let finishStats!: (stats: { total_documents: number }) => void
    let finishDates!: (dates: string[]) => void
    liveStatsApi.fetchLiveStats.mockImplementation(() => new Promise(resolve => { finishStats = resolve }))
    defaultDashboardApi.fetchSnapshotDates.mockImplementation(() => new Promise(resolve => { finishDates = resolve }))
    const mounted = mountDashboard()
    await flush()
    expect(mounted.dashboard.loading.value).toBe(false)
    expect(mounted.dashboard.tabList.value).toEqual([{ id: 1, title: 'Top' }])
    expect(mounted.dashboard.stats.value).toEqual({})
    finishStats({ total_documents: 25 })
    finishDates(['2026-07-27'])
    await flush()
    expect(mounted.dashboard.stats.value.total_documents).toBe(25)
    expect(mounted.dashboard.availableDates.value).toEqual(['2026-07-27'])
    mounted.app.unmount()
  })

  it('keeps rankings usable when the statistics request fails', async () => {
    liveStatsApi.fetchLiveStats.mockRejectedValue(new Error('statistics unavailable'))
    const mounted = mountDashboard()
    await flush()
    expect(mounted.dashboard.loading.value).toBe(false)
    expect(mounted.dashboard.loadError.value).toBeNull()
    expect(mounted.dashboard.tabList.value).toHaveLength(1)
    mounted.app.unmount()
  })

  it('accepts SSE during loading and ignores an older REST response arriving later', async () => {
    let finishSummary!: (value: { isFinalized: boolean; isEmbargoed: boolean }) => void
    let finishStats!: (value: { today_visits: number; source_counts: { github: number } }) => void
    defaultDashboardApi.fetchSummaryStatic.mockImplementation(() => new Promise(resolve => { finishSummary = resolve }))
    liveStatsApi.fetchLiveStats.mockImplementation(() => new Promise(resolve => { finishStats = resolve }))
    const mounted = mountDashboard()
    await flush()
    expect(mounted.dashboard.loading.value).toBe(true)
    mounted.dashboard.applyLiveStats({ today_visits: 20, source_counts: { github: 10 } })
    expect(mounted.dashboard.stats.value.today_visits).toBe(20)
    finishStats({ today_visits: 18, source_counts: { github: 8 } })
    finishSummary({ isFinalized: true, isEmbargoed: false })
    await flush()
    expect(mounted.dashboard.stats.value).toMatchObject({ today_visits: 20, source_counts: { github: 10 } })
    expect(mounted.dashboard.loading.value).toBe(false)
    mounted.visible.value = false
    await nextTick()
    mounted.dashboard.applyLiveStats({ today_visits: 99 })
    expect(mounted.dashboard.stats.value.today_visits).toBe(20)
    mounted.app.unmount()
  })

  it('resumes statistics after a short kept-alive navigation', async () => {
    const mounted = mountDashboard()
    await flush()
    mounted.visible.value = false
    await nextTick()
    liveStatsApi.fetchLiveStats.mockResolvedValue({ total_documents: 12 })
    mounted.visible.value = true
    await flush()
    expect(mounted.dashboard.stats.value.total_documents).toBe(12)
    expect(defaultDashboardApi.fetchTop).toHaveBeenCalledTimes(1)
    mounted.app.unmount()
  })

  it('restarts an interrupted first load when returning to the kept-alive view', async () => {
    defaultDashboardApi.fetchSummaryStatic.mockImplementationOnce(() => new Promise(() => {}))
    const mounted = mountDashboard()
    await flush()
    expect(mounted.dashboard.loading.value).toBe(true)
    mounted.visible.value = false
    await nextTick()
    mounted.visible.value = true
    await flush()
    expect(defaultDashboardApi.fetchSummaryStatic).toHaveBeenCalledTimes(2)
    expect(mounted.dashboard.loading.value).toBe(false)
    expect(mounted.dashboard.tabList.value).toHaveLength(1)
    mounted.app.unmount()
  })

  it('uses the selected source status and resolved date even when summary differs or fails', async () => {
    defaultDashboardApi.fetchTop.mockResolvedValue({
      items: [{ id: 1 }], isFinalized: true, isEmbargoed: false,
      resolvedDate: '2026-07-26', stale: true,
      sourceStatus: { github: { is_finalized: true, finalize_hour: 1 } },
    })
    defaultDashboardApi.fetchSummaryStatic.mockResolvedValue({ isFinalized: false, isEmbargoed: true })
    const mounted = mountDashboard()
    await flush()
    expect(mounted.dashboard.isEmbargoed.value).toBe(false)
    expect(mounted.dashboard.isFinalized.value).toBe(true)
    expect(mounted.dashboard.resolvedDate.value).toBe('2026-07-26')
    expect(mounted.dashboard.currentDate.value).toBe('2026-07-27')
    defaultDashboardApi.fetchSummaryStatic.mockRejectedValue(new Error('summary unavailable'))
    await mounted.dashboard.onDateChange('2026-07-26')
    expect(mounted.dashboard.tabList.value).toEqual([{ id: 1 }])
    expect(mounted.dashboard.loadError.value).toBeNull()
    mounted.app.unmount()
  })

  it('refreshes at the source close and preserves existing rows on a failed refresh', async () => {
    vi.setSystemTime(new Date('2026-07-27T00:59:30+08:00'))
    defaultDashboardApi.fetchTop.mockResolvedValue({
      items: [{ id: 1 }], isFinalized: false, isEmbargoed: false,
      resolvedDate: '2026-07-26', sourceStatus: { github: { is_finalized: false, finalize_hour: 1 } },
    })
    const mounted = mountDashboard()
    await flush()
    await mounted.dashboard.onDateChange('2026-07-26')
    defaultDashboardApi.fetchTop.mockResolvedValue({
      items: [{ id: 2 }], isFinalized: true, isEmbargoed: false,
      resolvedDate: '2026-07-26', sourceStatus: { github: { is_finalized: true, finalize_hour: 1 } },
    })
    await vi.advanceTimersByTimeAsync(30_100)
    expect(mounted.dashboard.isFinalized.value).toBe(true)
    expect(defaultDashboardApi.fetchTop).toHaveBeenLastCalledWith(expect.objectContaining({
      date: '2026-07-26', cacheBuster: expect.any(Number),
    }))
    defaultDashboardApi.fetchTop.mockRejectedValueOnce(new Error('temporary outage'))
    await vi.advanceTimersByTimeAsync(60_000)
    expect(mounted.dashboard.tabList.value).toEqual([{ id: 2 }])
    expect(mounted.dashboard.loadError.value).toBe('server')
    await vi.advanceTimersByTimeAsync(60_000)
    expect(mounted.dashboard.loadError.value).toBeNull()
    mounted.app.unmount()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('follows the CST date at midnight but keeps an explicit history selection', async () => {
    vi.setSystemTime(new Date('2026-07-27T23:59:50+08:00'))
    const mounted = mountDashboard()
    await flush()
    expect(mounted.dashboard.currentDate.value).toBe('2026-07-27')
    await vi.advanceTimersByTimeAsync(10_100)
    expect(mounted.dashboard.currentDate.value).toBe('2026-07-28')
    expect(defaultDashboardApi.fetchTop).toHaveBeenLastCalledWith(expect.objectContaining({ date: undefined }))
    await mounted.dashboard.onDateChange('2026-07-26')
    vi.setSystemTime(new Date('2026-07-28T23:59:50+08:00'))
    document.dispatchEvent(new Event('visibilitychange'))
    await flush()
    await vi.advanceTimersByTimeAsync(10_100)
    expect(mounted.dashboard.todayStr.value).toBe('2026-07-29')
    expect(mounted.dashboard.currentDate.value).toBe('2026-07-26')
    expect(defaultDashboardApi.fetchTop).toHaveBeenLastCalledWith(expect.objectContaining({ date: '2026-07-26' }))
    mounted.app.unmount()
  })

  it('reports an unreachable server as a network failure and retries with a fresh request', async () => {
    defaultDashboardApi.fetchTop.mockRejectedValueOnce(Object.assign(new Error('Network Error'), { name: 'AxiosError', code: 'ERR_NETWORK' }))
    const mounted = mountDashboard()
    await flush()
    expect(mounted.dashboard.loading.value).toBe(false)
    expect(mounted.dashboard.tabList.value).toEqual([])
    expect(mounted.dashboard.loadError.value).toBe('network')

    let finishTop!: (value: unknown) => void
    defaultDashboardApi.fetchTop.mockImplementationOnce(() => new Promise(resolve => { finishTop = resolve }))
    const retried = mounted.dashboard.retry()
    expect(mounted.dashboard.retrying.value).toBe(true)
    void mounted.dashboard.retry()
    expect(defaultDashboardApi.fetchTop).toHaveBeenCalledTimes(2)
    expect(defaultDashboardApi.fetchTop).toHaveBeenLastCalledWith(expect.objectContaining({ cacheBuster: expect.any(Number) }))
    finishTop({ items: [{ id: 7 }], sourceStatus: {} })
    await retried
    expect(mounted.dashboard.retrying.value).toBe(false)
    expect(mounted.dashboard.loadError.value).toBeNull()
    expect(mounted.dashboard.tabList.value).toEqual([{ id: 7 }])
    mounted.app.unmount()
  })

  it('classifies timeouts and offline browsers as network failures, HTTP errors as server failures', async () => {
    const cases: Array<[unknown, boolean, 'network' | 'server']> = [
      [{ code: 'ECONNABORTED', message: 'timeout of 15000ms exceeded' }, true, 'network'],
      [{ code: 'ERR_BAD_RESPONSE', response: { status: 502 } }, true, 'server'],
      [{ code: 'ERR_NETWORK', response: { status: 503 } }, true, 'server'],
      [new TypeError('items is not iterable'), true, 'server'],
      [new TypeError('items is not iterable'), false, 'network'],
    ]
    for (const [error, online, expected] of cases) {
      const onLine = vi.spyOn(window.navigator, 'onLine', 'get').mockReturnValue(online)
      defaultDashboardApi.fetchTop.mockRejectedValueOnce(error)
      const mounted = mountDashboard()
      try {
        await flush()
        expect(mounted.dashboard.loadError.value).toBe(expected)
      } finally {
        mounted.app.unmount()
        onLine.mockRestore()
      }
    }
  })

  it('pauses requests in a hidden page and refreshes when visible, with no work after unmount', async () => {
    const mounted = mountDashboard()
    await flush()
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
    await vi.advanceTimersByTimeAsync(120_000)
    expect(defaultDashboardApi.fetchTop).toHaveBeenCalledTimes(1)
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
    document.dispatchEvent(new Event('visibilitychange'))
    await flush()
    expect(defaultDashboardApi.fetchTop).toHaveBeenCalledTimes(2)
    mounted.app.unmount()
    await vi.advanceTimersByTimeAsync(120_000)
    document.dispatchEvent(new Event('visibilitychange'))
    expect(defaultDashboardApi.fetchTop).toHaveBeenCalledTimes(2)
  })
})
