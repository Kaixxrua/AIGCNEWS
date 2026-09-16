import { api } from '@/services/http/apiClient'
import type { Stats } from '@/features/dashboard/dashboardViewModel'

/* 首页统计带实时计数：首选 /dashboard/live-events SSE 推送（数据变更即推，
   数字即时滚动）；本 REST 接口保留为断流降级与首屏兜底，wire 形状即公开
   Stats 的计数子集（不含排行/访客字段）。 */
export const LIVE_EVENTS_URL = '/api/dashboard/live-events'

let inflight: Promise<Stats> | null = null

export const fetchLiveStats = async (signal?: AbortSignal): Promise<Stats> => {
  if (signal?.aborted) throw new DOMException('Request aborted', 'AbortError')
  if (!inflight) {
    const request = api.get<Stats>('/dashboard/live-stats')
      .then(response => response.data)
      .finally(() => { if (inflight === request) inflight = null })
    inflight = request
  }
  if (!signal) return inflight

  // 顶栏与仪表盘共用正在进行的请求；切页只取消当前订阅者。
  const request = inflight
  return new Promise<Stats>((resolve, reject) => {
    const abort = () => reject(new DOMException('Request aborted', 'AbortError'))
    signal.addEventListener('abort', abort, { once: true })
    request.then(
      stats => { signal.removeEventListener('abort', abort); resolve(stats) },
      error => { signal.removeEventListener('abort', abort); reject(error) },
    )
  })
}
