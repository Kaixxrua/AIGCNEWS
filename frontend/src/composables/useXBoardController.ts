import { computed, ref } from 'vue'
import type { DashboardApi } from '@/services/dashboard/dashboardContracts'
import { dashboardApi } from '@/services/dashboard/dashboardApi'
import type { TopDoc } from '@/features/dashboard/dashboardViewModel'
import { groupTweetsByHandle } from '@/features/xboard/xBoardViewModel'

export interface XBoardApi {
  fetchTop: DashboardApi['fetchTop']
  fetchSnapshotDates: DashboardApi['fetchSnapshotDates']
  deleteDocument: DashboardApi['deleteDocument']
}

export type XBoardTranslate = (key: string) => string

export interface XBoardControllerOptions {
  api?: XBoardApi
  translate?: XBoardTranslate
  now?: () => Date
}

const SNAPSHOT_DATE_LIMIT = 60
const TOP_LIMIT = 50

// XBoardView 自包含控制器：拉取快照日期与 source=x 推文，分组逻辑在 xBoardViewModel。
export const useXBoardController = (options: XBoardControllerOptions = {}) => {
  const api = options.api ?? dashboardApi
  const translate = options.translate ?? ((key: string) => key)
  const now = options.now ?? (() => new Date())

  const today = now().toISOString().slice(0, 10)
  const selectedDate = ref(today)
  const availableDates = ref<string[]>([])
  const docs = ref<TopDoc[]>([])
  const loading = ref(false)
  const deleting = ref(false)
  const errorMsg = ref('')
  const isActive = ref(true)
  const selectedIds = ref<Set<string>>(new Set())

  const sections = computed(() => groupTweetsByHandle(docs.value))

  let generation = 0
  let abortController: AbortController | null = null

  const loadTweets = async (date: string) => {
    const request = ++generation
    abortController?.abort()
    const controller = new AbortController()
    abortController = controller
    loading.value = true
    errorMsg.value = ''
    try {
      const result = await api.fetchTop({ source: 'x', period: 'daily', date, limit: TOP_LIMIT, signal: controller.signal })
      if (isActive.value && request === generation) docs.value = result.items
    } catch (error) {
      if (isActive.value && request === generation && !controller.signal.aborted) {
        errorMsg.value = error instanceof Error && error.message ? error.message : translate('xboard.loadFailed')
      }
    } finally {
      if (isActive.value && request === generation) loading.value = false
    }
  }

  const load = async () => {
    if (!isActive.value) return
    try {
      // 快照日期用于把默认日期回退到最近一个有数据的日期（今天可能还没跑采集）
      const dates = await api.fetchSnapshotDates({ source: 'x', period: 'daily', limit: SNAPSHOT_DATE_LIMIT })
      if (isActive.value) {
        availableDates.value = dates
        if (!dates.includes(selectedDate.value) && dates[0]) selectedDate.value = dates[0]
      }
    } catch {
      // 日期清单失败不阻塞推文加载
    }
    await loadTweets(selectedDate.value)
  }

  const onDateChange = (date: string) => {
    if (!date || date === selectedDate.value) return
    selectedDate.value = date
    selectedIds.value.clear()
    void loadTweets(date)
  }

  const refresh = () => loadTweets(selectedDate.value)

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

  const selectAll = () => {
    selectedIds.value = new Set(docs.value.map((doc) => doc.id).filter(Boolean) as string[])
  }

  const clearSelection = () => {
    selectedIds.value = new Set()
  }

  const deleteSelected = async (): Promise<number> => {
    const ids = Array.from(selectedIds.value)
    if (!ids.length) return 0
    deleting.value = true
    errorMsg.value = ''
    let deletedCount = 0
    try {
      const results = await Promise.all(ids.map((id) => api.deleteDocument(id).catch(() => ({ deleted: false, doc_id: id }))))
      deletedCount = results.filter((r) => r.deleted).length
      selectedIds.value = new Set(ids.filter((id) => !results.find((r) => r.doc_id === id)?.deleted))
      await refresh()
    } catch (error) {
      errorMsg.value = error instanceof Error && error.message ? error.message : translate('xboard.deleteFailed')
    } finally {
      deleting.value = false
    }
    return deletedCount
  }

  return {
    availableDates,
    clearSelection,
    deleteSelected,
    deleting,
    dispose,
    docs,
    errorMsg,
    load,
    loading,
    onDateChange,
    refresh,
    sections,
    selectedDate,
    selectedIds,
    selectAll,
    today,
    toggleSelection,
  }
}

export type XBoardController = ReturnType<typeof useXBoardController>
