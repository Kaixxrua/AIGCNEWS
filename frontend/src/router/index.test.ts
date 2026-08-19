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

// 契约：联系合作页是公开免鉴权页面，但挂 sitePage 门控 —— 管理员未启用时守卫重定向首页。
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

// 契约：订阅管理页要求登录；匿名深链走 /login 全屏回退，应用内交互走登录弹框。
describe('subscriptions auth contract', () => {
  it('anonymous deep link to subscriptions redirects to /login with redirect', () => {
    const resolved = router.resolve('/subscriptions')
    expect(getRoutePolicyRedirect(resolved as RouteLocationNormalized, { status: 'anonymous', isAdmin: false }))
      .toEqual({ path: '/login', query: { redirect: '/subscriptions' } })
  })
})
