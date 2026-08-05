import { describe, expect, it, vi } from 'vitest'
import { useXBoardController, type XBoardApi } from './useXBoardController'
import type { DashboardTop } from '@/services/dashboard/dashboardContracts'

const doc = (id: string, url: string, rawScore: number, overrides: Record<string, unknown> = {}) => ({ id, title: url, url, raw_score: rawScore, ...overrides })

const createApi = (overrides: Partial<XBoardApi> = {}): XBoardApi => ({
  fetchTop: vi.fn(async (): Promise<DashboardTop> => ({
    items: [
      doc('x:1', 'https://x.com/openai/status/1', 5),
      doc('x:2', 'https://x.com/karpathy/status/2', 50),
    ],
  })),
  fetchSnapshotDates: vi.fn(async () => ['2026-08-04', '2026-08-03']),
  deleteDocument: vi.fn(async () => ({ status: 'ok', message: 'deleted', doc_id: 'x:1', deleted: true })),
  ...overrides,
})

describe('useXBoardController', () => {
  it('defaults to today when present in snapshot dates and loads tweets grouped by handle', async () => {
    const api = createApi()
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()

    expect(api.fetchSnapshotDates).toHaveBeenCalledWith(expect.objectContaining({ source: 'x', period: 'daily' }))
    expect(api.fetchTop).toHaveBeenCalledWith(expect.objectContaining({
      source: 'x', period: 'daily', date: '2026-08-04', limit: 50,
    }))
    expect(controller.selectedDate.value).toBe('2026-08-04')
    expect(controller.sections.value.map((section) => section.handle)).toEqual(['karpathy', 'openai'])
    expect(controller.loading.value).toBe(false)
  })

  it('preserves media metadata from API response', async () => {
    const media = [{ type: 'photo', url: 'https://pbs.twimg.com/a.jpg', width: 1200, height: 800 }]
    const api = createApi({
      fetchTop: vi.fn(async (): Promise<DashboardTop> => ({
        items: [
          doc('x:1', 'https://x.com/openai/status/1', 5, { media }),
          doc('x:2', 'https://x.com/karpathy/status/2', 50),
        ],
      })),
    })
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()

    expect(controller.docs.value[0]?.media).toEqual(media)
    const flattened = controller.sections.value.flatMap((section) => section.tweets)
    expect(flattened.find((tweet) => tweet.url === 'https://x.com/openai/status/1')?.media).toEqual(media)
  })

  it('falls back to the latest snapshot date when today has no data yet', async () => {
    const api = createApi({ fetchSnapshotDates: vi.fn(async () => ['2026-08-02', '2026-08-01']) })
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()

    expect(controller.selectedDate.value).toBe('2026-08-02')
    expect(api.fetchTop).toHaveBeenCalledWith(expect.objectContaining({ date: '2026-08-02' }))
  })

  it('still loads tweets when the snapshot date listing fails', async () => {
    const api = createApi({ fetchSnapshotDates: vi.fn(async () => { throw new Error('dates down') }) })
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()

    expect(controller.selectedDate.value).toBe('2026-08-04')
    expect(controller.docs.value).toHaveLength(2)
    expect(controller.errorMsg.value).toBe('')
  })

  it('changes date via onDateChange and ignores empty or repeated values', async () => {
    const api = createApi()
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()
    const callsAfterLoad = (api.fetchTop as ReturnType<typeof vi.fn>).mock.calls.length

    controller.onDateChange('')
    controller.onDateChange('2026-08-04')
    expect((api.fetchTop as ReturnType<typeof vi.fn>).mock.calls.length).toBe(callsAfterLoad)

    controller.onDateChange('2026-08-03')
    await vi.waitFor(() => {
      expect(api.fetchTop).toHaveBeenLastCalledWith(expect.objectContaining({ date: '2026-08-03' }))
    })
  })

  it('surfaces an error message when tweet loading fails', async () => {
    const api = createApi({ fetchTop: vi.fn(async (): Promise<DashboardTop> => { throw new Error('boom') }) })
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()
    expect(controller.errorMsg.value).toBe('boom')
    expect(controller.docs.value).toHaveLength(0)
  })

  it('aborts stale loads and ignores their completions after dispose', async () => {
    let resolveTop: ((value: DashboardTop) => void) | undefined
    const api = createApi({
      fetchTop: vi.fn(() => new Promise<DashboardTop>((resolve) => { resolveTop = resolve })),
    })
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    const pending = controller.load()
    // fetchTop 在快照日期 resolve 之后才会被调用；先等它真正发出再 dispose
    await vi.waitFor(() => expect(resolveTop).toBeDefined())
    controller.dispose()
    resolveTop?.({ items: [doc('x:9', 'https://x.com/openai/status/9', 1)] })
    await pending
    expect(controller.docs.value).toHaveLength(0)
    expect(controller.loading.value).toBe(false)
  })

  it('tracks admin tweet selection and deletes selected tweets', async () => {
    const api = createApi()
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()

    controller.toggleSelection('x:1')
    expect(controller.selectedIds.value.has('x:1')).toBe(true)

    controller.selectAll()
    expect(controller.selectedIds.value.size).toBe(2)

    controller.clearSelection()
    expect(controller.selectedIds.value.size).toBe(0)

    controller.toggleSelection('x:1')
    const deleted = await controller.deleteSelected()
    expect(deleted).toBe(1)
    expect(api.deleteDocument).toHaveBeenCalledWith('x:1')
    expect(controller.selectedIds.value.size).toBe(0)
  })

  it('keeps unselected ids after partial delete failure', async () => {
    const api = createApi({
      deleteDocument: vi.fn(async (docId: string) =>
        docId === 'x:1'
          ? { status: 'ok', message: 'deleted', doc_id: 'x:1', deleted: true }
          : { status: 'ok', message: 'not found', doc_id: docId, deleted: false }
      ),
    })
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()
    controller.selectAll()

    const deleted = await controller.deleteSelected()
    expect(deleted).toBe(1)
    expect(controller.selectedIds.value.has('x:2')).toBe(true)
    expect(controller.selectedIds.value.has('x:1')).toBe(false)
  })
})
