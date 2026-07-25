import axios from 'axios'

export const api = axios.create({
  baseURL: '/api',
  timeout: 60_000,
  headers: {
    'Content-Type': 'application/json',
  },
})

api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('auth_token')
    if (token) {
      config.headers = config.headers ?? {}
      config.headers['Authorization'] = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error),
)

let _is401Handling = false

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const status = error?.response?.status
    const requestUrl: string = error?.config?.url ?? ''
    const data = error?.response?.data
    const message = error?.message ?? 'Unknown API error'

    const isSensitiveEndpoint = requestUrl.includes('/auth/me/mcp-tokens')
    console.error('[API Error]', {
      status,
      message,
      ...(isSensitiveEndpoint ? {} : { data }),
      url: requestUrl,
      method: error?.config?.method,
    })

    if (status === 401 && !_is401Handling) {
      const isAuthEndpoint = requestUrl.includes('/auth/login') || requestUrl.includes('/auth/me')

      localStorage.removeItem('auth_token')
      try {
        const { useAuthStore } = await import('../../stores/authStore')
        const { getActivePinia } = await import('pinia')
        const pinia = getActivePinia()
        if (pinia) {
          const authStore = useAuthStore(pinia)
          authStore.token = null
          authStore.user = null
        }
      } catch (_) {
        /* ignore */
      }

      if (!isAuthEndpoint) {
        _is401Handling = true
        try {
          const { default: router } = await import('../../router/index')
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
