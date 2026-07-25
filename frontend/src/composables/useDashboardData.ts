import {
  computed,
  onActivated,
  onBeforeUnmount,
  onDeactivated,
  onMounted,
  ref,
  watch,
} from 'vue'
import { fetchSnapshotDates } from '../services/dashboard/dashboardApi'
import { api } from '../services/http/apiClient'
import {
  DAILY_ONLY_TABS,
  isSourceStatCard,
  type PeriodKey,
  type Stats,
  type TabKey,
  type TopDoc,
} from '../features/dashboard/dashboardViewModel'

interface DashboardDataOptions {
  updateStatSources: (stats: Stats) => void
  updateVisitorSources: (stats: Stats) => void
  disableCountUp: () => void
}

export const useDashboardData = (options: DashboardDataOptions) => {
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

  const newDashboardSignal = (): AbortSignal => {
    dashboardController?.abort()
    dashboardController = new AbortController()
    return dashboardController.signal
  }

  const date = new Date()
  const todayStr = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
  const currentDate = ref<string>(todayStr)
  const availableDates = ref<string[]>([])
  let availabilityController: AbortController | null = null
  const isViewingHistory = computed(() => currentDate.value !== todayStr)
  const isFinalized = ref(false)
  const isEmbargoed = ref(false)

  const isPeriodDisabled = (periodKey: PeriodKey): boolean =>
    periodKey !== 'daily' && DAILY_ONLY_TABS.has(activeTab.value)

  const fetchDashboardData = async (tab: TabKey, period: PeriodKey, selectedDate?: string, signal?: AbortSignal) => {
    const dateParam = selectedDate || currentDate.value
    const [summaryRes, topRes] = await Promise.all([
      api.get('/dashboard/summary', { params: { period, date: dateParam }, signal }),
      api.get('/dashboard/top', { params: { limit: 10, source: tab, period, date: dateParam }, signal }),
    ])
    stats.value = summaryRes.data.stats ?? {}
    tabList.value = topRes.data.items ?? []
    isFinalized.value = summaryRes.data.is_finalized ?? false
    isEmbargoed.value = summaryRes.data.is_embargoed ?? false
    lastSuccessfulFetchAt = Date.now()
  }

  const fetchAvailableDates = async (tab = activeTab.value, period = activePeriod.value) => {
    availabilityController?.abort()
    const controller = new AbortController()
    availabilityController = controller
    try {
      const dates = await fetchSnapshotDates(90, tab, period, controller.signal)
      if (!controller.signal.aborted && tab === activeTab.value && period === activePeriod.value) {
        availableDates.value = dates
      }
    } catch (error: any) {
      if (error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED') return
      console.warn('[Dashboard] 获取快照日期失败', error)
    }
  }

  const fetchUserCountMetric = async (signal?: AbortSignal) => {
    try {
      const response = await api.get('/dashboard/visitor-count', { signal })
      stats.value = {
        ...stats.value,
        registered_users: response.data.registered_users ?? stats.value.registered_users ?? 0,
        today_registered_users: response.data.today_registered_users ?? 0,
        user_count: response.data.user_count ?? 0,
      }
      options.updateVisitorSources(stats.value)
    } catch (error: any) {
      if (error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED') return
      console.warn('[Dashboard] 获取用户数失败', error)
    }
  }

  const stopDashboardRequests = () => {
    dashboardController?.abort()
    dashboardController = null
    availabilityController?.abort()
    availabilityController = null
  }

  const refreshDashboardInBackground = async () => {
    if (loading.value || tabLoading.value) return
    const signal = newDashboardSignal()
    try {
      await Promise.all([
        fetchDashboardData(activeTab.value, activePeriod.value, currentDate.value, signal),
        fetchAvailableDates(),
        fetchUserCountMetric(signal),
      ])
      options.updateStatSources(stats.value)
    } catch (error: any) {
      if (error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED') return
      console.warn('[Dashboard] 后台刷新失败', error)
    }
  }

  onMounted(async () => {
    const signal = newDashboardSignal()
    try {
      await Promise.all([
        fetchDashboardData(activeTab.value, activePeriod.value, currentDate.value, signal),
        fetchAvailableDates(),
        fetchUserCountMetric(signal),
      ])
    } catch (error: any) {
      if (error?.name !== 'CanceledError' && error?.code !== 'ERR_CANCELED') errorMsg.value = String(error)
    } finally {
      loading.value = false
      options.updateStatSources(stats.value)
    }
  })

  onActivated(() => {
    if (!hasActivatedOnce) {
      hasActivatedOnce = true
      return
    }
    if (Date.now() - lastSuccessfulFetchAt >= viewRefreshInterval) {
      void refreshDashboardInBackground()
    }
  })

  onDeactivated(stopDashboardRequests)
  onBeforeUnmount(stopDashboardRequests)

  watch(activeTab, (tab) => {
    if (DAILY_ONLY_TABS.has(tab) && activePeriod.value !== 'daily') activePeriod.value = 'daily'
  })

  watch([activeTab, activePeriod], async ([tab, period]) => {
    tabLoading.value = true
    tabList.value = []
    const signal = newDashboardSignal()
    try {
      await fetchAvailableDates(tab, period)
      await fetchDashboardData(tab, period, currentDate.value, signal)
      options.updateStatSources(stats.value)
    } catch (error: any) {
      if (error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED') return
      console.error('Failed to load dashboard data', error)
    } finally {
      tabLoading.value = false
    }
  })

  const onDateChange = async (selectedDate: string) => {
    currentDate.value = selectedDate
    tabLoading.value = true
    tabList.value = []
    options.disableCountUp()
    const signal = newDashboardSignal()
    try {
      await fetchDashboardData(activeTab.value, activePeriod.value, selectedDate, signal)
      options.updateStatSources(stats.value)
    } catch (error: any) {
      if (error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED') return
      console.error('Failed to load dashboard data by date', error)
    } finally {
      tabLoading.value = false
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
