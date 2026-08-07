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
import type {
  DashboardApi,
} from '@/services/dashboard/dashboardContracts'
import {
  DAILY_ONLY_TABS,
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

export const useDashboardData = (options: DashboardDataOptions) => {
  const dashboardApi = options.dashboardApi ?? defaultDashboardApi
  const now = options.now ?? Date.now
  const createAbortController = options.createAbortController ?? (() => new AbortController())
  const activeTab = ref<TabKey>('arxiv')
  const activePeriod = ref<PeriodKey>('daily')
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

  const beginAvailabilityRequest = () => {
    availabilityController?.abort()
    availabilityController = createAbortController()
    availabilityGeneration += 1
    return { controller: availabilityController, generation: availabilityGeneration }
  }

  const isPeriodDisabled = (periodKey: PeriodKey): boolean =>
    periodKey !== 'daily' && DAILY_ONLY_TABS.has(activeTab.value)

  const fetchDashboardData = async (
    tab: TabKey,
    period: PeriodKey,
    selectedDate: string,
    controller: AbortController,
    generation: number,
  ) => {
    const [summary, top] = await Promise.all([
      dashboardApi.fetchSummary({ period, date: selectedDate, signal: controller.signal }),
      dashboardApi.fetchTop({ limit: 10, source: tab, period, date: selectedDate, signal: controller.signal }),
    ])
    if (!isCurrentDashboardRequest(controller, generation)) return false
    stats.value = summary.stats
    tabList.value = top.items
    isFinalized.value = summary.isFinalized
    isEmbargoed.value = summary.isEmbargoed
    lastSuccessfulFetchAt = now()
    return true
  }

  const fetchAvailableDates = async (tab = activeTab.value, period = activePeriod.value) => {
    const { controller, generation } = beginAvailabilityRequest()
    try {
      const dates = await dashboardApi.fetchSnapshotDates({ limit: 90, source: tab, period, signal: controller.signal })
      if (
        availabilityController === controller
        && availabilityGeneration === generation
        && !controller.signal.aborted
        && tab === activeTab.value
        && period === activePeriod.value
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
        fetchDashboardData(activeTab.value, activePeriod.value, currentDate.value, controller, generation),
        fetchAvailableDates(),
        fetchUserCountMetric(controller, generation),
      ])
      if (isCurrentDashboardRequest(controller, generation)) options.updateStatSources(stats.value)
    } catch (error: unknown) {
      if (isCanceledError(error)) return
      console.warn('[Dashboard] 后台刷新失败', error)
    }
  }

  onMounted(async () => {
    const { controller, generation } = beginDashboardRequest()
    try {
      await Promise.all([
        fetchDashboardData(activeTab.value, activePeriod.value, currentDate.value, controller, generation),
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

  watch(activeTab, (tab) => {
    if (DAILY_ONLY_TABS.has(tab) && activePeriod.value !== 'daily') activePeriod.value = 'daily'
  })

  watch([activeTab, activePeriod], async ([tab, period]) => {
    tabLoading.value = true
    tabList.value = []
    const { controller, generation } = beginDashboardRequest()
    try {
      await fetchAvailableDates(tab, period)
      const applied = await fetchDashboardData(tab, period, currentDate.value, controller, generation)
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
      const applied = await fetchDashboardData(activeTab.value, activePeriod.value, selectedDate, controller, generation)
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
    activePeriod,
    isPeriodDisabled,
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
    selectSourceTab,
    onDateChange,
    hasData,
  }
}
