import { describe, expect, it } from 'vitest'
import { MCP_OAUTH_SCOPE_GRANT_KEYS, isFramed, isSafeClientRedirect, parseAuthorizationQuery } from './mcpOAuthConsent'

describe('parseAuthorizationQuery', () => {
  it('keeps the authorization request fields and drops everything else', () => {
    expect(parseAuthorizationQuery({
      response_type: 'code',
      client_id: 'aigc_oc_1',
      redirect_uri: 'http://localhost:33418/callback',
      state: 'a b',
      code_challenge: 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM',
      code_challenge_method: 'S256',
      scope: 'projects:favorites:read tracking:read',
      resource: 'https://aigcnews.cn/api/mcp/oauth',
      prompt: 'consent',
      utm_source: 'x',
    })).toEqual({
      request: {
        response_type: 'code',
        client_id: 'aigc_oc_1',
        redirect_uri: 'http://localhost:33418/callback',
        state: 'a b',
        code_challenge: 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM',
        code_challenge_method: 'S256',
        scope: 'projects:favorites:read tracking:read',
        resource: 'https://aigcnews.cn/api/mcp/oauth',
      },
      duplicated: false,
    })
  })

  it('treats a field without a value as missing', () => {
    expect(parseAuthorizationQuery({ client_id: 'aigc_oc_1', state: null })).toEqual({ request: { client_id: 'aigc_oc_1' }, duplicated: false })
  })

  it('flags a request field that appears more than once', () => {
    const parsed = parseAuthorizationQuery({ client_id: 'aigc_oc_1', redirect_uri: ['http://localhost/a', 'https://evil.example/b'] })
    expect(parsed.duplicated).toBe(true)
    expect(parsed.request).toEqual({ client_id: 'aigc_oc_1' })
    // 不属于授权请求的参数重复不算
    expect(parseAuthorizationQuery({ client_id: 'aigc_oc_1', utm: ['a', 'b'] }).duplicated).toBe(false)
  })
})

describe('isSafeClientRedirect', () => {
  it('accepts the registered callback with parameters appended', () => {
    expect(isSafeClientRedirect('http://localhost:33418/callback?code=x&state=y', 'http://localhost:33418/callback')).toBe(true)
    expect(isSafeClientRedirect('https://claude.ai/api/mcp/auth_callback?code=x', 'https://claude.ai/api/mcp/auth_callback')).toBe(true)
    expect(isSafeClientRedirect('cursor://anysphere.cursor-retrieval/oauth/callback?code=x', 'cursor://anysphere.cursor-retrieval/oauth/callback')).toBe(true)
    expect(isSafeClientRedirect('com.example.app:/cb?keep=1&code=x', 'com.example.app:/cb?keep=1')).toBe(true)
  })

  it('rejects anything that does not start with the callback the page sent', () => {
    expect(isSafeClientRedirect('https://evil.example/cb?code=x', 'http://localhost:33418/callback')).toBe(false)
    expect(isSafeClientRedirect('http://localhost:33418/callback?code=x', undefined)).toBe(false)
    expect(isSafeClientRedirect('http://localhost:33418/callback?code=x', '')).toBe(false)
    expect(isSafeClientRedirect(undefined, 'http://localhost:33418/callback')).toBe(false)
    expect(isSafeClientRedirect(42, 'http://localhost:33418/callback')).toBe(false)
  })

  it('rejects script and local-content schemes even when the prefix matches', () => {
    for (const uri of ['javascript:alert(1)//', 'JavaScript:alert(1)//', 'data:text/html,x', 'vbscript:x', 'file:///etc/passwd', 'blob:https://aigcnews.cn/x', 'about:blank']) {
      expect(isSafeClientRedirect(`${uri}?code=x`, uri), uri).toBe(false)
    }
    expect(isSafeClientRedirect('not a url', 'not a url')).toBe(false)
  })
})

describe('isFramed', () => {
  it('is false for a top-level page and true inside a frame or when top cannot be read', () => {
    expect(isFramed()).toBe(false)
    const top = {} as Window
    expect(isFramed({ self: {} as Window, top } as unknown as Window)).toBe(true)
    const throwing = Object.defineProperty({ self: {} }, 'top', { get: () => { throw new DOMException('blocked', 'SecurityError') } })
    expect(isFramed(throwing as unknown as Window)).toBe(true)
  })
})

describe('MCP_OAUTH_SCOPE_GRANT_KEYS', () => {
  it('describes every scope the backend can grant', () => {
    // 与 backend/app/api/routes_auth.py 的 MCP_TOKEN_SCOPES 一致
    expect(Object.keys(MCP_OAUTH_SCOPE_GRANT_KEYS).sort()).toEqual(['projects:favorites:read', 'tracking:read'])
  })
})
