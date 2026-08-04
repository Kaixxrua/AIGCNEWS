import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  fetchCurrentUser,
  loginWithPassword,
  type AuthUserDTO,
} from '@/services/auth/authApi'
import { AUTH_TOKEN_KEY } from '@/services/http/authTokenStorage'

export type AuthUser = AuthUserDTO
export type AuthStatus = 'initializing' | 'authenticated' | 'anonymous' | 'degraded'

const TOKEN_KEY = AUTH_TOKEN_KEY
const PENDING_CHAT_KEY = 'pending_chat_message'

function readStorage(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function writeStorage(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    // Authentication still works for the current page when storage is unavailable.
  }
}

function removeStorage(key: string): void {
  try {
    localStorage.removeItem(key)
  } catch {
    // Keep in-memory state authoritative when storage is unavailable.
  }
}

function isUnauthorized(error: unknown): boolean {
  return typeof error === 'object'
    && error !== null
    && 'response' in error
    && (error as { response?: { status?: number } }).response?.status === 401
}

export const useAuthStore = defineStore('auth', () => {
  // ── State ──────────────────────────────────────────────────────────────────
  const token = ref<string | null>(readStorage(TOKEN_KEY))
  const user = ref<AuthUser | null>(null)
  const status = ref<AuthStatus>('initializing')
  /** 未登录用户在 Chat 页输入后点发送，临时缓存消息，登录后回填 */
  const pendingChatMessage = ref<string>(readStorage(PENDING_CHAT_KEY) ?? '')

  // ── Getters ────────────────────────────────────────────────────────────────
  const isLoggedIn = computed(() => status.value === 'authenticated')
  const isAdmin = computed(() => status.value === 'authenticated' && user.value?.role === 'admin')

  // ── Actions ────────────────────────────────────────────────────────────────

  /** 缓存待发送消息（未登录时）*/
  function savePendingMessage(msg: string): void {
    pendingChatMessage.value = msg
    writeStorage(PENDING_CHAT_KEY, msg)
  }

  /** 消费并清除缓存消息 */
  function consumePendingMessage(): string {
    const msg = pendingChatMessage.value
    pendingChatMessage.value = ''
    removeStorage(PENDING_CHAT_KEY)
    return msg
  }

  /** 登录：调用 POST /api/auth/login，保存 token/user，返回 user */
  async function login(email: string, password: string): Promise<AuthUser> {
    const data = await loginWithPassword(email, password)
    token.value = data.access_token
    writeStorage(TOKEN_KEY, data.access_token)
    // 登录后立即拉取完整用户信息
    await fetchMe()
    status.value = 'authenticated'
    return user.value!
  }

  /** 退出：清除 token/user，跳转 /login */
  function logout(): void {
    token.value = null
    user.value = null
    status.value = 'anonymous'
    removeStorage(TOKEN_KEY)
    import('@/router/index').then(({ default: router }) => {
      router.push('/login')
    })
  }

  /** 刷新当前用户信息 */
  async function fetchMe(): Promise<void> {
    user.value = await fetchCurrentUser()
  }

  /** 从 localStorage 恢复 token；仅服务端确认 401 时清除凭据。 */
  async function initFromStorage(): Promise<void> {
    status.value = 'initializing'
    const storedToken = readStorage(TOKEN_KEY)
    if (!storedToken) {
      token.value = null
      user.value = null
      status.value = 'anonymous'
      return
    }

    token.value = storedToken
    try {
      await fetchMe()
      status.value = 'authenticated'
    } catch (error: unknown) {
      if (isUnauthorized(error)) {
        token.value = null
        user.value = null
        status.value = 'anonymous'
        removeStorage(TOKEN_KEY)
        return
      }
      status.value = 'degraded'
    }
  }

  return {
    token,
    user,
    status,
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
