import axios from 'axios'
import { showToast } from '@/composables/useToast'
import { i18n } from '@/i18n'
import {
  readAuthToken,
  removeAuthToken,
} from '@/services/http/authTokenStorage'
import { useLoginPrompt } from '@/composables/useLoginPrompt'

export const api = axios.create({
  baseURL: '/api',
  timeout: 60_000,
  headers: {
    'Content-Type': 'application/json',
  },
})

api.interceptors.request.use(
  (config) => {
    const token = readAuthToken()
    config.__authToken = token ?? null
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
    const requestToken = (error?.config as { __authToken?: string | null } | undefined)?.__authToken ?? null

    const isSensitiveEndpoint =
      requestUrl.includes('/auth/me/mcp-tokens')
      || requestUrl.includes('/auth/me/feed-token')
    console.error('[API Error]', {
      status,
      message,
      ...(isSensitiveEndpoint ? {} : { data }),
      url: requestUrl,
      method: error?.config?.method,
    })

    if (status === 401 && !_is401Handling) {
      const isAuthEndpoint = requestUrl.includes('/auth/login')
        || requestUrl.includes('/auth/me')
        || requestUrl.includes('/auth/oauth/consume')
      let invalidated = false

      try {
        const { useAuthStore } = await import('@/stores/authStore')
        const { getActivePinia } = await import('pinia')
        const pinia = getActivePinia()
        if (pinia) {
          const authStore = useAuthStore(pinia)
          // 只有实际携带当前会话令牌的请求才能使会话失效；匿名 401 不弹登录窗。
          // An old request must not invalidate a newer login session.
          if (requestToken && authStore.token === requestToken) {
            authStore.invalidateSession()
            invalidated = true
          }
        } else if (requestToken && readAuthToken() === requestToken) {
          removeAuthToken()
          invalidated = true
        }
      } catch (_) {
        /* ignore */
      }

      if (invalidated && !isAuthEndpoint) {
        _is401Handling = true
        try {
          showToast(i18n.global.t('auth.sessionExpired'))
          const currentTarget = `${window.location.pathname}${window.location.search}${window.location.hash}`
          useLoginPrompt().requestLogin(currentTarget)
        } finally {
          _is401Handling = false
        }
      }
    }

    return Promise.reject(error)
  },
)
