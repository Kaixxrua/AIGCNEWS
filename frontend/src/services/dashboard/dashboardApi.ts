import { api } from '../http/apiClient'

export type GitHubHotPeriod = 'daily' | 'weekly' | 'monthly'

export interface GitHubHotRepo {
  repo_id?: string | number
  full_name?: string
  title?: string
  url?: string
  description?: string | null
  language?: string | null
  topics_json?: string | string[] | null
  stars?: number | string | null
  forks?: number | string | null
}

export interface GitHubHotResponse {
  period: GitHubHotPeriod | string
  window_days?: number
  items: GitHubHotRepo[]
  total?: number
  snapshot_count?: number
}

export async function fetchSnapshotDates(
  limit = 60,
  source?: string,
  period?: string,
  signal?: AbortSignal,
): Promise<string[]> {
  const res = await api.get('/dashboard/snapshot-dates', { params: { limit, source, period }, signal })
  return res.data?.dates ?? []
}

export async function fetchGitHubHotRepos(
  period: GitHubHotPeriod = 'daily',
  limit = 30,
): Promise<GitHubHotResponse> {
  const res = await api.get('/dashboard/github-hot', { params: { period, limit } })
  return {
    period: res.data?.period ?? period,
    window_days: res.data?.window_days,
    items: Array.isArray(res.data?.items) ? res.data.items : [],
    total: res.data?.total,
    snapshot_count: res.data?.snapshot_count,
  }
}
