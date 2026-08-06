import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { WeChatFollowApi } from '@/services/wechat/wechatFollowApi'
import type {
  WeChatArticle,
  WeChatArticleDetail,
  WeChatCatalogAccount,
  WeChatFeedResult,
} from '@/features/wechat/wechatModel'
import { useWechatFollowController } from './useWechatFollowController'

const account = (id: number, followed = false): WeChatCatalogAccount => ({
  id,
  nickname: `公众号${id}`,
  alias: '',
  avatar_url: '',
  signature: '',
  sort_order: 0,
  followed,
})

const article = (accountId: number, overrides: Partial<WeChatArticle> = {}): WeChatArticle => ({
  id: accountId * 100,
  account_id: accountId,
  stable_article_key: `k${accountId}`,
  message_id: '',
  itemidx: 1,
  title: `文章${accountId}`,
  digest: '',
  author: '',
  article_url: '',
  cover_url: '',
  source_url: '',
  has_content: false,
  published_at: null,
  created_at: null,
  updated_at: null,
  ...overrides,
})

const feedResult = (accountIds: number[]): WeChatFeedResult => ({
  items: accountIds.map((id) => ({
    account: account(id, true),
    articles: [article(id)],
  })),
  per_account: 5,
})

const createApi = (): WeChatFollowApi => ({
  fetchCatalog: vi.fn(),
  followAccount: vi.fn(),
  unfollowAccount: vi.fn(),
  fetchFeed: vi.fn(),
  fetchArticleDetail: vi.fn(),
})

describe('useWechatFollowController', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  it('loads catalog and marks followed accounts', async () => {
    const api = createApi()
    vi.mocked(api.fetchCatalog).mockResolvedValue([account(7, true), account(8)])

    const controller = useWechatFollowController({ api })
    await controller.loadCatalog()

    expect(controller.catalog.value).toHaveLength(2)
    expect(controller.followedAccounts.value.map((a) => a.id)).toEqual([7])
  })

  it('surfaces catalog load errors', async () => {
    const api = createApi()
    vi.mocked(api.fetchCatalog).mockRejectedValue({
      response: { data: { detail: { message: '服务端错误' } } },
    })

    const controller = useWechatFollowController({ api })
    await controller.loadCatalog()

    expect(controller.error.value).toBe('服务端错误')
  })

  it('toggles follow optimistically and reloads feed', async () => {
    const api = createApi()
    vi.mocked(api.fetchCatalog).mockResolvedValue([account(7)])
    vi.mocked(api.followAccount).mockResolvedValue({ account_id: 7, followed: true })
    vi.mocked(api.fetchFeed).mockResolvedValue(feedResult([7]))

    const controller = useWechatFollowController({ api })
    await controller.loadCatalog()
    const target = controller.catalog.value[0]!

    const pending = controller.toggleFollow(target)
    expect(target.followed).toBe(true) // 乐观更新立即生效
    await pending

    expect(api.followAccount).toHaveBeenCalledWith(7)
    expect(api.fetchFeed).toHaveBeenCalledTimes(1)
    expect(controller.feed.value[0]?.account.id).toBe(7)
  })

  it('rolls back follow flag when the request fails', async () => {
    const api = createApi()
    vi.mocked(api.fetchCatalog).mockResolvedValue([account(7)])
    vi.mocked(api.followAccount).mockRejectedValue({
      response: { data: { detail: { message: '公众号不存在' } } },
    })

    const controller = useWechatFollowController({ api })
    await controller.loadCatalog()
    const target = controller.catalog.value[0]!

    await controller.toggleFollow(target)

    expect(target.followed).toBe(false)
    expect(controller.error.value).toBe('公众号不存在')
  })

  it('unfollows and removes the account from feed and selection', async () => {
    const api = createApi()
    vi.mocked(api.fetchCatalog).mockResolvedValue([account(7, true)])
    vi.mocked(api.unfollowAccount).mockResolvedValue({ account_id: 7, followed: false })

    const controller = useWechatFollowController({ api })
    await controller.loadCatalog()
    controller.feed.value = feedResult([7]).items
    controller.selectAccount(7)
    const target = controller.catalog.value[0]!

    await controller.toggleFollow(target)

    expect(api.unfollowAccount).toHaveBeenCalledWith(7)
    expect(target.followed).toBe(false)
    expect(controller.feed.value).toEqual([])
    expect(controller.selectedAccountId.value).toBeNull()
  })

  it('ignores concurrent follow toggles for the same account', async () => {
    const api = createApi()
    vi.mocked(api.fetchCatalog).mockResolvedValue([account(7)])
    let resolveFollow: ((value: { account_id: number; followed: boolean }) => void) | undefined
    vi.mocked(api.followAccount).mockImplementation(
      () => new Promise((resolve) => { resolveFollow = resolve }),
    )
    vi.mocked(api.fetchFeed).mockResolvedValue(feedResult([7]))

    const controller = useWechatFollowController({ api })
    await controller.loadCatalog()
    const target = controller.catalog.value[0]!

    const first = controller.toggleFollow(target)
    await controller.toggleFollow(target) // 进行中被忽略
    expect(api.followAccount).toHaveBeenCalledTimes(1)

    resolveFollow?.({ account_id: 7, followed: true })
    await first
  })

  it('toggles article expansion by key', () => {
    const controller = useWechatFollowController({ api: createApi() })
    const key = controller.articleKey(7, 11, 'k7')

    expect(key).toBe('7:11')
    expect(controller.isArticleExpanded(key)).toBe(false)

    controller.toggleArticleExpanded(key)
    expect(controller.isArticleExpanded(key)).toBe(true)

    controller.toggleArticleExpanded(key)
    expect(controller.isArticleExpanded(key)).toBe(false)
  })

  it('falls back to stable key when article id is null', () => {
    const controller = useWechatFollowController({ api: createApi() })
    expect(controller.articleKey(7, null, 'k7')).toBe('7:k7')
  })

  it('lazily loads sanitized article detail on first expand and caches it', async () => {
    const api = createApi()
    const target = article(7, { has_content: true })
    const detail: WeChatArticleDetail = {
      ...target,
      content_html: '<section><p>正文</p><script>alert(1)</script></section>',
      content_fetched_at: '2026-08-06T08:00:00Z',
    }
    vi.mocked(api.fetchArticleDetail).mockResolvedValue(detail)

    const controller = useWechatFollowController({ api })
    const key = controller.articleKey(7, target.id, target.stable_article_key)

    controller.toggleArticleExpanded(key, 7, target)
    await vi.waitFor(() => {
      expect(controller.articleDetails.value.has(key)).toBe(true)
    })

    expect(api.fetchArticleDetail).toHaveBeenCalledWith(7, target.id)
    const cached = controller.articleDetails.value.get(key)
    expect(cached?.content_html).toContain('<p>正文</p>')
    expect(cached?.content_html).not.toContain('script')
    expect(controller.articleDetailLoading.value.has(key)).toBe(false)
    expect(controller.articleDetailErrors.value.has(key)).toBe(false)

    // 再次展开/收起不重复请求
    controller.toggleArticleExpanded(key, 7, target)
    controller.toggleArticleExpanded(key, 7, target)
    await controller.ensureArticleDetail(key, 7, target)
    expect(api.fetchArticleDetail).toHaveBeenCalledTimes(1)
  })

  it('skips detail loading when the article has no full text', async () => {
    const api = createApi()
    const controller = useWechatFollowController({ api })
    const target = article(7) // has_content: false
    const key = controller.articleKey(7, target.id, target.stable_article_key)

    controller.toggleArticleExpanded(key, 7, target)
    await controller.ensureArticleDetail(key, 7, target)

    expect(api.fetchArticleDetail).not.toHaveBeenCalled()
    expect(controller.articleDetails.value.has(key)).toBe(false)
  })

  it('skips detail loading when article id is null', async () => {
    const api = createApi()
    const controller = useWechatFollowController({ api })
    const target = article(7, { id: null, has_content: true })
    const key = controller.articleKey(7, null, target.stable_article_key)

    await controller.ensureArticleDetail(key, 7, target)

    expect(api.fetchArticleDetail).not.toHaveBeenCalled()
  })

  it('records detail load errors and retries on demand', async () => {
    const api = createApi()
    const target = article(7, { has_content: true })
    vi.mocked(api.fetchArticleDetail).mockRejectedValueOnce({
      response: { data: { detail: { message: '文章不存在' } } },
    })

    const controller = useWechatFollowController({ api })
    const key = controller.articleKey(7, target.id, target.stable_article_key)

    await controller.ensureArticleDetail(key, 7, target)
    expect(controller.articleDetailErrors.value.get(key)).toBe('文章不存在')
    expect(controller.articleDetails.value.has(key)).toBe(false)

    // 失败后不会自动重试，需要显式 retry
    await controller.ensureArticleDetail(key, 7, target)
    expect(api.fetchArticleDetail).toHaveBeenCalledTimes(1)

    vi.mocked(api.fetchArticleDetail).mockResolvedValueOnce({
      ...target,
      content_html: '<p>恢复</p>',
      content_fetched_at: null,
    })
    controller.retryArticleDetail(key, 7, target)
    await vi.waitFor(() => {
      expect(controller.articleDetails.value.has(key)).toBe(true)
    })
    expect(api.fetchArticleDetail).toHaveBeenCalledTimes(2)
    expect(controller.articleDetailErrors.value.has(key)).toBe(false)
  })

  it('ignores duplicate detail loads while one is in flight', async () => {
    const api = createApi()
    const target = article(7, { has_content: true })
    let resolveDetail: ((value: WeChatArticleDetail) => void) | undefined
    vi.mocked(api.fetchArticleDetail).mockImplementation(
      () => new Promise((resolve) => { resolveDetail = resolve }),
    )

    const controller = useWechatFollowController({ api })
    const key = controller.articleKey(7, target.id, target.stable_article_key)

    const first = controller.ensureArticleDetail(key, 7, target)
    await controller.ensureArticleDetail(key, 7, target) // 进行中被忽略
    expect(api.fetchArticleDetail).toHaveBeenCalledTimes(1)
    expect(controller.articleDetailLoading.value.has(key)).toBe(true)

    resolveDetail?.({ ...target, content_html: '<p>x</p>', content_fetched_at: null })
    await first
    expect(controller.articleDetailLoading.value.has(key)).toBe(false)
  })

  it('filters visible feed by selected account and toggles selection off', async () => {
    const api = createApi()
    const controller = useWechatFollowController({ api })
    controller.feed.value = feedResult([7, 8]).items

    controller.selectAccount(7)
    expect(controller.visibleFeed.value.map((e) => e.account.id)).toEqual([7])

    controller.selectAccount(7) // 再点取消过滤
    expect(controller.selectedAccountId.value).toBeNull()
    expect(controller.visibleFeed.value).toHaveLength(2)
  })

  it('persists follow box collapsed state in localStorage', () => {
    const controller = useWechatFollowController({ api: createApi() })
    expect(controller.followBoxCollapsed.value).toBe(true) // 默认收起

    controller.toggleFollowBoxCollapsed()
    expect(controller.followBoxCollapsed.value).toBe(false)
    expect(window.localStorage.getItem('wechat:followBoxCollapsed')).toBe('0')

    const restored = useWechatFollowController({ api: createApi() })
    expect(restored.followBoxCollapsed.value).toBe(false)
  })

  it('defaults to collapsed when localStorage is unavailable', () => {
    const getSpy = vi
      .spyOn(Storage.prototype, 'getItem')
      .mockImplementation(() => {
        throw new Error('denied')
      })

    const controller = useWechatFollowController({ api: createApi() })
    expect(controller.followBoxCollapsed.value).toBe(true)

    getSpy.mockRestore()
  })

  it('stops loading after dispose', async () => {
    const api = createApi()
    vi.mocked(api.fetchCatalog).mockResolvedValue([account(7)])

    const controller = useWechatFollowController({ api })
    controller.dispose()
    await controller.loadCatalog()

    expect(api.fetchCatalog).not.toHaveBeenCalled()
  })
})
