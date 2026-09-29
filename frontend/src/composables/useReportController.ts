import { onMounted, onUnmounted, ref, watch, type Ref } from 'vue'
import {
  coerceReportStreamText,
  todayInReportTimeZone,
  type ReportKey,
  type ReportResponse,
  type ReportStreamEvent,
} from '@/features/report/reportViewModel'

interface ReportControllerOperations {
  loadCachedReport: (params: {
    source: ReportKey
    date: string
    locale: string
  }, signal?: AbortSignal) => Promise<ReportResponse | undefined>
  connectReportStream: (options: {
    source: ReportKey
    date: string
    locale: string
    onMessage: (payload: unknown) => void | Promise<void>
    onDone: () => void
    onError: (error: unknown) => void
  }) => unknown
}

interface UseReportControllerOptions {
  operations: ReportControllerOperations
  resetAutoScroll: () => void
  scrollToBottom: () => Promise<void>
  locale: Ref<string>
  /** 初始选中日期（如 RSS 条目回链的 ?date=）；缺省为 CST 今天。 */
  initialDate?: string | null
}

export const useReportController = ({
  operations,
  resetAutoScroll,
  scrollToBottom,
  locale,
  initialDate,
}: UseReportControllerOptions) => {
  const reportContent = ref('')
  const isGenerating = ref(false)
  const isCached = ref(false)
  const errorMsg = ref('')
  const selectedSource = ref<ReportKey>('all')
  const selectedDate = ref(initialDate || todayInReportTimeZone())

  // generation + AbortController 竞态守卫（对齐 useXBoardController）：
  // 源/日期/locale 连发切换时只应用最新一次缓存读取，过期请求直接中止
  const isActive = ref(true)
  let loadGeneration = 0
  let loadAbortController: AbortController | null = null

  const loadCachedReport = async () => {
    const request = ++loadGeneration
    loadAbortController?.abort()
    const controller = new AbortController()
    loadAbortController = controller
    try {
      const data = await operations.loadCachedReport({
        source: selectedSource.value,
        date: selectedDate.value,
        locale: locale.value,
      }, controller.signal)
      if (!isActive.value || request !== loadGeneration) return
      if (data?.content) {
        reportContent.value = data.content
        isCached.value = true
        errorMsg.value = ''
        return
      }
      reportContent.value = ''
      isCached.value = false
    } catch {
      if (controller.signal.aborted || !isActive.value || request !== loadGeneration) return
      reportContent.value = ''
      isCached.value = false
    }
  }

  const generate = async () => {
    if (isGenerating.value) return
    isGenerating.value = true
    reportContent.value = ''
    errorMsg.value = ''
    resetAutoScroll()

    await operations.connectReportStream({
      source: selectedSource.value,
      date: selectedDate.value,
      locale: locale.value,
      onMessage: async (payload: unknown) => {
        const event = payload as ReportStreamEvent
        if (event.type === 'content' || event.type === 'chunk') {
          reportContent.value += coerceReportStreamText(event.data)
          await scrollToBottom()
        } else if (event.type === 'error') {
          errorMsg.value = String(event.data ?? 'Unknown error')
        }
      },
      onDone: () => { isGenerating.value = false },
      onError: (error: unknown) => {
        errorMsg.value = String(error)
        isGenerating.value = false
      },
    })
  }

  onMounted(() => {
    void loadCachedReport()
  })

  onUnmounted(() => {
    isActive.value = false
    loadGeneration += 1
    loadAbortController?.abort()
    loadAbortController = null
  })

  watch([selectedSource, selectedDate, locale], () => {
    if (isGenerating.value) return
    void loadCachedReport()
  })

  return {
    reportContent,
    isGenerating,
    isCached,
    errorMsg,
    selectedSource,
    selectedDate,
    generate,
  }
}
