import { describe, expect, it } from 'vitest'
import router from './index'
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
