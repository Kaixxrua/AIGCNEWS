import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => {
  const requestUse = vi.fn()
  const responseUse = vi.fn()
  const get = vi.fn()
  const post = vi.fn()
  const patch = vi.fn()
  const del = vi.fn()
  const apiClient = {
    get,
    post,
    patch,
    delete: del,
    interceptors: {
      request: { use: requestUse },
      response: { use: responseUse },
    },
  }
  return {
    apiClient,
    create: vi.fn(() => apiClient),
    requestUse,
    responseUse,
    requestLogin: vi.fn(),
    useAuthStore: vi.fn(),
    getActivePinia: vi.fn(),
    showToast: vi.fn(),
    recordResponse: vi.fn(),
    recordFailure: vi.fn(),
  }
})

vi.mock('axios', () => ({ default: { create: mocks.create } }))
vi.mock('../../stores/authStore', () => ({ useAuthStore: mocks.useAuthStore }))
vi.mock('pinia', () => ({ getActivePinia: mocks.getActivePinia }))
vi.mock('@/composables/useLoginPrompt', () => ({ useLoginPrompt: () => ({ requestLogin: mocks.requestLogin }) }))
vi.mock('@/composables/useToast', () => ({ showToast: mocks.showToast }))
vi.mock('@/services/http/fallbackEntry', () => ({
  fallbackEntryState: { recordResponse: mocks.recordResponse, recordFailure: mocks.recordFailure },
}))

import { api } from './apiClient'
import { setRuntimeAuthToken } from './authTokenStorage'

type RejectedInterceptor = (error: any) => Promise<never>
type FulfilledInterceptor = (response: any) => any
type RequestInterceptor = (config: any) => any

const requestInterceptor = mocks.requestUse.mock.calls[0]![0] as RequestInterceptor
const responseFulfilledInterceptor = mocks.responseUse.mock.calls[0]![0] as FulfilledInterceptor
const responseRejectedInterceptor = mocks.responseUse.mock.calls[0]![1] as RejectedInterceptor

describe('frontend API transport contract', () => {
  beforeEach(() => {
    mocks.requestLogin.mockReset()
    mocks.useAuthStore.mockReset()
    mocks.getActivePinia.mockReset()
    mocks.showToast.mockReset()
    mocks.recordResponse.mockReset()
    mocks.recordFailure.mockReset()
    localStorage.clear()
    setRuntimeAuthToken(null)
    vi.restoreAllMocks()
  })

  it('creates one JSON Axios client rooted at /api with a 60 second timeout', () => {
    expect(api).toBe(mocks.apiClient)
    expect(mocks.create).toHaveBeenCalledOnce()
    expect(mocks.create).toHaveBeenCalledWith({
      baseURL: '/api',
      timeout: 60_000,
      headers: { 'Content-Type': 'application/json' },
    })
  })

  it('reports every response and failure to the fallback entry offer', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const response = { status: 200, data: {} }
    expect(responseFulfilledInterceptor(response)).toBe(response)
    expect(mocks.recordResponse).toHaveBeenCalledOnce()

    const error = { code: 'ERR_NETWORK', message: 'Network Error', config: { url: '/dashboard/summary-static', method: 'get' } }
    await expect(responseRejectedInterceptor(error)).rejects.toBe(error)
    expect(mocks.recordFailure).toHaveBeenCalledWith(error)
  })

  it('adds the current bearer token while preserving unauthenticated requests', () => {
    const anonymous = { headers: { Accept: 'application/json' } }
    expect(requestInterceptor(anonymous)).toBe(anonymous)
    expect(anonymous.headers).toEqual({ Accept: 'application/json' })

    setRuntimeAuthToken('current-token')
    const authenticated: { headers?: Record<string, string>; __authToken?: string | null } = {}
    expect(requestInterceptor(authenticated)).toBe(authenticated)
    expect(authenticated.headers).toEqual({ Authorization: 'Bearer current-token' })
    expect(authenticated.__authToken).toBe('current-token')
  })

  it('uses the authenticated in-memory token when browser persistence is unavailable', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage blocked')
    })
    setRuntimeAuthToken('memory-only-token')

    const request: { headers?: Record<string, string>; __authToken?: string | null } = {}
    expect(requestInterceptor(request)).toBe(request)
    expect(request.headers).toEqual({ Authorization: 'Bearer memory-only-token' })
    expect(request.__authToken).toBe('memory-only-token')
  })

  it('redacts MCP token response data from API error logging', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const error = {
      message: 'request failed',
      config: { url: '/auth/me/mcp-tokens', method: 'post' },
      response: { status: 500, data: { token: 'must-not-be-logged' } },
    }

    await expect(responseRejectedInterceptor(error)).rejects.toBe(error)

    expect(errorSpy).toHaveBeenCalledWith('[API Error]', {
      status: 500,
      message: 'request failed',
      url: '/auth/me/mcp-tokens',
      method: 'post',
    })
    expect(JSON.stringify(errorSpy.mock.calls)).not.toContain('must-not-be-logged')
  })

  it('opens the shared login prompt for non-auth 401 responses after clearing auth state', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const authStore = { token: 'old-token', user: { id: 1 } as unknown, status: 'authenticated', invalidateSession: vi.fn(() => localStorage.removeItem('auth_token')) }
    mocks.getActivePinia.mockReturnValue({})
    mocks.useAuthStore.mockReturnValue(authStore)
    localStorage.setItem('auth_token', 'old-token')

    const firstError = { config: { url: '/projects', __authToken: 'old-token' }, response: { status: 401 } }
    await expect(responseRejectedInterceptor(firstError)).rejects.toBe(firstError)

    expect(mocks.showToast).toHaveBeenCalledOnce()
    expect(mocks.requestLogin).toHaveBeenCalledOnce()
    expect(mocks.requestLogin).toHaveBeenCalledWith('/')
    expect(localStorage.getItem('auth_token')).toBeNull()
    expect(authStore.invalidateSession).toHaveBeenCalledOnce()
    expect(authStore.token).toBe('old-token')
    expect(authStore.user).toEqual({ id: 1 })
    expect(authStore.status).toBe('authenticated')
  })

  it('does not invalidate or prompt for an anonymous 401 response', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const authStore = { token: null, user: null, status: 'anonymous', invalidateSession: vi.fn() }
    mocks.getActivePinia.mockReturnValue({})
    mocks.useAuthStore.mockReturnValue(authStore)
    const error = { config: { url: '/auth/oauth/consume', __authToken: null }, response: { status: 401 } }

    await expect(responseRejectedInterceptor(error)).rejects.toBe(error)

    expect(authStore.invalidateSession).not.toHaveBeenCalled()
    expect(mocks.showToast).not.toHaveBeenCalled()
    expect(mocks.requestLogin).not.toHaveBeenCalled()
  })

  it('preserves the full browser target when an authenticated request expires', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const authStore = { token: 'old-token', user: null, status: 'authenticated', invalidateSession: vi.fn() }
    mocks.getActivePinia.mockReturnValue({})
    mocks.useAuthStore.mockReturnValue(authStore)
    window.history.replaceState({}, '', '/projects?source=website#saved')
    const error = { config: { url: '/projects', __authToken: 'old-token' }, response: { status: 401 } }

    await expect(responseRejectedInterceptor(error)).rejects.toBe(error)

    expect(mocks.requestLogin).toHaveBeenCalledWith('/projects?source=website#saved')
  })

  it('reasserts the login prompt for each subsequent 401 without navigating away', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    mocks.getActivePinia.mockReturnValue({})
    mocks.useAuthStore.mockReturnValue({ token: 'old-token', user: null, status: 'authenticated', invalidateSession: vi.fn(() => localStorage.removeItem('auth_token')) })

    const firstError = { config: { url: '/projects', __authToken: 'old-token' }, response: { status: 401 } }
    await expect(responseRejectedInterceptor(firstError)).rejects.toBe(firstError)
    const secondError = { config: { url: '/papers/search', __authToken: 'old-token' }, response: { status: 401 } }
    await expect(responseRejectedInterceptor(secondError)).rejects.toBe(secondError)

    expect(mocks.showToast).toHaveBeenCalledTimes(2)
    expect(mocks.requestLogin).toHaveBeenCalledTimes(2)
  })

  it.each(['/auth/login', '/auth/me', '/auth/me/mcp-tokens', '/auth/oauth/consume'])('cleans auth state but suppresses the login prompt for %s', async (url) => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const authStore = { token: 'old-token', user: { id: 1 } as unknown, status: 'authenticated', invalidateSession: vi.fn(() => localStorage.removeItem('auth_token')) }
    mocks.getActivePinia.mockReturnValue({})
    mocks.useAuthStore.mockReturnValue(authStore)
    localStorage.setItem('auth_token', 'old-token')
    const error = { config: { url, __authToken: 'old-token' }, response: { status: 401 } }

    await expect(responseRejectedInterceptor(error)).rejects.toBe(error)

    expect(localStorage.getItem('auth_token')).toBeNull()
    expect(authStore.invalidateSession).toHaveBeenCalledOnce()
    expect(authStore.token).toBe('old-token')
    expect(authStore.user).toEqual({ id: 1 })
    expect(authStore.status).toBe('authenticated')
    expect(mocks.showToast).not.toHaveBeenCalled()
    expect(mocks.requestLogin).not.toHaveBeenCalled()
  })
})
