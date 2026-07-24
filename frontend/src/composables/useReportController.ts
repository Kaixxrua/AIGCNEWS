import { onMounted, ref, watch } from 'vue'
import {
  coercePeriodForReport,
  coerceReportStreamText,
  type PeriodKey,
  type ReportKey,
  type ReportResponse,
  type ReportStreamEvent,
} from '../features/report/reportViewModel'

interface ReportControllerOperations {
  loadCachedReport: (params: {
    source: ReportKey
    period: PeriodKey
    date: string
  }) => Promise<ReportResponse | undefined>
  connectReportStream: (options: {
    source: ReportKey
    period: PeriodKey
    date: string
    onMessage: (payload: unknown) => void | Promise<void>
    onDone: () => void
    onError: (error: unknown) => void
  }) => unknown
}

interface UseReportControllerOptions {
  operations: ReportControllerOperations
  resetAutoScroll: () => void
  scrollToBottom: () => Promise<void>
}

export const useReportController = ({
  operations,
  resetAutoScroll,
  scrollToBottom,
}: UseReportControllerOptions) => {
  const reportContent = ref('')
  const isGenerating = ref(false)
  const isCached = ref(false)
  const errorMsg = ref('')
  const selectedSource = ref<ReportKey>('all')
  const selectedPeriod = ref<PeriodKey>('daily')
  const selectedDate = ref(new Date().toISOString().slice(0, 10))

  const loadCachedReport = async () => {
    try {
      const data = await operations.loadCachedReport({
        source: selectedSource.value,
        period: selectedPeriod.value,
        date: selectedDate.value,
      })
      if (data?.content) {
        reportContent.value = data.content
        isCached.value = true
        errorMsg.value = ''
        return
      }
      reportContent.value = ''
      isCached.value = false
    } catch {
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
      period: selectedPeriod.value,
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

  watch(selectedSource, source => {
    selectedPeriod.value = coercePeriodForReport(source, selectedPeriod.value)
  })

  watch([selectedSource, selectedPeriod, selectedDate], () => {
    if (isGenerating.value) return
    void loadCachedReport()
  })

  return {
    reportContent,
    isGenerating,
    isCached,
    errorMsg,
    selectedSource,
    selectedPeriod,
    selectedDate,
    generate,
  }
}
