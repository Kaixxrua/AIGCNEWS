import { afterEach, describe, expect, it, vi } from 'vitest'
import { createRouter, createWebHistory, type Router } from 'vue-router'
import mainSource from '../main.ts?raw'

// 只有一条兜底路由：这里只看首次导航之后地址栏里还剩什么。
const createAppRouter = () => createRouter({
  history: createWebHistory(),
  routes: [{ path: '/:path(.*)*', component: { render: () => null } }],
})

// app.use(router) 做的首次导航：按 history 创建时记下的地址 push。
const firstNavigation = (router: Router) => router.push(router.options.history.location)

describe('shared ?style= link and the router', () => {
  let router: Router | null = null

  afterEach(() => {
    router?.options.history.destroy()
    router = null
    window.history.replaceState(null, '', '/')
    vi.resetModules()
  })

  it('stays out of the address when it is read before the router is created', async () => {
    window.history.replaceState(null, '', '/papers?style=simple&q=rag')
    const { styleFromLink } = await import('./styleLink')
    router = createAppRouter()
    await firstNavigation(router)

    expect(styleFromLink).toBe('simple')
    expect(`${location.pathname}${location.search}`).toBe('/papers?q=rag')
    expect(router.currentRoute.value.query).toEqual({ q: 'rag' })
  })

  // 反过来，history 先建好，参数读得再早也会被首次导航写回地址：styleLink.ts 必须排在路由前面就是因为这个。
  it('comes back when the router is created first', async () => {
    window.history.replaceState(null, '', '/papers?style=simple&q=rag')
    router = createAppRouter()
    await import('./styleLink')
    await firstNavigation(router)

    expect(location.search).toBe('?style=simple&q=rag')
  })

  it('is read by the first import of main.ts and handed to installAppStyle', () => {
    expect(mainSource.match(/^import .+$/m)?.[0]).toBe("import { styleFromLink } from './theme/styleLink'")
    expect(mainSource).toContain('installAppStyle(styleFromLink)')
  })
})
