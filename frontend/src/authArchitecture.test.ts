import { describe, expect, it } from 'vitest'
import mainSource from './main.ts?raw'
import routerSource from './router/index.ts?raw'
import loginSource from './views/LoginView.vue?raw'

describe('authentication architecture contracts', () => {
  it('mounts the application before starting asynchronous auth restore', () => {
    expect(mainSource.indexOf("app.mount('#app')")).toBeGreaterThanOrEqual(0)
    expect(mainSource.indexOf("app.mount('#app')")).toBeLessThan(mainSource.indexOf("import('./stores/authStore')"))
  })

  it('keeps login always enterable while register and forgot-password remain guest-only', () => {
    const loginRoute = routerSource.slice(routerSource.indexOf("path: '/login'"), routerSource.indexOf("path: '/register'"))
    const registerRoute = routerSource.slice(routerSource.indexOf("path: '/register'"), routerSource.indexOf("path: '/forgot-password'"))
    const forgotRoute = routerSource.slice(routerSource.indexOf("path: '/forgot-password'"), routerSource.indexOf('// ── 主 Layout'))

    expect(loginRoute).not.toContain('guestOnly')
    expect(registerRoute).toContain('guestOnly: true')
    expect(forgotRoute).toContain('guestOnly: true')
  })

  it('uses the safe redirect after successful login', () => {
    expect(loginSource).toContain('getSafeInternalRedirect(route.query.redirect)')
    expect(loginSource).toContain('await router.push(redirect.value)')
  })
})
