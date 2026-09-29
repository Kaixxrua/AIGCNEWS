import { api } from '@/services/http/apiClient'

export interface RecommendedWebsiteInput {
  title: string
  url: string
  description: string
  category: string
  sort_order: number
}

export interface RecommendedWebsite extends RecommendedWebsiteInput {
  id: number
  /** 保存时从网站抓取、存为本站素材的图标（/api/media/site/…）；抓不到为空串。 */
  icon_url?: string
  created_at: string
  updated_at: string
}

export async function fetchRecommendedWebsites(): Promise<RecommendedWebsite[]> {
  const response = await api.get<{ items: RecommendedWebsite[] }>('/site/recommended-websites')
  return response.data.items
}

export async function createRecommendedWebsite(input: RecommendedWebsiteInput): Promise<RecommendedWebsite> {
  const response = await api.post<RecommendedWebsite>('/ops/recommended-websites', input)
  return response.data
}

export async function updateRecommendedWebsite(id: number, input: RecommendedWebsiteInput): Promise<RecommendedWebsite> {
  const response = await api.put<RecommendedWebsite>(`/ops/recommended-websites/${id}`, input)
  return response.data
}

export async function deleteRecommendedWebsite(id: number): Promise<void> {
  await api.delete(`/ops/recommended-websites/${id}`)
}
