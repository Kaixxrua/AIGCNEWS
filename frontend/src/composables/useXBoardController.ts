import { computed, ref } from 'vue'
import type { DashboardApi } from '@/services/dashboard/dashboardContracts'
import { dashboardApi } from '@/services/dashboard/dashboardApi'
import type { TopDoc } from '@/features/dashboard/dashboardViewModel'
import { clampPage, groupTweetsByHandle, pageCount } from '@/features/xboard/xBoardViewModel'

export interface XBoardApi {
  fetchRecentX: DashboardApi['fetchRecentX']
  fetchSnapshotDates: DashboardApi['fetchSnapshotDates']
  deleteDocument: DashboardApi['deleteDocument']
  bulkDeleteDocuments: DashboardApi['bulkDeleteDocuments']
}

export type XBoardTranslate = (key: string) => string

export interface XBoardControllerOptions {
  api?: XBoardApi
  translate?: XBoardTranslate
  now?: () => Date
}

const SNAPSHOT_DATE_LIMIT = 60
// 看板一次拉全量（后端 limit 上限/DB 读取上限均为 500），客户端分页
const TOP_LIMIT = 500
// 窗口长度固定 24 小时：日期选择器只做整数天位移（days_back），
// 窗口 = [所选日期的当前钟点 - 24h, 所选日期的当前钟点]，随访问时刻滑动
export const XBOARD_RECENT_WINDOW_HOURS = 24
export const XBOARD_PAGE_SIZE = 20

/** 本地日历日 YYYY-MM-DD（滑动窗口按用户本地「天」位移，与日期选择器一致） */
const localDateString = (value: Date): string => {
  const y = value.getFullYear()
  const m = String(value.getMonth() + 1).padStart(2, '0')
  const d = String(value.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

/** 两个日期串的整天差（date 串按 UTC 午夜解析，差值与时区无关）；date 晚于 base 返回负数 */
const dayDiff = (base: string, date: string): number =>
  Math.round((Date.parse(base) - Date.parse(date)) / 86_400_000)

// XBoardView 自包含控制器：单一滑动窗口语义——所有查询都走 /dashboard/x/recent，
// 日期选择器换算为 days_back 整数天位移；首次进入与点选同一天是同一条查询。
export const useXBoardController = (options: XBoardControllerOptions = {}) => {
  const api = options.api ?? dashboardApi
  const translate = options.translate ?? ((key: string) => key)
  const now = options.now ?? (() => new Date())

  const today = localDateString(now())
  const selectedDate = ref(today)
  const availableDates = ref<string[]>([])
  const docs = ref<TopDoc[]>([])
  const loading = ref(false)
  const deleting = ref(false)
  const errorMsg = ref('')
  const isActive = ref(true)
  const selectedIds = ref<Set<string>>(new Set())
  const page = ref(1)

  // 选中日期 → 整数天位移（未来日期已被 onDateChange 拦截，这里夹取兜底）
  const daysBack = computed(() => Math.max(0, dayDiff(today, selectedDate.value)))

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
    try {
      const result = await api.fetchRecentX({
        hours: XBOARD_RECENT_WINDOW_HOURS,
        daysBack: daysBack.value,
        limit: TOP_LIMIT,
        signal: controller.signal,
        cacheBuster: Date.now(),
      })
      if (isActive.value && request === generation) {
        docs.value = result.items
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
      // 快照日期清单仅用于空态提示「最早可翻到哪天」，不再回退选中日期：
      // 滑动窗口下今天永远有定义（窗口覆盖过去 24h），无需对齐到快照日
      availableDates.value = await api.fetchSnapshotDates({ source: 'x', period: 'daily', limit: SNAPSHOT_DATE_LIMIT, cacheBuster: Date.now() })
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
    // 空值/同日/未来日都不触发重拉：同日同窗口（查询字面相同），未来日无定义
    if (!date || date === selectedDate.value || dayDiff(today, date) < 0) return
    selectedDate.value = date
    selectedIds.value.clear()
    page.value = 1
    void loadTweets()
  }

  const showRecent = () => {
    // 回到今天 = days_back 归零；已是今天时视为刷新：窗口随当前时刻重新滑动
    selectedDate.value = today
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
    daysBack,
    deleteSelected,
    deleting,
    dispose,
    docs,
    errorMsg,
    goPage,
    hasNext,
    hasPrev,
    load,
    loading,
    onDateChange,
    pageSize: XBOARD_PAGE_SIZE,
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
  }
}

export type XBoardController = ReturnType<typeof useXBoardController>
