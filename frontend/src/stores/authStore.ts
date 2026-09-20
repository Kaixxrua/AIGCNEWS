import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  fetchCurrentUser,
  uploadAvatar,
  consumeOAuthHandoff,
  consumeOAuthBindHandoff,
  loginWithPassword,
  type AuthUserDTO,
} from '@/services/auth/authApi'
import {
  AUTH_TOKEN_KEY,
  setRuntimeAuthToken,
} from '@/services/http/authTokenStorage'

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
  setRuntimeAuthToken(token.value)
  const user = ref<AuthUser | null>(null)
  const status = ref<AuthStatus>('initializing')
  const logoutInProgress = ref(false)
  let initializationPromise: Promise<void> | null = null
  /** 未登录用户在 Chat 页输入后点发送，临时缓存消息，登录后回填 */
  const pendingChatMessage = ref<string>(readStorage(PENDING_CHAT_KEY) ?? '')

  // ── Getters ────────────────────────────────────────────────────────────────
  const authRevision = ref(0)
  const isLoggedIn = computed(() => status.value === 'authenticated')
  const isAdmin = computed(() => status.value === 'authenticated' && user.value?.role === 'admin')
  const isMember = computed(() => {
    if (status.value !== 'authenticated' || user.value?.membership_tier !== 'member') return false
    const expiry = user.value.membership_expires_at
    if (expiry == null || expiry.trim() === '') return true
    const timestamp = Date.parse(expiry)
    // 与后端 resolve_effective_tier 保持 fail-open：无法解析的历史值不误伤会员。
    return Number.isNaN(timestamp) || timestamp > Date.now()
  })
  const userId = computed(() => user.value?.user_id ?? null)

  const nextRevision = (): number => {
    authRevision.value += 1
    return authRevision.value
  }

  const isCurrent = (revision: number, expectedToken: string | null): boolean =>
    authRevision.value === revision && token.value === expectedToken

  const staleAuthOperation = () => new Error('Authentication context changed')

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

  const fetchMeForContext = async (revision: number, expectedToken: string): Promise<AuthUser> => {
    const currentUser = await fetchCurrentUser()
    if (!isCurrent(revision, expectedToken)) throw staleAuthOperation()
    user.value = currentUser
    return currentUser
  }

  /** 登录：调用 POST /api/auth/login，保存 token/user，返回 user */
  async function login(email: string, password: string): Promise<AuthUser> {
    const revision = nextRevision()
    const previousToken = token.value
    const data = await loginWithPassword(email, password)
    if (!isCurrent(revision, previousToken)) throw staleAuthOperation()
    token.value = data.access_token
    setRuntimeAuthToken(data.access_token)
    writeStorage(TOKEN_KEY, data.access_token)
    // 登录后立即拉取完整用户信息；整个过程绑定本次登录 revision。
    const currentUser = await fetchMeForContext(revision, data.access_token)
    if (!isCurrent(revision, data.access_token)) throw staleAuthOperation()
    status.value = 'authenticated'
    return currentUser
  }

  async function loginWithOAuthHandoff(): Promise<string> {
    const revision = nextRevision()
    const previousToken = token.value
    const data = await consumeOAuthHandoff()
    if (!isCurrent(revision, previousToken)) throw staleAuthOperation()
    token.value = data.access_token
    setRuntimeAuthToken(data.access_token)
    writeStorage(TOKEN_KEY, data.access_token)
    await fetchMeForContext(revision, data.access_token)
    if (!isCurrent(revision, data.access_token)) throw staleAuthOperation()
    status.value = 'authenticated'
    return data.redirect_to
  }

  /** 消费 OAuth 账户绑定 handoff；不签发/轮换令牌，只刷新当前用户信息。 */
  async function consumeOAuthBinding(): Promise<string> {
    const data = await consumeOAuthBindHandoff()
    await fetchMe()
    return data.redirect_to
  }

  /** 安装服务端签发的新令牌，并使使用旧令牌的异步操作失效。 */
  function replaceToken(accessToken: string): void {
    const nextToken = accessToken.trim()
    if (!nextToken) throw new Error('Replacement token is empty')
    nextRevision()
    token.value = nextToken
    setRuntimeAuthToken(nextToken)
    writeStorage(TOKEN_KEY, nextToken)
  }

  /** 统一清除当前会话，并使所有旧的异步认证请求失效。 */
  function invalidateSession(): void {
    nextRevision()
    token.value = null
    setRuntimeAuthToken(null)
    user.value = null
    status.value = 'anonymous'
    removeStorage(TOKEN_KEY)
  }

  /** 退出：标记为主动退出，避免受保护页面的失效监听误弹登录窗。 */
  function logout(): void {
    logoutInProgress.value = true
    invalidateSession()
    import('@/router/index').then(({ default: router }) => router.push('/'))
      .finally(() => { logoutInProgress.value = false })
  }

  /** 刷新当前用户信息；结果只写入发起时仍然有效的会话。 */
  async function fetchMe(): Promise<void> {
    const revision = authRevision.value
    const expectedToken = token.value
    if (!expectedToken) return
    await fetchMeForContext(revision, expectedToken)
  }

  /** A completed upload must not overwrite a newer login or restore a logged-out user. */
  async function updateAvatar(file: File): Promise<void> {
    const revision = authRevision.value
    const expectedToken = token.value
    if (!expectedToken || !isLoggedIn.value) throw staleAuthOperation()
    const updated = await uploadAvatar(file)
    if (!isCurrent(revision, expectedToken)) throw staleAuthOperation()
    user.value = updated
  }

  /** 从 localStorage 恢复 token；仅服务端确认 401 时清除凭据。 */
  async function initFromStorage(): Promise<void> {
    const revision = nextRevision()
    const storedToken = readStorage(TOKEN_KEY)
    status.value = 'initializing'
    if (!storedToken) {
      if (!isCurrent(revision, token.value)) return
      token.value = null
      setRuntimeAuthToken(null)
      user.value = null
      status.value = 'anonymous'
      return
    }

    token.value = storedToken
    setRuntimeAuthToken(storedToken)
    try {
      await fetchMeForContext(revision, storedToken)
      if (isCurrent(revision, storedToken)) status.value = 'authenticated'
    } catch (error: unknown) {
      if (!isCurrent(revision, storedToken)) return
      if (isUnauthorized(error)) {
        invalidateSession()
        return
      }
      status.value = 'degraded'
    }
  }

  /** 认证恢复与失败重试保持单飞；已确认的登录/匿名状态不重复请求。 */
  function ensureInitialized(): Promise<void> {
    if (status.value !== 'initializing' && status.value !== 'degraded') return Promise.resolve()
    if (!initializationPromise) {
      initializationPromise = initFromStorage().finally(() => {
        initializationPromise = null
      })
    }
    return initializationPromise
  }

  return {
    token,
    user,
    status,
    logoutInProgress,
    isLoggedIn,
    isAdmin,
    isMember,
    userId,
    replaceToken,
    invalidateSession,
    pendingChatMessage,
    savePendingMessage,
    consumePendingMessage,
    login,
    loginWithOAuthHandoff,
    consumeOAuthBinding,
    logout,
    fetchMe,
    updateAvatar,
    initFromStorage,
    ensureInitialized,
  }
})
