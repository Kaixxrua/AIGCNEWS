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

/**
 * 按 arXiv 编号（不带版本号）取站内这篇，字段与详情相同。站内没有这篇为 null；网络或服务出错时照样抛出，
 * 调用方好给「重试」。
 */
export async function fetchPaperByArxiv(arxivId: string): Promise<PaperItem | null> {
  try {
    const res = await api.get<PaperItem>(`/papers/arxiv/${encodeURIComponent(arxivId)}`)
    return res.data && typeof res.data === 'object' && res.data.id ? res.data : null
  } catch (error) {
    if ((error as { response?: { status?: unknown } } | null)?.response?.status === 404) return null
    throw error
  }
}
