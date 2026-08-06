import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { WeChatFollowApi } from '@/services/wechat/wechatFollowApi'
import type { WeChatCatalogAccount, WeChatFeedResult } from '@/features/wechat/wechatModel'
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

const feedResult = (accountIds: number[]): WeChatFeedResult => ({
  items: accountIds.map((id) => ({
    account: account(id, true),
    articles: [
      {
        id: id * 100,
        account_id: id,
        stable_article_key: `k${id}`,
        message_id: '',
        itemidx: 1,
        title: `文章${id}`,
        digest: '',
        author: '',
        article_url: '',
        cover_url: '',
        source_url: '',
        published_at: null,
        created_at: null,
        updated_at: null,
      },
    ],
  })),
  per_account: 5,
})

const createApi = (): WeChatFollowApi => ({
  fetchCatalog: vi.fn(),
  followAccount: vi.fn(),
  unfollowAccount: vi.fn(),
  fetchFeed: vi.fn(),
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
    expect(controller.followBoxCollapsed.value).toBe(false)

    controller.toggleFollowBoxCollapsed()
    expect(controller.followBoxCollapsed.value).toBe(true)
    expect(window.localStorage.getItem('wechat:followBoxCollapsed')).toBe('1')

    const restored = useWechatFollowController({ api: createApi() })
    expect(restored.followBoxCollapsed.value).toBe(true)
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
