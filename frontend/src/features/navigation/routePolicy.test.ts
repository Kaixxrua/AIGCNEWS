import { describe, expect, it } from 'vitest'
import type { RouteLocationNormalized } from 'vue-router'
import {
  getFeatureGateRedirect,
  getRoutePolicyRedirect,
  type FeatureGateState,
  type RouteAuthState,
} from './routePolicy'

const route = (meta: RouteLocationNormalized['meta'], fullPath = '/private') => ({
  meta,
  fullPath,
}) as RouteLocationNormalized

const auth = (
  status: RouteAuthState['status'],
  isAdmin = false,
): RouteAuthState => ({ status, isAdmin })

describe('getRoutePolicyRedirect', () => {
  it('redirects confirmed anonymous users from auth and admin routes', () => {
    expect(getRoutePolicyRedirect(route({ requiresAuth: true }, '/papers/1/read'), auth('anonymous')))
      .toEqual({ path: '/login', query: { redirect: '/papers/1/read' } })
    expect(getRoutePolicyRedirect(route({ requiresAdmin: true }, '/monitor'), auth('anonymous')))
      .toEqual({ path: '/login', query: { redirect: '/monitor' } })
  })

  it.each(['initializing', 'degraded'] as const)(
    'does not prematurely redirect protected routes while %s',
    (status) => {
      expect(getRoutePolicyRedirect(route({ requiresAuth: true }), auth(status))).toBeNull()
      expect(getRoutePolicyRedirect(route({ requiresAdmin: true }), auth(status))).toBeNull()
    },
  )

  it('redirects a confirmed non-admin but permits a confirmed admin', () => {
    expect(getRoutePolicyRedirect(route({ requiresAdmin: true }), auth('authenticated')))
      .toEqual({ path: '/' })
    expect(getRoutePolicyRedirect(route({ requiresAdmin: true }), auth('authenticated', true)))
      .toBeNull()
  })

  it('redirects guest-only routes only for confirmed authentication', () => {
    expect(getRoutePolicyRedirect(route({ guestOnly: true }), auth('authenticated')))
      .toEqual({ path: '/' })
    expect(getRoutePolicyRedirect(route({ guestOnly: true }), auth('initializing'))).toBeNull()
    expect(getRoutePolicyRedirect(route({ guestOnly: true }), auth('degraded'))).toBeNull()
    expect(getRoutePolicyRedirect(route({ guestOnly: true }), auth('anonymous'))).toBeNull()
  })
})

describe('getFeatureGateRedirect', () => {
  const features = (overrides: Partial<FeatureGateState> = {}): FeatureGateState => ({
    xSource: true,
    wechatSource: true,
    ...overrides,
  })

  it('redirects feature-gated routes home when the source is disabled', () => {
    expect(getFeatureGateRedirect(route({ feature: 'xSource' }), features({ xSource: false })))
      .toEqual({ path: '/' })
    expect(getFeatureGateRedirect(route({ feature: 'wechatSource' }), features({ wechatSource: false })))
      .toEqual({ path: '/' })
  })

  it('permits enabled feature routes and routes without feature meta', () => {
    expect(getFeatureGateRedirect(route({ feature: 'xSource' }), features())).toBeNull()
    expect(getFeatureGateRedirect(route({}), features({ xSource: false, wechatSource: false })))
      .toBeNull()
  })
})
