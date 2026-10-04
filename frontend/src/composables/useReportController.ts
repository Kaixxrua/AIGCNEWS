import { onMounted, onUnmounted, ref, watch, type Ref } from 'vue'
import {
  coerceReportStreamText,
  shiftReportDate,
  todayInReportTimeZone,
  type ReportKey,
  type ReportResponse,
  type ReportStreamEvent,
} from '@/features/report/reportViewModel'

interface ReportControllerOperations {
  /** 读某一天的一期简报；那天没有这一期时返回 undefined，其余失败照常抛出。 */
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
  /** 初始选中日期（如 RSS 条目回链的 ?date=）；缺省时跟着最新一期走。 */
  initialDate?: string | null
  /** 初始选中的简报种类（如站内速查结果回链的 ?type=）；缺省为全部。 */
  initialSource?: ReportKey | null
  /** 取当前时刻（测试注入）；「今天」每次读取时按 CST 现算。 */
  now?: () => Date
}

/**
 * 阅读区的状态：读取中；读到了；今天这一期还没发布（pending）；那天没有这一期（missing）；没读出来（failed，可重试）。
 */
export type ReportLoadState = 'loading' | 'ready' | 'pending' | 'missing' | 'failed'

// 没指定日期时显示这一类最近的一期：简报每天早上 8 点多才生成，今天的还没有就往前找，最多找这么多天。
export const LATEST_LOOKBACK_DAYS = 7

export const useReportController = ({
  operations,
  resetAutoScroll,
  scrollToBottom,
  locale,
  initialDate,
  initialSource,
  now = () => new Date(),
}: UseReportControllerOptions) => {
  const reportContent = ref('')
  const isGenerating = ref(false)
  const isCached = ref(false)
  const errorMsg = ref('')
  const selectedSource = ref<ReportKey>(initialSource || 'all')
  const selectedDate = ref(initialDate || todayInReportTimeZone(now()))
  const loadState = ref<ReportLoadState>('loading')
  // 状态说的是哪一天：读到的那一期，或者没找到的那一天。和内容一起换，改选日期后、新结果到之前不跟着变。
  const issueDate = ref(selectedDate.value)
  // 跟着最新一期走、今天的还没出而往前找到一期时，记下今天是哪天，阅读区据此提示「今天的还没发布」；其余时候为空。
  const fallbackFrom = ref('')

  // 地址栏没带 ?date=、也没手选过日期时跟着最新一期走；选了某一天就停在那一天。
  let followLatest = !initialDate
  // 往前找到一期后改写的选中日期：这次改写不再触发重读。
  let landedDate: string | null = null

  // generation + AbortController 竞态守卫（对齐 useXBoardController）：
  // 源/日期/locale 连发切换时只应用最新一次缓存读取，过期请求直接中止
  const isActive = ref(true)
  let loadGeneration = 0
  let loadAbortController: AbortController | null = null

  const settle = (state: ReportLoadState, date: string, content = '', from = '') => {
    reportContent.value = content
    isCached.value = Boolean(content)
    issueDate.value = date
    fallbackFrom.value = from
    loadState.value = state
    if (date !== selectedDate.value) {
      landedDate = date
      selectedDate.value = date
    }
  }

  const loadCachedReport = async () => {
    const request = ++loadGeneration
    loadAbortController?.abort()
    const controller = new AbortController()
    loadAbortController = controller
    landedDate = null
    loadState.value = 'loading'
    const isStale = () => controller.signal.aborted || !isActive.value || request !== loadGeneration
    const source = selectedSource.value
    const reportLocale = locale.value
    const today = todayInReportTimeZone(now())
    const latest = followLatest
    const first = latest ? today : selectedDate.value
    const last = latest ? shiftReportDate(today, -LATEST_LOOKBACK_DAYS) : first
    try {
      for (let date = first; date >= last; date = shiftReportDate(date, -1)) {
        const data = await operations.loadCachedReport({ source, date, locale: reportLocale }, controller.signal)
        if (isStale()) return
        if (!data?.content) continue
        errorMsg.value = ''
        settle('ready', date, data.content, latest && date !== today ? today : '')
        return
      }
      settle(first === today ? 'pending' : 'missing', first)
    } catch {
      if (isStale()) return
      reportContent.value = ''
      isCached.value = false
      fallbackFrom.value = ''
      loadState.value = 'failed'
    }
  }

  // 手选某一天（日期框、站内速查回链）：停在那一天，不再跟着最新一期走。
  const selectDate = (date: string) => {
    followLatest = false
    selectedDate.value = date
  }

  const retry = () => {
    if (isGenerating.value) return
    void loadCachedReport()
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

  watch([selectedSource, selectedDate, locale], ([source, date, nextLocale], [previousSource, previousDate, previousLocale]) => {
    const landed = landedDate
    landedDate = null
    if (date !== previousDate) {
      // 往前找到的那一期已经显示着，不用再读；别处直接改了日期也当作选了那一天
      if (date === landed && source === previousSource && nextLocale === previousLocale) return
      if (date !== landed) followLatest = false
    }
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
    loadState,
    issueDate,
    fallbackFrom,
    selectDate,
    retry,
    generate,
  }
}
