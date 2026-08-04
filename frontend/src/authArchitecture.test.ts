import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import LoginView from '@/views/LoginView.vue'
import router from '@/router'
import { getSafeInternalRedirect } from '@/features/auth/authViewModel'

const probe = vi.hoisted(() => ({ order: [] as string[], login: null as null | ReturnType<typeof vi.fn> }))

vi.mock('@/App.vue', async () => {
  const { h, onMounted } = await import('vue')
  return {
    default: {
      name: 'App',
      setup() {
        onMounted(() => probe.order.push('app-mounted'))
        return () => h('div')
      },
    },
  }
})

vi.mock('@/stores/authStore', () => ({
  useAuthStore: () => ({
    login: probe.login ?? vi.fn().mockResolvedValue(undefined),
    initFromStorage: () => {
      probe.order.push('auth-restored')
      return Promise.resolve()
    },
  }),
}))

vi.mock('@/views/LayoutView.vue', () => ({
  default: { name: 'LayoutView', template: '<div><router-view /></div>' },
}))

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {},
  missingWarn: false,
  fallbackWarn: false,
})

const mountLogin = async (initialPath: string) => {
  const testRouter = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/login', component: LoginView },
      { path: '/', component: { template: '<div />' } },
      { path: '/projects', component: { template: '<div />' } },
    ],
  })
  await testRouter.push(initialPath)
  await testRouter.isReady()
  const wrapper = mount(LoginView, {
    global: { plugins: [testRouter, i18n], stubs: { RouterLink: true } },
  })
  return { testRouter, wrapper }
}

const submitLogin = async (wrapper: Awaited<ReturnType<typeof mountLogin>>['wrapper']) => {
  await wrapper.find('input[type="email"]').setValue('user@example.com')
  await wrapper.find('input[type="password"]').setValue('secret-1')
  await wrapper.find('button.btn-primary').trigger('click')
  await flushPromises()
}

describe('authentication architecture behavior', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    probe.order.length = 0
    probe.login = vi.fn().mockResolvedValue(undefined)
  })

  it('mounts the application before starting asynchronous auth restore', async () => {
    vi.resetModules()
    document.body.innerHTML = '<div id="app"></div>'

    await import('./main')
    await vi.waitFor(() => expect(probe.order).toContain('auth-restored'))

    expect(probe.order).toEqual(['app-mounted', 'auth-restored'])
  })

  it('keeps login always enterable while register and forgot-password remain guest-only', () => {
    const metaOf = (path: string) => router.getRoutes().find((route) => route.path === path)?.meta ?? {}

    expect(metaOf('/login')).not.toHaveProperty('guestOnly')
    expect(metaOf('/register')).toMatchObject({ guestOnly: true })
    expect(metaOf('/forgot-password')).toMatchObject({ guestOnly: true })
  })

  it('rejects external and protocol-relative redirect targets', () => {
    expect(getSafeInternalRedirect('https://evil.example/phish')).toBe('/')
    expect(getSafeInternalRedirect('//evil.example/phish')).toBe('/')
    expect(getSafeInternalRedirect(undefined)).toBe('/')
    expect(getSafeInternalRedirect('/projects')).toBe('/projects')
  })

  it('redirects to the safe internal target after successful login', async () => {
    const { testRouter, wrapper } = await mountLogin('/login?redirect=/projects')
    const pushSpy = vi.spyOn(testRouter, 'push')

    await submitLogin(wrapper)

    expect(probe.login).toHaveBeenCalledWith('user@example.com', 'secret-1')
    expect(pushSpy).toHaveBeenCalledWith('/projects')
  })

  it('falls back to home when the login redirect points off-site', async () => {
    const { testRouter, wrapper } = await mountLogin('/login?redirect=https://evil.example/phish')
    const pushSpy = vi.spyOn(testRouter, 'push')

    await submitLogin(wrapper)

    expect(pushSpy).toHaveBeenCalledWith('/')
  })
})
