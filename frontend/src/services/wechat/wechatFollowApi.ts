import { api } from '@/services/http/apiClient'
import type {
  WeChatArticleDetail,
  WeChatCatalogAccount,
  WeChatFeedResult,
} from '@/features/wechat/wechatModel'

export interface WeChatFollowApi {
  fetchCatalog(): Promise<WeChatCatalogAccount[]>
  followAccount(accountId: number): Promise<{ account_id: number; followed: boolean }>
  unfollowAccount(accountId: number): Promise<{ account_id: number; followed: boolean }>
  fetchFeed(perAccount?: number): Promise<WeChatFeedResult>
  fetchArticleDetail(accountId: number, articleId: number): Promise<WeChatArticleDetail>
}

const normalizeCatalogAccount = (raw: Partial<WeChatCatalogAccount> | null | undefined): WeChatCatalogAccount => ({
  id: Number(raw?.id) || 0,
  nickname: raw?.nickname ?? '',
  alias: raw?.alias ?? '',
  avatar_url: raw?.avatar_url ?? '',
  signature: raw?.signature ?? '',
  sort_order: Number(raw?.sort_order) || 0,
  followed: raw?.followed === true,
})

export const wechatFollowApi: WeChatFollowApi = {
  async fetchCatalog(): Promise<WeChatCatalogAccount[]> {
    const { data } = await api.get('/ops/wechat/catalog')
    const items = Array.isArray(data?.items) ? data.items : []
    return items.map(normalizeCatalogAccount)
  },

  async followAccount(accountId: number): Promise<{ account_id: number; followed: boolean }> {
    return (
      await api.post(`/ops/wechat/accounts/${encodeURIComponent(accountId)}/follow`)
    ).data
  },

  async unfollowAccount(accountId: number): Promise<{ account_id: number; followed: boolean }> {
    return (
      await api.delete(`/ops/wechat/accounts/${encodeURIComponent(accountId)}/follow`)
    ).data
  },

  async fetchFeed(perAccount = 5): Promise<WeChatFeedResult> {
    const { data } = await api.get('/ops/wechat/feed', {
      params: { per_account: perAccount },
    })
    const items = Array.isArray(data?.items) ? data.items : []
    return {
      items: items.map((entry: { account?: Partial<WeChatCatalogAccount>; articles?: unknown[] }) => ({
        account: normalizeCatalogAccount(entry?.account),
        articles: Array.isArray(entry?.articles) ? entry.articles : [],
      })),
      per_account: Number(data?.per_account) || perAccount,
    }
  },

  async fetchArticleDetail(accountId: number, articleId: number): Promise<WeChatArticleDetail> {
    const { data } = await api.get(
      `/ops/wechat/accounts/${encodeURIComponent(accountId)}/articles/${encodeURIComponent(articleId)}`,
    )
    return data
  },
}
