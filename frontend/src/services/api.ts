import axios from 'axios'

export const api = axios.create({
  baseURL: 'http://118.89.101.11:8000/api',
  timeout: 60_000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// ── 请求拦截器：自动添加 Authorization 头 ────────────────────────────────────
api.interceptors.request.use(
  (config) => {
    // 延迟导入 authStore，避免循环依赖（api.ts ← authStore.ts → api.ts）
    // 直接从 localStorage 读取 token，保持轻量
    const token = localStorage.getItem('auth_token')
    if (token) {
      config.headers = config.headers ?? {}
      config.headers['Authorization'] = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error),
)

// ── 响应拦截器：全局捕获 401 ──────────────────────────────────────────────────
let _is401Handling = false

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const status = error?.response?.status
    const requestUrl: string = error?.config?.url ?? ''
    const data = error?.response?.data
    const message = error?.message ?? 'Unknown API error'

    console.error('[API Error]', {
      status,
      message,
      data,
      url: requestUrl,
      method: error?.config?.method,
    })

    // 401 处理：
    // - /auth/login 的 401 → 密码错误，不做跳转
    // - /auth/me 的 401 → 初始化时 token 失效，只静默清除，不弹窗/不跳转
    // - 其他接口的 401 → 登录过期，弹窗提示并跳转 /login
    if (status === 401 && !_is401Handling) {
      const isAuthEndpoint =
        requestUrl.includes('/auth/login') || requestUrl.includes('/auth/me')

      // 无论如何，先清除本地 token
      localStorage.removeItem('auth_token')
      try {
        const { useAuthStore } = await import('../stores/authStore')
        const { getActivePinia } = await import('pinia')
        const pinia = getActivePinia()
        if (pinia) {
          const authStore = useAuthStore(pinia)
          authStore.token = null
          authStore.user = null
        }
      } catch (_) { /* ignore */ }

      // 只有非鉴权端点的 401 才弹窗并跳转
      if (!isAuthEndpoint) {
        _is401Handling = true
        try {
          const { default: router } = await import('../router/index')
          alert('登录已过期，请重新登录')
          await router.push('/login')
        } finally {
          _is401Handling = false
        }
      }
    }

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

// ── Papers API ────────────────────────────────────────────────────────────────

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

/** 全文搜索所有来源文档 */
export async function searchPapers(q: string, limit = 20): Promise<PaperItem[]> {
  const res = await api.get('/papers/search', { params: { q, limit } })
  return res.data?.items ?? []
}

/** 今日高分 Arxiv Top10 冷启动推荐 */
export async function fetchTop10Today(): Promise<PaperItem[]> {
  const res = await api.get('/papers/top10-today')
  return res.data?.items ?? []
}

/** 按 id 获取论文详情 */
export async function fetchPaperDetail(paperId: string): Promise<PaperItem | null> {
  try {
    const res = await api.get(`/papers/${paperId}`)
    return res.data ?? null
  } catch {
    return null
  }
}
