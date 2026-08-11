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
