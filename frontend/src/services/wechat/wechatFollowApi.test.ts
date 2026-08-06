import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { wechatFollowApi } from '@/services/wechat/wechatFollowApi'
import { api } from '@/services/http/apiClient'

vi.mock('@/services/http/apiClient', () => ({
  api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}))

describe('wechatFollowApi', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset()
    vi.mocked(api.post).mockReset()
    vi.mocked(api.delete).mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('fetches catalog and normalizes follow flags', async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      data: {
        items: [
          { id: 7, nickname: 'A', followed: true },
          { id: 8, nickname: 'B' },
        ],
        total: 2,
      },
    })
    const items = await wechatFollowApi.fetchCatalog()
    expect(api.get).toHaveBeenCalledWith('/ops/wechat/catalog')
    expect(items).toHaveLength(2)
    expect(items[0]?.followed).toBe(true)
    expect(items[1]?.followed).toBe(false)
    expect(items[1]?.nickname).toBe('B')
  })

  it('returns empty catalog when items missing', async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ data: {} })
    expect(await wechatFollowApi.fetchCatalog()).toEqual([])
  })

  it('follows an account via POST with encoded id', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ data: { account_id: 7, followed: true } })
    const result = await wechatFollowApi.followAccount(7)
    expect(api.post).toHaveBeenCalledWith('/ops/wechat/accounts/7/follow')
    expect(result.followed).toBe(true)
  })

  it('unfollows an account via DELETE with encoded id', async () => {
    vi.mocked(api.delete).mockResolvedValueOnce({ data: { account_id: 7, followed: false } })
    const result = await wechatFollowApi.unfollowAccount(7)
    expect(api.delete).toHaveBeenCalledWith('/ops/wechat/accounts/7/follow')
    expect(result.followed).toBe(false)
  })

  it('fetches feed with per_account param and normalizes entries', async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      data: {
        items: [
          {
            account: { id: 7, nickname: 'A', followed: true },
            articles: [{ id: 1, title: 'T' }],
          },
          { account: { id: 8, nickname: 'B', followed: true } },
        ],
        per_account: 3,
      },
    })
    const result = await wechatFollowApi.fetchFeed(3)
    expect(api.get).toHaveBeenCalledWith('/ops/wechat/feed', { params: { per_account: 3 } })
    expect(result.per_account).toBe(3)
    expect(result.items).toHaveLength(2)
    expect(result.items[0]?.articles).toHaveLength(1)
    expect(result.items[1]?.articles).toEqual([])
    expect(result.items[0]?.account.followed).toBe(true)
  })

  it('falls back to requested per_account when response omits it', async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ data: { items: [] } })
    const result = await wechatFollowApi.fetchFeed(8)
    expect(result.per_account).toBe(8)
    expect(result.items).toEqual([])
  })

  it('fetches article detail with encoded ids', async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      data: {
        id: 11,
        account_id: 7,
        stable_article_key: 'k7',
        has_content: true,
        content_html: '<section><p>正文</p></section>',
        content_fetched_at: '2026-08-06T08:00:00Z',
      },
    })
    const detail = await wechatFollowApi.fetchArticleDetail(7, 11)
    expect(api.get).toHaveBeenCalledWith('/ops/wechat/accounts/7/articles/11')
    expect(detail.content_html).toContain('正文')
    expect(detail.has_content).toBe(true)
    expect(detail.content_fetched_at).toBe('2026-08-06T08:00:00Z')
  })
})
