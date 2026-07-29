import { describe, expect, it } from 'vitest'
import type { RouteLocationNormalized } from 'vue-router'
import { getRoutePolicyRedirect, type RouteAuthState } from './routePolicy'

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
