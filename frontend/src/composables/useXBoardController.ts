import { computed, ref } from 'vue'
import type { DashboardApi } from '@/services/dashboard/dashboardContracts'
import { dashboardApi } from '@/services/dashboard/dashboardApi'
import type { TopDoc } from '@/features/dashboard/dashboardViewModel'
import { clampPage, extractXHandle, followedAccountDisplayName, followedAccountHandle, groupTweetsByHandle, mergePagedTweets, pageCount } from '@/features/xboard/xBoardViewModel'
import { useXAccountSubscriptions } from '@/features/xboard/useXAccountSubscriptions'

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
// 看板每页拉取上限（与后端 limit 上限一致）；满页时沿 nextCursor 续页，
// 不再把 500 当作窗口总量上限
const TOP_LIMIT = 500
// 单次刷新最多自动续页数：硬顶 4000 条/窗口，防止异常窗口无限请求
const MAX_PAGES_PER_LOAD = 8
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
  const watchAccounts = ref<{ handle: string; displayName: string }[] | null>(null)
  const loading = ref(false)
  const deleting = ref(false)
  const errorMsg = ref('')
  const isActive = ref(true)
  const selectedIds = ref<Set<string>>(new Set())
  const subscriptions = useXAccountSubscriptions()
  const page = ref(1)

  // 选中日期 → 整数天位移（未来日期已被 onDateChange 拦截，这里夹取兜底）
  const daysBack = computed(() => Math.max(0, dayDiff(today, selectedDate.value)))

  const availableAccounts = computed(() => watchAccounts.value?.map((account) => account.handle) ?? Array.from(new Set(
    docs.value.map(followedAccountHandle).filter(Boolean),
  )).sort((a, b) => a.localeCompare(b)))
  const availableAccountOptions = computed(() => {
    if (watchAccounts.value !== null) return watchAccounts.value
    const labels = new Map<string, string>()
    // API 按时间倒序返回；同一账号采用最新可用昵称，覆盖转贴上的后台备注名。
    const nicknames = new Map<string, string>()
    for (const doc of docs.value) {
      const author = extractXHandle(doc.url)
      const nickname = doc.author_name?.trim()
      if (author && nickname && !nicknames.has(author)) nicknames.set(author, nickname)
    }
    for (const doc of docs.value) {
      const handle = followedAccountHandle(doc)
      if (!handle) continue
      const label = followedAccountDisplayName(doc)
      const current = labels.get(handle)
      // A configured/name label wins over an @handle fallback from older rows.
      if (!current || (current.startsWith('@') && !label.startsWith('@'))) {
        labels.set(handle, label || `@${handle}`)
      }
    }
    return availableAccounts.value
      .map((handle) => ({ handle, displayName: nicknames.get(handle) || labels.get(handle) || `@${handle}` }))
      .sort((a, b) => a.displayName.localeCompare(b.displayName))
  })
  const followedAccounts = computed(() => availableAccounts.value.filter(subscriptions.follows))
  const unfollowedAccounts = computed(() => new Set(availableAccounts.value.filter(
    (handle) => !subscriptions.follows(handle),
  )))
  const visibleDocs = computed(() => docs.value.filter((doc) => {
    const handle = followedAccountHandle(doc)
    if (watchAccounts.value !== null && !availableAccounts.value.includes(handle)) return false
    // 无法识别归属账号的旧数据不静默丢弃。
    return !handle || subscriptions.follows(handle)
  }))
  const sections = computed(() => groupTweetsByHandle(visibleDocs.value))
  const totalPages = computed(() => pageCount(visibleDocs.value.length, XBOARD_PAGE_SIZE))
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
      const pages: TopDoc[][] = []
      let cursor: string | undefined
      for (let depth = 0; depth < MAX_PAGES_PER_LOAD; depth += 1) {
        const result = await api.fetchRecentX({
          hours: XBOARD_RECENT_WINDOW_HOURS,
          daysBack: daysBack.value,
          limit: TOP_LIMIT,
          cursor,
          signal: controller.signal,
          cacheBuster: Date.now(),
        })
        if (!isActive.value || request !== generation) return
        if (result.accounts !== undefined) watchAccounts.value = result.accounts
        pages.push(result.items)
        // 首批到达即渲染；后续 keyset 页在后台渐进合并，避免大窗口一直空转。
        docs.value = mergePagedTweets(pages)
        if (!result.hasMore || !result.nextCursor) break
        cursor = result.nextCursor
      }
      if (isActive.value && request === generation) {
        docs.value = mergePagedTweets(pages)
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
    await Promise.all([loadDates(), loadTweets()])
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

  const removeHiddenTweetSelections = () => {
    const visibleIds = new Set(visibleDocs.value.map((doc) => String(doc.id ?? '')).filter(Boolean))
    selectedIds.value = new Set([...selectedIds.value].filter((id) => visibleIds.has(id)))
  }

  const toggleFollowAccount = (handle: string) => {
    subscriptions.toggle(handle)
    page.value = 1
    removeHiddenTweetSelections()
  }

  const followAllAccounts = () => {
    subscriptions.followAll()
    page.value = 1
  }

  const unfollowAllAccounts = () => {
    subscriptions.unfollowAll()
    page.value = 1
    removeHiddenTweetSelections()
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
    availableAccountOptions,
    availableAccounts,
    availableDates,
    clearSelection,
    currentPage,
    daysBack,
    deleteSelected,
    deleting,
    dispose,
    docs,
    errorMsg,
    followAllAccounts,
    followedAccounts,
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
    toggleFollowAccount,
    toggleSelection,
    totalPages,
    unfollowAllAccounts,
    unfollowedAccounts,
    visibleDocs,
  }
}

export type XBoardController = ReturnType<typeof useXBoardController>
