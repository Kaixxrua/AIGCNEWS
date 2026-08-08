import { computed, ref } from 'vue'
import type { DashboardApi } from '@/services/dashboard/dashboardContracts'
import { dashboardApi } from '@/services/dashboard/dashboardApi'
import type { TopDoc } from '@/features/dashboard/dashboardViewModel'
import type { XSnapshotRebuildResponse } from '@/services/dashboard/dashboardContracts'
import { clampPage, groupTweetsByHandle, pageCount } from '@/features/xboard/xBoardViewModel'

export interface XBoardApi {
  fetchTop: DashboardApi['fetchTop']
  fetchRecentX: DashboardApi['fetchRecentX']
  fetchSnapshotDates: DashboardApi['fetchSnapshotDates']
  deleteDocument: DashboardApi['deleteDocument']
  bulkDeleteDocuments: DashboardApi['bulkDeleteDocuments']
  rebuildXSnapshot: DashboardApi['rebuildXSnapshot']
}

export type XBoardViewMode = 'recent' | 'date'

export type XBoardTranslate = (key: string) => string

export interface XBoardControllerOptions {
  api?: XBoardApi
  translate?: XBoardTranslate
  now?: () => Date
}

const SNAPSHOT_DATE_LIMIT = 60
// 看板一次拉全量（后端 limit 上限/DB 读取上限均为 500），客户端分页
const TOP_LIMIT = 500
// 默认视图：滚动最近 24 小时发布的推文（绝对时间窗，与用户时区无关，展示层已做时区换算）
export const XBOARD_RECENT_WINDOW_HOURS = 24
export const XBOARD_PAGE_SIZE = 20

// XBoardView 自包含控制器：拉取快照日期与 source=x 推文，分组逻辑在 xBoardViewModel。
export const useXBoardController = (options: XBoardControllerOptions = {}) => {
  const api = options.api ?? dashboardApi
  const translate = options.translate ?? ((key: string) => key)
  const now = options.now ?? (() => new Date())

  const today = now().toISOString().slice(0, 10)
  const selectedDate = ref(today)
  const viewMode = ref<XBoardViewMode>('recent')
  const availableDates = ref<string[]>([])
  const docs = ref<TopDoc[]>([])
  const loading = ref(false)
  const deleting = ref(false)
  const rebuilding = ref(false)
  const errorMsg = ref('')
  const isActive = ref(true)
  const selectedIds = ref<Set<string>>(new Set())
  const page = ref(1)
  // 日期模式专用：昨日榜单 CST 15:00 定稿前被后端静默，空态需区分「无数据」
  const isEmbargoed = ref(false)

  const sections = computed(() => groupTweetsByHandle(docs.value))
  const totalPages = computed(() => pageCount(docs.value.length, XBOARD_PAGE_SIZE))
  // 只读夹取页：删除清空末页等场景自动回落，无需 watcher
  const currentPage = computed(() => clampPage(page.value, totalPages.value))
  const hasPrev = computed(() => currentPage.value > 1)
  const hasNext = computed(() => currentPage.value < totalPages.value)

  const goPage = (next: number) => {
    page.value = clampPage(next, totalPages.value)
  }

  let generation = 0
  let abortController: AbortController | null = null

  const loadTweets = async () => {
    const request = ++generation
    abortController?.abort()
    const controller = new AbortController()
    abortController = controller
    loading.value = true
    errorMsg.value = ''
    const mode = viewMode.value
    const date = selectedDate.value
    try {
      const result = mode === 'recent'
        ? await api.fetchRecentX({ hours: XBOARD_RECENT_WINDOW_HOURS, limit: TOP_LIMIT, signal: controller.signal, cacheBuster: Date.now() })
        : await api.fetchTop({ source: 'x', period: 'daily', date, limit: TOP_LIMIT, signal: controller.signal, cacheBuster: Date.now() })
      if (isActive.value && request === generation) {
        docs.value = result.items
        // recent 模式无静默期语义；fetchRecentX 不返回该字段，统一复位
        isEmbargoed.value = mode === 'date' && 'isEmbargoed' in result ? result.isEmbargoed : false
      }
    } catch (error) {
      if (isActive.value && request === generation && !controller.signal.aborted) {
        errorMsg.value = error instanceof Error && error.message ? error.message : translate('xboard.loadFailed')
      }
    } finally {
      if (isActive.value && request === generation) loading.value = false
    }
  }

  const loadDates = async () => {
    try {
      // 快照日期用于把默认日期回退到最近一个有数据的日期（今天可能还没跑采集）
      const dates = await api.fetchSnapshotDates({ source: 'x', period: 'daily', limit: SNAPSHOT_DATE_LIMIT, cacheBuster: Date.now() })
      if (isActive.value) {
        availableDates.value = dates
        if (!dates.includes(selectedDate.value) && dates[0]) selectedDate.value = dates[0]
      }
    } catch {
      // 日期清单失败不阻塞推文加载
    }
  }

  const load = async () => {
    if (!isActive.value) return
    await loadDates()
    await loadTweets()
  }

  const onDateChange = (date: string) => {
    if (!date) return
    if (date === selectedDate.value && viewMode.value === 'date') return
    selectedDate.value = date
    viewMode.value = 'date'
    selectedIds.value.clear()
    page.value = 1
    void loadTweets()
  }

  const showRecent = () => {
    // 已在 recent 模式时视为刷新：窗口随当前时刻重新滑动
    viewMode.value = 'recent'
    selectedIds.value.clear()
    page.value = 1
    return loadTweets()
  }

  const refresh = () => {
    page.value = 1
    return loadTweets()
  }

  const dispose = () => {
    isActive.value = false
    generation += 1
    abortController?.abort()
    loading.value = false
  }

  const toggleSelection = (docId: string) => {
    const next = new Set(selectedIds.value)
    if (next.has(docId)) next.delete(docId)
    else next.add(docId)
    selectedIds.value = next
  }

  const selectAll = (ids?: string[]) => {
    const pool = ids ?? (docs.value.map((doc) => doc.id).filter(Boolean) as string[])
    selectedIds.value = new Set(pool)
  }

  /** 页级全选切换：给定 id 全部已选则移除，否则并入（供「本页全选」复选框）。 */
  const toggleSelectAll = (ids: string[]) => {
    if (!ids.length) return
    const next = new Set(selectedIds.value)
    if (ids.every((id) => next.has(id))) ids.forEach((id) => next.delete(id))
    else ids.forEach((id) => next.add(id))
    selectedIds.value = next
  }

  const clearSelection = () => {
    selectedIds.value = new Set()
  }

  /**
   * 管理员补拉：从已入库推文按发布日（CST）重建 X 日榜快照。
   * 补拉可能新增历史快照日期、改变当前榜单，日期清单与推文都需重拉。
   */
  const rebuild = async (targetDate?: string): Promise<XSnapshotRebuildResponse | null> => {
    if (rebuilding.value) return null
    rebuilding.value = true
    errorMsg.value = ''
    try {
      const result = await api.rebuildXSnapshot(targetDate)
      await loadDates()
      await loadTweets()
      return result
    } catch (error) {
      errorMsg.value = error instanceof Error && error.message ? error.message : translate('xboard.rebuildFailed')
      return null
    } finally {
      rebuilding.value = false
    }
  }

  const rebuildSelectedDate = () => rebuild(selectedDate.value)

  const rebuildAllDates = () => rebuild(undefined)

  const deleteSelected = async (): Promise<{ deleted: number; notFound: number }> => {
    const ids = Array.from(selectedIds.value)
    if (!ids.length) return { deleted: 0, notFound: 0 }
    deleting.value = true
    errorMsg.value = ''
    let result = { deleted: 0, notFound: 0 }
    try {
      const response = await api.bulkDeleteDocuments(ids)
      result = {
        deleted: response.deleted_count ?? 0,
        notFound: response.not_found_count ?? 0,
      }
      selectedIds.value = new Set(ids.filter((id) => !response.doc_ids?.includes(id)))
      // 删除后重拉不走 refresh()：保留当前页码，由 currentPage 夹取自动回落
      await loadTweets()
    } catch (error) {
      errorMsg.value = error instanceof Error && error.message ? error.message : translate('xboard.deleteFailed')
    } finally {
      deleting.value = false
    }
    return result
  }

  return {
    availableDates,
    clearSelection,
    currentPage,
    deleteSelected,
    deleting,
    dispose,
    docs,
    errorMsg,
    goPage,
    hasNext,
    hasPrev,
    isEmbargoed,
    load,
    loading,
    onDateChange,
    pageSize: XBOARD_PAGE_SIZE,
    rebuildAllDates,
    rebuildSelectedDate,
    rebuilding,
    recentWindowHours: XBOARD_RECENT_WINDOW_HOURS,
    refresh,
    sections,
    selectedDate,
    selectedIds,
    selectAll,
    showRecent,
    today,
    toggleSelectAll,
    toggleSelection,
    totalPages,
    viewMode,
  }
}

export type XBoardController = ReturnType<typeof useXBoardController>
