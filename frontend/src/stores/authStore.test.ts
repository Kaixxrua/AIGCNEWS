import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchCurrentUser } from '@/services/auth/authApi'
import { useAuthStore } from './authStore'

vi.mock('../services/auth/authApi', () => ({
  fetchCurrentUser: vi.fn(),
  loginWithPassword: vi.fn(),
}))

const routerPush = vi.hoisted(() => vi.fn())
vi.mock('@/router/index', () => ({ default: { push: routerPush } }))

const mockedFetchCurrentUser = vi.mocked(fetchCurrentUser)
const user = { user_id: 1, email: 'user@example.com', role: 'user' as const }

describe('auth store bootstrap', () => {
  beforeEach(() => {
    localStorage.clear()
    mockedFetchCurrentUser.mockReset()
    setActivePinia(createPinia())
  })

  it('becomes anonymous without a stored token', async () => {
    const store = useAuthStore()

    expect(store.status).toBe('initializing')
    await store.initFromStorage()

    expect(store.status).toBe('anonymous')
    expect(store.isLoggedIn).toBe(false)
    expect(mockedFetchCurrentUser).not.toHaveBeenCalled()
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
    await vi.waitFor(() => expect(routerPush).toHaveBeenCalledWith('/'))

    expect(store.token).toBeNull()
    expect(store.user).toBeNull()
    expect(store.status).toBe('anonymous')
    expect(localStorage.getItem('auth_token')).toBeNull()
    expect(routerPush).not.toHaveBeenCalledWith('/login')
    // 待发送消息是会话上下文，不随登出丢失
    expect(store.consumePendingMessage()).toBe('稍后发送')
  })
})
