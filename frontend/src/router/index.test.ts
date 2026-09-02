import { describe, expect, it } from 'vitest'
import type { RouteLocationNormalized } from 'vue-router'
import router from './index'
import { getRoutePolicyDecision } from '@/features/navigation/routePolicy'
import { NAV_ITEMS } from '@/features/navigation/navigationModel'

// 契约：微信公众号页与对话聊天页仅对管理员开放 —— 导航入口隐藏 + 路由守卫拦截
describe('modal-only login route contract', () => {
  it('/login is unmatched because login is rendered as a modal', () => {
    const resolved = router.resolve('/login')

    expect(router.getRoutes().some((route) => route.path === '/login')).toBe(false)
    expect(resolved.matched).toHaveLength(0)
  })
})

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
    expect(getRoutePolicyDecision(resolved as RouteLocationNormalized, { status: 'anonymous', isAdmin: false })).toBeNull()
  })
})

describe('projects website collection deep link contract', () => {
  it('keeps the website collection on the shared projects route', () => {
    const resolved = router.resolve('/projects?source=website')
    expect(resolved.name).toBe('github-projects')
    expect(resolved.path).toBe('/projects')
    expect(resolved.query).toEqual({ source: 'website' })
    expect(getRoutePolicyDecision(resolved as RouteLocationNormalized, { status: 'anonymous', isAdmin: false })).toBeNull()
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

// 契约：会员结算页要求登录 —— 匿名深链触发登录弹窗，
// 保留完整路径用于登录后返回（会员页本身公开获客）。
describe('membership checkout auth contract', () => {
  it('checkout route requires auth', () => {
    const record = router.getRoutes().find((r) => r.path === '/membership/checkout')
    expect(record, 'missing route /membership/checkout').toBeDefined()
    expect(record?.name).toBe('membership-checkout')
    expect(record?.meta.requiresAuth).toBe(true)
  })

  it('anonymous deep link to checkout preserves the full redirect', () => {
    const resolved = router.resolve('/membership/checkout?plan=yearly')
    expect(getRoutePolicyDecision(resolved as RouteLocationNormalized, { status: 'anonymous', isAdmin: false }))
      .toEqual({ kind: 'login', target: '/membership/checkout?plan=yearly' })
  })

  it('authenticated visitor is permitted to open checkout', () => {
    const resolved = router.resolve('/membership/checkout')
    expect(getRoutePolicyDecision(resolved as RouteLocationNormalized, { status: 'authenticated', isAdmin: false })).toBeNull()
  })
})

// 契约：/mcp 对游客开放（Red 权限变更锚点）—— 页面是获客入口，路由不带
// requiresAuth/requiresAdmin，匿名深链不再触发登录重定向；Token 签发与
// 收藏授权改由页面内向导在「下一步」处门禁，后端 Token API 仍以 401 兜底。
describe('mcp guest access contract', () => {
  it('mcp route carries no auth requirement', () => {
    const record = router.getRoutes().find((r) => r.path === '/mcp')
    expect(record, 'missing route /mcp').toBeDefined()
    expect(record?.name).toBe('mcp-connect')
    expect(record?.meta.requiresAuth).toBeUndefined()
    expect(record?.meta.requiresAdmin).toBeUndefined()
  })

  it('mcp nav item is visible to guests', () => {
    const item = NAV_ITEMS.find((n) => n.to === '/mcp')
    expect(item, 'missing nav item /mcp').toBeDefined()
    expect(item?.requiresAuth).toBeUndefined()
  })

  it.each(['anonymous', 'initializing', 'degraded'] as const)('%s visitor is not redirected away from mcp', (status) => {
    const resolved = router.resolve('/mcp')
    expect(getRoutePolicyDecision(resolved as RouteLocationNormalized, { status, isAdmin: false })).toBeNull()
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
    expect(getRoutePolicyDecision(resolved as RouteLocationNormalized, { status: 'anonymous', isAdmin: false }))
      .toEqual({ kind: 'login', target: '/subscriptions' })
    expect(getRoutePolicyDecision(resolved as RouteLocationNormalized, { status: 'authenticated', isAdmin: false })).toBeNull()
  })
})

// 契约：/dsh 对游客开放（Red 权限变更锚点）—— 路由不带 requiresAuth，
// 匿名深链不再触发登录重定向；DSH 专用 Token 的签发改由向导在「下一步」
// 处要求登录后进行，后端 ensure/rotate 接口仍以 401 兜底。
describe('dsh guest access contract', () => {
  it('dsh route carries no auth requirement', () => {
    const record = router.getRoutes().find((r) => r.path === '/dsh')
    expect(record, 'missing route /dsh').toBeDefined()
    expect(record?.name).toBe('dsh')
    expect(record?.meta.requiresAuth).toBeUndefined()
    expect(record?.meta.requiresAdmin).toBeUndefined()
  })

  it.each(['anonymous', 'initializing', 'degraded'] as const)('%s visitor is not redirected away from dsh', (status) => {
    const resolved = router.resolve('/dsh')
    expect(getRoutePolicyDecision(resolved as RouteLocationNormalized, { status, isAdmin: false })).toBeNull()
  })
})
