import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, nextTick, ref } from 'vue'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import GitHubProjectsView from './GitHubProjectsView.vue'
import ProjectFiltersPanel from '@/components/projects/ProjectFiltersPanel.vue'
import ProjectPagination from '@/components/projects/ProjectPagination.vue'
import ToolWebsiteAddDialog from '@/components/projects/ToolWebsiteAddDialog.vue'
import ToolWebsiteEditDialog from '@/components/projects/ToolWebsiteEditDialog.vue'
import BrowserHomeGuideDialog from '@/components/projects/BrowserHomeGuideDialog.vue'
import McpPromptExampleList from '@/components/mcp/McpPromptExampleList.vue'
import { MCP_PROMO_DISMISSED_STORAGE_KEY, MCP_PROMO_EXAMPLE_IDS } from '@/features/mcp/mcpExamplePrompts'
import type { GitHubProjectItem } from '@/services/projects/projectApi'

const controllerSpy = vi.hoisted(() => vi.fn())
const routerPush = vi.hoisted(() => vi.fn())
const requestLogin = vi.hoisted(() => vi.fn())
const ctlBox = vi.hoisted(() => ({ current: null as null | Record<string, any> }))
const authBox = vi.hoisted(() => ({ current: null as null | { isLoggedIn: boolean; isAdmin: boolean } }))
const routeStateBox = vi.hoisted(() => ({ current: null as null | Record<string, any> }))

vi.mock('@/router', () => ({ default: { push: routerPush } }))
vi.mock('@/composables/useLoginPrompt', () => ({ useLoginPrompt: () => ({ requestLogin }) }))

vi.mock('@/stores/authStore', async () => {
  const { reactive } = await import('vue')
  if (!authBox.current) authBox.current = reactive({ isLoggedIn: true, isAdmin: false })
  return { useAuthStore: () => authBox.current }
})

vi.mock('@/composables/useProjectRouteState', async () => {
  const { ref } = await import('vue')
  routeStateBox.current = {
    applyRouteState: vi.fn(() => true),
    currentProjectsRedirect: vi.fn(() => '/projects'),
    endStateBatch: vi.fn(),
    isApplyingRouteState: ref(false),
    isReplacingRoute: ref(false),
    replaceRouteFromState: vi.fn(),
  }
  return {
    useProjectRouteState: () => routeStateBox.current,
    defaultProjectScopeForQuery: () => 'today',
    defaultProjectSortForScope: () => 'stars',
    defaultProjectSortForSource: () => 'stars',
    defaultProjectSortForQuery: () => 'stars',
  }
})

vi.mock('@/composables/useProjectCatalogController', async () => {
  const { ref } = await import('vue')
  ctlBox.current = {
    addToolError: ref(''),
    addingTool: ref(false),
    categories: ref([]),
    categoriesLoading: ref(false),
    deletingWebsiteId: ref(null),
    editError: ref(''),
    errorMsg: ref(''),
    favoriteBusyKey: ref(''),
    isMyCollection: ref(false),
    isPersonalView: ref(false),
    isViewActive: ref(true),
    lastSuccessfulFetchAt: ref(0),
    loading: ref(false),
    pageSize: ref(20),
    personalTags: ref([]),
    projects: ref([]),
    recommendBusyKey: ref(''),
    requiresPersonalLogin: ref(false),
    savingEdit: ref(false),
    successMsg: ref(''),
    tagsLoading: ref(false),
    taxonomy: ref([]),
    taxonomyLoading: ref(false),
    total: ref(0),
    loadCategories: vi.fn(),
    loadProjects: vi.fn(),
    loadTaxonomy: vi.fn(),
    recommendProject: vi.fn(),
    refreshReads: vi.fn(),
    removeToolWebsite: vi.fn(),
    toggleFavorite: vi.fn(),
    submitEditWebsite: vi.fn().mockResolvedValue(true),
    submitToolWebsite: vi.fn().mockResolvedValue(true),
    handleLogout: vi.fn(),
    deactivate: vi.fn(),
    activate: vi.fn(),
  }
  return { useProjectCatalogController: controllerSpy.mockReturnValue(ctlBox.current) }
})

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {},
  missingWarn: false,
  fallbackWarn: false,
})

const testRouter = createRouter({
  history: createMemoryHistory(),
  routes: [{ path: '/projects', name: 'github-projects', component: GitHubProjectsView }],
})

const mountView = async () => {
  await testRouter.push('/projects')
  await testRouter.isReady()
  const wrapper = mount(GitHubProjectsView, {
    global: {
      plugins: [testRouter, i18n],
      stubs: { Teleport: true, McpPromptExampleList: true },
    },
  })
  await flushPromises()
  return wrapper
}

const controller = () => ctlBox.current as Record<string, any>
const routeState = () => routeStateBox.current as Record<string, any>
const auth = () => authBox.current as { isLoggedIn: boolean; isAdmin: boolean }

const refDefaults: Record<string, unknown> = {
  addToolError: '',
  addingTool: false,
  categories: [],
  categoriesLoading: false,
  deletingWebsiteId: null,
  editError: '',
  errorMsg: '',
  favoriteBusyKey: '',
  isMyCollection: false,
  isPersonalView: false,
  isViewActive: true,
  lastSuccessfulFetchAt: 0,
  loading: false,
  pageSize: 20,
  personalTags: [],
  projects: [],
  recommendBusyKey: '',
  requiresPersonalLogin: false,
  savingEdit: false,
  successMsg: '',
  tagsLoading: false,
  taxonomy: [],
  taxonomyLoading: false,
  total: 0,
}

const websiteRepo = (patch: Partial<GitHubProjectItem> = {}): GitHubProjectItem => ({
  full_name: 'My Tool',
  title: 'My Tool',
  url: 'https://tool.example.com',
  website_id: 7,
  source: 'website',
  user_added: true,
  ...patch,
})

beforeEach(() => {
  for (const [key, value] of Object.entries(controller())) {
    if (value && typeof value === 'object' && 'value' in value) {
      value.value = refDefaults[key]
    } else if (typeof value === 'function' && 'mockClear' in value) {
      value.mockClear()
    }
  }
  controller().submitEditWebsite.mockResolvedValue(true)
  controller().submitToolWebsite.mockResolvedValue(true)
  routeState().applyRouteState.mockClear().mockReturnValue(true)
  routeState().endStateBatch.mockClear()
  routeState().replaceRouteFromState.mockClear()
  routeState().isApplyingRouteState.value = false
  routeState().isReplacingRoute.value = false
  auth().isLoggedIn = true
  auth().isAdmin = false
  controllerSpy.mockClear()
  routerPush.mockClear()
  requestLogin.mockClear()
  window.localStorage.removeItem(MCP_PROMO_DISMISSED_STORAGE_KEY)
})

describe('GitHubProjectsView controller wiring', () => {
  it('hands shared route-state refs and seam callbacks to the controller', async () => {
    await mountView()

    expect(controllerSpy).toHaveBeenCalledOnce()
    const init = controllerSpy.mock.calls[0]![0]
    expect(Object.keys(init.routeState)).toEqual([
      'source', 'selectedScope', 'selectedCategory', 'selectedSubcategory', 'searchQuery',
      'debouncedQuery', 'selectedLanguage', 'selectedTag', 'sort', 'page',
    ])
    expect(init.isLoggedIn()).toBe(true)
    expect(init.currentRedirect()).toBe('/projects')
    expect(init.replaceRouteFromState).toBe(routeState().replaceRouteFromState)

    await init.navigateToLogin('/projects?source=website')
    expect(requestLogin).toHaveBeenCalledWith('/projects?source=website')
    expect(routerPush).not.toHaveBeenCalledWith(expect.objectContaining({ path: '/login' }))
  })

  it('refreshes reads on mount when route state applies', async () => {
    await mountView()
    expect(controller().refreshReads).toHaveBeenCalledTimes(1)

    controller().refreshReads.mockClear()
    routeState().applyRouteState.mockReturnValue(false)
    await mountView()
    expect(controller().refreshReads).not.toHaveBeenCalled()
  })

  it('reloads and rewrites the route when filters change', async () => {
    const wrapper = await mountView()
    controller().loadProjects.mockClear()
    routeState().replaceRouteFromState.mockClear()

    wrapper.findComponent(ProjectFiltersPanel).vm.$emit('update:sort', 'hot')
    await nextTick()

    expect(routeState().replaceRouteFromState).toHaveBeenCalled()
    expect(controller().loadProjects).toHaveBeenCalled()
  })

  it('pages through results via the pagination contract', async () => {
    controller().total.value = 100
    controller().projects.value = [websiteRepo()]
    const wrapper = await mountView()
    controller().loadProjects.mockClear()

    const pagination = wrapper.findComponent(ProjectPagination)
    expect(pagination.exists()).toBe(true)
    pagination.vm.$emit('goPage', 2)
    await nextTick()

    expect(pagination.props('page')).toBe(2)
    expect(routeState().replaceRouteFromState).toHaveBeenCalled()
    expect(controller().loadProjects).toHaveBeenCalled()
  })

  it('deactivates the controller when the view unmounts', async () => {
    const wrapper = await mountView()
    controller().deactivate.mockClear()

    wrapper.unmount()

    expect(controller().deactivate).toHaveBeenCalled()
  })

  it('renders the last-push relative time only when pushed_at is present', async () => {
    controller().projects.value = [
      { full_name: 'owner/pushed', pushed_at: '2026-08-08' },
      { full_name: 'owner/unpushed' },
    ]
    const wrapper = await mountView()

    const cards = wrapper.findAllComponents({ name: 'ProjectResultCard' })
    expect(cards).toHaveLength(2)
    const lastPushPattern = /今天|昨天|\d+天前|上个月|\d+个月前|去年|\d+年前/
    expect(cards[0]!.text()).toMatch(lastPushPattern)
    expect(cards[1]!.text()).not.toMatch(lastPushPattern)
  })

  it('lays cards out inside masonry columns', async () => {
    controller().projects.value = [
      { full_name: 'owner/one', description_zh: '一' },
      { full_name: 'owner/two', description_zh: '二' },
      { full_name: 'owner/three', description_zh: '三' },
    ]
    const wrapper = await mountView()

    // jsdom 无 ResizeObserver：回退单列，全部卡片包进同一个 .projects-col
    const columns = wrapper.findAll('.projects-col')
    expect(columns).toHaveLength(1)
    expect(columns[0]!.findAllComponents({ name: 'ProjectResultCard' })).toHaveLength(3)
  })

  it('does not render empty masonry columns when the desktop capacity exceeds results', async () => {
    const originalClientWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientWidth')
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, value: 1400 })
    class DesktopResizeObserver {
      private readonly callback: ResizeObserverCallback
      constructor(callback: ResizeObserverCallback) { this.callback = callback }
      observe() { this.callback([], this as unknown as ResizeObserver) }
      disconnect() {}
    }
    vi.stubGlobal('ResizeObserver', DesktopResizeObserver)
    controller().projects.value = [
      { full_name: 'owner/one', description_zh: '一' },
      { full_name: 'owner/two', description_zh: '二' },
      { full_name: 'owner/three', description_zh: '三' },
    ]

    try {
      const wrapper = await mountView()
      const columns = wrapper.findAll('.projects-col')
      expect(columns).toHaveLength(3)
      expect(columns.flatMap((column) => column.findAllComponents({ name: 'ProjectResultCard' }))).toHaveLength(3)
      wrapper.unmount()
    } finally {
      vi.unstubAllGlobals()
      if (originalClientWidth) Object.defineProperty(HTMLElement.prototype, 'clientWidth', originalClientWidth)
      else delete (HTMLElement.prototype as unknown as { clientWidth?: number }).clientWidth
    }
  })

  it('reactivates inside keep-alive and refreshes stale reads without clearing content', async () => {
    const Harness = defineComponent({
      components: { GitHubProjectsView },
      setup: () => ({ show: ref(true) }),
      template: '<KeepAlive><GitHubProjectsView v-if="show" /></KeepAlive>',
    })
    await testRouter.push('/projects')
    await testRouter.isReady()
    const wrapper = mount(Harness, {
      global: { plugins: [testRouter, i18n], stubs: { Teleport: true, McpPromptExampleList: true } },
    })
    await flushPromises()
    expect(controller().activate).toHaveBeenCalledTimes(1)

    controller().refreshReads.mockClear()
    controller().deactivate.mockClear()
    ;(wrapper.vm as unknown as { show: boolean }).show = false
    await nextTick()
    expect(controller().deactivate).toHaveBeenCalled()

    ;(wrapper.vm as unknown as { show: boolean }).show = true
    await nextTick()
    expect(controller().activate).toHaveBeenCalledTimes(2)
    expect(controller().refreshReads).toHaveBeenCalledWith({ clearSuccess: false, preserveContent: true })
  })
})

describe('GitHubProjectsView dialog orchestration', () => {
  const switchToWebsiteSource = async (wrapper: Awaited<ReturnType<typeof mountView>>) => {
    wrapper.findComponent(ProjectFiltersPanel).vm.$emit('changeSource', 'website')
    await nextTick()
  }

  it('opens the add dialog from the website view and closes it via the close event', async () => {
    const wrapper = await mountView()
    await switchToWebsiteSource(wrapper)

    const addButton = wrapper.find('.projects-add-btn')
    expect(addButton.exists()).toBe(true)
    await addButton.trigger('click')
    await nextTick()

    expect(controller().loadTaxonomy).toHaveBeenCalled()
    expect(wrapper.findComponent(ToolWebsiteAddDialog).props('open')).toBe(true)

    await wrapper.find('.tool-modal__close').trigger('click')
    await nextTick()
    expect(wrapper.findComponent(ToolWebsiteAddDialog).props('open')).toBe(false)
  })

  it('opens the browser-home guide from the website view and closes it via the close event', async () => {
    const wrapper = await mountView()
    await switchToWebsiteSource(wrapper)

    const guideButton = wrapper.find('.projects-home-btn')
    expect(guideButton.exists()).toBe(true)
    await guideButton.trigger('click')
    await nextTick()

    const dialog = wrapper.findComponent(BrowserHomeGuideDialog)
    expect(dialog.props('open')).toBe(true)

    dialog.vm.$emit('close')
    await nextTick()
    expect(wrapper.findComponent(BrowserHomeGuideDialog).props('open')).toBe(false)
  })

  it('opens the login prompt for anonymous add attempts instead of leaving the page', async () => {
    auth().isLoggedIn = false
    const wrapper = await mountView()
    await switchToWebsiteSource(wrapper)

    await wrapper.find('.projects-add-btn').trigger('click')

    expect(requestLogin).toHaveBeenCalledWith('/projects?source=website')
    expect(wrapper.findComponent(ToolWebsiteAddDialog).props('open')).toBe(false)
  })

  it('closes the add dialog only after a successful submission', async () => {
    const wrapper = await mountView()
    await switchToWebsiteSource(wrapper)
    await wrapper.find('.projects-add-btn').trigger('click')
    const dialog = wrapper.findComponent(ToolWebsiteAddDialog)

    controller().submitToolWebsite.mockResolvedValueOnce(false)
    dialog.vm.$emit('submitAuto', 'https://tool.example.com')
    await flushPromises()
    expect(dialog.props('open')).toBe(true)

    dialog.vm.$emit('submitAuto', 'https://tool.example.com')
    await flushPromises()
    expect(controller().submitToolWebsite).toHaveBeenLastCalledWith('https://tool.example.com')
    expect(wrapper.findComponent(ToolWebsiteAddDialog).props('open')).toBe(false)
  })

  it('opens the edit dialog from a card edit event and closes it after a successful save', async () => {
    const repo = websiteRepo()
    controller().projects.value = [repo]
    controller().total.value = 1
    const wrapper = await mountView()
    await switchToWebsiteSource(wrapper)

    wrapper.findComponent({ name: 'ProjectResultCard' }).vm.$emit('edit', repo)
    await nextTick()
    const editDialog = wrapper.findComponent(ToolWebsiteEditDialog)
    expect(editDialog.props('open')).toBe(true)
    expect(editDialog.props('target')).toEqual(repo)

    controller().submitEditWebsite.mockResolvedValueOnce(false)
    editDialog.vm.$emit('submit', 7, { title: 'Renamed' })
    await flushPromises()
    expect(wrapper.findComponent(ToolWebsiteEditDialog).props('open')).toBe(true)

    editDialog.vm.$emit('submit', 7, { title: 'Renamed' })
    await flushPromises()
    expect(controller().submitEditWebsite).toHaveBeenLastCalledWith(7, { title: 'Renamed' })
    const closed = wrapper.findComponent(ToolWebsiteEditDialog)
    expect(closed.props('open')).toBe(false)
    expect(closed.props('target')).toBeNull()
  })

  it('routes the personal login prompt through the current redirect', async () => {
    controller().requiresPersonalLogin.value = true
    const wrapper = await mountView()

    await wrapper.find('.projects-login-prompt__action').trigger('click')

    expect(requestLogin).toHaveBeenCalledWith('/projects')
    expect(routerPush).not.toHaveBeenCalledWith(expect.objectContaining({ path: '/login' }))
  })
})

describe('GitHubProjectsView MCP guidance', () => {
  it('shows the MCP promo card with the promo example subset by default', async () => {
    const wrapper = await mountView()

    const promo = wrapper.find('.projects-mcp-promo')
    expect(promo.exists()).toBe(true)
    expect(promo.find('a[href="/mcp"]').exists()).toBe(true)

    const list = wrapper.findComponent(McpPromptExampleList)
    expect(list.exists()).toBe(true)
    expect(list.props('examples').map((example: { id: string }) => example.id)).toEqual([...MCP_PROMO_EXAMPLE_IDS])
    expect(list.props('mode')).toBe('demo-copy')
  })

  it('hides the promo card when a weekly dismissal is still active', async () => {
    window.localStorage.setItem(MCP_PROMO_DISMISSED_STORAGE_KEY, String(Date.now() + 7 * 24 * 60 * 60 * 1000))
    const wrapper = await mountView()

    expect(wrapper.find('.projects-mcp-promo').exists()).toBe(false)
  })

  it('shows the promo card again after the stored dismissal expires', async () => {
    window.localStorage.setItem(MCP_PROMO_DISMISSED_STORAGE_KEY, String(Date.now() - 1000))
    const wrapper = await mountView()

    expect(wrapper.find('.projects-mcp-promo').exists()).toBe(true)
  })

  it('hides the promo card while the personal login prompt is shown', async () => {
    controller().requiresPersonalLogin.value = true
    const wrapper = await mountView()

    expect(wrapper.find('.projects-mcp-promo').exists()).toBe(false)
  })

  it('uses source-aware hero labels and keeps the MCP promo public-only', async () => {
    const wrapper = await mountView()
    expect(wrapper.find('.projects-hero .projects-kicker').text()).toBe('projects.heroLibraryKicker')
    expect(wrapper.find('.projects-mcp-promo').exists()).toBe(true)

    wrapper.findComponent(ProjectFiltersPanel).vm.$emit('changeSource', 'website')
    await nextTick()
    expect(wrapper.find('.projects-hero .projects-kicker').text()).toBe('projects.heroWebsiteKicker')
    expect(wrapper.find('.projects-mcp-promo').exists()).toBe(false)

    wrapper.findComponent(ProjectFiltersPanel).vm.$emit('changeSource', 'favorites')
    await nextTick()
    expect(wrapper.find('.projects-hero .projects-kicker').text()).toBe('projects.heroFavoritesKicker')
    expect(wrapper.find('.projects-mcp-promo').exists()).toBe(false)
  })

  it('dismisses the promo card for the session only without persisting', async () => {
    const wrapper = await mountView()

    await wrapper.find('.projects-mcp-promo__dismiss').trigger('click')
    await nextTick()

    expect(wrapper.find('.projects-mcp-promo').exists()).toBe(false)
    expect(window.localStorage.getItem(MCP_PROMO_DISMISSED_STORAGE_KEY)).toBeNull()
  })

  it('persists a weekly dismissal from the dismiss-week button', async () => {
    const wrapper = await mountView()

    await wrapper.find('.projects-mcp-promo__dismiss-week').trigger('click')
    await nextTick()

    expect(wrapper.find('.projects-mcp-promo').exists()).toBe(false)
    const stored = Number(window.localStorage.getItem(MCP_PROMO_DISMISSED_STORAGE_KEY))
    expect(Number.isFinite(stored)).toBe(true)
    expect(stored).toBeGreaterThan(Date.now())
  })

  it('runs an in-site search demo when an example emits demo', async () => {
    const wrapper = await mountView()
    controller().loadProjects.mockClear()

    wrapper.findComponent(McpPromptExampleList).vm.$emit('demo', 'RAG 框架')
    await nextTick()

    const init = controllerSpy.mock.calls[0]![0]
    expect(init.routeState.searchQuery.value).toBe('RAG 框架')
    expect(init.routeState.debouncedQuery.value).toBe('RAG 框架')
    expect(controller().loadProjects).toHaveBeenCalled()
  })
})
