import { createApp, defineComponent, h, KeepAlive, nextTick, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const defaultDashboardApi = vi.hoisted(() => ({
  fetchSummary: vi.fn(),
  fetchTop: vi.fn(),
  fetchSnapshotDates: vi.fn(),
  fetchVisitorCount: vi.fn(),
  fetchGitHubHotRepos: vi.fn(),
}))
vi.mock('../services/dashboard/dashboardApi', () => ({ dashboardApi: defaultDashboardApi }))

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
  const disableCountUp = vi.fn()
  const visible = ref(true)
  const DashboardHarness = defineComponent({
    name: 'DashboardHarness',
    setup() {
      dashboard = useDashboardData({ updateStatSources, updateVisitorSources, disableCountUp, ...overrides })
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
  return { app, dashboard, visible, updateStatSources, updateVisitorSources, disableCountUp }
}

describe('Dashboard request lifecycle contract', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 6, 27, 12))
    Object.values(defaultDashboardApi).forEach(mock => mock.mockReset())
    defaultDashboardApi.fetchSummary.mockResolvedValue({ stats: { total_documents: 3 }, isFinalized: true, isEmbargoed: false })
    defaultDashboardApi.fetchTop.mockResolvedValue({ items: [{ id: 1, title: 'Top' }] })
    defaultDashboardApi.fetchSnapshotDates.mockResolvedValue(['2026-07-27'])
    defaultDashboardApi.fetchVisitorCount.mockResolvedValue({ registeredUsers: 7, todayRegisteredUsers: 2, userCount: 9 })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('loads summary, top ten, snapshot availability, and visitors with shared date defaults', async () => {
    let resolveVisitors!: (value: { registeredUsers: number; todayRegisteredUsers: number; userCount: number }) => void
    defaultDashboardApi.fetchVisitorCount.mockImplementation(() => new Promise((resolve) => { resolveVisitors = resolve }))
    const mounted = mountDashboard()
    await flush()
    resolveVisitors({ registeredUsers: 7, todayRegisteredUsers: 2, userCount: 9 })
    await flush()

    expect(mounted.dashboard.activeTab.value).toBe('arxiv')
    expect(mounted.dashboard.activePeriod.value).toBe('daily')
    expect(defaultDashboardApi.fetchSummary).toHaveBeenCalledWith({ period: 'daily', date: '2026-07-27', signal: expect.any(AbortSignal) })
    expect(defaultDashboardApi.fetchTop).toHaveBeenCalledWith({
      limit: 10, source: 'arxiv', period: 'daily', date: '2026-07-27', signal: expect.any(AbortSignal),
    })
    expect(defaultDashboardApi.fetchSnapshotDates).toHaveBeenCalledWith({ limit: 90, source: 'arxiv', period: 'daily', signal: expect.any(AbortSignal) })
    expect(defaultDashboardApi.fetchVisitorCount).toHaveBeenCalledWith(expect.any(AbortSignal))
    expect(mounted.dashboard.stats.value).toMatchObject({ total_documents: 3, registered_users: 7, user_count: 9 })
    expect(mounted.dashboard.tabList.value).toEqual([{ id: 1, title: 'Top' }])
    expect(mounted.dashboard.isFinalized.value).toBe(true)
    expect(mounted.dashboard.isEmbargoed.value).toBe(false)
    expect(mounted.dashboard.hasData.value).toBe(true)
    expect(mounted.updateVisitorSources).toHaveBeenCalledBefore(mounted.updateStatSources)
    mounted.app.unmount()
  })

  it('forces daily-only tabs back to daily while keeping loading domains independent', async () => {
    const mounted = mountDashboard()
    await flush()
    mounted.dashboard.activePeriod.value = 'weekly'
    await flush()
    mounted.dashboard.activeTab.value = 'news'
    await flush()

    expect(mounted.dashboard.activePeriod.value).toBe('daily')
    expect(mounted.dashboard.loading.value).toBe(false)
    await vi.waitFor(() => expect(mounted.dashboard.tabLoading.value).toBe(false))
    expect(mounted.dashboard.isPeriodDisabled('weekly')).toBe(true)
    mounted.app.unmount()
  })

  it('uses the selected date, clears the list, disables count-up, and preserves callback order', async () => {
    const mounted = mountDashboard()
    await flush()
    mounted.updateStatSources.mockClear()
    mounted.disableCountUp.mockClear()
    const pending = mounted.dashboard.onDateChange('2026-07-20')
    expect(mounted.dashboard.tabList.value).toEqual([])
    expect(mounted.disableCountUp).toHaveBeenCalledOnce()
    await pending

    expect(defaultDashboardApi.fetchSummary).toHaveBeenCalledWith({ period: 'daily', date: '2026-07-20', signal: expect.any(AbortSignal) })
    expect(mounted.updateStatSources).toHaveBeenCalledAfter(mounted.disableCountUp)
    expect(mounted.dashboard.isViewingHistory.value).toBe(true)
    mounted.app.unmount()
  })

  it('aborts dashboard and availability requests on replacement and deactivation', async () => {
    const dashboardSignals: AbortSignal[] = []
    defaultDashboardApi.fetchSummary.mockImplementation(async ({ signal }) => {
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
    mounted.dashboard.activeTab.value = 'github'
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
      fetchSummary: vi.fn(() => new Promise<Summary>((resolve) => deferred.push({ resolve }))),
      fetchTop: vi.fn(async () => ({ items: [] })),
      fetchSnapshotDates: vi.fn(async () => []),
      fetchVisitorCount: vi.fn(async () => ({ registeredUsers: 0, todayRegisteredUsers: 0, userCount: 0 })),
      fetchGitHubHotRepos: vi.fn(async () => ({ period: 'daily', items: [] })),
    }
    const mounted = mountDashboard({ dashboardApi: injectedApi, now: () => new Date(2026, 6, 27, 12).getTime() })
    await flush()
    mounted.dashboard.activeTab.value = 'github'
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
    expect(defaultDashboardApi.fetchSummary).toHaveBeenCalledTimes(1)

    mounted.visible.value = false
    await nextTick()
    mounted.visible.value = true
    await flush()
    expect(defaultDashboardApi.fetchSummary).toHaveBeenCalledTimes(1)

    mounted.visible.value = false
    await nextTick()
    vi.advanceTimersByTime(60_000)
    mounted.visible.value = true
    await flush()
    expect(defaultDashboardApi.fetchSummary).toHaveBeenCalledTimes(2)
    mounted.app.unmount()
  })
})
