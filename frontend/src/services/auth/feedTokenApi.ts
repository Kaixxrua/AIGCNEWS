import { api } from '@/services/http/apiClient'

// 完整 token 只供当前操作拼装会员 RSS 链接；页面不得持久化或渲染该值。
export interface FeedTokenInfo {
  token: string
  token_hint: string
  created: boolean
  created_at: string | null
}

export async function getFeedToken(): Promise<FeedTokenInfo> {
  const res = await api.get<FeedTokenInfo>('/auth/me/feed-token')
  return res.data
}

export async function rotateFeedToken(): Promise<FeedTokenInfo> {
  const res = await api.post<FeedTokenInfo>('/auth/me/feed-token/rotate')
  return res.data
}
