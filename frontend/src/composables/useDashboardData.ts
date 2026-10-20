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
import { timelineTweets } from '@/features/xboard/xBoardViewModel'
import { createDashboardHistoryCache } from '@/features/dashboard/dashboardHistoryCache'
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
  initialTab?: TabKey
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

/** 榜单没加载出来的原因：network 是连不上（离线、断网、超时），server 是服务端出错或其他异常。 */
export type DashboardLoadError = 'network' | 'server'

const NETWORK_ERROR_CODES = new Set(['ERR_NETWORK', 'ECONNABORTED', 'ETIMEDOUT'])

// 页面只说原因和下一步，不显示 AxiosError 原文。
const classifyLoadError = (error: unknown): DashboardLoadError => {
  if (typeof navigator !== 'undefined' && navigator.onLine === false) return 'network'
  if (!error || typeof error !== 'object') return 'server'
  const candidate = error as { response?: unknown; code?: string }
  return candidate.response === undefined && NETWORK_ERROR_CODES.has(candidate.code ?? '') ? 'network' : 'server'
}

const cstDate = (timestamp: number) => new Date(timestamp + 8 * 3_600_000).toISOString().slice(0, 10)

/* 动态计数由实时推送和 live-stats 常驻值提供，静态 summary 只负责快照元数据。
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
  const historyCache = createDashboardHistoryCache(dashboardApi, now)
  const activeTab = ref<TabKey>(options.initialTab ?? 'github')
  /* 周期切换已下线，榜单只剩日榜；wire 仍显式传 daily，查询行为不变 */
  const PERIOD: PeriodKey = 'daily'
  const tabList = ref<TopDoc[]>([])
  const stats = ref<Stats>({})
  const loading = ref(true)
  const tabLoading = ref(false)
  const loadError = ref<DashboardLoadError | null>(null)
  const retrying = ref(false)
  const viewRefreshInterval = 60_000
  let lastSuccessfulFetchAt = 0
  let hasActivatedOnce = false
  let dashboardController: AbortController | null = null
  let dashboardGeneration = 0
  let liveStatsRevision = 0
  let refreshTimer: ReturnType<typeof setTimeout> | undefined
  let prefetchTimer: ReturnType<typeof setTimeout> | undefined
  let prefetchController: AbortController | null = null
  let availableDatesSource: TabKey | null = null

  const beginDashboardRequest = () => {
    clearTimeout(refreshTimer)
    dashboardController?.abort()
    dashboardController = createAbortController()
    dashboardGeneration += 1
    return { controller: dashboardController, generation: dashboardGeneration }
  }

  const isCurrentDashboardRequest = (controller: AbortController, generation: number) =>
    dashboardController === controller && dashboardGeneration === generation && !controller.signal.aborted

  const todayStr = ref(cstDate(now()))
  const currentDate = ref<string>(todayStr.value)
  const resolvedDate = ref<string>(todayStr.value)
  const availableDates = ref<string[]>([])
  let availabilityController: AbortController | null = null
  let availabilityGeneration = 0
  const isViewingHistory = computed(() => currentDate.value !== todayStr.value)
  const isFinalized = ref(false)
  const isEmbargoed = ref(false)
  const sourceStatus = ref<SourceStatusMap>({})

  const beginAvailabilityRequest = () => {
    availabilityController?.abort()
    availabilityController = createAbortController()
    availabilityGeneration += 1
    return { controller: availabilityController, generation: availabilityGeneration }
  }

  const scheduleHistoryPrefetch = () => {
    clearTimeout(prefetchTimer)
    prefetchTimer = setTimeout(async () => {
      if (!dashboardController || loading.value || tabLoading.value
        || document.visibilityState === 'hidden' || availableDatesSource !== activeTab.value) return
      prefetchController?.abort()
      const controller = createAbortController()
      prefetchController = controller
      const tab = activeTab.value
      const selectedDate = currentDate.value
      const dates = [...new Set(availableDates.value)]
        .filter(date => date < todayStr.value && date !== selectedDate)
        .sort((a, b) => Math.abs(Date.parse(a) - Date.parse(selectedDate)) - Math.abs(Date.parse(b) - Date.parse(selectedDate)))
        .slice(0, 3)
      // 串行预取相邻日期；与点击请求合并，离开页面后取消。
      for (const date of dates) {
        if (controller.signal.aborted || tab !== activeTab.value || selectedDate !== currentDate.value) break
        try {
          await historyCache.fetchTop({ limit: tab === 'x' ? 500 : 10, source: tab, period: PERIOD, date, signal: controller.signal })
        } catch {
          // 预取失败不影响当前榜单，真正点击时仍可重试。
        }
      }
    }, 200)
  }

  const fetchDashboardData = async (
    tab: TabKey,
    selectedDate: string,
    controller: AbortController,
    generation: number,
    refresh = false,
  ) => {
    // 今天不显式传 date，让后端回溯到最近一个可展示快照；历史日期仍精确查询。
    const requestDate = selectedDate === todayStr.value ? undefined : selectedDate
    if (!requestDate) void loadLiveStats(controller, generation)
    // 历史榜单的状态已由 top 返回，无需等待扫描全部来源的 summary。
    const staticSummaryRequest = requestDate ? Promise.resolve(null) : dashboardApi.fetchSummaryStatic
      ? dashboardApi.fetchSummaryStatic({ period: PERIOD, date: requestDate, signal: controller.signal })
      : dashboardApi.fetchSummary({ period: PERIOD, date: requestDate, signal: controller.signal })
    const [summary, top] = await Promise.all([
      staticSummaryRequest.catch(() => null),
      historyCache.fetchTop({
        limit: tab === 'x' ? 500 : 10, source: tab, period: PERIOD, date: requestDate, signal: controller.signal,
        ...(refresh ? { cacheBuster: now() } : {}),
      }),
    ])
    if (!isCurrentDashboardRequest(controller, generation)) return false
    const legacySummary = summary as { stats?: Stats }
    if (legacySummary?.stats) {
      // 实时计数可能先到；旧版 summary 只补齐尚未取得的字段。
      stats.value = mergeLiveStats(legacySummary.stats, stats.value)
    }
    tabList.value = tab === 'x' ? timelineTweets(top.items).slice(0, 10) : top.items
    isFinalized.value = top.sourceStatus[tab]?.is_finalized ?? top.isFinalized ?? summary?.isFinalized ?? false
    isEmbargoed.value = top.isEmbargoed ?? false
    resolvedDate.value = top.resolvedDate || selectedDate
    sourceStatus.value = top.sourceStatus
    loadError.value = null
    lastSuccessfulFetchAt = now()
    scheduleRefresh()
    scheduleHistoryPrefetch()
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
      ) {
        availableDates.value = dates
        availableDatesSource = tab
        scheduleHistoryPrefetch()
      }
    } catch (error: unknown) {
      if (isCanceledError(error)) return
      console.warn('[Dashboard] 获取快照日期失败', error)
    }
  }


  const stopDashboardRequests = () => {
    clearTimeout(refreshTimer)
    clearTimeout(prefetchTimer)
    prefetchController?.abort()
    prefetchController = null
    document.removeEventListener('visibilitychange', onVisibilityChange)
    dashboardController?.abort()
    dashboardController = null
    dashboardGeneration += 1
    availabilityController?.abort()
    availabilityController = null
    availabilityGeneration += 1
  }

  const refreshDashboardInBackground = async () => {
    const nextToday = cstDate(now())
    if (currentDate.value === todayStr.value) currentDate.value = nextToday
    todayStr.value = nextToday
    const { controller, generation } = beginDashboardRequest()
    try {
      void fetchAvailableDates()
      await fetchDashboardData(activeTab.value, currentDate.value, controller, generation, true)
      if (isCurrentDashboardRequest(controller, generation)) options.updateStatSources(stats.value)
    } catch (error: unknown) {
      if (isCanceledError(error)) return
      console.warn('[Dashboard] 后台刷新失败', error)
      if (isCurrentDashboardRequest(controller, generation)) loadError.value = classifyLoadError(error)
    } finally {
      if (isCurrentDashboardRequest(controller, generation)) {
        loading.value = false
        tabLoading.value = false
        scheduleRefresh()
      }
    }
  }

  const scheduleRefresh = () => {
    clearTimeout(refreshTimer)
    const timestamp = now()
    const nextMidnight = Date.parse(cstDate(timestamp) + 'T00:00:00+08:00') + 86_400_000
    const closeHour = sourceStatus.value[activeTab.value]?.finalize_hour
    const closeAt = closeHour == null ? 0
      : Date.parse(resolvedDate.value + 'T00:00:00+08:00') + (24 + closeHour) * 3_600_000
    const delay = Math.min(viewRefreshInterval, nextMidnight - timestamp + 50,
      closeAt > timestamp ? closeAt - timestamp + 50 : viewRefreshInterval)
    refreshTimer = setTimeout(() => {
      if (document.visibilityState === 'hidden') scheduleRefresh()
      else void refreshDashboardInBackground()
    }, delay)
  }

  const onVisibilityChange = () => {
    if (document.visibilityState === 'visible') void refreshDashboardInBackground()
  }

  const loadLiveStats = async (controller: AbortController, generation: number) => {
    const revision = liveStatsRevision
    try {
      const live = await fetchLiveStats(controller.signal)
      if (!isCurrentDashboardRequest(controller, generation) || revision !== liveStatsRevision) return
      stats.value = mergeLiveStats(stats.value, live)
      options.updateStatSources(stats.value)
    } catch {
      // 统计失败不阻塞榜单；SSE 或下次激活继续补齐。
    }
  }

  /* 重新激活时补齐实时计数；停用、切页后的延迟响应不得回写。 */
  const refreshLiveStats = async () => {
    // Global counters remain live even while the selected board is in its
    // embargo window; only historical dates must stop the live poll.
    if (loading.value || tabLoading.value || isViewingHistory.value) return
    const controller = dashboardController
    const generation = dashboardGeneration
    if (!controller) return
    await loadLiveStats(controller, generation)
  }

  /* SSE 推送/降级轮询可在榜单加载期间独立更新计数。
     数字变化由 RollingNumber 差位滚动承接。 */
  const applyLiveStats = (incoming: Stats) => {
    if (!dashboardController || dashboardController.signal.aborted || isViewingHistory.value) return
    liveStatsRevision += 1
    stats.value = mergeLiveStats(stats.value, incoming)
    options.updateStatSources(stats.value)
  }

  onMounted(async () => {
    document.addEventListener('visibilitychange', onVisibilityChange)
    const { controller, generation } = beginDashboardRequest()
    try {
      void fetchAvailableDates()
      await fetchDashboardData(activeTab.value, currentDate.value, controller, generation)
    } catch (error: unknown) {
      if (!isCanceledError(error) && isCurrentDashboardRequest(controller, generation)) loadError.value = classifyLoadError(error)
    } finally {
      if (isCurrentDashboardRequest(controller, generation)) {
        loading.value = false
        options.updateStatSources(stats.value)
        scheduleRefresh()
      }
    }
  })

  onActivated(() => {
    document.addEventListener('visibilitychange', onVisibilityChange)
    if (!hasActivatedOnce) {
      hasActivatedOnce = true
      return
    }
    if (!dashboardController) beginDashboardRequest()
    scheduleRefresh()
    scheduleHistoryPrefetch()
    if (cstDate(now()) !== todayStr.value || loading.value || tabLoading.value || now() - lastSuccessfulFetchAt >= viewRefreshInterval) void refreshDashboardInBackground()
    else void refreshLiveStats()
  })

  onDeactivated(stopDashboardRequests)
  onBeforeUnmount(stopDashboardRequests)

  watch(activeTab, async (tab) => {
    tabLoading.value = true
    tabList.value = []
    const { controller, generation } = beginDashboardRequest()
    try {
      void fetchAvailableDates(tab)
      const applied = await fetchDashboardData(tab, currentDate.value, controller, generation)
      if (applied) options.updateStatSources(stats.value)
    } catch (error: unknown) {
      if (isCanceledError(error)) return
      console.error('Failed to load dashboard data', error)
      if (isCurrentDashboardRequest(controller, generation)) loadError.value = classifyLoadError(error)
    } finally {
      if (isCurrentDashboardRequest(controller, generation)) {
        loading.value = false
        tabLoading.value = false
        scheduleRefresh()
      }
    }
  })

  const onDateChange = async (selectedDate: string) => {
    currentDate.value = selectedDate
    resolvedDate.value = selectedDate
    tabLoading.value = true
    tabList.value = []
    const { controller, generation } = beginDashboardRequest()
    try {
      const applied = await fetchDashboardData(activeTab.value, selectedDate, controller, generation)
      if (applied) options.updateStatSources(stats.value)
    } catch (error: unknown) {
      if (isCanceledError(error)) return
      console.error('Failed to load dashboard data by date', error)
      if (isCurrentDashboardRequest(controller, generation)) loadError.value = classifyLoadError(error)
    } finally {
      if (isCurrentDashboardRequest(controller, generation)) {
        loading.value = false
        tabLoading.value = false
        scheduleRefresh()
      }
    }
  }

  /* 失败后手动重试：走后台刷新同一条路径（带 cacheBuster），返回前按钮保持忙碌。 */
  const retry = async () => {
    if (retrying.value) return
    retrying.value = true
    try {
      await refreshDashboardInBackground()
    } finally {
      retrying.value = false
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
    loadError,
    retrying,
    retry,
    currentDate,
    todayStr,
    resolvedDate,
    availableDates,
    isViewingHistory,
    isFinalized,
    isEmbargoed,
    sourceStatus,
    selectSourceTab,
    onDateChange,
    hasData,
    refreshLiveStats,
    applyLiveStats,
  }
}
