import { afterEach, describe, expect, it, vi } from 'vitest'
import type { RouteLocationNormalized } from 'vue-router'
import {
  getFeatureGateRedirect,
  getRoutePolicyDecision,
  getSitePageGateRedirect,
  getWebsiteCollectionRedirect,
  resolveWebsiteCollectionRedirect,
  WEBSITE_PICKS_WAIT_MS,
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

describe('getWebsiteCollectionRedirect', () => {
  const personal = { name: 'github-projects', query: { source: 'website' } } as Pick<RouteLocationNormalized, 'name' | 'query'>

  it.each(['anonymous', 'degraded'] as const)('sends %s visitors to the editor picks while there are some', (status) => {
    expect(getWebsiteCollectionRedirect(personal, { status }, 29)).toEqual({ path: '/websites' })
  })

  it('keeps visitors on the collection while the picks are empty or unknown', () => {
    expect(getWebsiteCollectionRedirect(personal, { status: 'anonymous' }, 0)).toBeNull()
    expect(getWebsiteCollectionRedirect(personal, { status: 'anonymous' }, null)).toBeNull()
  })

  it.each(['authenticated', 'initializing'] as const)('never moves %s users off their collection', (status) => {
    expect(getWebsiteCollectionRedirect(personal, { status }, 29)).toBeNull()
  })

  it('leaves the other project views alone', () => {
    const others = [
      { name: 'github-projects', query: {} },
      { name: 'github-projects', query: { source: 'favorites' } },
      { name: 'recommended-websites', query: { source: 'website' } },
    ] as Pick<RouteLocationNormalized, 'name' | 'query'>[]
    for (const to of others) expect(getWebsiteCollectionRedirect(to, { status: 'anonymous' }, 29)).toBeNull()
  })
})

describe('resolveWebsiteCollectionRedirect', () => {
  const personal = { name: 'github-projects', query: { source: 'website' } } as Pick<RouteLocationNormalized, 'name' | 'query'>
  const visitor = (status: RouteAuthState['status'], settlesAs: RouteAuthState['status'] = status) => {
    const state = { status, ensureInitialized: vi.fn(async () => { state.status = settlesAs }) }
    return state
  }
  const picks = (count: number) => vi.fn(async () => Array.from({ length: count }, (_, id) => ({ id })))

  afterEach(() => { vi.useRealTimers() })

  it('waits for the sign-in check, then sends visitors to the editor picks', async () => {
    const auth = visitor('initializing', 'anonymous')
    const load = picks(29)

    expect(await resolveWebsiteCollectionRedirect(personal, auth, load)).toEqual({ path: '/websites' })
    expect(auth.ensureInitialized).toHaveBeenCalledOnce()
    expect(load).toHaveBeenCalledOnce()
  })

  it('never asks for the picks for signed-in users', async () => {
    const load = picks(29)

    expect(await resolveWebsiteCollectionRedirect(personal, visitor('initializing', 'authenticated'), load)).toBeNull()
    expect(await resolveWebsiteCollectionRedirect(personal, visitor('authenticated'), load)).toBeNull()
    expect(load).not.toHaveBeenCalled()
  })

  it('keeps visitors on the collection when the picks are empty or cannot be fetched', async () => {
    expect(await resolveWebsiteCollectionRedirect(personal, visitor('anonymous'), picks(0))).toBeNull()
    expect(await resolveWebsiteCollectionRedirect(personal, visitor('degraded'), async () => null)).toBeNull()
    expect(await resolveWebsiteCollectionRedirect(personal, visitor('anonymous'), () => Promise.reject(new Error('chunk')))).toBeNull()
  })

  it('stops waiting for slow picks after the time limit and leaves no timer behind', async () => {
    vi.useFakeTimers()
    let settled = false
    const pending = resolveWebsiteCollectionRedirect(personal, visitor('anonymous'), () => new Promise(() => {}))
    void pending.then(() => { settled = true })

    await vi.advanceTimersByTimeAsync(WEBSITE_PICKS_WAIT_MS - 1)
    expect(settled).toBe(false)
    await vi.advanceTimersByTimeAsync(1)
    expect(await pending).toBeNull()

    await resolveWebsiteCollectionRedirect(personal, visitor('anonymous'), picks(3))
    expect(vi.getTimerCount()).toBe(0)
  })

  it('does nothing on the other pages', async () => {
    const auth = visitor('initializing', 'anonymous')
    const load = picks(29)
    const projects = { name: 'github-projects', query: {} } as Pick<RouteLocationNormalized, 'name' | 'query'>

    expect(await resolveWebsiteCollectionRedirect(projects, auth, load)).toBeNull()
    expect(auth.ensureInitialized).not.toHaveBeenCalled()
    expect(load).not.toHaveBeenCalled()
  })
})
