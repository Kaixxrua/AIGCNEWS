import axios from 'axios'
import { showToast } from '@/composables/useToast'
import { i18n } from '@/i18n'
import { readAuthToken, removeAuthToken } from '@/services/http/authTokenStorage'
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

      removeAuthToken()
      try {
        const { useAuthStore } = await import('@/stores/authStore')
        const { getActivePinia } = await import('pinia')
        const pinia = getActivePinia()
        if (pinia) {
          const authStore = useAuthStore(pinia)
          authStore.token = null
          authStore.user = null
          authStore.status = 'anonymous'
        }
      } catch (_) {
        /* ignore */
      }

      if (!isAuthEndpoint) {
        _is401Handling = true
        try {
          showToast(i18n.global.t('auth.sessionExpired'))
          useLoginPrompt().requestLogin()
        } finally {
          _is401Handling = false
        }
      }
    }

    return Promise.reject(error)
  },
)
