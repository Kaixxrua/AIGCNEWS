import { api } from '../http/apiClient'

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
  local_pdf_path?: string | null
  pdf_media_url?: string | null
  created_at?: string
}

export async function searchPapers(q: string, limit = 20): Promise<PaperItem[]> {
  const res = await api.get('/papers/search', { params: { q, limit } })
  return res.data?.items ?? []
}

export async function fetchTop10Today(): Promise<PaperItem[]> {
  const res = await api.get('/papers/top10-today')
  return res.data?.items ?? []
}

export async function fetchPaperDetail(paperId: string): Promise<PaperItem | null> {
  try {
    const res = await api.get(`/papers/${paperId}`)
    return res.data ?? null
  } catch {
    return null
  }
}
