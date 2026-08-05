import { api } from '@/services/http/apiClient'
import type {
  WeChatAccountForm,
  WeChatArticleListResult,
  WeChatLoginAttempt,
  WeChatOfficialAccount,
  WeChatOfficialAccountSearchResult,
  WeChatSessionSummary,
  WeChatSyncSubmitResult,
} from '@/features/wechat/wechatModel'
import { buildWeChatAccountPayload } from '@/features/wechat/wechatModel'

export interface WeChatApi {
  createLoginSession(): Promise<WeChatLoginAttempt>
  fetchQrCodeUrl(attemptId: string): string
  fetchQrCodeBlob(attemptId: string): Promise<Blob>
  fetchLoginStatus(attemptId: string): Promise<WeChatLoginAttempt>
  completeLogin(attemptId: string): Promise<WeChatSessionSummary>
  cancelLogin(attemptId: string): Promise<{ status: string; attempt_id: string }>
  fetchSession(): Promise<WeChatSessionSummary>
  searchAccounts(query: string, begin?: number, size?: number): Promise<WeChatOfficialAccountSearchResult>
  fetchAccounts(): Promise<WeChatOfficialAccount[]>
  saveAccount(form: WeChatAccountForm): Promise<WeChatOfficialAccount>
  fetchArticles(accountId: number, offset?: number, limit?: number): Promise<WeChatArticleListResult>
  submitSync(accountId: number): Promise<WeChatSyncSubmitResult>
}

export const wechatApi: WeChatApi = {
  async createLoginSession() {
    return (await api.post('/ops/wechat/login-sessions')).data
  },

  fetchQrCodeUrl(attemptId: string): string {
    return `/api/ops/wechat/login-sessions/${encodeURIComponent(attemptId)}/qrcode`
  },

  async fetchQrCodeBlob(attemptId: string): Promise<Blob> {
    const response = await api.get(
      `/ops/wechat/login-sessions/${encodeURIComponent(attemptId)}/qrcode`,
      { responseType: 'blob' },
    )
    return response.data as Blob
  },

  async fetchLoginStatus(attemptId: string): Promise<WeChatLoginAttempt> {
    return (
      await api.get(
        `/ops/wechat/login-sessions/${encodeURIComponent(attemptId)}/status`,
      )
    ).data
  },

  async completeLogin(attemptId: string): Promise<WeChatSessionSummary> {
    return (
      await api.post(
        `/ops/wechat/login-sessions/${encodeURIComponent(attemptId)}/complete`,
      )
    ).data
  },

  async cancelLogin(attemptId: string): Promise<{ status: string; attempt_id: string }> {
    return (
      await api.delete(
        `/ops/wechat/login-sessions/${encodeURIComponent(attemptId)}`,
      )
    ).data
  },

  async fetchSession(): Promise<WeChatSessionSummary> {
    return (await api.get('/ops/wechat/session')).data
  },

  async searchAccounts(
    query: string,
    begin = 0,
    size = 5,
  ): Promise<WeChatOfficialAccountSearchResult> {
    const { data } = await api.get('/ops/wechat/accounts/search', {
      params: { q: query, begin, size },
    })
    return {
      items: Array.isArray(data?.items) ? data.items : [],
      total: Number(data?.total) || 0,
      begin: Number(data?.begin) ?? begin,
      size: Number(data?.size) ?? size,
    }
  },

  async fetchAccounts(): Promise<WeChatOfficialAccount[]> {
    const { data } = await api.get('/ops/wechat/accounts')
    return Array.isArray(data?.items) ? data.items : []
  },

  async saveAccount(form: WeChatAccountForm): Promise<WeChatOfficialAccount> {
    return (await api.post('/ops/wechat/accounts', buildWeChatAccountPayload(form))).data
  },

  async fetchArticles(
    accountId: number,
    offset = 0,
    limit = 20,
  ): Promise<WeChatArticleListResult> {
    const { data } = await api.get(
      `/ops/wechat/accounts/${encodeURIComponent(accountId)}/articles`,
      { params: { offset, limit } },
    )
    return {
      items: Array.isArray(data?.items) ? data.items : [],
      total: Number(data?.total) || 0,
      offset: Number(data?.offset) ?? offset,
      limit: Number(data?.limit) ?? limit,
    }
  },

  async submitSync(accountId: number): Promise<WeChatSyncSubmitResult> {
    return (
      await api.post(`/ops/wechat/accounts/${encodeURIComponent(accountId)}/sync`)
    ).data
  },
}
