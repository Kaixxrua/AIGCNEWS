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
import type { GitHubProjectItem } from '@/services/projects/projectApi'

const controllerSpy = vi.hoisted(() => vi.fn())
const routerPush = vi.hoisted(() => vi.fn())
const ctlBox = vi.hoisted(() => ({ current: null as null | Record<string, any> }))
const authBox = vi.hoisted(() => ({ current: null as null | { isLoggedIn: boolean; isAdmin: boolean } }))
const routeStateBox = vi.hoisted(() => ({ current: null as null | Record<string, any> }))

vi.mock('@/router', () => ({ default: { push: routerPush } }))

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
    defaultProjectSortForScope: () => 'stars',
    defaultProjectSortForSource: () => 'stars',
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
      stubs: { Teleport: true },
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
    expect(routerPush).toHaveBeenCalledWith({ path: '/login', query: { redirect: '/projects?source=website' } })
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

  it('reactivates inside keep-alive and refreshes stale reads without clearing content', async () => {
    const Harness = defineComponent({
      components: { GitHubProjectsView },
      setup: () => ({ show: ref(true) }),
      template: '<KeepAlive><GitHubProjectsView v-if="show" /></KeepAlive>',
    })
    await testRouter.push('/projects')
    await testRouter.isReady()
    const wrapper = mount(Harness, {
      global: { plugins: [testRouter, i18n], stubs: { Teleport: true } },
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

  it('redirects anonymous add attempts to login instead of opening the dialog', async () => {
    auth().isLoggedIn = false
    const wrapper = await mountView()
    await switchToWebsiteSource(wrapper)

    await wrapper.find('.projects-add-btn').trigger('click')

    expect(routerPush).toHaveBeenCalledWith({ path: '/login', query: { redirect: '/projects?source=website' } })
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

    expect(routerPush).toHaveBeenCalledWith({ path: '/login', query: { redirect: '/projects' } })
  })
})
