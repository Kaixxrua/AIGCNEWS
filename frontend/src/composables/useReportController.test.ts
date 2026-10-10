import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, ref, type Ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { LATEST_LOOKBACK_DAYS, useReportController } from './useReportController'
import type { ReportKey, ReportResponse } from '@/features/report/reportViewModel'

type LoadParams = { source: ReportKey; date: string; locale: string }

// 2026-10-04 06:30 CST：当天这一期要 8 点多才生成
const EARLY_MORNING = new Date('2026-10-03T22:30:00Z')

const issue = (date: string, content = `briefing ${date}`): ReportResponse => ({ content, date, id: 1 })

const withSetup = ({
  issues = {} as Record<string, string>,
  initialDate = null as string | null,
  initialSource = null as ReportKey | null,
  now = () => EARLY_MORNING,
  load,
  isLoggedIn,
}: {
  isLoggedIn?: Ref<boolean>
  issues?: Record<string, string>
  initialDate?: string | null
  initialSource?: ReportKey | null
  now?: () => Date
  load?: (params: LoadParams) => Promise<ReportResponse | undefined>
} = {}) => {
  const loadCachedReport = vi.fn(load ?? (async ({ source, date }: LoadParams) => {
    const content = issues[`${source}:${date}`]
    return content === undefined ? undefined : issue(date, content)
  }))
  const locale = ref('zh-CN')
  let controller!: ReturnType<typeof useReportController>
  const wrapper = mount(defineComponent({
    setup() {
      controller = useReportController({
        operations: { loadCachedReport, connectReportStream: vi.fn() },
        isLoggedIn,
        resetAutoScroll: vi.fn(),
        scrollToBottom: vi.fn(async () => {}),
        locale,
        initialDate,
        initialSource,
        now,
      })
      return () => null
    },
  }))
  const requestedDates = () => loadCachedReport.mock.calls.map(([params]) => `${params.source}:${params.date}`)
  return { controller, loadCachedReport, requestedDates, locale, wrapper }
}

describe('useReportController without a chosen date', () => {
  it('shows the latest issue when today’s is not out yet and says so', async () => {
    const { controller, requestedDates } = withSetup({ issues: { 'all:2026-10-03': 'yesterday' } })
    expect(controller.loadState.value).toBe('loading')
    await flushPromises()

    expect(controller.reportContent.value).toBe('yesterday')
    expect(controller.loadState.value).toBe('ready')
    expect(controller.selectedDate.value).toBe('2026-10-03')
    expect(controller.issueDate.value).toBe('2026-10-03')
    expect(controller.fallbackFrom.value).toBe('2026-10-04')
    expect(controller.isCached.value).toBe(true)
    // 选中日期改成找到的那一期不会再读一次
    expect(requestedDates()).toEqual(['all:2026-10-04', 'all:2026-10-03'])
  })

  it('shows today’s issue without a notice once it is out', async () => {
    const { controller, requestedDates } = withSetup({ issues: { 'all:2026-10-04': 'today', 'all:2026-10-03': 'yesterday' } })
    await flushPromises()

    expect(controller.reportContent.value).toBe('today')
    expect(controller.selectedDate.value).toBe('2026-10-04')
    expect(controller.fallbackFrom.value).toBe('')
    expect(requestedDates()).toEqual(['all:2026-10-04'])
  })

  it('stops looking after a week and reports today as not out yet', async () => {
    const { controller, loadCachedReport } = withSetup()
    await flushPromises()

    expect(loadCachedReport).toHaveBeenCalledTimes(LATEST_LOOKBACK_DAYS + 1)
    expect(controller.loadState.value).toBe('pending')
    expect(controller.issueDate.value).toBe('2026-10-04')
    expect(controller.selectedDate.value).toBe('2026-10-04')
    expect(controller.reportContent.value).toBe('')
    expect(controller.isCached.value).toBe(false)
  })

  it('starts from today again when the section changes', async () => {
    const { controller, requestedDates } = withSetup({
      issues: { 'all:2026-10-03': 'overview', 'arxiv:2026-10-04': 'research today' },
    })
    await flushPromises()
    expect(controller.selectedDate.value).toBe('2026-10-03')

    controller.selectedSource.value = 'arxiv'
    await flushPromises()

    expect(controller.reportContent.value).toBe('research today')
    expect(controller.selectedDate.value).toBe('2026-10-04')
    expect(controller.fallbackFrom.value).toBe('')
    expect(requestedDates()).toEqual(['all:2026-10-04', 'all:2026-10-03', 'arxiv:2026-10-04'])
  })

  it('works out today afresh on every load', async () => {
    let now = EARLY_MORNING
    const { controller, locale, requestedDates } = withSetup({
      issues: { 'all:2026-10-03': 'saturday', 'all:2026-10-05': 'monday' },
      now: () => now,
    })
    await flushPromises()
    expect(controller.selectedDate.value).toBe('2026-10-03')

    // 页面开了一夜，第二天早上 9 点换个语言
    now = new Date('2026-10-05T01:00:00Z')
    locale.value = 'en-US'
    await flushPromises()

    expect(controller.reportContent.value).toBe('monday')
    expect(controller.fallbackFrom.value).toBe('')
    expect(requestedDates().slice(-1)).toEqual(['all:2026-10-05'])
  })

  it('stops following the latest issue once a day is picked', async () => {
    const { controller, requestedDates } = withSetup({ issues: { 'all:2026-10-03': 'yesterday' } })
    await flushPromises()

    controller.selectDate('2026-10-01')
    await flushPromises()
    expect(controller.loadState.value).toBe('missing')
    expect(controller.issueDate.value).toBe('2026-10-01')
    expect(controller.selectedDate.value).toBe('2026-10-01')
    expect(controller.fallbackFrom.value).toBe('')

    controller.selectedSource.value = 'github'
    await flushPromises()
    expect(requestedDates().slice(2)).toEqual(['all:2026-10-01', 'github:2026-10-01'])
  })
})

describe('useReportController with a chosen date', () => {
  it('says the day has no issue instead of looking further back', async () => {
    const { controller, requestedDates } = withSetup({ initialDate: '2026-09-28', issues: { 'all:2026-09-27': 'older' } })
    await flushPromises()

    expect(controller.loadState.value).toBe('missing')
    expect(controller.issueDate.value).toBe('2026-09-28')
    expect(controller.selectedDate.value).toBe('2026-09-28')
    expect(controller.reportContent.value).toBe('')
    expect(requestedDates()).toEqual(['all:2026-09-28'])
  })

  it('says today’s issue is not out yet when today is chosen early', async () => {
    const { controller, requestedDates } = withSetup({ initialDate: '2026-10-04', initialSource: 'news' })
    await flushPromises()

    expect(controller.loadState.value).toBe('pending')
    expect(requestedDates()).toEqual(['news:2026-10-04'])
  })

  it('treats a date set directly on the ref as a choice too', async () => {
    const { controller, requestedDates } = withSetup({ issues: { 'all:2026-10-03': 'yesterday', 'all:2026-09-30': 'tuesday' } })
    await flushPromises()

    controller.selectedDate.value = '2026-09-30'
    await flushPromises()
    controller.selectedSource.value = 'x'
    await flushPromises()

    expect(requestedDates().slice(2)).toEqual(['all:2026-09-30', 'x:2026-09-30'])
    expect(controller.loadState.value).toBe('missing')
  })
})

describe('useReportController failures', () => {
  it('reports a failed load and loads again on retry', async () => {
    let fail = true
    const { controller } = withSetup({
      load: async ({ date }) => {
        if (fail) throw new Error('Network Error')
        return issue(date, 'back')
      },
    })
    await flushPromises()
    expect(controller.loadState.value).toBe('failed')
    expect(controller.reportContent.value).toBe('')
    expect(controller.errorMsg.value).toBe('')

    fail = false
    controller.retry()
    expect(controller.loadState.value).toBe('loading')
    await flushPromises()
    expect(controller.loadState.value).toBe('ready')
    expect(controller.reportContent.value).toBe('back')
  })

  it('fails instead of looking further back when an earlier day errors', async () => {
    const { controller, loadCachedReport } = withSetup({
      load: async ({ date }) => {
        if (date === '2026-10-04') return undefined
        throw new Error('Request failed with status code 429')
      },
    })
    await flushPromises()

    expect(controller.loadState.value).toBe('failed')
    expect(loadCachedReport).toHaveBeenCalledTimes(2)
  })

  it('keeps only the latest of overlapping loads', async () => {
    const pending: Array<{ date: string; source: ReportKey; resolve: (value: ReportResponse | undefined) => void }> = []
    const { controller } = withSetup({
      initialDate: '2026-10-02',
      load: ({ source, date }) => new Promise(resolve => { pending.push({ source, date, resolve }) }),
    })
    await flushPromises()
    controller.selectedSource.value = 'github'
    await flushPromises()

    expect(pending.map(item => item.source)).toEqual(['all', 'github'])
    pending[1]!.resolve(issue('2026-10-02', 'engineering'))
    await flushPromises()
    pending[0]!.resolve(issue('2026-10-02', 'overview'))
    await flushPromises()

    expect(controller.reportContent.value).toBe('engineering')
    expect(controller.loadState.value).toBe('ready')
  })
})


describe('briefing authentication transitions', () => {
  it('reloads the same issue on login and removes full content synchronously on logout', async () => {
    const loggedIn = ref(false)
    const { controller, loadCachedReport, wrapper } = withSetup({
      isLoggedIn: loggedIn, initialDate: '2026-10-02',
      load: async ({ date }) => ({ ...issue(date, loggedIn.value ? 'FULL PRIVATE BODY' : 'Preview'), is_preview: !loggedIn.value }),
    })
    await flushPromises()
    expect(controller.isPreview.value).toBe(true)
    loggedIn.value = true
    await flushPromises()
    expect(controller.reportContent.value).toBe('FULL PRIVATE BODY')
    expect(controller.isPreview.value).toBe(false)
    expect(loadCachedReport.mock.lastCall?.[0].date).toBe('2026-10-02')
    loggedIn.value = false
    expect(controller.reportContent.value).toBe('')
    await flushPromises()
    expect(controller.reportContent.value).toBe('Preview')
    wrapper.unmount()
  })
})
