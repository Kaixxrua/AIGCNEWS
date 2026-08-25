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

/* 动态计数由 live-stats 直接读取 Redis/数据库，静态 summary 只负责快照元数据。
   保留已知的较新计数，避免旧客户端或兼容接口响应把数字从 4001 回退到 3993。 */
const MONOTONIC_COUNTER_FIELDS = [
  'total_documents', 'registered_users', 'user_count', 'total_visits',
  'mcp_total_calls', 'mcp_dsh_calls',
] as const

const mergeLiveStats = (current: Stats, incoming: Stats): Stats => {
  const merged: Stats = { ...current, ...incoming }
  for (const key of MONOTONIC_COUNTER_FIELDS) {
    const oldValue = current[key]
    const newValue = incoming[key]
    if (typeof oldValue === 'number' && typeof newValue === 'number') {
      Object.assign(merged, { [key]: Math.max(oldValue, newValue) })
    }
  }
  // Enrichment buckets are a state projection, not monotonic counters. Replace
  // them verbatim so failed/deleted/repaired projects can lower the success card.
  if (incoming.github_enrichment) merged.github_enrichment = incoming.github_enrichment
  return merged
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
    // 今天不显式传 date，让后端回溯到最近一个可展示快照；历史日期仍精确查询。
    const requestDate = selectedDate === todayStr ? undefined : selectedDate
    const staticSummaryRequest = dashboardApi.fetchSummaryStatic
      ? dashboardApi.fetchSummaryStatic({ period: PERIOD, date: requestDate, signal: controller.signal })
      : dashboardApi.fetchSummary({ period: PERIOD, date: requestDate, signal: controller.signal })
    const [summary, top, live] = await Promise.all([
      staticSummaryRequest,
      dashboardApi.fetchTop({ limit: 10, source: tab, period: PERIOD, date: requestDate, signal: controller.signal }),
      fetchLiveStats(controller.signal),
    ])
    if (!isCurrentDashboardRequest(controller, generation)) return false
    const legacySummary = summary as { stats?: Stats }
    if (legacySummary.stats) {
      stats.value = mergeLiveStats(stats.value, legacySummary.stats)
    }
    stats.value = mergeLiveStats(stats.value, live)
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
      ])
      if (isCurrentDashboardRequest(controller, generation)) options.updateStatSources(stats.value)
    } catch (error: unknown) {
      if (isCanceledError(error)) return
      console.warn('[Dashboard] 后台刷新失败', error)
    }
  }

  /* 10s 实时计数轮询：合并最新计数，变化的数字走滚筒差位滚动，无变化静止。
     历史日期/静默期/加载中跳过；停用、切页后的延迟响应不得回写。 */
  const refreshLiveStats = async () => {
    // Global counters remain live even while the selected board is in its
    // embargo window; only historical dates must stop the live poll.
    if (loading.value || tabLoading.value || isViewingHistory.value) return
    const controller = dashboardController
    const generation = dashboardGeneration
    if (!controller) return
    try {
      const live = await fetchLiveStats(controller.signal)
      if (!isCurrentDashboardRequest(controller, generation) || isViewingHistory.value) return
      stats.value = mergeLiveStats(stats.value, live)
      options.updateStatSources(stats.value)
    } catch (error: unknown) {
      if (!isCanceledError(error)) {
        /* 实时计数失败静默，保留当前展示值 */
      }
    }
  }

  onMounted(async () => {
    const { controller, generation } = beginDashboardRequest()
    try {
      await Promise.all([
        fetchDashboardData(activeTab.value, currentDate.value, controller, generation),
        fetchAvailableDates(),
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
