import { describe, expect, it, vi } from 'vitest'
import { useXBoardController, type XBoardApi } from './useXBoardController'
import type { DashboardRecentX, DashboardTop } from '@/services/dashboard/dashboardContracts'

const doc = (id: string, url: string, rawScore: number, overrides: Record<string, unknown> = {}) => ({ id, title: url, url, raw_score: rawScore, ...overrides })

const recentDocs = () => [
  doc('x:1', 'https://x.com/openai/status/1', 5),
  doc('x:2', 'https://x.com/karpathy/status/2', 50),
]

const createApi = (overrides: Partial<XBoardApi> = {}): XBoardApi => ({
  fetchTop: vi.fn(async (): Promise<DashboardTop> => ({ items: recentDocs(), isEmbargoed: false, sourceStatus: {} })),
  fetchRecentX: vi.fn(async (): Promise<DashboardRecentX> => ({ items: recentDocs(), total: 2, windowHours: 24 })),
  fetchSnapshotDates: vi.fn(async () => ['2026-08-04', '2026-08-03']),
  deleteDocument: vi.fn(async () => ({ status: 'ok', message: 'deleted', doc_id: 'x:1', deleted: true })),
  bulkDeleteDocuments: vi.fn(async () => ({ status: 'ok', message: 'deleted', doc_ids: ['x:1'], deleted_count: 1, not_found_count: 0 })),
  rebuildXSnapshot: vi.fn(async () => ({ status: 'succeeded', message: 'ok', results: [{ date: '2026-08-03', upserted: 3 }], skipped_no_date: 0 })),
  ...overrides,
})

describe('useXBoardController', () => {
  it('defaults to the rolling 24h view and loads tweets grouped by handle', async () => {
    const api = createApi()
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()

    expect(controller.viewMode.value).toBe('recent')
    expect(api.fetchSnapshotDates).toHaveBeenCalledWith(expect.objectContaining({ source: 'x', period: 'daily' }))
    expect(api.fetchRecentX).toHaveBeenCalledWith(expect.objectContaining({ hours: 24, limit: 500 }))
    expect(api.fetchTop).not.toHaveBeenCalled()
    expect(controller.selectedDate.value).toBe('2026-08-04')
    expect(controller.sections.value.map((section) => section.handle)).toEqual(['karpathy', 'openai'])
    expect(controller.loading.value).toBe(false)
  })

  it('preserves media metadata from API response', async () => {
    const media = [{ type: 'photo', url: 'https://pbs.twimg.com/a.jpg', width: 1200, height: 800 }]
    const api = createApi({
      fetchRecentX: vi.fn(async (): Promise<DashboardRecentX> => ({
        items: [
          doc('x:1', 'https://x.com/openai/status/1', 5, { media }),
          doc('x:2', 'https://x.com/karpathy/status/2', 50),
        ],
        total: 2,
        windowHours: 24,
      })),
    })
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()

    expect(controller.docs.value[0]?.media).toEqual(media)
    const flattened = controller.sections.value.flatMap((section) => section.tweets)
    expect(flattened.find((tweet) => tweet.url === 'https://x.com/openai/status/1')?.media).toEqual(media)
  })

  it('falls back to the latest snapshot date for the picker while staying in recent mode', async () => {
    const api = createApi({ fetchSnapshotDates: vi.fn(async () => ['2026-08-02', '2026-08-01']) })
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()

    // 日期选择器回退到最近有快照的日期，但默认视图仍是滚动窗口（不走 fetchTop）
    expect(controller.selectedDate.value).toBe('2026-08-02')
    expect(controller.viewMode.value).toBe('recent')
    expect(api.fetchTop).not.toHaveBeenCalled()

    // 在 recent 模式下选中同一日期字符串：切换到快照日视图
    controller.onDateChange('2026-08-02')
    await vi.waitFor(() => {
      expect(api.fetchTop).toHaveBeenLastCalledWith(expect.objectContaining({ date: '2026-08-02' }))
    })
    expect(controller.viewMode.value).toBe('date')
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

    controller.onDateChange('')
    expect(api.fetchTop).not.toHaveBeenCalled()

    // recent 模式下选择日期（即使是同一字符串）→ 切换到快照日视图
    controller.onDateChange('2026-08-04')
    await vi.waitFor(() => {
      expect(api.fetchTop).toHaveBeenLastCalledWith(expect.objectContaining({ date: '2026-08-04' }))
    })
    expect(controller.viewMode.value).toBe('date')
    const callsAfterSwitch = (api.fetchTop as ReturnType<typeof vi.fn>).mock.calls.length

    // date 模式下重复同一日期 → 不再重拉
    controller.onDateChange('2026-08-04')
    expect((api.fetchTop as ReturnType<typeof vi.fn>).mock.calls.length).toBe(callsAfterSwitch)

    controller.onDateChange('2026-08-03')
    await vi.waitFor(() => {
      expect(api.fetchTop).toHaveBeenLastCalledWith(expect.objectContaining({ date: '2026-08-03' }))
    })
  })

  it('showRecent switches back from date mode and re-slides the window on repeat calls', async () => {
    const api = createApi()
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()
    controller.onDateChange('2026-08-03')
    await vi.waitFor(() => expect(controller.viewMode.value).toBe('date'))
    controller.toggleSelection('x:1')
    controller.goPage(1)

    await controller.showRecent()
    expect(controller.viewMode.value).toBe('recent')
    expect(controller.selectedIds.value.size).toBe(0)
    expect((api.fetchRecentX as ReturnType<typeof vi.fn>).mock.calls.length).toBe(2)

    // 已在 recent 模式时再次触发 = 刷新滚动窗口
    await controller.showRecent()
    expect((api.fetchRecentX as ReturnType<typeof vi.fn>).mock.calls.length).toBe(3)
  })

  it('refresh reloads the current mode', async () => {
    const api = createApi()
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()
    await controller.refresh()
    expect((api.fetchRecentX as ReturnType<typeof vi.fn>).mock.calls.length).toBe(2)
    expect(api.fetchTop).not.toHaveBeenCalled()

    controller.onDateChange('2026-08-03')
    await vi.waitFor(() => expect(controller.viewMode.value).toBe('date'))
    const recentCalls = (api.fetchRecentX as ReturnType<typeof vi.fn>).mock.calls.length
    await controller.refresh()
    expect(api.fetchTop).toHaveBeenLastCalledWith(expect.objectContaining({ date: '2026-08-03' }))
    expect((api.fetchRecentX as ReturnType<typeof vi.fn>).mock.calls.length).toBe(recentCalls)
  })

  it('surfaces an error message when tweet loading fails', async () => {
    const api = createApi({ fetchRecentX: vi.fn(async (): Promise<DashboardRecentX> => { throw new Error('boom') }) })
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()
    expect(controller.errorMsg.value).toBe('boom')
    expect(controller.docs.value).toHaveLength(0)
  })

  it('aborts stale loads and ignores their completions after dispose', async () => {
    let resolveRecent: ((value: DashboardRecentX) => void) | undefined
    const api = createApi({
      fetchRecentX: vi.fn(() => new Promise<DashboardRecentX>((resolve) => { resolveRecent = resolve })),
    })
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    const pending = controller.load()
    // fetchRecentX 在快照日期 resolve 之后才会被调用；先等它真正发出再 dispose
    await vi.waitFor(() => expect(resolveRecent).toBeDefined())
    controller.dispose()
    resolveRecent?.({ items: [doc('x:9', 'https://x.com/openai/status/9', 1)], total: 1, windowHours: 24 })
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
    const result = await controller.deleteSelected()
    expect(result).toEqual({ deleted: 1, notFound: 0 })
    expect(api.bulkDeleteDocuments).toHaveBeenCalledWith(['x:1'])
    expect(controller.selectedIds.value.size).toBe(0)
    // 删除后按当前模式（recent）重拉
    expect((api.fetchRecentX as ReturnType<typeof vi.fn>).mock.calls.length).toBe(2)
  })

  it('keeps unselected ids after partial delete failure', async () => {
    const api = createApi({
      bulkDeleteDocuments: vi.fn(async () => ({
        status: 'ok',
        message: 'partial',
        doc_ids: ['x:1'],
        deleted_count: 1,
        not_found_count: 1,
      })),
    })
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()
    controller.selectAll()

    const result = await controller.deleteSelected()
    expect(result).toEqual({ deleted: 1, notFound: 1 })
    expect(controller.selectedIds.value.has('x:2')).toBe(true)
    expect(controller.selectedIds.value.has('x:1')).toBe(false)
  })

  const docPage = (count: number) =>
    Array.from({ length: count }, (_, index) => doc(`x:${index + 1}`, `https://x.com/openai/status/${index + 1}`, index))

  const createPagedApi = (count: number, overrides: Partial<XBoardApi> = {}) => createApi({
    fetchRecentX: vi.fn(async (): Promise<DashboardRecentX> => ({ items: docPage(count), total: count, windowHours: 24 })),
    ...overrides,
  })

  it('fetches the rolling window with limit 500 and paginates client-side at 20 per page', async () => {
    const api = createPagedApi(45)
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()

    expect(api.fetchRecentX).toHaveBeenCalledWith(expect.objectContaining({ limit: 500 }))
    expect(controller.pageSize).toBe(20)
    expect(controller.totalPages.value).toBe(3)
    expect(controller.currentPage.value).toBe(1)
    expect(controller.hasPrev.value).toBe(false)
    expect(controller.hasNext.value).toBe(true)

    controller.goPage(2)
    expect(controller.currentPage.value).toBe(2)
    expect(controller.hasPrev.value).toBe(true)
    expect(controller.hasNext.value).toBe(true)

    controller.goPage(3)
    expect(controller.hasNext.value).toBe(false)

    // goPage 内部夹取越界页
    controller.goPage(99)
    expect(controller.currentPage.value).toBe(3)
    controller.goPage(0)
    expect(controller.currentPage.value).toBe(1)
  })

  it('resets to page 1 on date change and refresh', async () => {
    const api = createPagedApi(45, {
      fetchTop: vi.fn(async (): Promise<DashboardTop> => ({ items: docPage(45), isEmbargoed: false, sourceStatus: {} })),
    })
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()
    controller.goPage(2)

    controller.onDateChange('2026-08-03')
    await vi.waitFor(() => {
      expect(api.fetchTop).toHaveBeenLastCalledWith(expect.objectContaining({ date: '2026-08-03' }))
    })
    expect(controller.currentPage.value).toBe(1)

    controller.goPage(3)
    await controller.refresh()
    expect(controller.currentPage.value).toBe(1)
  })

  it('clamps the page back after delete empties the last page', async () => {
    // 21 条 = 2 页，末页仅 1 条；删除末页唯一条目后应自动回夹到第 1 页
    let items = docPage(21)
    const api = createApi({
      fetchRecentX: vi.fn(async (): Promise<DashboardRecentX> => ({ items, total: items.length, windowHours: 24 })),
      bulkDeleteDocuments: vi.fn(async () => {
        items = items.slice(0, 20)
        return { status: 'ok', message: 'deleted', doc_ids: ['x:21'], deleted_count: 1, not_found_count: 0 }
      }),
    })
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()
    expect(controller.totalPages.value).toBe(2)

    controller.goPage(2)
    controller.toggleSelection('x:21')
    await controller.deleteSelected()

    expect(controller.docs.value).toHaveLength(20)
    expect(controller.totalPages.value).toBe(1)
    expect(controller.currentPage.value).toBe(1)
  })

  it('toggleSelectAll only affects the given page ids and selection survives page turns', async () => {
    const api = createPagedApi(45)
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()

    const pageOneIds = controller.docs.value.slice(0, 20).map((item) => String(item.id))
    controller.toggleSelectAll(pageOneIds)
    expect(controller.selectedIds.value.size).toBe(20)

    // 跨页选择保留（翻页不清空选中集）
    controller.goPage(2)
    expect(controller.selectedIds.value.size).toBe(20)

    // 给定 id 全部已选 → 再触发即移除
    controller.toggleSelectAll(pageOneIds)
    expect(controller.selectedIds.value.size).toBe(0)

    // 部分已选 → 并入剩余
    controller.toggleSelection('x:1')
    controller.toggleSelectAll(pageOneIds)
    expect(controller.selectedIds.value.size).toBe(20)

    // 空集 no-op
    controller.toggleSelectAll([])
    expect(controller.selectedIds.value.size).toBe(20)
  })

  it('tracks the embargo flag in date mode and resets it in recent mode', async () => {
    const api = createApi({
      fetchTop: vi.fn(async (): Promise<DashboardTop> => ({ items: [], isEmbargoed: true, sourceStatus: {} })),
    })
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()
    expect(controller.isEmbargoed.value).toBe(false)

    controller.onDateChange('2026-08-03')
    await vi.waitFor(() => expect(controller.viewMode.value).toBe('date'))
    expect(controller.isEmbargoed.value).toBe(true)

    await controller.showRecent()
    expect(controller.isEmbargoed.value).toBe(false)
  })

  it('rebuilds the selected date snapshot and reloads dates and tweets', async () => {
    const api = createApi()
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()
    const recentCalls = (api.fetchRecentX as ReturnType<typeof vi.fn>).mock.calls.length
    const datesCalls = (api.fetchSnapshotDates as ReturnType<typeof vi.fn>).mock.calls.length

    const result = await controller.rebuildSelectedDate()

    expect(api.rebuildXSnapshot).toHaveBeenCalledWith('2026-08-04')
    expect(result?.results?.[0]?.upserted).toBe(3)
    expect((api.fetchSnapshotDates as ReturnType<typeof vi.fn>).mock.calls.length).toBe(datesCalls + 1)
    expect((api.fetchRecentX as ReturnType<typeof vi.fn>).mock.calls.length).toBe(recentCalls + 1)
    expect(controller.rebuilding.value).toBe(false)
  })

  it('rebuilds all historical dates when no target is given', async () => {
    const api = createApi()
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()

    await controller.rebuildAllDates()

    expect(api.rebuildXSnapshot).toHaveBeenCalledWith(undefined)
  })

  it('surfaces an error message when rebuild fails', async () => {
    const api = createApi({
      rebuildXSnapshot: vi.fn(async () => { throw new Error('rebuild boom') }),
    })
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()

    const result = await controller.rebuildSelectedDate()

    expect(result).toBeNull()
    expect(controller.errorMsg.value).toBe('rebuild boom')
    expect(controller.rebuilding.value).toBe(false)
  })
})
