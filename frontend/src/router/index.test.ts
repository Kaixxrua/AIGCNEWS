/// <reference types="node" />
import { readdirSync } from 'node:fs'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { RouteLocationNormalized } from 'vue-router'
import router from './index'
import { getRoutePolicyDecision } from '@/features/navigation/routePolicy'
import { NAV_ITEMS } from '@/features/navigation/navigationModel'

const { requestPasswordReset } = vi.hoisted(() => ({ requestPasswordReset: vi.fn() }))
vi.mock('@/composables/useLoginPrompt', () => ({
  useLoginPrompt: () => ({ requestPasswordReset, requestLogin: vi.fn(), rememberLoginRedirect: vi.fn() }),
}))
vi.mock('@/views/DashboardView.vue', () => ({ default: { template: '<div />' } }))

describe('modal-only login route contract', () => {
  it('/login has no page of its own because login is rendered as a modal', () => {
    const resolved = router.resolve('/login')

    expect(router.getRoutes().some((route) => route.path === '/login')).toBe(false)
    expect(resolved.name).toBe('not-found')
  })
})

// 契约：未知路径显示「页面不存在」，地址原样保留、不再跳回首页；兜底挂在 Layout 里，报头和 dock
// 照常可用。/forgot-password 仍先由全局守卫打开重置密码弹框，不被兜底路由吞掉
describe('unknown path fallback contract', () => {
  afterEach(async () => {
    requestPasswordReset.mockClear()
    await router.replace('/')
  })

  it.each(['/no-such-page', '/papers', '/a/b/c?x=1'])('navigating to %s shows the not-found page in place', async (path) => {
    await router.push(path)
    expect(router.currentRoute.value.name).toBe('not-found')
    expect(router.currentRoute.value.fullPath).toBe(path)
    expect(router.currentRoute.value.matched.map((record) => record.path)).toEqual(['/', '/:pathMatch(.*)*'])
  })

  it('keeps known pages reachable', async () => {
    await router.push('/websites')
    expect(router.currentRoute.value.name).toBe('recommended-websites')
  })

  it('still opens the password-reset prompt for /forgot-password', async () => {
    await router.push('/forgot-password?redirect=/projects')
    expect(requestPasswordReset).toHaveBeenCalledWith('/projects')
    expect(router.currentRoute.value.fullPath).toBe('/')
  })
})

// 契约：微信公众号页与对话聊天页已整体移除 —— 路由不再匹配、导航不再出现，旧书签打开显示「页面不存在」
describe('removed pages contract', () => {
  afterEach(async () => {
    await router.replace('/')
  })

  it.each(['/wechat', '/chat'])('route %s is gone and shows the not-found page', async (path) => {
    expect(router.resolve(path).name).toBe('not-found')
    expect(NAV_ITEMS.some((n) => n.to === path)).toBe(false)
    await router.push(path)
    expect(router.currentRoute.value.name).toBe('not-found')
    expect(router.currentRoute.value.fullPath).toBe(path)
  })
})

// 契约：边缘按 public/__routes 的首段清单判断地址有没有页面，清单外的地址回 404 状态码（正文仍是
// index.html，由上面的兜底页显示「页面不存在」）。清单必须和路由表的顶层首段一一对应：漏一个，那个
// 栏目在搜索引擎眼里就成了 404；多一个，下线的地址就还是 200。/forgot-password 没有路由记录、由全局
// 守卫处理，单列在 GUARD_ENTRIES。
describe('edge route allowlist contract', () => {
  const GUARD_ENTRIES = ['forgot-password']
  const allowlist = () => readdirSync(`${process.cwd()}/public/__routes`).sort()

  it('lists exactly the first path segments the router serves', () => {
    const segments = new Set(GUARD_ENTRIES)
    for (const record of router.getRoutes()) {
      const first = record.path.split('/')[1] ?? ''
      if (first === '' || first.startsWith(':pathMatch')) continue
      // 首段是动态参数的路由（如 /:slug）会让任何首段都可能有页面，清单就失效了，加这种路由要先改边缘规则
      expect(first, `top-level dynamic segment in ${record.path}`).not.toMatch(/^:/)
      segments.add(first)
    }
    expect(allowlist()).toEqual([...segments].sort())
  })

  it.each(['login', 'wechat', 'chat', 'news', 'no-such-page'])('does not list %s', (segment) => {
    expect(allowlist()).not.toContain(segment)
  })
})

// 契约：监控后台仅对管理员开放 —— 导航入口隐藏 + 路由守卫拦截
describe('admin-only pages contract', () => {
  it.each(['/monitor'])('route %s requires admin', (path) => {
    const record = router.getRoutes().find((r) => r.path === path)
    expect(record, `missing route ${path}`).toBeDefined()
    expect(record?.meta.requiresAdmin).toBe(true)
  })

  it.each(['/monitor'])('nav item %s is admin-only', (to) => {
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
  it('opens editor websites on a distinct public route without a project scope', () => {
    const resolved = router.resolve('/websites')
    expect(resolved.name).toBe('recommended-websites')
    expect(resolved.query).toEqual({})
    const projects = router.resolve('/projects')
    expect(resolved.matched[resolved.matched.length - 1]?.components?.default).not.toBe(projects.matched[projects.matched.length - 1]?.components?.default)
    expect(getRoutePolicyDecision(resolved as RouteLocationNormalized, { status: 'anonymous', isAdmin: false })).toBeNull()
  })
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
  it('keeps the authenticated route with a guest-visible Dock entry', () => {
    const record = router.getRoutes().find((r) => r.path === '/subscriptions')
    expect(record, 'missing route /subscriptions').toBeDefined()
    expect(record?.name).toBe('subscriptions')
    expect(record?.meta.requiresAuth).toBe(true)
    expect(NAV_ITEMS.some((item) => item.to === '/subscriptions')).toBe(true)
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
