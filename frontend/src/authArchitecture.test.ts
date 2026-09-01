import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import router from '@/router'
import { getSafeInternalRedirect } from '@/features/auth/authViewModel'

const probe = vi.hoisted(() => ({ order: [] as string[] }))

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
    ensureInitialized: () => {
      probe.order.push('auth-restored')
      return Promise.resolve()
    },
  }),
}))

vi.mock('@/services/visit/visitBeacon', () => ({ sendVisitBeacon: vi.fn() }))
vi.mock('@/pwa/registerPwa', () => ({ registerPwa: vi.fn() }))
vi.mock('@/pwa/installPrompt', () => ({ initializeInstallPrompt: vi.fn() }))
vi.mock('@/components/pwa/PwaInstallGuide.vue', () => ({ default: { template: '<div />' } }))

vi.mock('@/views/LayoutView.vue', () => ({
  default: { name: 'LayoutView', template: '<div><router-view /></div>' },
}))

describe('authentication architecture behavior', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    probe.order.length = 0
  })

  it('mounts the application before ensuring asynchronous auth initialization', async () => {
    vi.resetModules()
    document.body.innerHTML = '<div id="app"></div>'

    await import('./main')
    await vi.waitFor(() => expect(probe.order).toContain('app-mounted'))
    await vi.waitFor(() => expect(probe.order).toContain('auth-restored'))

    expect(probe.order).toEqual(['app-mounted', 'auth-restored'])
  })

  it('has no login page while register and forgot-password remain guest-only', () => {
    const metaOf = (path: string) => router.getRoutes().find((route) => route.path === path)?.meta ?? {}

    expect(router.getRoutes().some((route) => route.path === '/login')).toBe(false)
    expect(router.resolve('/login').matched).toHaveLength(0)
    expect(metaOf('/register')).toMatchObject({ guestOnly: true })
    expect(metaOf('/forgot-password')).toMatchObject({ guestOnly: true })
  })

  it('rejects external and protocol-relative redirect targets', () => {
    expect(getSafeInternalRedirect('https://evil.example/phish')).toBe('/')
    expect(getSafeInternalRedirect('//evil.example/phish')).toBe('/')
    expect(getSafeInternalRedirect(undefined)).toBe('/')
    expect(getSafeInternalRedirect('/projects')).toBe('/projects')
  })
})
