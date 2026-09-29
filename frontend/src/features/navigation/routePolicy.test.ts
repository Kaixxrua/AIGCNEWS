import { describe, expect, it } from 'vitest'
import type { RouteLocationNormalized } from 'vue-router'
import {
  getFeatureGateRedirect,
  getRoutePolicyDecision,
  getSitePageGateRedirect,
  type FeatureGateState,
  type RouteAuthState,
  type SitePageGateState,
} from './routePolicy'

const route = (meta: RouteLocationNormalized['meta'], fullPath = '/private') => ({
  meta,
  fullPath,
}) as RouteLocationNormalized

const auth = (
  status: RouteAuthState['status'],
  isAdmin = false,
): RouteAuthState => ({ status, isAdmin })

describe('getRoutePolicyDecision', () => {
  it('requests the login modal for confirmed anonymous users on auth and admin routes', () => {
    expect(getRoutePolicyDecision(route({ requiresAuth: true }, '/papers/1/read'), auth('anonymous')))
      .toEqual({ kind: 'login', target: '/papers/1/read' })
    expect(getRoutePolicyDecision(route({ requiresAdmin: true }, '/monitor'), auth('anonymous')))
      .toEqual({ kind: 'login', target: '/monitor' })
  })

  it.each(['initializing', 'degraded'] as const)(
    'blocks protected routes while auth is %s',
    (status) => {
      expect(getRoutePolicyDecision(route({ requiresAuth: true }), auth(status)))
        .toEqual({ kind: 'block' })
      expect(getRoutePolicyDecision(route({ requiresAdmin: true }), auth(status)))
        .toEqual({ kind: 'block' })
    },
  )

  it('redirects a confirmed non-admin but permits a confirmed admin', () => {
    expect(getRoutePolicyDecision(route({ requiresAdmin: true }), auth('authenticated')))
      .toEqual({ kind: 'redirect', to: { path: '/' } })
    expect(getRoutePolicyDecision(route({ requiresAdmin: true }), auth('authenticated', true)))
      .toBeNull()
  })

  it('redirects guest-only routes only for confirmed authentication', () => {
    expect(getRoutePolicyDecision(route({ guestOnly: true }), auth('authenticated')))
      .toEqual({ kind: 'redirect', to: { path: '/' } })
    expect(getRoutePolicyDecision(route({ guestOnly: true }), auth('initializing'))).toBeNull()
    expect(getRoutePolicyDecision(route({ guestOnly: true }), auth('degraded'))).toBeNull()
    expect(getRoutePolicyDecision(route({ guestOnly: true }), auth('anonymous'))).toBeNull()
  })

  it('preserves query and hash as the modal return target for protected deep links', () => {
    expect(getRoutePolicyDecision(
      route({ requiresAuth: true }, '/membership/checkout?plan=yearly#payment'),
      auth('anonymous'),
    )).toEqual({ kind: 'login', target: '/membership/checkout?plan=yearly#payment' })
  })

  it('anonymous requiresAdmin requests login instead of the non-admin home redirect', () => {
    expect(getRoutePolicyDecision(route({ requiresAdmin: true }, '/monitor'), auth('anonymous')))
      .toEqual({ kind: 'login', target: '/monitor' })
    expect(getRoutePolicyDecision(route({ requiresAdmin: true }, '/monitor'), auth('authenticated')))
      .toEqual({ kind: 'redirect', to: { path: '/' } })
  })
})

describe('getFeatureGateRedirect', () => {
  const features = (overrides: Partial<FeatureGateState> = {}): FeatureGateState => ({
    xSource: true,
    ...overrides,
  })

  it('redirects feature-gated routes home when the source is disabled', () => {
    expect(getFeatureGateRedirect(route({ feature: 'xSource' }), features({ xSource: false })))
      .toEqual({ path: '/' })
  })

  it('permits enabled feature routes and routes without feature meta', () => {
    expect(getFeatureGateRedirect(route({ feature: 'xSource' }), features())).toBeNull()
    expect(getFeatureGateRedirect(route({}), features({ xSource: false })))
      .toBeNull()
  })
})

describe('getSitePageGateRedirect', () => {
  const sitePages = (contactPage: boolean): SitePageGateState => ({ contactPage })

  it('redirects site-page routes home when the page is not enabled', () => {
    expect(getSitePageGateRedirect(route({ sitePage: 'contactPage' }), sitePages(false)))
      .toEqual({ path: '/' })
  })

  it('permits enabled site-page routes and routes without sitePage meta', () => {
    expect(getSitePageGateRedirect(route({ sitePage: 'contactPage' }), sitePages(true))).toBeNull()
    expect(getSitePageGateRedirect(route({}), sitePages(false))).toBeNull()
  })
})
