import { api } from '../http/apiClient'
import type {
  DashboardApi,
  DashboardSnapshotDatesWireResponse,
  DashboardSummaryWireResponse,
  DashboardTopWireResponse,
  DashboardVisitorCountWireResponse,
  GitHubHotPeriod,
  GitHubHotResponse,
  GitHubHotWireResponse,
} from './dashboardContracts'

export type {
  DashboardApi,
  DashboardSnapshotDatesParams,
  DashboardSummary,
  DashboardSummaryParams,
  DashboardTop,
  DashboardTopParams,
  DashboardVisitorCount,
  GitHubHotPeriod,
  GitHubHotRepo,
  GitHubHotResponse,
} from './dashboardContracts'

export const dashboardApi: DashboardApi = {
  async fetchSummary({ period, date, signal }) {
    const response = await api.get<DashboardSummaryWireResponse>('/dashboard/summary', {
      params: { period, date },
      signal,
    })
    return {
      stats: response.data?.stats ?? {},
      isFinalized: response.data?.is_finalized ?? false,
      isEmbargoed: response.data?.is_embargoed ?? false,
    }
  },

  async fetchTop({ source, period, date, limit = 10, signal }) {
    const response = await api.get<DashboardTopWireResponse>('/dashboard/top', {
      params: { limit, source, period, date },
      signal,
    })
    return { items: Array.isArray(response.data?.items) ? response.data.items : [] }
  },

  async fetchSnapshotDates({ limit = 60, source, period, signal }) {
    const response = await api.get<DashboardSnapshotDatesWireResponse>('/dashboard/snapshot-dates', {
      params: { limit, source, period },
      signal,
    })
    return Array.isArray(response.data?.dates) ? response.data.dates : []
  },

  async fetchVisitorCount(signal) {
    const response = await api.get<DashboardVisitorCountWireResponse>('/dashboard/visitor-count', { signal })
    return {
      registeredUsers: response.data?.registered_users ?? 0,
      todayRegisteredUsers: response.data?.today_registered_users ?? 0,
      userCount: response.data?.user_count ?? 0,
    }
  },

  async fetchGitHubHotRepos(period: GitHubHotPeriod = 'daily', limit = 30): Promise<GitHubHotResponse> {
    const response = await api.get<GitHubHotWireResponse>('/dashboard/github-hot', { params: { period, limit } })
    return {
      period: response.data?.period ?? period,
      window_days: response.data?.window_days,
      items: Array.isArray(response.data?.items) ? response.data.items : [],
      total: response.data?.total,
      snapshot_count: response.data?.snapshot_count,
    }
  },
}

export function fetchSnapshotDates(
  limit = 60,
  source?: string,
  period?: string,
  signal?: AbortSignal,
): Promise<string[]> {
  return dashboardApi.fetchSnapshotDates({
    limit,
    source: source as Parameters<DashboardApi['fetchSnapshotDates']>[0]['source'],
    period: period as Parameters<DashboardApi['fetchSnapshotDates']>[0]['period'],
    signal,
  })
}

export function fetchGitHubHotRepos(
  period: GitHubHotPeriod = 'daily',
  limit = 30,
): Promise<GitHubHotResponse> {
  return dashboardApi.fetchGitHubHotRepos(period, limit)
}
