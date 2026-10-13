import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { consumeOAuthHandoff, fetchCurrentUser, uploadAvatar } from '@/services/auth/authApi'
import { useAuthStore } from './authStore'

vi.mock('../services/auth/authApi', () => ({
  consumeOAuthHandoff: vi.fn(),
  fetchCurrentUser: vi.fn(),
  loginWithPassword: vi.fn(),
  uploadAvatar: vi.fn(),
}))

const routerPush = vi.hoisted(() => vi.fn())
vi.mock('@/router/index', () => ({ default: { push: routerPush } }))

const mockedConsumeOAuthHandoff = vi.mocked(consumeOAuthHandoff)
const mockedFetchCurrentUser = vi.mocked(fetchCurrentUser)
const user = { user_id: 1, email: 'user@example.com', role: 'user' as const }

describe('auth store bootstrap', () => {
  beforeEach(() => {
    localStorage.clear()
    mockedConsumeOAuthHandoff.mockReset()
    mockedFetchCurrentUser.mockReset()
    setActivePinia(createPinia())
  })

  it('does not restore a signed-out account when its avatar upload completes', async () => {
    localStorage.setItem('auth_token', 'saved-token')
    mockedFetchCurrentUser.mockResolvedValue(user)
    const store = useAuthStore()
    await store.ensureInitialized()
    let resolveUpload!: (value: typeof user) => void
    vi.mocked(uploadAvatar).mockImplementation(() => new Promise(resolve => { resolveUpload = resolve }))
    const upload = store.updateAvatar(new File(['png'], 'avatar.png'))
    store.invalidateSession()
    resolveUpload(user)
    await expect(upload).rejects.toThrow('Authentication context changed')
    expect(store.user).toBeNull()
  })

  it.each([
    { membership_tier: 'free' as const },
    { membership_tier: 'member' as const, membership_expires_at: '2020-01-01T00:00:00Z' },
    {},
  ])('opens former member features for every authenticated account: %j', async (billing) => {
    localStorage.setItem('auth_token', 'saved-token')
    mockedFetchCurrentUser.mockResolvedValue({ ...user, ...billing })
    const store = useAuthStore()
    expect(store.isMember).toBe(false)
    await store.ensureInitialized()
    expect(store.isMember).toBe(true)
    expect(store.isAdmin).toBe(false)
    store.invalidateSession()
    expect(store.isMember).toBe(false)
  })

  it('becomes anonymous without a stored token', async () => {
    const store = useAuthStore()

    expect(store.status).toBe('initializing')
    await store.initFromStorage()

    expect(store.status).toBe('anonymous')
    expect(store.isLoggedIn).toBe(false)
    expect(mockedFetchCurrentUser).not.toHaveBeenCalled()
  })

  it('single-flights concurrent initialization requests', async () => {
    localStorage.setItem('auth_token', 'saved-token')
    let resolveRequest: ((value: typeof user) => void) | undefined
    mockedFetchCurrentUser.mockImplementation(() => new Promise(resolve => { resolveRequest = resolve }))
    const store = useAuthStore()

    const first = store.ensureInitialized()
    const second = store.ensureInitialized()

    // Pinia wraps action return values, so single-flight is observable by one underlying request.
    expect(mockedFetchCurrentUser).toHaveBeenCalledTimes(1)

    resolveRequest?.(user)
    await Promise.all([first, second])

    expect(store.status).toBe('authenticated')
    await store.ensureInitialized()
    expect(mockedFetchCurrentUser).toHaveBeenCalledTimes(1)
  })

  it('serializes OAuth handoff behind an in-flight bootstrap', async () => {
    localStorage.setItem('auth_token', 'saved-token')
    let resolveBootstrap: ((value: typeof user) => void) | undefined
    mockedFetchCurrentUser
      .mockImplementationOnce(() => new Promise(resolve => { resolveBootstrap = resolve }))
      .mockResolvedValueOnce(user)
    mockedConsumeOAuthHandoff.mockResolvedValue({
      access_token: 'oauth-token',
      role: 'user',
      redirect_to: '/mcp',
    })
    const store = useAuthStore()

    const bootstrap = store.ensureInitialized()
    const handoff = (async () => {
      await store.ensureInitialized()
      return store.loginWithOAuthHandoff()
    })()
    expect(mockedConsumeOAuthHandoff).not.toHaveBeenCalled()

    resolveBootstrap?.(user)
    await bootstrap
    await expect(handoff).resolves.toBe('/mcp')

    expect(mockedConsumeOAuthHandoff).toHaveBeenCalledOnce()
    expect(store.token).toBe('oauth-token')
    expect(store.status).toBe('authenticated')
  })

  it('single-flights recovery retries after an unconfirmed failure', async () => {
    localStorage.setItem('auth_token', 'saved-token')
    mockedFetchCurrentUser.mockRejectedValueOnce(new Error('offline'))
    const store = useAuthStore()
    await store.ensureInitialized()
    expect(store.status).toBe('degraded')

    let resolveRetry: ((value: typeof user) => void) | undefined
    mockedFetchCurrentUser.mockImplementationOnce(() => new Promise(resolve => { resolveRetry = resolve }))
    const first = store.ensureInitialized()
    const second = store.ensureInitialized()

    expect(store.status).toBe('initializing')
    expect(mockedFetchCurrentUser).toHaveBeenCalledTimes(2)
    resolveRetry?.(user)
    await Promise.all([first, second])

    expect(store.status).toBe('authenticated')
    expect(store.user).toEqual(user)
  })

  it('restores a confirmed authenticated user', async () => {
    localStorage.setItem('auth_token', 'saved-token')
    mockedFetchCurrentUser.mockResolvedValue(user)
    const store = useAuthStore()

    await store.initFromStorage()

    expect(store.token).toBe('saved-token')
    expect(store.user).toEqual(user)
    expect(store.status).toBe('authenticated')
    expect(store.isLoggedIn).toBe(true)
  })

  it('clears credentials only after a confirmed 401', async () => {
    localStorage.setItem('auth_token', 'expired-token')
    mockedFetchCurrentUser.mockRejectedValue({ response: { status: 401 } })
    const store = useAuthStore()

    await store.initFromStorage()

    expect(store.token).toBeNull()
    expect(store.user).toBeNull()
    expect(store.status).toBe('anonymous')
    expect(localStorage.getItem('auth_token')).toBeNull()
  })

  it('retains credentials and degrades for an unconfirmed failure', async (error) => {
    localStorage.setItem('auth_token', 'saved-token')
    mockedFetchCurrentUser.mockRejectedValue(error)
    const store = useAuthStore()

    await store.initFromStorage()

    expect(store.token).toBe('saved-token')
    expect(store.user).toBeNull()
    expect(store.status).toBe('degraded')
    expect(localStorage.getItem('auth_token')).toBe('saved-token')
  })
})

describe('auth store logout', () => {
  beforeEach(() => {
    localStorage.clear()
    routerPush.mockReset()
    setActivePinia(createPinia())
  })

  it('clears credentials and navigates home instead of /login', async () => {
    localStorage.setItem('auth_token', 'session-token')
    const store = useAuthStore()
    store.savePendingMessage('稍后发送')

    store.logout()
    expect(store.logoutInProgress).toBe(true)
    await vi.waitFor(() => expect(routerPush).toHaveBeenCalledWith('/'))
    await vi.waitFor(() => expect(store.logoutInProgress).toBe(false))

    expect(store.token).toBeNull()
    expect(store.user).toBeNull()
    expect(store.status).toBe('anonymous')
    expect(localStorage.getItem('auth_token')).toBeNull()
    expect(routerPush).not.toHaveBeenCalledWith('/login')
    // 待发送消息是会话上下文，不随登出丢失
    expect(store.consumePendingMessage()).toBe('稍后发送')
  })
})
