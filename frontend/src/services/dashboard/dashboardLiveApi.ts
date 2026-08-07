import { api } from '@/services/http/apiClient'
import type { Stats } from '@/features/dashboard/dashboardViewModel'

/* 首页统计带实时计数：前端每 10s 轮询一次，仅数字变化时滚筒滚动差位。
   wire 形状即公开 Stats 的计数子集（不含排行/访客字段）。 */
export const fetchLiveStats = async (signal?: AbortSignal): Promise<Stats> => {
  const response = await api.get<Stats>('/dashboard/live-stats', { signal })
  return response.data
}
