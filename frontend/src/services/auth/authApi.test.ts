import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { InternalAxiosRequestConfig } from 'axios'
import { api } from '@/services/http/apiClient'
import { setRuntimeAuthToken } from '@/services/http/authTokenStorage'
import { startOAuth, startOAuthBind } from './authApi'

const originalAdapter = api.defaults.adapter
const assign = vi.fn()
const authorizationUrl = 'https://provider.test/authorize?state=single-use-state'

beforeEach(() => {
  assign.mockReset()
  setRuntimeAuthToken('current-session-token')
  vi.stubGlobal('window', { location: { assign } })
})

afterEach(() => {
  api.defaults.adapter = originalAdapter
  setRuntimeAuthToken(null)
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('OAuth browser navigation', () => {
  it.each(['github', 'google', 'wechat', 'qq', 'linuxdo'])('authenticates %s binding before navigating to its authorization page', async (provider) => {
    const adapter = vi.fn(async (config: InternalAxiosRequestConfig) => {
      expect(assign).not.toHaveBeenCalled()
      return { config, status: 200, statusText: 'OK', headers: {}, data: { authorization_url: authorizationUrl } }
    })
    api.defaults.adapter = adapter

    await startOAuthBind(provider, '/projects?source=all&tab=saved')

    expect(adapter).toHaveBeenCalledOnce()
    const request = adapter.mock.calls[0]![0]
    expect(request.method).toBe('post')
    expect(request.url).toBe(`/auth/oauth/${provider}/bind/start`)
    expect(request.headers.Authorization).toBe('Bearer current-session-token')
    expect(request.params).toEqual({ redirect_to: '/projects?source=all&tab=saved' })
    expect(api.getUri(request)).not.toContain('current-session-token')
    expect(assign).toHaveBeenCalledExactlyOnceWith(authorizationUrl)
  })

  it.each([401, 503])('stays on the current page if binding fails with HTTP %s', async (status) => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const error = { response: { status, data: { detail: 'oauth_unavailable' } } }
    api.defaults.adapter = vi.fn().mockRejectedValue(error)

    await expect(startOAuthBind('linuxdo', '/')).rejects.toBe(error)

    expect(assign).not.toHaveBeenCalled()
  })

  it('keeps anonymous login on the public start endpoint', async () => {
    setRuntimeAuthToken(null)
    const adapter = vi.fn()
    api.defaults.adapter = adapter

    await startOAuth('linuxdo', '/projects?source=all')

    expect(assign).toHaveBeenCalledExactlyOnceWith('/api/auth/oauth/linuxdo/start?redirect_to=%2Fprojects%3Fsource%3Dall')
    expect(adapter).not.toHaveBeenCalled()
  })
})
