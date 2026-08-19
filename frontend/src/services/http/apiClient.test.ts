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
  }
})

vi.mock('axios', () => ({ default: { create: mocks.create } }))
vi.mock('../../stores/authStore', () => ({ useAuthStore: mocks.useAuthStore }))
vi.mock('pinia', () => ({ getActivePinia: mocks.getActivePinia }))
vi.mock('@/composables/useLoginPrompt', () => ({ useLoginPrompt: () => ({ requestLogin: mocks.requestLogin }) }))
vi.mock('@/composables/useToast', () => ({ showToast: mocks.showToast }))

import { api } from './apiClient'

type RejectedInterceptor = (error: any) => Promise<never>
type RequestInterceptor = (config: any) => any

const requestInterceptor = mocks.requestUse.mock.calls[0]![0] as RequestInterceptor
const responseRejectedInterceptor = mocks.responseUse.mock.calls[0]![1] as RejectedInterceptor

describe('frontend API transport contract', () => {
  beforeEach(() => {
    mocks.requestLogin.mockReset()
    mocks.useAuthStore.mockReset()
    mocks.getActivePinia.mockReset()
    mocks.showToast.mockReset()
    localStorage.clear()
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

  it('adds the current bearer token while preserving unauthenticated requests', () => {
    const anonymous = { headers: { Accept: 'application/json' } }
    expect(requestInterceptor(anonymous)).toBe(anonymous)
    expect(anonymous.headers).toEqual({ Accept: 'application/json' })

    localStorage.setItem('auth_token', 'current-token')
    const authenticated: { headers?: Record<string, string> } = {}
    expect(requestInterceptor(authenticated)).toBe(authenticated)
    expect(authenticated.headers).toEqual({ Authorization: 'Bearer current-token' })
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
    const authStore = { token: 'old-token', user: { id: 1 } as unknown, status: 'authenticated' }
    mocks.getActivePinia.mockReturnValue({})
    mocks.useAuthStore.mockReturnValue(authStore)
    localStorage.setItem('auth_token', 'old-token')

    const firstError = { config: { url: '/projects' }, response: { status: 401 } }
    await expect(responseRejectedInterceptor(firstError)).rejects.toBe(firstError)

    expect(mocks.showToast).toHaveBeenCalledOnce()
    expect(mocks.requestLogin).toHaveBeenCalledOnce()
    expect(mocks.requestLogin).toHaveBeenCalledWith()
    expect(localStorage.getItem('auth_token')).toBeNull()
    expect(authStore).toEqual({ token: null, user: null, status: 'anonymous' })
  })

  it('reasserts the login prompt for each subsequent 401 without navigating away', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    mocks.getActivePinia.mockReturnValue({})
    mocks.useAuthStore.mockReturnValue({ token: 'old-token', user: null, status: 'authenticated' })

    const firstError = { config: { url: '/projects' }, response: { status: 401 } }
    await expect(responseRejectedInterceptor(firstError)).rejects.toBe(firstError)
    const secondError = { config: { url: '/papers/search' }, response: { status: 401 } }
    await expect(responseRejectedInterceptor(secondError)).rejects.toBe(secondError)

    expect(mocks.showToast).toHaveBeenCalledTimes(2)
    expect(mocks.requestLogin).toHaveBeenCalledTimes(2)
  })

  it.each(['/auth/login', '/auth/me', '/auth/me/mcp-tokens'])('cleans auth state but suppresses the login prompt for %s', async (url) => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const authStore = { token: 'old-token', user: { id: 1 } as unknown, status: 'authenticated' }
    mocks.getActivePinia.mockReturnValue({})
    mocks.useAuthStore.mockReturnValue(authStore)
    localStorage.setItem('auth_token', 'old-token')
    const error = { config: { url }, response: { status: 401 } }

    await expect(responseRejectedInterceptor(error)).rejects.toBe(error)

    expect(localStorage.getItem('auth_token')).toBeNull()
    expect(authStore).toEqual({ token: null, user: null, status: 'anonymous' })
    expect(mocks.showToast).not.toHaveBeenCalled()
    expect(mocks.requestLogin).not.toHaveBeenCalled()
  })
})
