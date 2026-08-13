import {
  computed,
  onActivated,
  onBeforeUnmount,
  onDeactivated,
  onMounted,
  ref,
  watch,
} from 'vue'
import { dashboardApi as defaultDashboardApi } from '@/services/dashboard/dashboardApi'
import { fetchLiveStats } from '@/services/dashboard/dashboardLiveApi'
import type {
  DashboardApi,
  SourceStatusMap,
} from '@/services/dashboard/dashboardContracts'
import {
  isSourceStatCard,
  type PeriodKey,
  type Stats,
  type TabKey,
  type TopDoc,
} from '@/features/dashboard/dashboardViewModel'

interface DashboardDataOptions {
  updateStatSources: (stats: Stats) => void
  updateVisitorSources: (stats: Stats) => void
  dashboardApi?: DashboardApi
  now?: () => number
  createAbortController?: () => AbortController
}

const isCanceledError = (error: unknown): boolean => {
  if (!error || typeof error !== 'object') return false
  const candidate = error as { name?: string; code?: string }
  return candidate.name === 'CanceledError' || candidate.code === 'ERR_CANCELED'
}

/* live-stats 轮询（10s 短缓存）拥有的实时计数字段。summary 走 3600s Redis 缓存，
   切 tab / KeepAlive 回页重新应用时不得用陈旧缓存覆盖这些较新的值，
   否则 MCP 调用数等累计计数会出现"前进后回退"的跳变。 */
const LIVE_COUNTER_FIELDS = [
  'total_documents', 'source_counts',
  'registered_users', 'today_registered_users', 'user_count',
  'today_new_documents', 'today_visits', 'total_visits', 'mcp_total_calls',
] as const

const pickLiveCounters = (source: Stats): Stats => {
  const picked: Stats = {}
  for (const key of LIVE_COUNTER_FIELDS) {
    const value = source[key]
    if (value !== undefined) Object.assign(picked, { [key]: value })
  }
  return picked
}

export const useDashboardData = (options: DashboardDataOptions) => {
  const dashboardApi = options.dashboardApi ?? defaultDashboardApi
  const now = options.now ?? Date.now
  const createAbortController = options.createAbortController ?? (() => new AbortController())
  const activeTab = ref<TabKey>('github')
  /* 周期切换已下线，榜单只剩日榜；wire 仍显式传 daily，查询行为不变 */
  const PERIOD: PeriodKey = 'daily'
  const tabList = ref<TopDoc[]>([])
  const stats = ref<Stats>({})
  const loading = ref(true)
  const tabLoading = ref(false)
  const errorMsg = ref('')
  const viewRefreshInterval = 60_000
  let lastSuccessfulFetchAt = 0
  let hasActivatedOnce = false
  let liveCountersLoaded = false
  let dashboardController: AbortController | null = null
  let dashboardGeneration = 0

  const beginDashboardRequest = () => {
    dashboardController?.abort()
    dashboardController = createAbortController()
    dashboardGeneration += 1
    return { controller: dashboardController, generation: dashboardGeneration }
  }

  const isCurrentDashboardRequest = (controller: AbortController, generation: number) =>
    dashboardController === controller && dashboardGeneration === generation && !controller.signal.aborted

  const date = new Date(now())
  const todayStr = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
  const currentDate = ref<string>(todayStr)
  const availableDates = ref<string[]>([])
  let availabilityController: AbortController | null = null
  let availabilityGeneration = 0
  const isViewingHistory = computed(() => currentDate.value !== todayStr)
  const isFinalized = ref(false)
  const isEmbargoed = ref(false)
  const sourceStatus = ref<SourceStatusMap>({})

  const beginAvailabilityRequest = () => {
    availabilityController?.abort()
    availabilityController = createAbortController()
    availabilityGeneration += 1
    return { controller: availabilityController, generation: availabilityGeneration }
  }

  const fetchDashboardData = async (
    tab: TabKey,
    selectedDate: string,
    controller: AbortController,
    generation: number,
  ) => {
    const [summary, top] = await Promise.all([
      dashboardApi.fetchSummary({ period: PERIOD, date: selectedDate, signal: controller.signal }),
      dashboardApi.fetchTop({ limit: 10, source: tab, period: PERIOD, date: selectedDate, signal: controller.signal }),
    ])
    if (!isCurrentDashboardRequest(controller, generation)) return false
    // live 轮询已跑过后，实时计数字段以较新的 live 值为准，屏蔽 summary 的陈旧缓存
    const liveCounters = liveCountersLoaded ? pickLiveCounters(stats.value) : null
    stats.value = liveCounters ? { ...summary.stats, ...liveCounters } : summary.stats
    tabList.value = top.items
    isFinalized.value = summary.isFinalized
    isEmbargoed.value = summary.isEmbargoed
    sourceStatus.value = top.sourceStatus
    lastSuccessfulFetchAt = now()
    return true
  }

  const fetchAvailableDates = async (tab = activeTab.value) => {
    const { controller, generation } = beginAvailabilityRequest()
    try {
      const dates = await dashboardApi.fetchSnapshotDates({ limit: 90, source: tab, period: PERIOD, signal: controller.signal })
      if (
        availabilityController === controller
        && availabilityGeneration === generation
        && !controller.signal.aborted
        && tab === activeTab.value
      ) availableDates.value = dates
    } catch (error: unknown) {
      if (isCanceledError(error)) return
      console.warn('[Dashboard] 获取快照日期失败', error)
    }
  }

  const fetchUserCountMetric = async (controller: AbortController, generation: number) => {
    try {
      const visitor = await dashboardApi.fetchVisitorCount(controller.signal)
      if (!isCurrentDashboardRequest(controller, generation)) return
      stats.value = {
        ...stats.value,
        registered_users: visitor.registeredUsers ?? stats.value.registered_users ?? 0,
        today_registered_users: visitor.todayRegisteredUsers ?? 0,
        user_count: visitor.userCount ?? 0,
        today_visits: visitor.todayVisits ?? 0,
        total_visits: visitor.totalVisits ?? 0,
      }
      options.updateVisitorSources(stats.value)
    } catch (error: unknown) {
      if (isCanceledError(error)) return
      console.warn('[Dashboard] 获取用户数失败', error)
    }
  }

  const stopDashboardRequests = () => {
    dashboardController?.abort()
    dashboardController = null
    dashboardGeneration += 1
    availabilityController?.abort()
    availabilityController = null
    availabilityGeneration += 1
  }

  const refreshDashboardInBackground = async () => {
    if (loading.value || tabLoading.value) return
    const { controller, generation } = beginDashboardRequest()
    try {
      await Promise.all([
        fetchDashboardData(activeTab.value, currentDate.value, controller, generation),
        fetchAvailableDates(),
        fetchUserCountMetric(controller, generation),
      ])
      if (isCurrentDashboardRequest(controller, generation)) options.updateStatSources(stats.value)
    } catch (error: unknown) {
      if (isCanceledError(error)) return
      console.warn('[Dashboard] 后台刷新失败', error)
    }
  }

  /* 10s 实时计数轮询：合并最新计数，变化的数字走滚筒差位滚动，无变化静止。
     历史日期/静默期/加载中跳过，避免覆盖对应口径的统计数字。 */
  const refreshLiveStats = async () => {
    if (loading.value || tabLoading.value || isViewingHistory.value || isEmbargoed.value) return
    try {
      const live = await fetchLiveStats()
      stats.value = { ...stats.value, ...live }
      liveCountersLoaded = true
      options.updateStatSources(stats.value)
    } catch {
      /* 实时计数失败静默，保留当前展示值 */
    }
  }

  onMounted(async () => {
    const { controller, generation } = beginDashboardRequest()
    try {
      await Promise.all([
        fetchDashboardData(activeTab.value, currentDate.value, controller, generation),
        fetchAvailableDates(),
        fetchUserCountMetric(controller, generation),
      ])
    } catch (error: unknown) {
      if (!isCanceledError(error) && isCurrentDashboardRequest(controller, generation)) errorMsg.value = String(error)
    } finally {
      if (isCurrentDashboardRequest(controller, generation)) {
        loading.value = false
        options.updateStatSources(stats.value)
      }
    }
  })

  onActivated(() => {
    if (!hasActivatedOnce) {
      hasActivatedOnce = true
      return
    }
    if (now() - lastSuccessfulFetchAt >= viewRefreshInterval) void refreshDashboardInBackground()
  })

  onDeactivated(stopDashboardRequests)
  onBeforeUnmount(stopDashboardRequests)

  watch(activeTab, async (tab) => {
    tabLoading.value = true
    tabList.value = []
    const { controller, generation } = beginDashboardRequest()
    try {
      await fetchAvailableDates(tab)
      const applied = await fetchDashboardData(tab, currentDate.value, controller, generation)
      if (applied) options.updateStatSources(stats.value)
    } catch (error: unknown) {
      if (isCanceledError(error)) return
      console.error('Failed to load dashboard data', error)
    } finally {
      if (isCurrentDashboardRequest(controller, generation)) tabLoading.value = false
    }
  })

  const onDateChange = async (selectedDate: string) => {
    currentDate.value = selectedDate
    tabLoading.value = true
    tabList.value = []
    const { controller, generation } = beginDashboardRequest()
    try {
      const applied = await fetchDashboardData(activeTab.value, selectedDate, controller, generation)
      if (applied) options.updateStatSources(stats.value)
    } catch (error: unknown) {
      if (isCanceledError(error)) return
      console.error('Failed to load dashboard data by date', error)
    } finally {
      if (isCurrentDashboardRequest(controller, generation)) tabLoading.value = false
    }
  }

  const selectSourceTab = (key: string) => {
    if (isSourceStatCard(key)) activeTab.value = key
  }

  const hasData = computed(() => {
    const total = Number(stats.value.total_documents ?? 0)
    return total > 0 || tabList.value.length > 0
  })

  return {
    activeTab,
    tabList,
    stats,
    loading,
    tabLoading,
    errorMsg,
    currentDate,
    availableDates,
    isViewingHistory,
    isFinalized,
    isEmbargoed,
    sourceStatus,
    selectSourceTab,
    onDateChange,
    hasData,
    refreshLiveStats,
  }
}
