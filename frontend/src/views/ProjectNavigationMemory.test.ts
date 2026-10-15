import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { computed, defineComponent, ref } from 'vue'
import { createMemoryHistory, createRouter, useRoute, type Router } from 'vue-router'
import { createI18n } from 'vue-i18n'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import GitHubProjectsView from './GitHubProjectsView.vue'
import AppDock from '@/components/layout/AppDock.vue'
import MobileNavigation from '@/components/layout/MobileNavigation.vue'
import ProjectFiltersPanel from '@/components/projects/ProjectFiltersPanel.vue'
import { KEEP_ALIVE_MAX, KEEP_ALIVE_VIEW_NAMES, NAV_ITEMS } from '@/features/navigation/navigationModel'
import { pageViewKey, useProjectNavigationMemory } from '@/composables/useProjectNavigationMemory'
import { useAuthStore } from '@/stores/authStore'

const box = vi.hoisted(() => ({ router: null as Router | null }))
const api = vi.hoisted(() => ({ list: vi.fn(), personal: vi.fn(), peek: vi.fn() }))
vi.mock('@/router', () => ({ default: {
  push: (...args: Parameters<Router['push']>) => box.router!.push(...args),
  replace: (...args: Parameters<Router['replace']>) => box.router!.replace(...args),
} }))
vi.mock('@/stores/authStore', async () => {
  const { reactive } = await import('vue')
  const auth = reactive({ isLoggedIn: true, isAdmin: false, ensureInitialized: async () => {} })
  return { useAuthStore: () => auth }
})
vi.mock('@/composables/useLoginPrompt', () => ({ useLoginPrompt: () => ({ requestLogin: vi.fn() }) }))
vi.mock('@vueuse/core', async (original) => ({
  ...await original<typeof import('@vueuse/core')>(),
  useMediaQuery: (query: string) => ref(query.includes('min-width')),
}))
vi.mock('@/composables/useProjectTrends', () => ({ useProjectTrends: () => ({ trends: ref(null), trendFor: () => undefined }) }))
vi.mock('@/services/projects/projectApi', async (original) => ({
  ...await original<typeof import('@/services/projects/projectApi')>(),
  fetchProjects: api.list,
  fetchMyProjectCollection: api.personal,
  fetchProjectPeek: api.peek,
  fetchProjectTrends: async () => ({ metric_date: '2026-10-15', items: {} }),
  fetchProjectCategories: async () => ({ items: [
    { slug: 'models', name: '模型 / 推理 / 部署', count: 812 },
    { slug: 'agents', name: '智能体', count: 100 },
  ] }),
  fetchMyProjectTags: async () => ({ items: [] }),
  fetchMyToolWebsiteQuota: async () => ({ unlimited: true }),
  fetchProjectTaxonomy: async () => ({ items: [] }),
}))

const repo = { full_name: 'Ebony-Vinyl/dsh-our-free-model', repo_id: 'Ebony-Vinyl/dsh-our-free-model', stars: 17000, description_zh: '免费模型插件' }
const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: {}, missingWarn: false, fallbackWarn: false })
let wrapper: VueWrapper | undefined
const dialogClose = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'close')
beforeAll(() => Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value() { this.removeAttribute('open') } }))
afterAll(() => {
  if (dialogClose) Object.defineProperty(HTMLDialogElement.prototype, 'close', dialogClose)
  else Reflect.deleteProperty(HTMLDialogElement.prototype, 'close')
})
const settle = async () => {
  await flushPromises()
  await vi.dynamicImportSettled()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await flushPromises()
}

const start = async (path = '/projects', mobile = false) => {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/projects', name: 'github-projects', component: GitHubProjectsView },
    { path: '/report', component: { template: '<div>Report</div>' } },
    { path: '/', component: { name: 'DashboardView', template: '<div>Dashboard</div>' } },
    { path: '/:pathMatch(.*)*', component: { template: '<div />' } },
  ] })
  box.router = router
  await router.push(path)
  await router.isReady()
  const Harness = defineComponent({
    components: { AppDock, MobileNavigation },
    setup() {
      const route = useRoute()
      return { route, targets: useProjectNavigationMemory(route), viewKey: computed(() => pageViewKey(route)),
        items: NAV_ITEMS.filter((item) => ['/', '/projects', '/projects?source=website', '/report'].includes(item.to)),
        names: KEEP_ALIVE_VIEW_NAMES, max: KEEP_ALIVE_MAX, mobile }
    },
    template: `<component :is="mobile ? 'MobileNavigation' : 'AppDock'" :items="items" :targets="targets" :current-path="route.path" :current-query="route.query" :is-admin="false" :is-logged-in="true" />
      <RouterView v-slot="{ Component }"><KeepAlive :include="names" :max="max"><component :is="Component" :key="viewKey" /></KeepAlive></RouterView>`,
  })
  wrapper = mount(Harness, { attachTo: document.body, global: { plugins: [router, i18n], stubs: { Teleport: true, McpPromptExampleList: true } } })
  await settle()
  return router
}
const navigate = async (entry: string) => {
  await wrapper!.get(`a[data-tour-nav="${entry}"]`).trigger('click')
  await settle()
}
const openProject = async () => {
  await wrapper!.get('.project-row__name a').trigger('click')
  await settle()
}

beforeEach(() => {
  api.list.mockReset().mockImplementation(async (params) => ({ items: [params.category === 'agents' ? { ...repo, full_name: 'example/agent', repo_id: 'example/agent' } : repo], total: 812 }))
  api.personal.mockReset().mockResolvedValue({ items: [], total: 0 })
  api.peek.mockReset().mockResolvedValue({ repo_id: repo.repo_id, status: 'ok', has_readme: true, readme: ['README'], readme_more: false, commit: null })
  localStorage.setItem('list_keys_hint', '1')
  ;(useAuthStore() as unknown as { isLoggedIn: boolean }).isLoggedIn = true
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  document.body.innerHTML = ''
  localStorage.clear()
  vi.restoreAllMocks()
})

describe('project browsing session', () => {
  it.each([false, true])('resumes filters, an open detail and both scroll positions through navigation (mobile nav: %s)', async (mobile) => {
    const router = await start('/projects', mobile)
    wrapper!.getComponent(ProjectFiltersPanel).vm.$emit('selectCategory', 'models')
    await settle()
    await openProject()
    const page = wrapper!.get('.projects-page').element as HTMLElement
    const detail = wrapper!.get('.project-pane__scroll').element as HTMLElement
    page.scrollTop = 420
    detail.scrollTop = 180
    for (const element of [page, detail]) element.dispatchEvent(new Event('scroll'))
    const calls = api.list.mock.calls.length
    await navigate('/report')
    expect(page.isConnected).toBe(false)
    // Browsers can reset scroll offsets when KeepAlive moves DOM into storage.
    page.scrollTop = detail.scrollTop = 0
    for (const element of [page, detail]) element.dispatchEvent(new Event('scroll'))
    await navigate('/projects')
    expect(router.currentRoute.value.query).toEqual({ scope: 'all', category: 'models', sort: 'hot' })
    expect(wrapper!.getComponent(ProjectFiltersPanel).props('selectedCategory')).toBe('models')
    expect(wrapper!.get('.project-pane__name').text()).toBe(repo.full_name)
    expect(wrapper!.get('.projects-page').element).toBe(page)
    expect(wrapper!.get('.project-pane__scroll').element).toBe(detail)
    expect(page.scrollTop).toBe(420)
    expect(detail.scrollTop).toBe(180)
    expect(api.list).toHaveBeenCalledTimes(calls)
  })

  it('retains public browsing across website, favorite and dashboard visits', async () => {
    const router = await start('/projects?scope=all&category=models&language=JavaScript&sort=updated&page=3&q=dsh')
    await openProject()
    const original = router.currentRoute.value.fullPath
    await navigate('/projects?source=website')
    expect(wrapper!.getComponent(ProjectFiltersPanel).props('source')).toBe('website')
    await router.push('/projects?source=favorites')
    await settle()
    await navigate('/')
    await navigate('/report')
    await navigate('/projects')
    expect(router.currentRoute.value.fullPath).toBe(original)
    expect(wrapper!.get('.project-pane__name').text()).toBe(repo.full_name)
    expect(wrapper!.getComponent(ProjectFiltersPanel).props('searchQuery')).toBe('dsh')
    expect(wrapper!.getComponent(ProjectFiltersPanel).props('sort')).toBe('updated')
  })

  it('honors explicit filter links and a fresh app starts without an open detail', async () => {
    const router = await start('/projects?scope=all&category=models')
    await openProject()
    await navigate('/report')
    await router.push('/projects?scope=all&category=agents')
    await settle()
    expect(wrapper!.getComponent(ProjectFiltersPanel).props('selectedCategory')).toBe('agents')
    expect(wrapper!.find('.project-pane').exists()).toBe(false)
    router.back()
    await settle()
    expect(router.currentRoute.value.path).toBe('/report')
    router.back()
    await settle()
    expect(wrapper!.getComponent(ProjectFiltersPanel).props('selectedCategory')).toBe('models')
    await router.push('/projects')
    await settle()
    expect(wrapper!.getComponent(ProjectFiltersPanel).props('selectedScope')).toBe('today')
    wrapper!.unmount()
    await start()
    expect(wrapper!.find('.project-pane').exists()).toBe(false)
    expect(wrapper!.getComponent(ProjectFiltersPanel).props('selectedCategory')).toBe('all')
  })

  it('refreshes stale data without closing the detail, and clears gated content after logout', async () => {
    await start('/projects?scope=all&category=models&q=dsh')
    await openProject()
    const calls = api.list.mock.calls.length
    await navigate('/report')
    vi.spyOn(Date, 'now').mockReturnValue(Date.now() + 61_000)
    await navigate('/projects')
    expect(api.list.mock.calls.length).toBeGreaterThan(calls)
    expect(wrapper!.get('.project-pane__name').text()).toBe(repo.full_name)
    await navigate('/report')
    ;(useAuthStore() as unknown as { isLoggedIn: boolean }).isLoggedIn = false
    await settle()
    await navigate('/projects')
    expect(wrapper!.find('.project-pane').exists()).toBe(false)
    expect(wrapper!.find('.project-row').exists()).toBe(false)
  })
})
