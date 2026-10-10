import { computed, ref, type Ref } from 'vue'
import {
  addMyToolWebsite,
  addMyToolWebsiteManual,
  favoriteProject,
  fetchMyProjectCollection,
  fetchMyToolWebsiteQuota,
  fetchMyProjectTags,
  fetchProjectCategories,
  fetchProjects,
  fetchProjectTaxonomy,
  recommendGitHubProject,
  removeMyToolWebsite,
  unfavoriteProject,
  unrecommendGitHubProject,
  updateMyToolWebsite,
  type GitHubProjectCategory,
  type GitHubProjectItem,
  type GitHubProjectSort,
  type GitHubProjectTag,
  type ManualToolWebsitePayload,
  type ProjectListParams,
  type ProjectScope,
  type ProjectSource,
  type ProjectTaxonomyItem,
  type ProjectViewSource,
  type ToolWebsiteUpdatePayload,
} from '@/services/projects/projectApi'
import {
  canFavoriteProject,
  canRecommendProject,
  isWebsite,
  projectFavoritePayload,
  projectKey,
  projectName,
} from '@/features/projects/projectPresentation'
import { defaultProjectSortForSource } from './useProjectRouteState'

const defaultApi = {
  addMyToolWebsite,
  addMyToolWebsiteManual,
  favoriteProject,
  fetchMyProjectCollection,
  fetchMyToolWebsiteQuota,
  fetchMyProjectTags,
  fetchProjectCategories,
  fetchProjects,
  fetchProjectTaxonomy,
  recommendGitHubProject,
  removeMyToolWebsite,
  unfavoriteProject,
  unrecommendGitHubProject,
  updateMyToolWebsite,
}

export type ProjectCatalogApi = Omit<typeof defaultApi, 'fetchMyToolWebsiteQuota'> & {
  fetchMyToolWebsiteQuota?: typeof fetchMyToolWebsiteQuota
}

type Translate = (key: string, params?: Record<string, unknown>) => string

export interface ProjectCatalogRouteStateRefs {
  source: Ref<ProjectViewSource>
  selectedScope: Ref<ProjectScope>
  selectedCategory: Ref<string>
  selectedSubcategory: Ref<string>
  searchQuery: Ref<string>
  debouncedQuery: Ref<string>
  selectedLanguage: Ref<string>
  selectedTag: Ref<string>
  sort: Ref<GitHubProjectSort>
  page: Ref<number>
}

export interface ProjectCatalogControllerOptions {
  api?: ProjectCatalogApi
  routeState?: ProjectCatalogRouteStateRefs
  t?: Translate
  isLoggedIn?: () => boolean
  ensureAuth?: () => Promise<unknown>
  isAdmin?: () => boolean
  currentRedirect?: () => string
  navigateToLogin?: (redirect: string) => void | Promise<void>
  replaceRouteFromState?: (force?: boolean) => void | Promise<void>
  confirm?: (message: string) => boolean
  now?: () => number
  pageSize?: number
}

export interface ProjectCatalogLoadOptions {
  clearSuccess?: boolean
  preserveContent?: boolean
}

const fallbackCategory = (): GitHubProjectCategory => ({
  slug: 'all',
  name: '全部',
  count: 0,
  kind: 'scope',
  scope: 'all',
  children: [],
})

const errorDetail = (error: unknown) => {
  const candidate = error as { response?: { data?: { detail?: unknown } }; message?: unknown }
  const detail = candidate?.response?.data?.detail
  if (detail && typeof detail === 'object' && 'message' in detail) {
    return String((detail as { message?: unknown }).message ?? candidate?.message ?? error)
  }
  return String(detail ?? candidate?.message ?? error)
}

export const useProjectCatalogController = (options: ProjectCatalogControllerOptions = {}) => {
  const api = options.api ?? defaultApi
  const t: Translate = options.t ?? ((key) => key)
  const loggedIn = options.isLoggedIn ?? (() => false)
  const admin = options.isAdmin ?? (() => false)
  const confirmAction = options.confirm ?? ((message) => window.confirm(message))
  const now = options.now ?? Date.now

  const categories = ref<GitHubProjectCategory[]>([])
  const personalTags = ref<GitHubProjectTag[]>([])
  const projects = ref<GitHubProjectItem[]>([])
  const taxonomy = ref<ProjectTaxonomyItem[]>([])
  const source = options.routeState?.source ?? ref<ProjectViewSource>('all')
  const selectedScope = options.routeState?.selectedScope ?? ref<ProjectScope>('all')
  const selectedCategory = options.routeState?.selectedCategory ?? ref('all')
  const selectedSubcategory = options.routeState?.selectedSubcategory ?? ref('all')
  const searchQuery = options.routeState?.searchQuery ?? ref('')
  const debouncedQuery = options.routeState?.debouncedQuery ?? ref('')
  const selectedLanguage = options.routeState?.selectedLanguage ?? ref('')
  const selectedTag = options.routeState?.selectedTag ?? ref('')
  const sort = options.routeState?.sort ?? ref<GitHubProjectSort>('stars')
  const page = options.routeState?.page ?? ref(1)
  const pageSize = ref(options.pageSize ?? 24)
  const total = ref(0)

  const loading = ref(false)
  const categoriesLoading = ref(false)
  const tagsLoading = ref(false)
  const taxonomyLoading = ref(false)
  const websiteQuota = ref<Awaited<ReturnType<typeof fetchMyToolWebsiteQuota>> | null>(null)
  const websiteQuotaLoading = ref(false)
  const addingTool = ref(false)
  const savingEdit = ref(false)
  const deletingWebsiteId = ref<number | string | null>(null)
  const favoriteBusyKey = ref('')
  const recommendBusyKey = ref('')
  const errorMsg = ref('')
  const successMsg = ref('')
  const addToolError = ref('')
  const editError = ref('')
  const isViewActive = ref(true)
  const lastSuccessfulFetchAt = ref(0)

  const publicSource = computed<ProjectSource>(() => source.value === 'website' ? 'website' : 'github')
  const isPersonalView = computed(() => source.value === 'favorites' || source.value === 'website')
  const isMyCollection = computed(() => isPersonalView.value)
  const requiresPersonalLogin = computed(() => isPersonalView.value && !loggedIn())
  const requiresCatalogLogin = computed(() => !isPersonalView.value && !loggedIn()
    && (Boolean(debouncedQuery.value.trim()) || page.value > 1))
  let promptedLoginTarget = ''

  let viewGeneration = 0
  let projectRequestGeneration = 0
  let categoryRequestGeneration = 0
  let tagRequestGeneration = 0
  let taxonomyRequestGeneration = 0

  const activeGeneration = (generation: number) => isViewActive.value && generation === viewGeneration
  const replaceRoute = (force = false) => options.replaceRouteFromState?.(force)

  const invalidateReads = () => {
    projectRequestGeneration += 1
    categoryRequestGeneration += 1
    tagRequestGeneration += 1
    taxonomyRequestGeneration += 1
  }

  const invalidateView = () => {
    viewGeneration += 1
    invalidateReads()
    loading.value = false
    categoriesLoading.value = false
    tagsLoading.value = false
    taxonomyLoading.value = false
    websiteQuotaLoading.value = false
    addingTool.value = false
    savingEdit.value = false
    deletingWebsiteId.value = null
    favoriteBusyKey.value = ''
    recommendBusyKey.value = ''
  }

  const deactivate = () => {
    isViewActive.value = false
    invalidateView()
  }

  const activate = () => {
    if (isViewActive.value) return
    isViewActive.value = true
    viewGeneration += 1
  }

  const resetFiltersForWebsiteView = () => {
    source.value = 'website'
    selectedScope.value = 'all'
    selectedCategory.value = 'all'
    selectedSubcategory.value = 'all'
    selectedLanguage.value = ''
    selectedTag.value = ''
    searchQuery.value = ''
    debouncedQuery.value = ''
    page.value = 1
    sort.value = defaultProjectSortForSource('website')
  }

  const buildListParams = (): ProjectListParams => ({
    source: publicSource.value,
    scope: selectedScope.value,
    category: selectedCategory.value === 'all' ? '' : selectedCategory.value,
    subcategory: selectedSubcategory.value === 'all' ? '' : selectedSubcategory.value,
    q: debouncedQuery.value.trim(),
    language: selectedLanguage.value,
    tag: isPersonalView.value ? selectedTag.value : '',
    page: page.value,
    page_size: pageSize.value,
    sort: isPersonalView.value && sort.value === 'relevance'
      ? defaultProjectSortForSource(source.value)
      : sort.value,
  })

  const upsertProjectItem = (item: GitHubProjectItem) => {
    const key = projectKey(item)
    const index = projects.value.findIndex((project) => projectKey(project) === key)
    if (index >= 0) projects.value.splice(index, 1, item)
    else {
      projects.value = [item, ...projects.value]
      total.value += 1
    }
  }

  const loadPersonalTags = async () => {
    const request = ++tagRequestGeneration
    const generation = viewGeneration
    if (!isPersonalView.value || requiresPersonalLogin.value) {
      personalTags.value = []
      tagsLoading.value = false
      return
    }
    const requestedSource = publicSource.value
    tagsLoading.value = true
    try {
      const data = await api.fetchMyProjectTags(requestedSource)
      if (!activeGeneration(generation) || request !== tagRequestGeneration || requestedSource !== publicSource.value || !isPersonalView.value) return
      personalTags.value = data.items
    } catch (error) {
      if (!activeGeneration(generation) || request !== tagRequestGeneration) return
      console.error('Failed to load personal tags:', error)
      personalTags.value = []
    } finally {
      if (activeGeneration(generation) && request === tagRequestGeneration) tagsLoading.value = false
    }
  }

  const loadCategories = async () => {
    const request = ++categoryRequestGeneration
    const generation = viewGeneration
    const requestedSource = publicSource.value
    if (isPersonalView.value) {
      categories.value = []
      categoriesLoading.value = false
      selectedCategory.value = 'all'
      selectedSubcategory.value = 'all'
      selectedScope.value = 'all'
      return
    }
    categoriesLoading.value = true
    try {
      const data = await api.fetchProjectCategories(requestedSource)
      if (!activeGeneration(generation) || request !== categoryRequestGeneration || requestedSource !== publicSource.value || isPersonalView.value) return
      categories.value = data.items.length ? data.items : [fallbackCategory()]
      const category = categories.value.find((item) => (item.kind ?? 'category') === 'category' && item.slug === selectedCategory.value)
      let filterChanged = false
      if (selectedCategory.value !== 'all' && !category) {
        selectedCategory.value = 'all'
        selectedSubcategory.value = 'all'
        filterChanged = true
      } else if (selectedSubcategory.value !== 'all' && !category?.children?.some((item) => item.slug === selectedSubcategory.value)) {
        selectedSubcategory.value = 'all'
        filterChanged = true
      }
      if (filterChanged) {
        page.value = 1
        void replaceRoute()
        void loadProjects({ clearSuccess: false })
      }
    } catch (error) {
      if (!activeGeneration(generation) || request !== categoryRequestGeneration) return
      console.error('Failed to load project categories:', error)
      categories.value = [fallbackCategory()]
    } finally {
      if (activeGeneration(generation) && request === categoryRequestGeneration) categoriesLoading.value = false
    }
  }

  const loadTaxonomy = async () => {
    if (!loggedIn() || taxonomy.value.length || taxonomyLoading.value) return
    const request = ++taxonomyRequestGeneration
    const generation = viewGeneration
    taxonomyLoading.value = true
    try {
      const data = await api.fetchProjectTaxonomy()
      if (activeGeneration(generation) && request === taxonomyRequestGeneration) taxonomy.value = data.items
    } catch (error) {
      if (activeGeneration(generation) && request === taxonomyRequestGeneration) console.error('Failed to load project taxonomy:', error)
    } finally {
      if (activeGeneration(generation) && request === taxonomyRequestGeneration) taxonomyLoading.value = false
    }
  }

  const loadProjects = async (loadOptions: ProjectCatalogLoadOptions = {}) => {
    const request = ++projectRequestGeneration
    const generation = viewGeneration
    if (options.ensureAuth) {
      await options.ensureAuth()
      if (!activeGeneration(generation) || request !== projectRequestGeneration) return
    }
    errorMsg.value = ''
    if (loadOptions.clearSuccess !== false) successMsg.value = ''
    if (requiresPersonalLogin.value) {
      projects.value = []
      total.value = 0
      loading.value = false
      return
    }
    if (requiresCatalogLogin.value) {
      projects.value = []
      loading.value = false
      await replaceRoute(true)
      if (!activeGeneration(generation) || request !== projectRequestGeneration || !requiresCatalogLogin.value) return
      // Typing a search shows the inline explanation; only its sign-in action opens the dialog.
      if (debouncedQuery.value.trim()) return
      const target = options.currentRedirect?.() ?? '/projects'
      if (!loadOptions.preserveContent && target !== promptedLoginTarget) {
        promptedLoginTarget = target
        await options.navigateToLogin?.(target)
      }
      return
    }
    promptedLoginTarget = ''
    if (!loadOptions.preserveContent) loading.value = true
    const personalRequest = isMyCollection.value
    try {
      let data = personalRequest
        ? await api.fetchMyProjectCollection(buildListParams())
        : await api.fetchProjects(buildListParams())
      if (!activeGeneration(generation) || request !== projectRequestGeneration || personalRequest !== isMyCollection.value) return
      const maxPage = Math.max(1, Math.ceil(data.total / pageSize.value))
      if (page.value > maxPage) {
        page.value = maxPage
        void replaceRoute()
        data = personalRequest
          ? await api.fetchMyProjectCollection(buildListParams())
          : await api.fetchProjects(buildListParams())
        if (!activeGeneration(generation) || request !== projectRequestGeneration || personalRequest !== isMyCollection.value) return
      }
      projects.value = data.items
      total.value = data.total
      lastSuccessfulFetchAt.value = now()
    } catch (error) {
      if (!activeGeneration(generation) || request !== projectRequestGeneration) return
      console.error('Failed to load projects:', error)
      if (!loadOptions.preserveContent) {
        errorMsg.value = t(personalRequest ? 'projects.loadFavoritesFailed' : 'projects.loadLibraryFailed')
        projects.value = []
        total.value = 0
      }
    } finally {
      if (activeGeneration(generation) && request === projectRequestGeneration) loading.value = false
    }
  }

  const loadWebsiteQuota = async () => {
    if (!loggedIn()) {
      websiteQuota.value = null
      return
    }
    const generation = viewGeneration
    websiteQuotaLoading.value = true
    if (!api.fetchMyToolWebsiteQuota) return
    try {
      const quota = await api.fetchMyToolWebsiteQuota()
      if (activeGeneration(generation)) websiteQuota.value = quota
    } catch (error) {
      console.error('Failed to load website quota:', error)
    } finally {
      if (activeGeneration(generation)) websiteQuotaLoading.value = false
    }
  }

  const refreshReads = async (loadOptions: ProjectCatalogLoadOptions = {}) => {
    const reads = [loadCategories(), loadPersonalTags(), loadProjects(loadOptions)]
    if (loggedIn() && source.value === 'website') reads.push(loadWebsiteQuota())
    await Promise.all(reads)
    if (loggedIn()) await loadTaxonomy()
  }

  const reloadAfterCollectionRemoval = async () => {
    if (!isMyCollection.value) return
    const maxPage = Math.max(1, Math.ceil(total.value / pageSize.value))
    if (page.value > maxPage) {
      page.value = maxPage
      void replaceRoute()
    }
    await Promise.all([loadCategories(), loadPersonalTags(), loadProjects({ clearSuccess: false })])
  }

  const toggleFavorite = async (item: GitHubProjectItem) => {
    if (!loggedIn()) {
      await options.navigateToLogin?.(options.currentRedirect?.() ?? '/projects')
      return
    }
    if (!canFavoriteProject(item) || favoriteBusyKey.value) return
    const generation = viewGeneration
    const key = projectKey(item)
    const previous = Boolean(item.is_favorited)
    const previousAt = item.favorited_at ?? null
    favoriteBusyKey.value = key
    errorMsg.value = ''
    successMsg.value = ''
    item.is_favorited = !previous
    item.favorited_at = previous ? null : new Date(now()).toISOString()
    try {
      const payload = projectFavoritePayload(item)
      const result = previous ? await api.unfavoriteProject(payload) : await api.favoriteProject(payload)
      if (!activeGeneration(generation)) return
      item.is_favorited = result.is_favorited
      item.favorited_at = result.favorited_at ?? item.favorited_at ?? null
      successMsg.value = t(previous ? 'projects.favoriteRemoved' : 'projects.favoriteAdded')
      if (isMyCollection.value && previous) {
        projects.value = projects.value.filter((project) => projectKey(project) !== key)
        total.value = Math.max(0, total.value - 1)
        await reloadAfterCollectionRemoval()
      }
    } catch (error) {
      item.is_favorited = previous
      item.favorited_at = previousAt
      if (activeGeneration(generation)) errorMsg.value = errorDetail(error)
    } finally {
      if (activeGeneration(generation) && favoriteBusyKey.value === key) favoriteBusyKey.value = ''
    }
  }

  const recommendProject = async (item: GitHubProjectItem) => {
    if (!canRecommendProject(item, admin()) || recommendBusyKey.value) return
    const generation = viewGeneration
    const key = projectKey(item)
    const wasRecommended = Boolean(item.is_recommended)
    if (wasRecommended && !confirmAction(t('projects.confirmUnrecommend', { name: projectName(item) }))) return
    recommendBusyKey.value = key
    errorMsg.value = ''
    successMsg.value = ''
    try {
      const payload = { repo_id: item.repo_id, full_name: item.full_name }
      const result = wasRecommended
        ? await api.unrecommendGitHubProject(payload)
        : await api.recommendGitHubProject(payload)
      if (!activeGeneration(generation)) return
      item.is_recommended = result.is_recommended
      item.recommended_at = result.recommended_at ?? null
      successMsg.value = t(wasRecommended ? 'projects.recommendationRemoved' : 'projects.recommendationAdded')
      if (wasRecommended && selectedScope.value === 'recommended') {
        projects.value = projects.value.filter((project) => projectKey(project) !== key)
        total.value = Math.max(0, total.value - 1)
      }
      await loadCategories()
    } catch (error) {
      if (activeGeneration(generation)) errorMsg.value = errorDetail(error)
    } finally {
      if (activeGeneration(generation) && recommendBusyKey.value === key) recommendBusyKey.value = ''
    }
  }

  const submitToolWebsite = async (request: string | ManualToolWebsitePayload) => {
    const generation = viewGeneration
    addingTool.value = true
    addToolError.value = ''
    successMsg.value = ''
    try {
      const result = typeof request === 'string'
        ? await api.addMyToolWebsite(request)
        : await api.addMyToolWebsiteManual(request)
      if (!activeGeneration(generation)) return false
      resetFiltersForWebsiteView()
      successMsg.value = result.message || t(result.duplicate ? 'projects.websiteExists' : 'projects.websiteAdded')
      void replaceRoute(true)
      await Promise.all([loadCategories(), loadPersonalTags(), loadProjects({ clearSuccess: false }), loadWebsiteQuota()])
      return activeGeneration(generation)
    } catch (error) {
      if (activeGeneration(generation)) {
        addToolError.value = errorDetail(error)
        const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
        if (detail && typeof detail === 'object' && 'error' in detail
          && (detail as { error?: unknown }).error === 'personal_website_quota_exceeded') {
          const quota = detail as Record<string, unknown>
          websiteQuota.value = {
            tier: quota.tier === 'member' ? 'member' : 'free',
            unlimited: Boolean(quota.unlimited),
            limit: quota.limit == null ? null : Number(quota.limit),
            used: Number(quota.used ?? 0),
            remaining: quota.remaining == null ? null : Number(quota.remaining),
            window_seconds: Number(quota.window_seconds ?? 86400),
            reset_at: typeof quota.reset_at === 'string' ? quota.reset_at : null,
          }
        }
      }
      return false
    } finally {
      if (activeGeneration(generation)) addingTool.value = false
    }
  }

  const submitEditWebsite = async (websiteId: string | number, payload: ToolWebsiteUpdatePayload) => {
    const generation = viewGeneration
    savingEdit.value = true
    editError.value = ''
    successMsg.value = ''
    try {
      const result = await api.updateMyToolWebsite(websiteId, payload)
      if (!activeGeneration(generation)) return false
      if (result.item) {
        upsertProjectItem(result.item)
      }
      successMsg.value = result.message || t('projects.websiteUpdated')
      await Promise.all([loadPersonalTags(), loadProjects({ clearSuccess: false })])
      return activeGeneration(generation)
    } catch (error) {
      if (activeGeneration(generation)) editError.value = errorDetail(error)
      return false
    } finally {
      if (activeGeneration(generation)) savingEdit.value = false
    }
  }

  const removeToolWebsite = async (item: GitHubProjectItem) => {
    if (!isWebsite(item) || !item.website_id || deletingWebsiteId.value) return
    const name = projectName(item) || t('projects.thisWebsite')
    if (!confirmAction(t('projects.confirmRemoveWebsite', { name }))) return
    const generation = viewGeneration
    deletingWebsiteId.value = item.website_id
    errorMsg.value = ''
    successMsg.value = ''
    try {
      const result = await api.removeMyToolWebsite(item.website_id)
      if (!activeGeneration(generation)) return
      successMsg.value = result.message || t('projects.websiteRemoved')
      projects.value = projects.value.filter((project) => projectKey(project) !== projectKey(item))
      total.value = Math.max(0, total.value - 1)
      await reloadAfterCollectionRemoval()
    } catch (error) {
      if (activeGeneration(generation)) errorMsg.value = errorDetail(error)
    } finally {
      if (activeGeneration(generation) && deletingWebsiteId.value === item.website_id) deletingWebsiteId.value = null
    }
  }

  const handleLogout = () => {
    invalidateView()
    if (!isPersonalView.value && !requiresCatalogLogin.value) return
    projects.value = []
    personalTags.value = []
    total.value = 0
    loading.value = false
    tagsLoading.value = false
    errorMsg.value = ''
    successMsg.value = ''
    websiteQuota.value = null
  }

  return {
    activate,
    addToolError,
    addingTool,
    categories,
    categoriesLoading,
    deactivate,
    debouncedQuery,
    deletingWebsiteId,
    editError,
    errorMsg,
    favoriteBusyKey,
    handleLogout,
    invalidateReads,
    invalidateView,
    isMyCollection,
    isPersonalView,
    isViewActive,
    lastSuccessfulFetchAt,
    loadCategories,
    loadPersonalTags,
    loadProjects,
    loadTaxonomy,
    loadWebsiteQuota,
    loading,
    page,
    pageSize,
    personalTags,
    projects,
    publicSource,
    recommendBusyKey,
    recommendProject,
    refreshReads,
    requiresPersonalLogin,
    requiresCatalogLogin,
    searchQuery,
    savingEdit,
    selectedCategory,
    selectedLanguage,
    selectedScope,
    selectedSubcategory,
    selectedTag,
    sort,
    source,
    submitEditWebsite,
    submitToolWebsite,
    successMsg,
    tagsLoading,
    taxonomy,
    taxonomyLoading,
    toggleFavorite,
    websiteQuota,
    websiteQuotaLoading,
    total,
    removeToolWebsite,
  }
}

export type ProjectCatalogController = ReturnType<typeof useProjectCatalogController>
