import { createApp, defineComponent, h, KeepAlive, nextTick, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const transport = vi.hoisted(() => ({ get: vi.fn() }))
const fetchSnapshotDates = vi.hoisted(() => vi.fn())
vi.mock('../services/http/apiClient', () => ({ api: transport }))
vi.mock('../services/dashboard/dashboardApi', () => ({ fetchSnapshotDates }))

import { useDashboardData } from './useDashboardData'

type DashboardData = ReturnType<typeof useDashboardData>

const flush = async () => {
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
  await nextTick()
}

const responseFor = (url: string) => {
  if (url === '/dashboard/summary') return { data: { stats: { total_documents: 3 }, is_finalized: true } }
  if (url === '/dashboard/top') return { data: { items: [{ id: 1, title: 'Top' }] } }
  return { data: { registered_users: 7, today_registered_users: 2, user_count: 9 } }
}

const mountDashboard = () => {
  let dashboard!: DashboardData
  const updateStatSources = vi.fn()
  const updateVisitorSources = vi.fn()
  const disableCountUp = vi.fn()
  const visible = ref(true)
  const DashboardHarness = defineComponent({
    name: 'DashboardHarness',
    setup() {
      dashboard = useDashboardData({ updateStatSources, updateVisitorSources, disableCountUp })
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
    transport.get.mockReset()
    fetchSnapshotDates.mockReset()
    transport.get.mockImplementation(async (url: string) => responseFor(url))
    fetchSnapshotDates.mockResolvedValue(['2026-07-27'])
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('loads summary, top ten, snapshot availability, and visitors with shared date defaults', async () => {
    let resolveVisitors!: (value: ReturnType<typeof responseFor>) => void
    transport.get.mockImplementation((url: string) => {
      if (url === '/dashboard/visitor-count') {
        return new Promise((resolve) => { resolveVisitors = resolve })
      }
      return Promise.resolve(responseFor(url))
    })
    const mounted = mountDashboard()
    await flush()
    resolveVisitors(responseFor('/dashboard/visitor-count'))
    await flush()

    expect(mounted.dashboard.activeTab.value).toBe('arxiv')
    expect(mounted.dashboard.activePeriod.value).toBe('daily')
    expect(transport.get).toHaveBeenCalledWith('/dashboard/summary', {
      params: { period: 'daily', date: '2026-07-27' }, signal: expect.any(AbortSignal),
    })
    expect(transport.get).toHaveBeenCalledWith('/dashboard/top', {
      params: { limit: 10, source: 'arxiv', period: 'daily', date: '2026-07-27' }, signal: expect.any(AbortSignal),
    })
    expect(fetchSnapshotDates).toHaveBeenCalledWith(90, 'arxiv', 'daily', expect.any(AbortSignal))
    expect(transport.get).toHaveBeenCalledWith('/dashboard/visitor-count', { signal: expect.any(AbortSignal) })
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
    expect(mounted.dashboard.tabLoading.value).toBe(false)
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

    expect(transport.get).toHaveBeenCalledWith('/dashboard/summary', {
      params: { period: 'daily', date: '2026-07-20' }, signal: expect.any(AbortSignal),
    })
    expect(mounted.updateStatSources).toHaveBeenCalledAfter(mounted.disableCountUp)
    expect(mounted.dashboard.isViewingHistory.value).toBe(true)
    mounted.app.unmount()
  })

  it('aborts dashboard and availability requests on replacement and deactivation', async () => {
    const dashboardSignals: AbortSignal[] = []
    transport.get.mockImplementation(async (url: string, config: { signal?: AbortSignal }) => {
      if (url === '/dashboard/summary') dashboardSignals.push(config.signal!)
      return responseFor(url)
    })
    const availabilitySignals: AbortSignal[] = []
    fetchSnapshotDates.mockImplementation(async (_limit: number, _tab: string, _period: string, signal: AbortSignal) => {
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

  it('skips first activation refresh and refreshes a kept-alive view after 60 seconds', async () => {
    const mounted = mountDashboard()
    await flush()
    expect(transport.get).toHaveBeenCalledTimes(3)

    mounted.visible.value = false
    await nextTick()
    mounted.visible.value = true
    await flush()
    expect(transport.get).toHaveBeenCalledTimes(3)

    mounted.visible.value = false
    await nextTick()
    vi.advanceTimersByTime(60_000)
    mounted.visible.value = true
    await flush()
    expect(transport.get).toHaveBeenCalledTimes(6)
    mounted.app.unmount()
  })
})
