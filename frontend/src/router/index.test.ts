import { describe, expect, it } from 'vitest'
import type { RouteLocationNormalized } from 'vue-router'
import router from './index'
import { getRoutePolicyRedirect } from '@/features/navigation/routePolicy'
import { NAV_ITEMS } from '@/features/navigation/navigationModel'

// 契约：微信公众号页与对话聊天页仅对管理员开放 —— 导航入口隐藏 + 路由守卫拦截
describe('admin-only pages contract', () => {
  it.each(['/chat', '/wechat'])('route %s requires admin', (path) => {
    const record = router.getRoutes().find((r) => r.path === path)
    expect(record, `missing route ${path}`).toBeDefined()
    expect(record?.meta.requiresAdmin).toBe(true)
  })

  it.each(['/chat', '/wechat'])('nav item %s is admin-only', (to) => {
    const item = NAV_ITEMS.find((n) => n.to === to)
    expect(item, `missing nav item ${to}`).toBeDefined()
    expect(item?.requiresAdmin).toBe(true)
  })
})

// 契约：论文阅读页对游客只读开放（Red 权限变更锚点）—— 路由不带 requiresAuth/requiresAdmin，
// 匿名访问不产生登录重定向；对话降级由 PaperReadView 的 conversationEnabled 控制。
describe('paper read guest access contract', () => {
  it('paper-read route carries no auth requirement', () => {
    const record = router.getRoutes().find((r) => r.path === '/papers/:id/read')
    expect(record, 'missing route /papers/:id/read').toBeDefined()
    expect(record?.meta.requiresAuth).toBeUndefined()
    expect(record?.meta.requiresAdmin).toBeUndefined()
  })

  it('anonymous visitor is not redirected away from a paper read page', () => {
    const resolved = router.resolve('/papers/abc123/read')
    expect(getRoutePolicyRedirect(resolved as RouteLocationNormalized, { status: 'anonymous', isAdmin: false })).toBeNull()
  })
})

describe('projects website collection deep link contract', () => {
  it('keeps the website collection on the shared projects route', () => {
    const resolved = router.resolve('/projects?source=website')
    expect(resolved.name).toBe('github-projects')
    expect(resolved.path).toBe('/projects')
    expect(resolved.query).toEqual({ source: 'website' })
    expect(getRoutePolicyRedirect(resolved as RouteLocationNormalized, { status: 'anonymous', isAdmin: false })).toBeNull()
  })
})

describe('contact site page contract', () => {
  it('contact route is public and carries the sitePage gate meta', () => {
    const record = router.getRoutes().find((r) => r.path === '/contact')
    expect(record, 'missing route /contact').toBeDefined()
    expect(record?.meta.sitePage).toBe('contactPage')
    expect(record?.meta.requiresAuth).toBeUndefined()
    expect(record?.meta.requiresAdmin).toBeUndefined()
  })
})

// 契约：会员结算页要求登录 —— 匿名深链守卫仍重定向 /login?redirect=，
// 保留 query/hash 用于支付计划参数（会员页本身公开获客）。
describe('membership checkout auth contract', () => {
  it('checkout route requires auth', () => {
    const record = router.getRoutes().find((r) => r.path === '/membership/checkout')
    expect(record, 'missing route /membership/checkout').toBeDefined()
    expect(record?.name).toBe('membership-checkout')
    expect(record?.meta.requiresAuth).toBe(true)
  })

  it('anonymous deep link to checkout preserves the full redirect', () => {
    const resolved = router.resolve('/membership/checkout?plan=yearly')
    expect(getRoutePolicyRedirect(resolved as RouteLocationNormalized, { status: 'anonymous', isAdmin: false }))
      .toEqual({ path: '/login', query: { redirect: '/membership/checkout?plan=yearly' } })
  })

  it('authenticated visitor is permitted to open checkout', () => {
    const resolved = router.resolve('/membership/checkout')
    expect(getRoutePolicyRedirect(resolved as RouteLocationNormalized, { status: 'authenticated', isAdmin: false })).toBeNull()
  })
})

// 契约：/dsh 要求登录（Red 权限变更锚点）—— 向导自动签发账号绑定的 DSH 专用
// MCP Token，不再有游客路径；匿名深链重定向 /login?redirect=/dsh，
// initializing/degraded 不误判为游客（由 getRoutePolicyRedirect 既有语义保证）。
describe('mcp auth contract', () => {
  it('mcp route requires auth', () => {
    const record = router.getRoutes().find((r) => r.path === '/mcp')
    expect(record, 'missing route /mcp').toBeDefined()
    expect(record?.name).toBe('mcp-connect')
    expect(record?.meta.requiresAuth).toBe(true)
  })

  it('anonymous deep link to mcp redirects to /login with redirect', () => {
    const resolved = router.resolve('/mcp')
    expect(getRoutePolicyRedirect(resolved as RouteLocationNormalized, { status: 'anonymous', isAdmin: false }))
      .toEqual({ path: '/login', query: { redirect: '/mcp' } })
  })

  it('authenticated visitor is permitted to open mcp', () => {
    const resolved = router.resolve('/mcp')
    expect(getRoutePolicyRedirect(resolved as RouteLocationNormalized, { status: 'authenticated', isAdmin: false })).toBeNull()
  })

  it.each(['initializing', 'degraded'] as const)('%s visitor is not redirected away from mcp', (status) => {
    const resolved = router.resolve('/mcp')
    expect(getRoutePolicyRedirect(resolved as RouteLocationNormalized, { status, isAdmin: false })).toBeNull()
  })
})

describe('subscriptions management compatibility contract', () => {
  it('keeps the authenticated deep-link route without a Dock entry', () => {
    const record = router.getRoutes().find((r) => r.path === '/subscriptions')
    expect(record, 'missing route /subscriptions').toBeDefined()
    expect(record?.name).toBe('subscriptions')
    expect(record?.meta.requiresAuth).toBe(true)
    expect(NAV_ITEMS.some((item) => item.to === '/subscriptions')).toBe(false)
  })

  it('redirects anonymous visitors while allowing authenticated visitors', () => {
    const resolved = router.resolve('/subscriptions')
    expect(getRoutePolicyRedirect(resolved as RouteLocationNormalized, { status: 'anonymous', isAdmin: false }))
      .toEqual({ path: '/login', query: { redirect: '/subscriptions' } })
    expect(getRoutePolicyRedirect(resolved as RouteLocationNormalized, { status: 'authenticated', isAdmin: false })).toBeNull()
  })
})

describe('dsh auth contract', () => {
  it('dsh route requires auth', () => {
    const record = router.getRoutes().find((r) => r.path === '/dsh')
    expect(record, 'missing route /dsh').toBeDefined()
    expect(record?.name).toBe('dsh')
    expect(record?.meta.requiresAuth).toBe(true)
  })

  it('anonymous deep link to dsh redirects to /login with redirect', () => {
    const resolved = router.resolve('/dsh')
    expect(getRoutePolicyRedirect(resolved as RouteLocationNormalized, { status: 'anonymous', isAdmin: false }))
      .toEqual({ path: '/login', query: { redirect: '/dsh' } })
  })

  it('authenticated visitor is permitted to open dsh', () => {
    const resolved = router.resolve('/dsh')
    expect(getRoutePolicyRedirect(resolved as RouteLocationNormalized, { status: 'authenticated', isAdmin: false })).toBeNull()
  })

  it.each(['initializing', 'degraded'] as const)('%s visitor is not redirected away from dsh', (status) => {
    const resolved = router.resolve('/dsh')
    expect(getRoutePolicyRedirect(resolved as RouteLocationNormalized, { status, isAdmin: false })).toBeNull()
  })
})
