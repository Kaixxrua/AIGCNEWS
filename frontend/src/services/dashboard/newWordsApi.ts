import { api } from '@/services/http/apiClient'

export interface NewWord {
  id: string
  term: string
  definition_zh: string
  definition_en: string
  reason_zh: string
  reason_en: string
  first_seen: string
  support?: { publishers: number; channels: number }
  sampling?: { feeds_checked: number; feeds_available: number; feeds_with_recent_items: number; documents: number; publishers: number }
  evidence: { id: string; title: string; url: string; source: string; published_at: string }[]
}

export interface NewWordsSnapshot {
  date: string
  generated_at: string | null
  status: 'ready' | 'pending' | 'empty'
  items: NewWord[]
}

export async function fetchNewWords(date: string, signal: AbortSignal): Promise<NewWordsSnapshot> {
  const response = await api.get<NewWordsSnapshot>('/dashboard/new-words', { params: { date }, signal })
  return response.data
}

export interface NewWordsHistory {
  items: NewWordsSnapshot[]
  next_before: string | null
}

export async function fetchNewWordsHistory(before: string, signal: AbortSignal): Promise<NewWordsHistory> {
  const response = await api.get<NewWordsHistory>('/dashboard/new-words/history', { params: { before }, signal })
  return response.data
}
