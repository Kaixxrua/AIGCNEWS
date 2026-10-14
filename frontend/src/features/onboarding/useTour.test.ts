import { defineComponent, nextTick, reactive, ref } from 'vue'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { i18n } from '@/i18n'
import { useTour } from './useTour'
import { MEMORY_KEY, claimGuest, readProgress, readTerminal, saveProgress, saveTerminal } from './persistence'
import { requestTour, tourActive, tourRequest } from './signals'
import { TOUR_STEPS, availableSteps, pageSteps } from './steps'

const api = vi.hoisted(() => ({ fetch: vi.fn(), update: vi.fn(), toast: vi.fn() }))
const auth = reactive({
  status: 'anonymous', userId: null as number | null, token: null as string | null,
  get isLoggedIn() { return this.status === 'authenticated' },
})
vi.mock('@/stores/authStore', () => ({ useAuthStore: () => auth }))
vi.mock('@/services/onboarding/onboardingApi', () => ({ fetchOnboarding: api.fetch, updateOnboarding: api.update }))
vi.mock('@/composables/useToast', () => ({ showToast: api.toast }))
vi.mock('@/composables/useFeatureFlags', async () => {
  const { ref } = await import('vue')
  return { useFeatureFlags: () => ({ featureFlags: ref({ xSource: true }), ensureFeatureFlags: async () => ({ xSource: true }) }) }
})
vi.mock('@/composables/useContactPageConfig', async () => {
  const { ref } = await import('vue')
  return { useContactPageConfig: () => ({ contactPageConfig: ref({ enabled: false }), ensureContactPageConfig: async () => ({ enabled: false }) }) }
})
let wrapper: VueWrapper | undefined
let tour: ReturnType<typeof useTour>
let router: Router
const blocked = ref(false)
const compact = ref(false)
async function setup(initial = '/report?date=2026-10-01#saved') {
  router = createRouter({
    history: createMemoryHistory(),
    routes: [...new Set([...TOUR_STEPS.map(step => step.route.split('?')[0]),
      '/subscriptions', '/monitor', '/membership/checkout', '/privacy', '/disclaimer', '/papers/:id/read',
    ])].map(path => ({
      path: path!, name: path!, component: { template: '<div />' },
      meta: { requiresAuth: path === '/subscriptions' || path === '/membership/checkout', requiresAdmin: path === '/monitor' },
    })),
  })
  await router.push(initial)
  await router.isReady()
  wrapper = mount(defineComponent({
    setup() { tour = useTour(blocked, compact); return () => null },
  }), { global: { plugins: [router, i18n] } })
  await flushPromises()
}
function login(id: number) { auth.userId = id; auth.token = `token-${id}`; auth.status = 'authenticated' }
beforeEach(() => {
  localStorage.clear(); sessionStorage.clear()
  auth.status = 'anonymous'; auth.userId = null; auth.token = null
  tourRequest.value = 0; tourActive.value = false; blocked.value = false
  compact.value = false
  api.fetch.mockReset().mockResolvedValue('unseen')
  api.update.mockReset().mockImplementation(async (_token, status) => status)
  api.toast.mockReset()
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined })

describe('desktop tour lifecycle', () => {
  it('does not open a welcome dialog or mark a fresh visitor as dismissed', async () => {
    await setup('/')
    expect(tour.phase.value).toBe('idle')
    expect(tourActive.value).toBe(false)
    expect(readTerminal('guest')).toBeUndefined()
    await router.push('/mcp'); await flushPromises()
    expect(tour.phase.value).toBe('idle')
    expect(readProgress('guest')).toBeNull()
  })
  it('guides only the current report and preserves its query and hash', async () => {
    saveTerminal('guest', 'skipped')
    await setup()
    requestTour(); await flushPromises()
    expect(tour.phase.value).toBe('welcome')
    expect(tour.pageGuide.value).toBe(true)
    expect(tour.steps.value.map(step => step.id)).toEqual(['report', 'papers', 'subscribe'])
    tour.start()
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/report?date=2026-10-01#saved')
    tour.next(); await flushPromises()
    expect(tour.navigationFailed.value).toBe(false)
    tour.next(); await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/report?date=2026-10-01#saved')
    expect(readProgress('guest')).toMatchObject({ step: 'subscribe', scope: '/report?date=2026-10-01#saved' })
    tour.skip(); await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/report?date=2026-10-01#saved')
    expect(readTerminal('guest')?.status).toBe('skipped')
    expect(readProgress('guest')).toBeNull()
    wrapper?.unmount()
    await setup()
    expect(tour.phase.value).toBe('idle')
    requestTour(); await flushPromises()
    expect(tour.phase.value).toBe('welcome')
    tour.start(); await flushPromises()
    expect(tour.index.value).toBe(0)
    expect(tour.step.value?.id).toBe('report')
  })
  it('resumes a page guide after refresh without visiting another page', async () => {
    saveTerminal('guest', 'skipped')
    await setup()
    requestTour(); await flushPromises()
    tour.start(); await flushPromises()
    tour.next(); await flushPromises()
    wrapper?.unmount()
    await setup('/report?date=2026-10-01#saved')
    expect(tour.phase.value).toBe('tour')
    expect(tour.step.value?.id).toBe('papers')
    expect(router.currentRoute.value.fullPath).toBe('/report?date=2026-10-01#saved')
    tour.skip(); await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/report?date=2026-10-01#saved')
  })
  it.each(['skipped', 'completed'] as const)('offers the full tour after a %s home guide', async (status) => {
    saveTerminal('guest', status)
    await setup('/?date=2026-10-01#saved')
    requestTour(); await flushPromises()
    tour.start(); await flushPromises()
    expect(tour.steps.value.map(step => step.id)).toEqual(['home'])
    tour.showFullTour(); await flushPromises()
    expect(tour.phase.value).toBe('welcome')
    expect(tour.pageGuide.value).toBe(false)
    expect(tour.steps.value.length).toBeGreaterThan(10)
    expect(readProgress('guest')).toBeNull()
    expect(readTerminal('guest')?.status).toBe(status)
    expect(router.currentRoute.value.fullPath).toBe('/?date=2026-10-01#saved')
    tour.start(); await flushPromises()
    tour.next(); await flushPromises()
    tour.next(); await flushPromises()
    tour.next(); await flushPromises()
    expect(router.currentRoute.value.path).toBe('/projects')
    expect(readProgress('guest')).toMatchObject({ step: 'projects', manual: true, scope: undefined })
    wrapper?.unmount()
    await setup('/projects')
    expect(tour.phase.value).toBe('tour')
    expect(tour.pageGuide.value).toBe(false)
    expect(tour.step.value?.id).toBe('projects')
    tour.skip(); await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/?date=2026-10-01#saved')
  })
  it('drops an unfinished page guide after moving to another page', async () => {
    saveTerminal('guest', 'skipped')
    await setup('/projects')
    requestTour(); await flushPromises()
    tour.start(); await flushPromises()
    wrapper?.unmount()
    await setup('/websites')
    expect(tour.phase.value).toBe('idle')
    expect(readProgress('guest')).toBeNull()
    requestTour(); await flushPromises()
    expect(tour.steps.value.map(step => step.id)).toEqual(['websites'])
  })
  it('keeps the first site tour and finishes without navigating to a protected route', async () => {
    await setup()
    requestTour(); await flushPromises()
    expect(tour.pageGuide.value).toBe(false)
    expect(tour.steps.value.length).toBeGreaterThan(10)
    tour.start(); await flushPromises()
    while (tour.index.value < tour.steps.value.length - 1) {
      tour.next(); await flushPromises()
      expect(router.currentRoute.value.path).not.toBe('/subscriptions')
    }
    tour.next(); await flushPromises()
    expect(tour.phase.value).toBe('idle')
    expect(readTerminal('guest')?.status).toBe('completed')
    expect(tourActive.value).toBe(false)
  })
  it('keeps first visits unobstructed after auth and other dialogs settle', async () => {
    auth.status = 'initializing'
    blocked.value = true
    await setup()
    expect(tour.phase.value).toBe('idle')
    auth.status = 'anonymous'; await flushPromises()
    expect(tour.phase.value).toBe('idle')
    blocked.value = false; await flushPromises()
    expect(tour.phase.value).toBe('idle')
    await router.push('/mcp'); await flushPromises()
    expect(tour.phase.value).toBe('idle')
    requestTour(); await flushPromises()
    expect(tour.phase.value).toBe('welcome')
  })
  it('waits for cross-device state without flashing the welcome', async () => {
    login(7)
    let resolve!: (status: string) => void
    api.fetch.mockReturnValue(new Promise(done => { resolve = done }))
    await setup()
    expect(tour.phase.value).toBe('idle')
    resolve('completed'); await flushPromises()
    expect(tour.phase.value).toBe('idle')
    expect(readTerminal('user:7')?.status).toBe('completed')
  })
  it('allows the help button to replay from a signed-in protected page', async () => {
    login(7)
    api.fetch.mockResolvedValue('completed')
    await setup('/subscriptions')
    requestTour(); await flushPromises()
    expect(tour.phase.value).toBe('welcome')
    expect(tour.steps.value.map(step => step.id)).toEqual(['subscriptionsPage'])
    tour.start(); await flushPromises()
    expect(router.currentRoute.value.path).toBe('/subscriptions')
    wrapper?.unmount()
    await setup('/subscriptions')
    expect(tour.step.value?.id).toBe('subscriptionsPage')
    expect(router.currentRoute.value.path).toBe('/subscriptions')
    tour.skip(); await flushPromises()
    expect(router.currentRoute.value.path).toBe('/subscriptions')
  })
  it('claims a guest dismissal once and ignores a stale response after account switching', async () => {
    saveTerminal('guest', 'skipped')
    await setup()
    let resolve!: (status: string) => void
    api.update.mockReturnValue(new Promise(done => { resolve = done }))
    login(7); await flushPromises()
    expect(api.update).toHaveBeenCalledWith('token-7', 'skipped')
    login(8); await flushPromises()
    expect(tour.phase.value).toBe('idle')
    resolve('skipped'); await flushPromises()
    expect(readTerminal('user:8')).toBeUndefined()
    expect(readTerminal('user:7')?.pending).toBe(true)
    expect(tour.phase.value).toBe('idle')
  })
  it('keeps a failed save locally and retries only that account when online', async () => {
    login(7)
    await setup()
    requestTour(); await flushPromises()
    api.update.mockRejectedValueOnce(new Error('offline'))
    tour.skip(); await flushPromises()
    expect(readTerminal('user:7')).toEqual({ status: 'skipped', pending: true })
    expect(api.toast).toHaveBeenCalledOnce()
    window.dispatchEvent(new Event('online')); await flushPromises()
    expect(readTerminal('user:7')?.pending).toBe(false)
  })
  it('does not reopen after a failed account read, and retries on focus', async () => {
    login(7)
    api.fetch.mockRejectedValueOnce(new Error('offline'))
    await setup()
    expect(tour.phase.value).toBe('idle')
    api.fetch.mockResolvedValue('completed')
    window.dispatchEvent(new Event('focus')); await flushPromises()
    expect(tour.phase.value).toBe('idle')
    expect(readTerminal('user:7')?.status).toBe('completed')
  })
  it('flushes a dismissal queued while the first account read is still pending', async () => {
    login(7)
    let resolve!: (status: string) => void
    api.fetch.mockReturnValue(new Promise(done => { resolve = done }))
    await setup()
    requestTour(); await flushPromises()
    tour.skip(); await flushPromises()
    expect(readTerminal('user:7')?.pending).toBe(true)
    resolve('unseen'); await flushPromises()
    expect(api.update).toHaveBeenCalledWith('token-7', 'skipped')
    expect(readTerminal('user:7')?.pending).toBe(false)
  })
  it('closing an anonymous tab after another account finishes does not invent a guest choice', async () => {
    saveProgress('guest', { step: 'projects', returnTo: '/report', manual: false })
    await setup()
    saveTerminal('user:7', 'completed', false)
    window.dispatchEvent(new StorageEvent('storage', { key: MEMORY_KEY }))
    await flushPromises()
    expect(tour.phase.value).toBe('idle')
    claimGuest('user:8')
    expect(readTerminal('user:8')).toBeUndefined()
  })
  it('serializes skip behind a pending navigation so a late route cannot pull the user away', async () => {
    saveProgress('guest', { step: 'style', returnTo: '/report?date=2026-10-01#saved', manual: false })
    await setup()
    tour.next(); await flushPromises()
    let release!: () => void
    const remove = router.beforeEach(to => to.path === '/projects' ? new Promise<void>(done => { release = done }) : undefined)
    tour.next(); await nextTick(); await flushPromises()
    tour.skip(); await flushPromises()
    release(); await flushPromises()
    expect(tour.phase.value).toBe('idle')
    expect(router.currentRoute.value.fullPath).toBe('/report?date=2026-10-01#saved')
    remove()
  })
})

describe('mobile tour lifecycle', () => {
  it('can switch from the page welcome to the full mobile tour', async () => {
    compact.value = true
    saveTerminal('guest', 'completed')
    await setup('/projects?source=website#saved')
    requestTour(); await flushPromises()
    expect(tour.steps.value.map(step => step.id)).toEqual(['myWebsites'])
    tour.showFullTour(); await flushPromises()
    expect(tour.phase.value).toBe('welcome')
    expect(tour.pageGuide.value).toBe(false)
    tour.start(); await flushPromises()
    expect(tour.step.value?.id).toBe('navigation')
    expect(tour.steps.value.some(step => step.desktopOnly)).toBe(false)
    tour.skip(); await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/projects?source=website#saved')
  })
  it('offers and completes the mobile tour without visiting desktop integrations or requiring login', async () => {
    compact.value = true
    await setup()
    requestTour(); await flushPromises()
    expect(tour.pageGuide.value).toBe(false)
    tour.start(); await flushPromises()
    const visited: string[] = []
    while (tour.phase.value === 'tour') {
      visited.push(tour.step.value!.id)
      expect(['/mcp', '/dsh', '/subscriptions']).not.toContain(router.currentRoute.value.path)
      if (tour.step.value?.id === 'papers') expect(router.currentRoute.value.query.type).toBe('arxiv')
      tour.next(); await flushPromises()
    }
    expect(visited).toEqual(expect.arrayContaining(['navigation', 'projects', 'ui', 'report', 'tracking', 'account', 'help']))
    expect(visited.filter(id => ['mcp', 'mcpExamples', 'dsh', 'search'].includes(id))).toEqual([])
    expect(readTerminal('guest')?.status).toBe('completed')
    expect(router.currentRoute.value.fullPath).toBe('/report?date=2026-10-01#saved')
    requestTour(); await flushPromises()
    expect(tour.phase.value).toBe('welcome')
    expect(tour.steps.value.map(step => step.id)).toEqual(['report', 'papers', 'subscribe'])
  })
  it('resumes past a saved desktop integration step and preserves the return location', async () => {
    saveProgress('guest', { step: 'mcp', returnTo: '/projects?source=website', manual: true })
    compact.value = true
    await setup('/mcp')
    expect(tour.step.value?.id).toBe('tracking')
    expect(router.currentRoute.value.path).toBe('/')
    tour.skip(); await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/projects?source=website')
  })
  it('preserves the current section across layout changes and advances past unavailable steps', async () => {
    saveProgress('guest', { step: 'navigation', returnTo: '/report?date=2026-10-01#saved', manual: false })
    await setup()
    while (tour.step.value?.id !== 'mcp') { tour.next(); await flushPromises() }
    compact.value = true; await flushPromises()
    expect(tour.step.value?.id).toBe('tracking')
    expect(router.currentRoute.value.path).toBe('/')
    compact.value = false; await flushPromises()
    expect(tour.step.value?.id).toBe('tracking')
    expect(tour.steps.value.some(step => step.id === 'mcp')).toBe(true)
  })
})

describe('current-page guide selection', () => {
  const desktop = availableSteps({ x: true, contact: true })
  it('selects page content without global navigation or another collection', () => {
    expect(pageSteps(desktop, '/').map(step => step.id)).toEqual(['home'])
    expect(pageSteps(desktop, '/projects').map(step => step.id)).toEqual(['projects', 'projectDetails'])
    expect(pageSteps(desktop, '/projects', 'website').map(step => step.id)).toEqual(['myWebsites'])
    expect(pageSteps(desktop, '/papers/42/read').map(step => step.id)).toEqual(['paperReadPage'])
  })
  it('offers relevant help on a mobile integration page', () => {
    const mobile = availableSteps({ x: true, contact: false }, true)
    expect(pageSteps(mobile, '/mcp', undefined, true).map(step => step.id)).toEqual(['mcp'])
    expect(pageSteps(mobile, '/dsh', undefined, true).map(step => step.id)).toEqual(['dsh'])
  })
})
