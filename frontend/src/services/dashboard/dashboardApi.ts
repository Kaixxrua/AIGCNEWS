import { api } from '@/services/http/apiClient'
import type {
  DashboardApi,
  DashboardRecentXWireResponse,
  DashboardSnapshotDatesWireResponse,
  DashboardSummaryWireResponse,
  DashboardStaticSummary,
  DashboardStaticSummaryWireResponse,
  DashboardTopWireResponse,
  DashboardVisitorCountWireResponse,
  GitHubHotPeriod,
  GitHubHotResponse,
  GitHubHotWireResponse,
  XSnapshotRebuildResponse,
} from './dashboardContracts'

export type {
  DashboardApi,
  DashboardRecentX,
  DashboardRecentXParams,
  DashboardSnapshotDatesParams,
  DashboardStaticSummary,
  DashboardStaticSummaryWireResponse,
  DashboardSummary,
  DashboardSummaryParams,
  DashboardTop,
  DashboardTopParams,
  DashboardVisitorCount,
  GitHubHotPeriod,
  GitHubHotRepo,
  GitHubHotResponse,
  SourceBoardStatus,
  SourceStatusMap,
} from './dashboardContracts'

export const dashboardApi: DashboardApi = {
  async fetchSummary({ period, date, signal }) {
    const params: Record<string, unknown> = {}
    if (period) params.period = period
    if (date) params.date = date
    const response = await api.get<DashboardSummaryWireResponse>('/dashboard/summary', {
      params,
      signal,
    })
    return {
      stats: response.data?.stats ?? {},
      isFinalized: response.data?.is_finalized ?? false,
      isEmbargoed: response.data?.is_embargoed ?? false,
    }
  },

  async fetchSummaryStatic({ period, date, signal }): Promise<DashboardStaticSummary> {
    const params: Record<string, unknown> = { _board: 'visible-v1' }
    if (period) params.period = period
    if (date) params.date = date
    const response = await api.get<DashboardStaticSummaryWireResponse>('/dashboard/summary-static', {
      params,
      signal,
    })
    return {
      isFinalized: response.data?.is_finalized ?? false,
      isEmbargoed: response.data?.is_embargoed ?? false,
    }
  },

  async fetchTop({ source, period, date, limit = 10, signal, cacheBuster }) {
    const params: Record<string, unknown> = { limit, source, period, _board: 'visible-v1' }
    if (date) params.date = date
    if (cacheBuster) params._t = cacheBuster
    const response = await api.get<DashboardTopWireResponse>('/dashboard/top', { params, signal })
    return {
      items: Array.isArray(response.data?.items) ? response.data.items : [],
      isFinalized: response.data?.is_finalized ?? false,
      resolvedDate: response.data?.resolved_date ?? undefined,
      stale: response.data?.stale ?? false,
      // 静默期标记必须透出：X 看板日期模式靠它区分「无数据」与「定稿前静默」
      isEmbargoed: response.data?.is_embargoed ?? false,
      // 分源定稿状态（tab 级徽章）；缺省视为全部未定稿
      sourceStatus: response.data?.source_status ?? {},
    }
  },

  async fetchRecentX({ hours = 24, daysBack = 0, limit = 500, cursor, signal, cacheBuster }) {
    const params: Record<string, unknown> = { hours, days_back: daysBack, limit }
    if (cursor) params.cursor = cursor
    if (cacheBuster) params._t = cacheBuster
    const response = await api.get<DashboardRecentXWireResponse>('/dashboard/x/recent', { params, signal })
    const items = Array.isArray(response.data?.items) ? response.data.items : []
    const nextCursor = typeof response.data?.next_cursor === 'string' && response.data.next_cursor
      ? response.data.next_cursor
      : null
    return {
      items,
      total: response.data?.total ?? items.length,
      windowHours: response.data?.window_hours ?? hours,
      accounts: Array.isArray(response.data?.accounts) ? response.data.accounts : [],
      hasMore: (response.data?.has_more ?? false) && nextCursor !== null,
      nextCursor,
    }
  },

  async fetchSnapshotDates({ limit = 60, source, period, signal, cacheBuster }) {
    const params: Record<string, unknown> = { limit, source, period }
    if (cacheBuster) params._t = cacheBuster
    const response = await api.get<DashboardSnapshotDatesWireResponse>('/dashboard/snapshot-dates', {
      params,
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
      todayVisits: response.data?.today_visits ?? 0,
      totalVisits: response.data?.total_visits ?? 0,
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

  async deleteDocument(docId: string) {
    const response = await api.delete<{ status: string; message: string; doc_id: string; deleted: boolean }>(`/ops/documents/${encodeURIComponent(docId)}`)
    return response.data
  },

  async bulkDeleteDocuments(docIds: string[]) {
    const response = await api.post<{ status: string; message: string; doc_ids: string[]; deleted_count: number; not_found_count: number }>('/ops/documents/bulk-delete', { doc_ids: docIds })
    return response.data
  },

  async rebuildXSnapshot(targetDate?: string) {
    const response = await api.post<XSnapshotRebuildResponse>('/ops/x/snapshots/rebuild', {
      target_date: targetDate ?? null,
    })
    return response.data
  },
}
