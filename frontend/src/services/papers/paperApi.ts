import { api } from '@/services/http/apiClient'

export interface PaperItem {
  id: string
  source: string
  source_channel?: string
  title: string
  url?: string
  summary?: string
  published_date?: string
  tags?: string
  score?: number
  raw_score?: number
  rank_in_period?: number
  /** JSON 字符串，如 '["Hao Li", "MeiJia Chen"]'。 */
  authors?: string[] | string | null
  arxiv_id?: string | null
  created_at?: string
}

export async function fetchPaperDetail(paperId: string): Promise<PaperItem | null> {
  try {
    const res = await api.get(`/papers/${paperId}`)
    return res.data ?? null
  } catch {
    return null
  }
}
