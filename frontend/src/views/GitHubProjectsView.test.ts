import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, nextTick, ref } from 'vue'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import GitHubProjectsView from './GitHubProjectsView.vue'
import projectsViewSource from './GitHubProjectsView.vue?raw'
import ProjectFiltersPanel from '@/components/projects/ProjectFiltersPanel.vue'
import ProjectPagination from '@/components/projects/ProjectPagination.vue'
import ToolWebsiteAddDialog from '@/components/projects/ToolWebsiteAddDialog.vue'
import ToolWebsiteEditDialog from '@/components/projects/ToolWebsiteEditDialog.vue'
import McpPromptExampleList from '@/components/mcp/McpPromptExampleList.vue'
import { MCP_EMPTY_STATE_EXAMPLE_IDS, MCP_PROMO_DISMISSED_STORAGE_KEY, MCP_PROMO_EXAMPLE_IDS } from '@/features/mcp/mcpExamplePrompts'
import type { GitHubProjectItem } from '@/services/projects/projectApi'
import { setAppDensity } from '@/composables/useAppDensity'
import { PEEK_OPEN_DELAY } from '@/composables/useProjectPeek'
import { READ_MARKS } from '@/composables/useReadMarks'

// 桌面榜单（≥1024px）按 useMediaQuery 判断；jsdom 没有 matchMedia，默认按手机与平板。
// 宽屏（≥1600px）的详情栏用一个共用的 ref，测试里可以中途把窗口改窄。
const viewport = vi.hoisted(() => ({ desktop: false, wide: { value: false } as { value: boolean } }))
vi.mock('@vueuse/core', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@vueuse/core')>()
  const { ref } = await import('vue')
  viewport.wide = ref(false)
  return {
    ...actual,
    useMediaQuery: (query: string) => (
      query === '(min-width: 1024px)' ? ref(viewport.desktop)
        : query === '(min-width: 1600px)' ? viewport.wide
          : actual.useMediaQuery(query)
    ),
  }
})
// 榜单的行情（火花线、名次升降）另有测试，这里不取
vi.mock('@/composables/useProjectTrends', async () => {
  const { ref } = await import('vue')
  return { useProjectTrends: () => ({ trends: ref(null), trendFor: () => undefined }) }
})
// 榜单悬停速览读 GitHub 的那两样换成假的，其余照常
const peekApi = vi.hoisted(() => ({ fetchProjectPeek: vi.fn(), fetchProjectTrends: vi.fn() }))
vi.mock('@/services/projects/projectApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/projects/projectApi')>()),
  fetchProjectPeek: peekApi.fetchProjectPeek,
  fetchProjectTrends: peekApi.fetchProjectTrends,
}))

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
    routeStateMatchesRoute: vi.fn(() => true),
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
    websiteQuota: ref(null),
    websiteQuotaLoading: ref(false),
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
  websiteQuota: null,
  websiteQuotaLoading: false,
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
  routeState().routeStateMatchesRoute.mockClear().mockReturnValue(true)
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
    controller().isPersonalView.value = true
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

  it('keeps sparse masonry cards at the dense-row column width instead of stretching', async () => {
    controller().isPersonalView.value = true
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
    ]

    try {
      const wrapper = await mountView()
      const vm = wrapper.vm as unknown as {
        masonryGridTemplate: string
        masonryColumnWidths: number[]
        masonryColumnCount: number
        effectiveMasonryColumnCount: number
      }
      const widths = [...String(vm.masonryGridTemplate).matchAll(/(\d+)px/g)].map((match) => Number(match[1]))
      expect(wrapper.findAll('.projects-col')).toHaveLength(2)
      expect(vm.masonryColumnCount).toBe(5)
      expect(vm.effectiveMasonryColumnCount).toBe(2)
      expect(vm.masonryColumnWidths).toHaveLength(5)
      expect(widths).toHaveLength(2)
      // 1400px 容量约 5 列；稀疏行必须沿用满列轨道宽（~270px），而不是
      // 把两张卡均分整行（~688px）。jsdom 不解析 v-bind CSS，因此断言计算值。
      expect(widths.every((width) => width >= 260 && width <= 280)).toBe(true)
      expect(vm.masonryColumnWidths.every((width) => width >= 260 && width <= 280)).toBe(true)
      wrapper.unmount()
    } finally {
      vi.unstubAllGlobals()
      if (originalClientWidth) Object.defineProperty(HTMLElement.prototype, 'clientWidth', originalClientWidth)
      else delete (HTMLElement.prototype as unknown as { clientWidth?: number }).clientWidth
    }
  })

  it('reads the masonry column floor and gap from the page so a skin can set its own columns', async () => {
    controller().isPersonalView.value = true
    const originalClientWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientWidth')
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, value: 1436 })
    class DesktopResizeObserver {
      private readonly callback: ResizeObserverCallback
      constructor(callback: ResizeObserverCallback) { this.callback = callback }
      observe() { this.callback([], this as unknown as ResizeObserver) }
      disconnect() {}
    }
    vi.stubGlobal('ResizeObserver', DesktopResizeObserver)
    // 漫画皮肤（comic-pages.css）在页面上声明的两个变量；jsdom 不跑那份样式表，故在此代答。
    const skinVars: Record<string, string> = { '--projects-masonry-min': ' 330px', '--projects-masonry-gap': ' 20px' }
    const originalGetComputedStyle = window.getComputedStyle.bind(window)
    const styleSpy = vi.spyOn(window, 'getComputedStyle').mockImplementation((element, pseudo) => {
      const style = originalGetComputedStyle(element, pseudo)
      if (!(element as HTMLElement).classList?.contains('projects-page')) return style
      return { paddingLeft: '0px', paddingRight: '0px', getPropertyValue: (name: string) => skinVars[name] ?? style.getPropertyValue(name) } as unknown as CSSStyleDeclaration
    })
    controller().projects.value = ['one', 'two', 'three', 'four', 'five'].map((name) => ({ full_name: `owner/${name}`, description_zh: name }))

    try {
      const wrapper = await mountView()
      const vm = wrapper.vm as unknown as { masonryColumnCount: number; masonryColumnWidths: number[] }
      // 默认 260/12 下 1436px 排 5 列；皮肤改成 330/20 后排 4 列，(1436 - 3 × 20) / 4 = 344。
      expect(vm.masonryColumnCount).toBe(4)
      expect(vm.masonryColumnWidths).toEqual([344, 344, 344, 344])
      expect(wrapper.findAll('.projects-col')).toHaveLength(4)
      wrapper.unmount()
    } finally {
      styleSpy.mockRestore()
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

  it('re-applies route state on reactivation when the query changed while deactivated', async () => {
    // 回归：dock 点「报告」再点「我的网页」(/projects?source=website)，
    // KeepAlive 按 route.path 复用实例，route.query watcher 在激活前被
    // isViewActive 拦截；onActivated 须检出失配并补应用，否则停在旧内容。
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

    ;(wrapper.vm as unknown as { show: boolean }).show = false
    await nextTick()
    routeState().applyRouteState.mockClear()
    controller().refreshReads.mockClear()
    routeState().routeStateMatchesRoute.mockReturnValue(false)

    ;(wrapper.vm as unknown as { show: boolean }).show = true
    await nextTick()

    expect(routeState().applyRouteState).toHaveBeenCalledTimes(1)
    expect(controller().refreshReads).toHaveBeenCalledWith()
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

  it('the website view has no browser-home guide entry', async () => {
    const wrapper = await mountView()
    await switchToWebsiteSource(wrapper)

    expect(wrapper.find('.projects-home-btn').exists()).toBe(false)
  })

  it('shows free users the upsell copy with a VIP link to the membership page', async () => {
    controller().websiteQuota.value = { unlimited: false, limit: 3, used: 1, remaining: 2, window_seconds: 86400, reset_at: null }
    const wrapper = await mountView()
    await switchToWebsiteSource(wrapper)

    const quota = wrapper.find('.projects-website-add__quota')
    expect(quota.text()).toContain('projects.websiteQuotaFreeUpsell')
    const vipLink = quota.find('a.projects-website-add__vip')
    expect(vipLink.exists()).toBe(true)
    expect(vipLink.text()).toBe('VIP')
    expect(vipLink.attributes('href')).toBe('/membership')
  })

  it('shows members the unlimited copy without the VIP upsell link', async () => {
    controller().websiteQuota.value = { unlimited: true, limit: null, used: 0, remaining: null, window_seconds: 86400, reset_at: null }
    const wrapper = await mountView()
    await switchToWebsiteSource(wrapper)

    const quota = wrapper.find('.projects-website-add__quota')
    expect(quota.text()).toContain('projects.websiteQuotaUnlimited')
    expect(quota.find('a.projects-website-add__vip').exists()).toBe(false)
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
  // 推广卡的常态是有结果的列表；无结果搜索由下方专门用例覆盖
  beforeEach(() => {
    controller().projects.value = [{ full_name: 'owner/one' }]
  })

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

  it('keeps expanded promo copy and controls in the same compact content row', async () => {
    const wrapper = await mountView()
    const promo = wrapper.get('details.projects-mcp-promo')

    promo.element.setAttribute('open', '')
    await nextTick()

    const content = promo.get('.projects-mcp-promo__content')
    expect(content.element.children[0]?.classList).toContain('projects-mcp-promo__controls')
    expect(content.element.children[1]?.classList).toContain('projects-mcp-promo__copy')
    expect(content.element.children[2]?.classList).toContain('projects-mcp-promo__action')
    expect(projectsViewSource).toMatch(/\.projects-page \.projects-mcp-promo\s*\{[^}]*width:\s*100%;[^}]*min-width:\s*0;/)
    expect(projectsViewSource).toMatch(/\.projects-mcp-promo__content\s*\{[^}]*display:\s*grid;/)
    expect(projectsViewSource).toMatch(/\.projects-mcp-promo__controls\s*\{[^}]*grid-column:\s*2;/)
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
    expect(wrapper.find('.projects-hero h1').text()).toBe('projects.pageTitle')
    expect(wrapper.find('.projects-mcp-promo').exists()).toBe(true)

    wrapper.findComponent(ProjectFiltersPanel).vm.$emit('changeSource', 'website')
    await nextTick()
    expect(wrapper.find('.projects-hero .projects-kicker').text()).toBe('projects.heroWebsiteKicker')
    expect(wrapper.find('.projects-hero h1').text()).toBe('projects.heroWebsiteKicker')
    expect(wrapper.find('.projects-mcp-promo').exists()).toBe(false)

    wrapper.findComponent(ProjectFiltersPanel).vm.$emit('changeSource', 'favorites')
    await nextTick()
    expect(wrapper.find('.projects-hero .projects-kicker').text()).toBe('projects.heroFavoritesKicker')
    expect(wrapper.find('.projects-hero h1').text()).toBe('projects.pageTitle')
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

  it('yields the promo card to the empty-state examples when a search finds nothing', async () => {
    controller().projects.value = []
    const wrapper = await mountView()
    controllerSpy.mock.calls[0]![0].routeState.searchQuery.value = 'aihot'
    await nextTick()

    expect(wrapper.find('.projects-mcp-promo').exists()).toBe(false)
    const lists = wrapper.findAllComponents(McpPromptExampleList)
    expect(lists).toHaveLength(1)
    expect(lists[0]!.props('examples').map((example: { id: string }) => example.id)).toEqual([...MCP_EMPTY_STATE_EXAMPLE_IDS])
  })

  it('keeps the promo card while an empty search is still loading', async () => {
    controller().projects.value = []
    controller().loading.value = true
    const wrapper = await mountView()
    controllerSpy.mock.calls[0]![0].routeState.searchQuery.value = 'aihot'
    await nextTick()

    expect(wrapper.find('.projects-mcp-promo').exists()).toBe(true)
    expect(wrapper.find('.empty-state').exists()).toBe(false)
  })
})


describe('GitHubProjectsView collection navigation', () => {
  it('links personal websites to the standalone website recommendations', async () => {
    const wrapper = await mountView()
    const filters = wrapper.findComponent(ProjectFiltersPanel)
    expect(filters.props('sourceOptions').map((option) => option.value)).toEqual(['all', 'website'])
    filters.vm.$emit('changeSource', 'website')
    await nextTick()
    expect(filters.props('source')).toBe('website')
    expect(wrapper.find('.projects-hero h1').text()).toBe('projects.heroWebsiteKicker')
    expect(wrapper.find('.website-tabs a[href="/websites"]').exists()).toBe(true)
    expect(wrapper.find('.website-tabs a[aria-current="page"]').attributes('href')).toBe('/projects?source=website')
    expect(wrapper.find('.website-tabs a[href="/projects?scope=recommended"]').exists()).toBe(false)
    filters.vm.$emit('changeSource', 'all')
    await nextTick()
    expect(routerPush).toHaveBeenCalledWith('/websites')
    expect(filters.props('source')).toBe('website')
  })

  it('marks my web collection for its comic skin and turns the card accents by global rank', async () => {
    controller().projects.value = Array.from({ length: 9 }, (_, index) => websiteRepo({ full_name: `Site ${index}`, title: `Site ${index}`, website_id: index + 1 }))
    const wrapper = await mountView()
    expect(wrapper.classes()).not.toContain('projects-page--websites')
    expect(wrapper.find('.projects-hero__lead').text()).toBe('projects.heroLibraryLead')
    wrapper.findComponent(ProjectFiltersPanel).vm.$emit('changeSource', 'website')
    // 测试控制器的个人视图是桩，不随来源切换；真实控制器里网页收藏必是个人视图。
    controller().isPersonalView.value = true
    await nextTick()

    expect(wrapper.classes()).toContain('projects-page--websites')
    expect(wrapper.find('.projects-hero h1').classes()).toContain('comic-title')
    expect(wrapper.find('.projects-hero__lead').text()).toBe('projects.heroWebsiteLead')
    // 与站长推荐页同序、每 8 张一轮；jsdom 单列，DOM 顺序即全局名次。
    const tones = wrapper.findAll('.project-card').map((card) => card.classes().find((name) => name.startsWith('project-card--tone-')))
    expect(tones).toEqual(['lime', 'cyan', 'purple', 'orange', 'purple', 'orange', 'lime', 'cyan', 'lime'].map((tone) => `project-card--tone-${tone}`))
  })

  it('keeps the GitHub source active without changing its current project scope', async () => {
    const wrapper = await mountView()
    const beforeScope = wrapper.findComponent(ProjectFiltersPanel).props('selectedScope')
    expect(wrapper.findAll('.projects-source-tab')).toHaveLength(0)
    expect(wrapper.classes()).toContain('projects-page--catalog')
    expect(wrapper.findComponent(ProjectFiltersPanel).props('selectedScope')).toBe(beforeScope)
  })
})

describe('GitHubProjectsView chart keyboard flow', () => {
  const chartRepo = (name: string, tags: string[] = []): GitHubProjectItem => ({
    full_name: `acme/${name}`,
    repo_id: `acme/${name}`,
    description_en: `${name} does one thing well.`,
    stars: 100,
    tags,
  })
  const spies: { mockRestore: () => void }[] = []
  let view: VueWrapper | null = null

  beforeEach(() => {
    viewport.desktop = true
    setAppDensity('compact')
    localStorage.setItem('list_keys_hint', '1')
    localStorage.removeItem('read_marks_projects')
    // jsdom 不排版：每一行都算整行在视野里；弹窗（aria-modal）画出来了才算开着
    spies.push(
      vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(
        { top: 10, bottom: 90, left: 0, right: 300, width: 300, height: 80, x: 0, y: 10, toJSON: () => ({}) } as DOMRect,
      ),
      vi.spyOn(Element.prototype, 'getClientRects').mockImplementation(function (this: Element) {
        return (this.getAttribute('aria-modal') === 'true' ? [{}] : []) as unknown as DOMRectList
      }),
      vi.spyOn(window, 'open').mockReturnValue(null),
    )
  })

  afterEach(() => {
    view?.unmount()
    view = null
    spies.splice(0).forEach((spy) => spy.mockRestore())
    viewport.desktop = false
    viewport.wide.value = false
    setAppDensity('compact')
    localStorage.removeItem('list_keys_hint')
    localStorage.removeItem('read_marks_projects')
    document.body.innerHTML = ''
  })

  // transition: false 换回真的过渡：这一页的过渡都由脚本播，jsdom 里没有 animate，当场播完（收起后的钩子也跑）
  const mountChart = async (stubs: Record<string, boolean> = {}) => {
    await testRouter.push('/projects')
    await testRouter.isReady()
    view = mount(GitHubProjectsView, {
      attachTo: document.body,
      global: { plugins: [testRouter, i18n], stubs: { Teleport: true, McpPromptExampleList: true, ...stubs } },
    })
    await flushPromises()
    return view
  }
  const press = async (key: string) => {
    window.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))
    await flushPromises()
  }
  const cursorKey = () => {
    const row = view!.find('.project-row.is-cursor')
    return row.exists() ? row.attributes('data-list-key') : null
  }
  const row = (name: string) => view!.get(`[data-list-key="github:acme/${name}"]`)
  // 换页：榜单先撤下等加载，新的一页到了再画
  const arrive = async (items: GitHubProjectItem[]) => {
    controller().loading.value = true
    await flushPromises()
    controller().projects.value = items
    controller().loading.value = false
    await flushPromises()
  }

  it('walks the rows with j / k, favourites with s, opens the tags with x and dims what o opened', async () => {
    controller().projects.value = [chartRepo('alpha', ['agents', 'cli', 'rust', 'mcp']), chartRepo('beta', ['cli']), chartRepo('gamma')]
    controller().total.value = 3
    const wrapper = await mountChart()
    expect(wrapper.findAll('.project-row').map((item) => item.attributes('data-list-key')))
      .toEqual(['github:acme/alpha', 'github:acme/beta', 'github:acme/gamma'])

    await press('j')
    expect(cursorKey()).toBe('github:acme/alpha')
    expect(document.activeElement).toBe(row('alpha').element)
    await press('j')
    await press('k')
    expect(cursorKey()).toBe('github:acme/alpha')

    await press('s')
    expect(controller().toggleFavorite).toHaveBeenCalledWith(expect.objectContaining({ full_name: 'acme/alpha' }))

    await press('x')
    expect(row('alpha').get('.project-row__chip--more').attributes('aria-expanded')).toBe('true')
    expect(row('alpha').findAll('.project-row__chip:not(.project-row__chip--more)')).toHaveLength(4)
    await press('x')
    expect(row('alpha').get('.project-row__chip--more').attributes('aria-expanded')).toBe('false')

    // 只有一个标签的行没有可开合的
    await press('j')
    await press('x')
    expect(row('beta').find('.project-row__chip--more').exists()).toBe(false)

    await press('o')
    expect(window.open).toHaveBeenCalledWith('https://github.com/acme/beta', '_blank', 'noopener')
    expect(row('beta').classes()).toContain('is-read')
    expect(row('alpha').classes()).not.toContain('is-read')

    await press('?')
    expect(wrapper.find('.list-keys-sheet').exists()).toBe(true)
    await press('Escape')
    expect(wrapper.find('.list-keys-sheet').exists()).toBe(false)
    await press('Escape')
    expect(cursorKey()).toBeNull()
  })

  it('pages on past either end and lands the cursor on the first or last row of the new page', async () => {
    controller().projects.value = [chartRepo('alpha'), chartRepo('beta')]
    controller().total.value = 60
    await mountChart()
    await press('j')
    await press('j')
    expect(cursorKey()).toBe('github:acme/beta')
    controller().loadProjects.mockClear()
    routeState().replaceRouteFromState.mockClear()

    await press('j')
    expect(routeState().replaceRouteFromState).toHaveBeenCalledOnce()
    expect(controller().loadProjects).toHaveBeenCalledOnce()
    await arrive([chartRepo('gamma'), chartRepo('delta')])
    expect(cursorKey()).toBe('github:acme/gamma')
    expect(document.activeElement).toBe(row('gamma').element)

    await press('k')
    expect(controller().loadProjects).toHaveBeenCalledTimes(2)
    await arrive([chartRepo('alpha'), chartRepo('beta')])
    expect(cursorKey()).toBe('github:acme/beta')

    // 第一页的第一行再往上没有页可翻，光标不动
    await press('k')
    await press('k')
    expect(cursorKey()).toBe('github:acme/alpha')
    expect(controller().loadProjects).toHaveBeenCalledTimes(2)
  })

  it('keeps repositories opened on an earlier visit dimmed, and leaves the comfortable cards without keys', async () => {
    localStorage.setItem('read_marks_projects', JSON.stringify({ 'github:acme/beta': Math.floor(Date.now() / 60_000) }))
    controller().projects.value = [chartRepo('alpha'), chartRepo('beta')]
    controller().total.value = 2
    const wrapper = await mountChart()
    expect(row('beta').classes()).toContain('is-read')
    expect(row('alpha').classes()).not.toContain('is-read')

    // 点项目名打开的也立刻变淡（jsdom 不跟外链）
    wrapper.element.addEventListener('click', (event: Event) => event.preventDefault())
    await row('alpha').get('.project-row__name a').trigger('click')
    expect(row('alpha').classes()).toContain('is-read')
    wrapper.unmount()
    view = null

    setAppDensity('comfortable')
    const cards = await mountChart()
    expect(cards.find('.project-chart').exists()).toBe(false)
    expect(cards.findAll('.project-card')).toHaveLength(2)
    expect(cards.find('.is-read').exists()).toBe(false)
    await press('j')
    await press('?')
    expect(cards.find('.is-cursor').exists()).toBe(false)
    expect(cards.find('.list-keys-sheet').exists()).toBe(false)
  })

  it('peeks at a row the pointer rests on, keeps it lit, gives Esc to the card before the cursor and dims what the card opened', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] })
    try {
      peekApi.fetchProjectPeek.mockImplementation(async (repoId: string) => ({
        repo_id: repoId, status: 'ok', has_readme: true, readme: [`${repoId} in one paragraph.`], readme_more: false, commit: null,
      }))
      peekApi.fetchProjectTrends.mockResolvedValue({ metric_date: '2026-10-02', previous_date: null, days: 30, items: {} })
      controller().projects.value = [chartRepo('alpha'), chartRepo('beta')]
      controller().total.value = 2
      const wrapper = await mountChart()
      wrapper.element.addEventListener('click', (event: Event) => event.preventDefault())
      let x = 40
      const rest = async (name: string) => {
        const event = new MouseEvent('pointermove', { clientX: x++, clientY: 50, bubbles: true })
        Object.defineProperty(event, 'pointerType', { value: 'mouse' })
        row(name).get('.project-row__desc').element.dispatchEvent(event)
        await vi.advanceTimersByTimeAsync(PEEK_OPEN_DELAY)
        await flushPromises()
      }

      await press('j')
      expect(cursorKey()).toBe('github:acme/alpha')
      await rest('beta')
      expect(wrapper.get('.project-peek').text()).toContain('acme/beta in one paragraph.')
      expect(row('beta').classes()).toContain('is-peeked')
      expect(row('alpha').classes()).not.toContain('is-peeked')
      expect(peekApi.fetchProjectPeek).toHaveBeenCalledWith('acme/beta')
      expect(peekApi.fetchProjectTrends).toHaveBeenCalledWith(['acme/beta', 'acme/alpha'], { days: 30 })

      await press('Escape')
      expect(wrapper.find('.project-peek').exists()).toBe(false)
      expect(row('beta').classes()).not.toContain('is-peeked')
      expect(cursorKey()).toBe('github:acme/alpha')
      await press('Escape')
      expect(cursorKey()).toBeNull()

      // 卡片里去 GitHub 的链接和行上的一样，点过的项目变淡
      await rest('beta')
      expect(row('beta').classes()).not.toContain('is-read')
      await wrapper.get('.project-peek .project-peek__link').trigger('click')
      expect(row('beta').classes()).toContain('is-read')
      expect(peekApi.fetchProjectPeek).toHaveBeenCalledOnce()
    } finally {
      vi.useRealTimers()
    }
  })

  // 宽屏详情栏：README 开头一段、没有提交、曲线空着
  const fakeGitHub = () => {
    peekApi.fetchProjectPeek.mockReset().mockImplementation(async (repoId: string) => ({
      repo_id: repoId, status: 'ok', has_readme: true, readme: [`${repoId} in one paragraph.`], readme_more: false, commit: null,
    }))
    peekApi.fetchProjectTrends.mockReset().mockResolvedValue({ metric_date: '2026-10-02', previous_date: null, days: 30, items: {} })
  }
  const pane = () => view!.find('.project-pane')
  const paneName = () => pane().get('.project-pane__name').text()
  const paneCount = () => pane().get('.project-pane__count').text()

  it('opens a clicked row beside the list on a wide screen, follows j / k there and sends the second o to GitHub', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] })
    try {
      fakeGitHub()
      viewport.wide.value = true
      controller().projects.value = [chartRepo('alpha'), chartRepo('beta'), chartRepo('gamma')]
      controller().total.value = 3
      const wrapper = await mountChart({ transition: false })

      // 点行里空白处：详情在右边打开，不去 GitHub，也不算看过
      await row('beta').trigger('click')
      await flushPromises()
      expect(window.open).not.toHaveBeenCalled()
      expect(paneName()).toBe('acme/beta')
      expect(paneCount()).toBe('2/3')
      expect(pane().text()).toContain('acme/beta in one paragraph.')
      expect(wrapper.classes()).toContain('has-pane')
      expect(row('beta').classes()).toEqual(expect.arrayContaining(['is-paned', 'project-row--paneable']))
      expect(row('beta').attributes('aria-current')).toBe('true')
      expect(row('beta').classes()).not.toContain('is-read')
      // 前后两行的 README 也先取来
      expect(peekApi.fetchProjectPeek.mock.calls.map(([repoId]) => repoId)).toEqual(['acme/beta', 'acme/gamma', 'acme/alpha'])

      // 点项目名也一样
      await row('alpha').get('.project-row__name a').trigger('click')
      await flushPromises()
      expect(paneName()).toBe('acme/alpha')
      expect(row('alpha').classes()).not.toContain('is-read')
      expect(row('beta').attributes('aria-current')).toBeUndefined()
      expect(window.open).not.toHaveBeenCalled()

      // 光标跟着详情走：j / k 换项目，s 收藏的是正在看的
      await press('j')
      expect(cursorKey()).toBe('github:acme/beta')
      expect(paneName()).toBe('acme/beta')
      await press('j')
      expect(paneName()).toBe('acme/gamma')
      await press('k')
      expect(paneName()).toBe('acme/beta')
      expect(row('gamma').classes()).not.toContain('is-paned')
      await press('s')
      expect(controller().toggleFavorite).toHaveBeenCalledWith(expect.objectContaining({ full_name: 'acme/beta' }))

      // 停够一秒算扫过（下次进来变淡），眼下不变淡
      await vi.advanceTimersByTimeAsync(READ_MARKS.dwellMs + READ_MARKS.flushMs)
      expect(Object.keys(JSON.parse(localStorage.getItem('read_marks_projects') ?? '{}'))).toEqual(['github:acme/beta'])
      expect(row('beta').classes()).not.toContain('is-read')

      // 详情栏开着时不浮速览卡片
      const rest = new MouseEvent('pointermove', { clientX: 40, clientY: 50, bubbles: true })
      Object.defineProperty(rest, 'pointerType', { value: 'mouse' })
      row('gamma').get('.project-row__desc').element.dispatchEvent(rest)
      await vi.advanceTimersByTimeAsync(PEEK_OPEN_DELAY)
      await flushPromises()
      expect(wrapper.find('.project-peek').exists()).toBe(false)

      // 详情已经是这一行时 o 才去 GitHub
      await press('o')
      expect(window.open).toHaveBeenCalledWith('https://github.com/acme/beta', '_blank', 'noopener')
      expect(row('beta').classes()).toContain('is-read')

      await press('?')
      expect(wrapper.get('.list-keys-sheet').text()).toContain('listKeys.projectPane')
      await press('Escape')
      expect(wrapper.find('.list-keys-sheet').exists()).toBe(false)
      expect(pane().exists()).toBe(true)

      // Esc 先收详情栏，光标留在那一行；再按一次才收光标
      await press('Escape')
      expect(pane().exists()).toBe(false)
      expect(wrapper.classes()).not.toContain('has-pane')
      expect(cursorKey()).toBe('github:acme/beta')
      await press('Escape')
      expect(cursorKey()).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })

  it('carries the pane on to the next or the previous page from either end, keeping the project in view while it loads', async () => {
    fakeGitHub()
    viewport.wide.value = true
    controller().projects.value = [chartRepo('alpha'), chartRepo('beta')]
    controller().total.value = 60
    await mountChart({ transition: false })
    await row('beta').trigger('click')
    await flushPromises()
    expect(paneCount()).toBe('2/60')
    controller().loadProjects.mockClear()

    await press('j')
    expect(controller().loadProjects).toHaveBeenCalledOnce()
    controller().loading.value = true
    await flushPromises()
    expect(paneName()).toBe('acme/beta')
    expect(pane().find('.project-pane__count').exists()).toBe(false)
    controller().projects.value = [chartRepo('gamma'), chartRepo('delta')]
    controller().loading.value = false
    await flushPromises()
    expect(paneName()).toBe('acme/gamma')
    expect(paneCount()).toBe('21/60')
    expect(cursorKey()).toBe('github:acme/gamma')

    // 栏里的「上一个」也一样，往前翻落在上一页的最后一个
    await pane().findAll('.project-pane__btn')[0]!.trigger('click')
    expect(controller().loadProjects).toHaveBeenCalledTimes(2)
    await arrive([chartRepo('alpha'), chartRepo('beta')])
    expect(paneName()).toBe('acme/beta')
    expect(paneCount()).toBe('2/60')
    expect(row('beta').attributes('aria-current')).toBe('true')
    // 光标悄悄跟到了这一行：键盘从这里接着走
    await press('k')
    expect(cursorKey()).toBe('github:acme/alpha')
    expect(paneName()).toBe('acme/alpha')
  })

  it('hands focus back to the row when the pane closes from inside, closes when the window narrows and leaves narrower desktops on GitHub', async () => {
    fakeGitHub()
    viewport.wide.value = true
    controller().projects.value = [chartRepo('alpha'), chartRepo('beta')]
    controller().total.value = 2
    const wrapper = await mountChart({ transition: false })
    // jsdom 不跟外链
    wrapper.element.addEventListener('click', (event: Event) => event.preventDefault())

    await row('alpha').trigger('click')
    await flushPromises()
    const close = pane().get('.project-pane__close')
    ;(close.element as HTMLElement).focus()
    await close.trigger('click')
    await flushPromises()
    expect(pane().exists()).toBe(false)
    expect(wrapper.classes()).not.toContain('has-pane')
    expect(document.activeElement).toBe(row('alpha').element)
    expect(cursorKey()).toBe('github:acme/alpha')

    await row('beta').trigger('click')
    await flushPromises()
    expect(paneName()).toBe('acme/beta')
    viewport.wide.value = false
    await flushPromises()
    expect(pane().exists()).toBe(false)
    expect(wrapper.classes()).not.toContain('has-pane')
    expect(row('beta').classes()).not.toContain('project-row--paneable')

    // 窄一些的桌面：点行里空白处不动，点项目名去 GitHub
    await row('alpha').trigger('click')
    await flushPromises()
    expect(pane().exists()).toBe(false)
    await row('alpha').get('.project-row__name a').trigger('click')
    expect(row('alpha').classes()).toContain('is-read')
    await press('?')
    expect(wrapper.get('.list-keys-sheet').text()).toContain('listKeys.projectOpen')
  })

  it('keeps the row it opens where it stood while the list narrows and widens, and leaves the top of the page alone', async () => {
    fakeGitHub()
    viewport.wide.value = true
    controller().projects.value = [chartRepo('alpha'), chartRepo('beta')]
    controller().total.value = 2
    const wrapper = await mountChart({ transition: false })
    const page = wrapper.element as HTMLElement
    // 让出右边一栏时榜单变窄、各行折得更高：beta 在页里往下挪 60px
    vi.mocked(HTMLElement.prototype.getBoundingClientRect).mockImplementation(function (this: HTMLElement) {
      const top = this.dataset.listKey === 'github:acme/beta' ? (page.classList.contains('has-pane') ? 460 : 400) - page.scrollTop : 10
      return { top, bottom: top + 80, left: 0, right: 300, width: 300, height: 80, x: 0, y: top, toJSON: () => ({}) } as DOMRect
    })

    page.scrollTop = 300
    await row('beta').trigger('click')
    await flushPromises()
    expect(page.scrollTop).toBe(360)
    await press('Escape')
    await flushPromises()
    expect(wrapper.classes()).not.toContain('has-pane')
    expect(page.scrollTop).toBe(300)

    // 页面还在顶上：标题和搜索框不动，那一行往下挪
    page.scrollTop = 0
    await row('beta').trigger('click')
    await flushPromises()
    expect(wrapper.classes()).toContain('has-pane')
    expect(page.scrollTop).toBe(0)
  })
})
