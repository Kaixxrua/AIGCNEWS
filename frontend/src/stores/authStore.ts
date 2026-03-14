import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '../services/api'

export interface AuthUser {
  user_id: number
  phone: string
  role: 'user' | 'admin'
}

const TOKEN_KEY = 'auth_token'
const PENDING_CHAT_KEY = 'pending_chat_message'

export const useAuthStore = defineStore('auth', () => {
  // ── State ──────────────────────────────────────────────────────────────────
  const token = ref<string | null>(localStorage.getItem(TOKEN_KEY))
  const user = ref<AuthUser | null>(null)
  /** 未登录用户在 Chat 页输入后点发送，临时缓存消息，登录后回填 */
  const pendingChatMessage = ref<string>(localStorage.getItem(PENDING_CHAT_KEY) ?? '')

  // ── Getters ────────────────────────────────────────────────────────────────
  const isLoggedIn = computed(() => !!token.value)
  const isAdmin = computed(() => user.value?.role === 'admin')

  // ── Actions ────────────────────────────────────────────────────────────────

  /** 缓存待发送消息（未登录时）*/
  function savePendingMessage(msg: string): void {
    pendingChatMessage.value = msg
    localStorage.setItem(PENDING_CHAT_KEY, msg)
  }

  /** 消费并清除缓存消息 */
  function consumePendingMessage(): string {
    const msg = pendingChatMessage.value
    pendingChatMessage.value = ''
    localStorage.removeItem(PENDING_CHAT_KEY)
    return msg
  }

  /** 登录：调用 POST /api/auth/login，保存 token/user，返回 user */
  async function login(phone: string, password: string): Promise<AuthUser> {
    const res = await api.post<{ access_token: string; role: string }>('/auth/login', { phone, password })
    const data = res.data
    token.value = data.access_token
    localStorage.setItem(TOKEN_KEY, data.access_token)
    // 登录后立即拉取完整用户信息
    await fetchMe()
    return user.value!
  }

  /** 退出：清除 token/user，跳转 /login */
  function logout(): void {
    token.value = null
    user.value = null
    localStorage.removeItem(TOKEN_KEY)
    import('../router/index').then(({ default: router }) => {
      router.push('/login')
    })
  }

  /** 刷新当前用户信息 */
  async function fetchMe(): Promise<void> {
    const res = await api.get<AuthUser>('/auth/me')
    user.value = res.data
  }

  /** 从 localStorage 恢复 token，若有效则调用 fetchMe() 恢复 user */
  async function initFromStorage(): Promise<void> {
    const storedToken = localStorage.getItem(TOKEN_KEY)
    if (!storedToken) return
    token.value = storedToken
    try {
      await fetchMe()
    } catch {
      // token 无效或过期，清除
      token.value = null
      user.value = null
      localStorage.removeItem(TOKEN_KEY)
    }
  }

  return {
    token,
    user,
    isLoggedIn,
    isAdmin,
    pendingChatMessage,
    savePendingMessage,
    consumePendingMessage,
    login,
    logout,
    fetchMe,
    initFromStorage,
  }
})
