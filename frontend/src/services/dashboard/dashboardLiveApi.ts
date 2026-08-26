import { api } from '@/services/http/apiClient'
import type { Stats } from '@/features/dashboard/dashboardViewModel'

/* 首页统计带实时计数：首选 /dashboard/live-events SSE 推送（数据变更即推，
   数字即时滚动）；本 REST 接口保留为断流降级与首屏兜底，wire 形状即公开
   Stats 的计数子集（不含排行/访客字段）。 */
export const LIVE_EVENTS_URL = '/api/dashboard/live-events'

export const fetchLiveStats = async (signal?: AbortSignal): Promise<Stats> => {
  const response = await api.get<Stats>('/dashboard/live-stats', { signal })
  return response.data
}
