import { describe, expect, it, vi } from 'vitest'
import { useXBoardController, type XBoardApi } from './useXBoardController'
import type { DashboardRecentX } from '@/services/dashboard/dashboardContracts'

const doc = (id: string, url: string, rawScore: number, overrides: Record<string, unknown> = {}) => ({ id, title: url, url, raw_score: rawScore, ...overrides })

const recentDocs = () => [
  doc('x:2', 'https://x.com/karpathy/status/2', 50, { published_at: '2026-08-04T07:00:00Z' }),
  doc('x:1', 'https://x.com/openai/status/1', 5, { published_at: '2026-08-04T06:00:00Z' }),
]

const createApi = (overrides: Partial<XBoardApi> = {}): XBoardApi => ({
  fetchRecentX: vi.fn(async (): Promise<DashboardRecentX> => ({ items: recentDocs(), total: 2, windowHours: 24, hasMore: false, nextCursor: null })),
  fetchSnapshotDates: vi.fn(async () => ['2026-08-04', '2026-08-03']),
  deleteDocument: vi.fn(async () => ({ status: 'ok', message: 'deleted', doc_id: 'x:1', deleted: true })),
  bulkDeleteDocuments: vi.fn(async () => ({ status: 'ok', message: 'deleted', doc_ids: ['x:1'], deleted_count: 1, not_found_count: 0 })),
  ...overrides,
})

describe('useXBoardController', () => {
  it('defaults to today (rolling 24h window) and loads tweets grouped by handle', async () => {
    const api = createApi()
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()

    expect(api.fetchSnapshotDates).toHaveBeenCalledWith(expect.objectContaining({ source: 'x', period: 'daily' }))
    expect(api.fetchRecentX).toHaveBeenCalledWith(expect.objectContaining({ hours: 24, daysBack: 0, limit: 500 }))
    expect(controller.selectedDate.value).toBe('2026-08-04')
    expect(controller.daysBack.value).toBe(0)
    expect(controller.sections.value.map((section) => section.handle)).toEqual(['karpathy', 'openai'])
    expect(controller.loading.value).toBe(false)
  })

  it('preserves media metadata from API response', async () => {
    const media = [{ type: 'photo', url: 'https://pbs.twimg.com/a.jpg', width: 1200, height: 800 }]
    const api = createApi({
      fetchRecentX: vi.fn(async (): Promise<DashboardRecentX> => ({
        items: [
          doc('x:1', 'https://x.com/openai/status/1', 5, { media, published_at: '2026-08-04T06:00:00Z' }),
          doc('x:2', 'https://x.com/karpathy/status/2', 50, { published_at: '2026-08-04T07:00:00Z' }),
        ],
        total: 2,
        windowHours: 24,
        hasMore: false,
        nextCursor: null,
      })),
    })
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()

    const openaiTweet = controller.docs.value.find((item) => item.url === 'https://x.com/openai/status/1')
    expect(openaiTweet?.media).toEqual(media)
    const flattened = controller.sections.value.flatMap((section) => section.tweets)
    expect(flattened.find((tweet) => tweet.url === 'https://x.com/openai/status/1')?.media).toEqual(media)
  })

  it('follows every available account by default and filters by the watched account', async () => {
    const api = createApi({
      fetchRecentX: vi.fn(async (): Promise<DashboardRecentX> => ({
        items: [
          doc('x:1', 'https://x.com/openai/status/1', 5),
          doc('x:2', 'https://x.com/original/status/2', 4, { retweeted_by: 'Karpathy' }),
          doc('x:3', 'not-a-tweet-url', 3),
        ],
        total: 3,
        windowHours: 24,
        hasMore: false,
        nextCursor: null,
      })),
    })
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()

    expect(controller.availableAccounts.value).toEqual(['karpathy', 'openai'])
    expect(controller.followedAccounts.value).toEqual(['karpathy', 'openai'])
    expect(controller.visibleDocs.value).toHaveLength(3)

    controller.toggleFollowAccount('karpathy')
    expect(controller.followedAccounts.value).toEqual(['openai'])
    // 无法识别账号的旧数据保留，纯转贴则按转贴者 karpathy 被过滤。
    expect(controller.visibleDocs.value.map((item) => item.id)).toEqual(['x:1', 'x:3'])

    controller.unfollowAllAccounts()
    expect(controller.followedAccounts.value).toEqual([])
    expect(controller.visibleDocs.value.map((item) => item.id)).toEqual(['x:3'])

    controller.followAllAccounts()
    expect(controller.visibleDocs.value).toHaveLength(3)
  })

  it('returns to page one and clears hidden admin selections when an account is unfollowed', async () => {
    const api = createPagedApi(45)
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()
    controller.goPage(2)
    controller.toggleSelection('x:1')

    controller.toggleFollowAccount('openai')

    expect(controller.currentPage.value).toBe(1)
    expect(controller.selectedIds.value.size).toBe(0)
    expect(controller.visibleDocs.value).toHaveLength(0)
  })

  it('keeps today selected even when the snapshot listing lacks today', async () => {
    // 滑动窗口语义：今天永远有定义（覆盖过去 24h），不再回退到最近快照日
    const api = createApi({ fetchSnapshotDates: vi.fn(async () => ['2026-08-02', '2026-08-01']) })
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()

    expect(controller.selectedDate.value).toBe('2026-08-04')
    expect(controller.daysBack.value).toBe(0)
    expect(api.fetchRecentX).toHaveBeenCalledWith(expect.objectContaining({ daysBack: 0 }))
  })

  it('still loads tweets when the snapshot date listing fails', async () => {
    const api = createApi({ fetchSnapshotDates: vi.fn(async () => { throw new Error('dates down') }) })
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()

    expect(controller.selectedDate.value).toBe('2026-08-04')
    expect(controller.docs.value).toHaveLength(2)
    expect(controller.errorMsg.value).toBe('')
  })

  it('shifts the window by whole days via onDateChange', async () => {
    const api = createApi()
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()

    controller.onDateChange('2026-08-03')
    await vi.waitFor(() => {
      expect(api.fetchRecentX).toHaveBeenLastCalledWith(expect.objectContaining({ daysBack: 1 }))
    })
    expect(controller.daysBack.value).toBe(1)

    controller.onDateChange('2026-08-01')
    await vi.waitFor(() => {
      expect(api.fetchRecentX).toHaveBeenLastCalledWith(expect.objectContaining({ daysBack: 3 }))
    })
  })

  it('ignores empty, repeated, or future dates so first entry and picking today are the same query', async () => {
    const api = createApi()
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()
    const callsAfterLoad = (api.fetchRecentX as ReturnType<typeof vi.fn>).mock.calls.length

    // 空值 no-op
    controller.onDateChange('')
    expect((api.fetchRecentX as ReturnType<typeof vi.fn>).mock.calls.length).toBe(callsAfterLoad)

    // 点选日期框里已显示的今天 = 同一窗口同一查询，不重拉（数量必然一致）
    controller.onDateChange('2026-08-04')
    expect((api.fetchRecentX as ReturnType<typeof vi.fn>).mock.calls.length).toBe(callsAfterLoad)

    // 未来日期无定义，忽略
    controller.onDateChange('2026-08-05')
    expect(controller.selectedDate.value).toBe('2026-08-04')
    expect((api.fetchRecentX as ReturnType<typeof vi.fn>).mock.calls.length).toBe(callsAfterLoad)

    // 切到昨天再切回同一昨天：重复值不重拉
    controller.onDateChange('2026-08-03')
    await vi.waitFor(() => expect(controller.daysBack.value).toBe(1))
    const callsAfterSwitch = (api.fetchRecentX as ReturnType<typeof vi.fn>).mock.calls.length
    controller.onDateChange('2026-08-03')
    expect((api.fetchRecentX as ReturnType<typeof vi.fn>).mock.calls.length).toBe(callsAfterSwitch)
  })

  it('showRecent returns to today and re-slides the window on repeat calls', async () => {
    const api = createApi()
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()
    controller.onDateChange('2026-08-03')
    await vi.waitFor(() => expect(controller.daysBack.value).toBe(1))
    controller.toggleSelection('x:1')

    await controller.showRecent()
    expect(controller.selectedDate.value).toBe('2026-08-04')
    expect(controller.daysBack.value).toBe(0)
    expect(controller.selectedIds.value.size).toBe(0)
    expect(api.fetchRecentX).toHaveBeenLastCalledWith(expect.objectContaining({ daysBack: 0 }))

    // 已是今天时再次触发 = 刷新滚动窗口
    const calls = (api.fetchRecentX as ReturnType<typeof vi.fn>).mock.calls.length
    await controller.showRecent()
    expect((api.fetchRecentX as ReturnType<typeof vi.fn>).mock.calls.length).toBe(calls + 1)
  })

  it('refresh reloads the current window', async () => {
    const api = createApi()
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()
    await controller.refresh()
    expect((api.fetchRecentX as ReturnType<typeof vi.fn>).mock.calls.length).toBe(2)

    controller.onDateChange('2026-08-03')
    await vi.waitFor(() => expect(controller.daysBack.value).toBe(1))
    await controller.refresh()
    // 刷新保持当前位移：仍以 daysBack=1 重拉
    expect(api.fetchRecentX).toHaveBeenLastCalledWith(expect.objectContaining({ daysBack: 1 }))
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
    resolveRecent?.({ items: [doc('x:9', 'https://x.com/openai/status/9', 1)], total: 1, windowHours: 24, hasMore: false, nextCursor: null })
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
    // 删除后按当前窗口重拉
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
    Array.from({ length: count }, (_, index) => doc(
      `x:${index + 1}`,
      `https://x.com/openai/status/${index + 1}`,
      index,
      // 发布时间倒序即索引升序（x:1 最新），与文档 id 次序一致
      { published_at: new Date(Date.UTC(2026, 7, 4, 8, 0, 0) - (index + 1) * 60_000).toISOString() },
    ))

  const createPagedApi = (count: number, overrides: Partial<XBoardApi> = {}) => createApi({
    fetchRecentX: vi.fn(async (): Promise<DashboardRecentX> => ({ items: docPage(count), total: count, windowHours: 24, hasMore: false, nextCursor: null })),
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
    const api = createPagedApi(45)
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()
    controller.goPage(2)

    controller.onDateChange('2026-08-03')
    await vi.waitFor(() => {
      expect(api.fetchRecentX).toHaveBeenLastCalledWith(expect.objectContaining({ daysBack: 1 }))
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
      fetchRecentX: vi.fn(async (): Promise<DashboardRecentX> => ({ items, total: items.length, windowHours: 24, hasMore: false, nextCursor: null })),
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
  it('follows nextCursor pages until hasMore=false, merging and deduping across pages', async () => {
    const pageOne = [
      doc('x:1', 'https://x.com/openai/status/1', 5, { published_at: '2026-08-04T07:00:00Z' }),
      doc('x:2', 'https://x.com/openai/status/2', 6, { published_at: '2026-08-04T06:00:00Z' }),
    ]
    const pageTwo = [
      // 与第一页重叠的条目（窗口推挤/边界并列）必须去重
      doc('x:2', 'https://x.com/openai/status/2', 6, { published_at: '2026-08-04T06:00:00Z' }),
      doc('x:3', 'https://x.com/karpathy/status/3', 50, { published_at: '2026-08-04T05:00:00Z' }),
    ]
    const calls: Array<{ cursor?: string }> = []
    const api = createApi({
      fetchRecentX: vi.fn(async (params): Promise<DashboardRecentX> => {
        calls.push({ cursor: params.cursor })
        if (!params.cursor) {
          return { items: pageOne, total: 2, windowHours: 24, hasMore: true, nextCursor: 'cursor-2' }
        }
        return { items: pageTwo, total: 2, windowHours: 24, hasMore: false, nextCursor: null }
      }),
    })
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()

    expect(calls).toEqual([{ cursor: undefined }, { cursor: 'cursor-2' }])
    // 合并后按发布时间倒序、跨页去重
    expect(controller.docs.value.map((item) => item.id)).toEqual(['x:1', 'x:2', 'x:3'])
  })

  it('stops at the page budget even if the server keeps returning hasMore', async () => {
    const api = createApi({
      fetchRecentX: vi.fn(async (params): Promise<DashboardRecentX> => ({
        items: [doc(`x:${params.cursor ?? 'first'}`, `https://x.com/openai/status/${params.cursor ?? '1'}`, 1)],
        total: 1,
        windowHours: 24,
        hasMore: true,
        nextCursor: `${(params.cursor ? Number(params.cursor) : 0) + 1}`,
      })),
    })
    const controller = useXBoardController({ api, now: () => new Date('2026-08-04T08:00:00Z') })
    await controller.load()

    // 硬顶 MAX_PAGES_PER_LOAD=8：最多 8 次请求，不会无限续页
    expect(api.fetchRecentX).toHaveBeenCalledTimes(8)
    expect(controller.docs.value).toHaveLength(8)
  })
})
