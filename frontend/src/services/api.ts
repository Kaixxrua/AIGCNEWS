import axios from 'axios'

export const api = axios.create({
  baseURL: 'http://localhost:8001/api',
  timeout: 60_000,
  headers: {
    'Content-Type': 'application/json',
  },
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error?.response?.status
    const data = error?.response?.data
    const message = error?.message ?? 'Unknown API error'

    console.error('[API Error]', {
      status,
      message,
      data,
      url: error?.config?.url,
      method: error?.config?.method,
    })

    return Promise.reject(error)
  },
)

// ── Dashboard API ────────────────────────────────────────────────────────────

/**
 * 获取有快照数据的日期列表（降序），用于日历高亮标记。
 * @param limit 最多返回日期数量，默认 60
 * @returns 日期字符串数组 ['2026-03-12', '2026-03-11', ...]
 */
export async function fetchSnapshotDates(limit = 60): Promise<string[]> {
  const res = await api.get('/dashboard/snapshot-dates', { params: { limit } })
  return res.data?.dates ?? []
}
