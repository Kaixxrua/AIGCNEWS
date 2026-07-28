<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { compareLocaleStrings } from '../i18n/formatters'
import {
  addMyToolWebsite,
  addMyToolWebsiteManual,
  favoriteProject,
  fetchMyProjectCollection,
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
  type ProjectScope,
  type ProjectSource,
  type ManualToolWebsitePayload,
  type ProjectTaxonomyItem,
  type ProjectViewSource,
  type ToolWebsiteUpdatePayload,
} from '../services/api'
import router from '../router'
import { useAuthStore } from '../stores/authStore'
import ProjectResultCard from '../components/projects/ProjectResultCard.vue'
import ToolWebsiteAddDialog from '../components/projects/ToolWebsiteAddDialog.vue'
import ToolWebsiteEditDialog from '../components/projects/ToolWebsiteEditDialog.vue'
import ProjectFiltersPanel from '../components/projects/ProjectFiltersPanel.vue'
import ProjectPagination from '../components/projects/ProjectPagination.vue'
import {
  defaultProjectSortForScope,
  defaultProjectSortForSource,
  useProjectRouteState,
} from '../composables/useProjectRouteState'
import {
  canEditWebsiteProject,
  canFavoriteProject,
  canRecommendProject,
  isWebsite,
  projectFavoritePayload,
  projectKey,
  projectLogoKey,
  projectName,
  type ProjectChip,
} from '../features/projects/projectPresentation'

defineOptions({ name: 'GitHubProjectsView' })
const { t } = useI18n()

const authStore = useAuthStore()
const route = useRoute()
const categories = ref<GitHubProjectCategory[]>([])
const personalTags = ref<GitHubProjectTag[]>([])
const projects = ref<GitHubProjectItem[]>([])
const selectedScope = ref<ProjectScope>('all')
const selectedCategory = ref('all')
const selectedSubcategory = ref('all')
const searchQuery = ref('')
const debouncedQuery = ref('')
const source = ref<ProjectViewSource>('all')
const selectedLanguage = ref('')
const selectedTag = ref('')
const sort = ref<GitHubProjectSort>('stars')
const page = ref(1)
const pageSize = ref(24)
const pageJump = ref('')
const total = ref(0)
const loading = ref(false)
const categoriesLoading = ref(false)
const tagsLoading = ref(false)
const errorMsg = ref('')
const successMsg = ref('')
const addDialogOpen = ref(false)
const taxonomy = ref<ProjectTaxonomyItem[]>([])
const taxonomyLoading = ref(false)
const addingTool = ref(false)
const addToolError = ref('')
const editDialogOpen = ref(false)
const editTarget = ref<GitHubProjectItem | null>(null)
const editError = ref('')
const savingEdit = ref(false)
const deletingWebsiteId = ref<number | string | null>(null)
const favoriteBusyKey = ref('')
const recommendBusyKey = ref('')
const currentRequestId = ref(0)
const categoryRequestId = ref(0)
const tagRequestId = ref(0)
const isViewActive = ref(true)
const VIEW_REFRESH_INTERVAL = 60_000
let lastSuccessfulFetchAt = 0
let hasActivatedOnce = false
let searchTimer: number | undefined

type SourceOption = { value: ProjectViewSource; label: string; hint: string; authOnly?: boolean }

const {
  applyRouteState,
  currentProjectsRedirect,
  endStateBatch,
  isApplyingRouteState,
  isReplacingRoute,
  replaceRouteFromState,
} = useProjectRouteState(route, router, {
  source,
  selectedScope,
  selectedCategory,
  selectedSubcategory,
  searchQuery,
  debouncedQuery,
  selectedLanguage,
  selectedTag,
  sort,
  page,
})

const defaultSortForSource = defaultProjectSortForSource
const defaultSortForScope = (scopeValue: ProjectScope, sourceValue: ProjectViewSource = source.value) => (
  defaultProjectSortForScope(scopeValue, sourceValue)
)

const sourceOptions = computed<SourceOption[]>(() => [
  { value: 'all', label: t('projects.source.allLabel'), hint: t('projects.source.allHint') },
  { value: 'website', label: t('projects.source.websiteLabel'), hint: t('projects.source.websiteHint'), authOnly: true },
  { value: 'favorites', label: t('projects.source.favoritesLabel'), hint: t('projects.source.favoritesHint'), authOnly: true },
])

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
const hasPrev = computed(() => page.value > 1)
const hasNext = computed(() => page.value < totalPages.value)
const scopeCategories = computed(() => categories.value.filter((item) => item.kind === 'scope'))
const allScope = computed(() => scopeCategories.value.find((item) => item.scope === 'all' || item.slug === 'all'))
const recommendedScope = computed(() => scopeCategories.value.find((item) => item.scope === 'recommended' || item.slug === 'recommended'))
const todayScope = computed(() => scopeCategories.value.find((item) => item.scope === 'today' || item.slug === 'today'))
const semanticCategories = computed(() => categories.value.filter((item) => (item.kind ?? 'category') === 'category'))
const activeCategory = computed(() => semanticCategories.value.find((item) => item.slug === selectedCategory.value))
const visibleSubcategories = computed(() => activeCategory.value?.children ?? [])
const activeSubcategory = computed(() => visibleSubcategories.value.find((item) => item.slug === selectedSubcategory.value))
const publicSource = computed<ProjectSource>(() => (source.value === 'website' ? 'website' : 'github'))
const isPersonalView = computed(() => source.value === 'favorites' || source.value === 'website')
const requiresPersonalLogin = computed(() => isPersonalView.value && !authStore.isLoggedIn)
const isMyCollection = computed(() => isPersonalView.value)
const isWebsiteOnlyView = computed(() => source.value === 'website')
const sourceLabel = computed(() => sourceOptions.value.find((item) => item.value === source.value)?.label ?? t('projects.all'))
const personalLoginCopy = computed(() => (
  isWebsiteOnlyView.value
    ? {
        kicker: t('projects.loginWebsiteKicker'),
        title: t('projects.loginWebsiteTitle'),
        description: t('projects.loginWebsiteDescription'),
      }
    : {
        kicker: t('projects.loginFavoritesKicker'),
        title: t('projects.loginFavoritesTitle'),
        description: t('projects.loginFavoritesDescription'),
      }
))
const starsBadgeLabel = computed(() => {
  if (source.value === 'all') return 'GitHub Stars > 500'
  return ''
})
const activeFilterLabel = computed(() => {
  if (selectedTag.value) return t('projects.filterTag', { tag: selectedTag.value })
  if (selectedLanguage.value) return t('projects.filterLanguage', { language: selectedLanguage.value })
  if (isPersonalView.value) return t('projects.noTagFilter')
  if (selectedScope.value === 'recommended') return recommendedScope.value?.name || t('projects.recommended')
  if (selectedScope.value === 'today') return todayScope.value?.name || t('projects.today')
  if (activeCategory.value && activeSubcategory.value) {
    return `${activeCategory.value.name} / ${activeSubcategory.value.name}`
  }
  if (activeCategory.value) return activeCategory.value.name
  return t('projects.allCategories')
})
const hasActiveFilter = computed(() => (
  selectedScope.value !== 'all'
  || selectedCategory.value !== 'all'
  || selectedSubcategory.value !== 'all'
  || !!selectedLanguage.value
  || !!selectedTag.value
))

const repoName = projectName
const logoKey = projectLogoKey
const brokenLogoKeys = ref<Set<string>>(new Set())
const loadedLogoKeys = ref<Set<string>>(new Set())
const isWebsiteLogoLoaded = (repo: GitHubProjectItem) => {
  const key = logoKey(repo)
  return Boolean(key && loadedLogoKeys.value.has(key))
}
const markWebsiteLogoLoaded = (repo: GitHubProjectItem) => {
  const key = logoKey(repo)
  if (!key || loadedLogoKeys.value.has(key)) return
  loadedLogoKeys.value = new Set([...loadedLogoKeys.value, key])
}
const hideBrokenLogo = (repo: GitHubProjectItem) => {
  const key = logoKey(repo)
  if (!key) return
  brokenLogoKeys.value = new Set([...brokenLogoKeys.value, key])
  if (loadedLogoKeys.value.has(key)) {
    const nextLoadedKeys = new Set(loadedLogoKeys.value)
    nextLoadedKeys.delete(key)
    loadedLogoKeys.value = nextLoadedKeys
  }
}
const favoritePayload = projectFavoritePayload
const canFavorite = canFavoriteProject
const canRecommendCard = (repo: GitHubProjectItem) => canRecommendProject(repo, authStore.isAdmin)
const canEditCard = (repo: GitHubProjectItem) => canEditWebsiteProject(repo, isWebsiteOnlyView.value)

const upsertProjectItem = (item: GitHubProjectItem) => {
  const key = projectKey(item)
  const index = projects.value.findIndex((repo) => projectKey(repo) === key)
  if (index >= 0) {
    projects.value.splice(index, 1, item)
  } else {
    projects.value = [item, ...projects.value]
    total.value += 1
  }
}

const mergePersonalTagsFromItems = (items: GitHubProjectItem[]) => {
  if (!isPersonalView.value) return
  const ignoredTags = new Set(['AI 工具', '网页收藏'])
  const counts = new Map(personalTags.value.map((item) => [item.label, item.count]))
  for (const item of items) {
    for (const rawTag of item.tags ?? []) {
      const label = String(rawTag).trim()
      if (!label || ignoredTags.has(label)) continue
      counts.set(label, Math.max(counts.get(label) ?? 0, 1))
    }
  }
  personalTags.value = Array.from(counts.entries())
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count || compareLocaleStrings(a.label, b.label))
}

const loadPersonalTags = async () => {
  const requestId = tagRequestId.value + 1
  tagRequestId.value = requestId
  if (!isPersonalView.value || requiresPersonalLogin.value) {
    personalTags.value = []
    tagsLoading.value = false
    return
  }
  const tagSource = publicSource.value
  tagsLoading.value = true
  try {
    const data = await fetchMyProjectTags(tagSource)
    if (requestId !== tagRequestId.value || !isPersonalView.value || tagSource !== publicSource.value) return
    personalTags.value = data.items
  } catch (error) {
    if (requestId !== tagRequestId.value) return
    console.error('Failed to load personal tags:', error)
    personalTags.value = []
  } finally {
    if (requestId === tagRequestId.value) {
      tagsLoading.value = false
    }
  }
}

const loadCategories = async () => {
  const requestId = categoryRequestId.value + 1
  categoryRequestId.value = requestId
  const categorySource = publicSource.value
  if (isPersonalView.value) {
    categories.value = []
    categoriesLoading.value = false
    if (selectedCategory.value !== 'all' || selectedSubcategory.value !== 'all' || selectedScope.value !== 'all') {
      selectedCategory.value = 'all'
      selectedSubcategory.value = 'all'
      selectedScope.value = 'all'
    }
    return
  }
  categoriesLoading.value = true
  try {
    const data = await fetchProjectCategories(categorySource)
    if (requestId !== categoryRequestId.value || isPersonalView.value || categorySource !== publicSource.value) return
    categories.value = data.items.length
      ? data.items
      : [{ slug: 'all', name: '全部', count: 0, kind: 'scope', scope: 'all', children: [] }]
    let filterChanged = false
    if (selectedCategory.value !== 'all' && !semanticCategories.value.some((item) => item.slug === selectedCategory.value)) {
      selectedCategory.value = 'all'
      selectedSubcategory.value = 'all'
      filterChanged = true
    }
    if (selectedSubcategory.value !== 'all' && !visibleSubcategories.value.some((item) => item.slug === selectedSubcategory.value)) {
      selectedSubcategory.value = 'all'
      filterChanged = true
    }
    if (filterChanged && !isApplyingRouteState.value) {
      page.value = 1
      void replaceRouteFromState()
      loadProjects({ clearSuccess: false })
    }
  } catch (error) {
    if (requestId !== categoryRequestId.value) return
    console.error('Failed to load project categories:', error)
    categories.value = [{ slug: 'all', name: '全部', count: 0, kind: 'scope', scope: 'all', children: [] }]
  } finally {
    if (requestId === categoryRequestId.value) {
      categoriesLoading.value = false
    }
  }
}

const loadTaxonomy = async () => {
  if (!authStore.isLoggedIn || taxonomy.value.length || taxonomyLoading.value) return
  taxonomyLoading.value = true
  try {
    const data = await fetchProjectTaxonomy()
    taxonomy.value = data.items
  } catch (error) {
    console.error('Failed to load project taxonomy:', error)
  } finally {
    taxonomyLoading.value = false
  }
}

const loadProjects = async (options: { clearSuccess?: boolean; preserveContent?: boolean } = {}) => {
  const requestId = currentRequestId.value + 1
  currentRequestId.value = requestId
  errorMsg.value = ''
  if (options.clearSuccess !== false) successMsg.value = ''
  if (requiresPersonalLogin.value) {
    projects.value = []
    total.value = 0
    loading.value = false
    return
  }
  if (!options.preserveContent) loading.value = true

  try {
    const loadParams = () => ({
      source: publicSource.value,
      scope: selectedScope.value,
      category: selectedCategory.value === 'all' ? '' : selectedCategory.value,
      subcategory: selectedSubcategory.value === 'all' ? '' : selectedSubcategory.value,
      q: debouncedQuery.value.trim(),
      language: selectedLanguage.value,
      tag: isPersonalView.value ? selectedTag.value : '',
      page: page.value,
      page_size: pageSize.value,
      sort: sort.value,
    })
    let data = isMyCollection.value
      ? await fetchMyProjectCollection(loadParams())
      : await fetchProjects(loadParams())
    if (requestId !== currentRequestId.value) return
    const maxPage = Math.max(1, Math.ceil(data.total / pageSize.value))
    if (page.value > maxPage) {
      page.value = maxPage
      void replaceRouteFromState()
      data = isMyCollection.value
        ? await fetchMyProjectCollection(loadParams())
        : await fetchProjects(loadParams())
      if (requestId !== currentRequestId.value) return
    }
    projects.value = data.items
    total.value = data.total
    lastSuccessfulFetchAt = Date.now()
    mergePersonalTagsFromItems(data.items)
  } catch (error) {
    if (requestId !== currentRequestId.value) return
    console.error('Failed to load projects:', error)
    if (!options.preserveContent) {
      errorMsg.value = t(isMyCollection.value ? 'projects.loadFavoritesFailed' : 'projects.loadLibraryFailed')
      projects.value = []
      total.value = 0
    }
  } finally {
    if (requestId === currentRequestId.value) {
      loading.value = false
    }
  }
}

const resetAndLoad = () => {
  if (isApplyingRouteState.value) return
  page.value = 1
  void replaceRouteFromState()
  loadProjects()
}

const changeSource = (nextSource: ProjectViewSource) => {
  if (source.value === nextSource) return
  const nextSort = defaultSortForSource(nextSource)
  isApplyingRouteState.value = true
  source.value = nextSource
  resetScopeToAll()
  selectedCategory.value = 'all'
  selectedSubcategory.value = 'all'
  selectedLanguage.value = ''
  selectedTag.value = ''
  page.value = 1
  sort.value = nextSort
  endStateBatch()
  void replaceRouteFromState(true)
  loadCategories()
  loadProjects()
}

const selectScope = (scope: ProjectScope) => {
  if (
    selectedScope.value === scope
    && selectedCategory.value === 'all'
    && selectedSubcategory.value === 'all'
    && !selectedLanguage.value
  ) return
  selectedScope.value = scope
  selectedCategory.value = 'all'
  selectedSubcategory.value = 'all'
  selectedLanguage.value = ''
  selectedTag.value = ''
  sort.value = defaultSortForScope(scope)
}

const resetScopeToAll = () => {
  selectedScope.value = 'all'
}

const clearLanguageFilter = () => {
  if (!selectedLanguage.value) return
  selectedLanguage.value = ''
}

const selectPersonalTag = (tag: string) => {
  const cleanTag = tag.trim()
  if (!cleanTag || selectedTag.value === cleanTag) return
  resetScopeToAll()
  selectedCategory.value = 'all'
  selectedSubcategory.value = 'all'
  selectedLanguage.value = ''
  selectedTag.value = cleanTag
  page.value = 1
}

const clearPersonalTag = () => {
  if (!selectedTag.value) return
  selectedTag.value = ''
  page.value = 1
}

const selectCategory = (slug: string) => {
  if (selectedScope.value === 'all' && selectedCategory.value === slug && selectedSubcategory.value === 'all') return
  resetScopeToAll()
  selectedCategory.value = slug
  selectedSubcategory.value = 'all'
  selectedLanguage.value = ''
  selectedTag.value = ''
}

const selectSubcategory = (slug: string) => {
  if (selectedSubcategory.value === slug) return
  resetScopeToAll()
  selectedSubcategory.value = slug
  selectedLanguage.value = ''
  selectedTag.value = ''
}

const handleChipClick = (chip: ProjectChip) => {
  page.value = 1
  if (chip.type === 'subcategory') {
    resetScopeToAll()
    selectedCategory.value = chip.categorySlug || selectedCategory.value
    selectedSubcategory.value = chip.value
    selectedLanguage.value = ''
    selectedTag.value = ''
    searchQuery.value = ''
    debouncedQuery.value = ''
    return
  }
  if (chip.type === 'category') {
    resetScopeToAll()
    selectedCategory.value = chip.value
    selectedSubcategory.value = 'all'
    selectedLanguage.value = ''
    selectedTag.value = ''
    searchQuery.value = ''
    debouncedQuery.value = ''
    return
  }
  if (chip.type === 'language') {
    if (source.value === 'website') {
      source.value = 'all'
      loadCategories()
    }
    resetScopeToAll()
    selectedCategory.value = 'all'
    selectedSubcategory.value = 'all'
    selectedLanguage.value = chip.value
    selectedTag.value = ''
    searchQuery.value = ''
    debouncedQuery.value = ''
    return
  }
  if (chip.type === 'tag' && isPersonalView.value) {
    searchQuery.value = ''
    debouncedQuery.value = ''
    selectPersonalTag(chip.value)
    return
  }
  resetScopeToAll()
  selectedCategory.value = 'all'
  selectedSubcategory.value = 'all'
  selectedLanguage.value = ''
  selectedTag.value = ''
  searchQuery.value = chip.value
  debouncedQuery.value = chip.value
}

const goPage = (nextPage: number) => {
  const target = Math.max(1, Math.min(totalPages.value, nextPage))
  pageJump.value = ''
  if (target === page.value) return
  page.value = target
  void replaceRouteFromState()
  loadProjects()
}

const jumpToPage = () => {
  const parsed = Number(pageJump.value)
  if (!Number.isFinite(parsed) || parsed < 1) {
    pageJump.value = ''
    return
  }
  goPage(Math.floor(parsed))
}

watch(searchQuery, (value) => {
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => {
    debouncedQuery.value = value
  }, 280)
})

const goToPersonalLogin = () => {
  router.push({ path: '/login', query: { redirect: currentProjectsRedirect() } })
}

const openAddDialog = () => {
  if (!authStore.isLoggedIn) {
    router.push({ path: '/login', query: { redirect: '/projects?source=website' } })
    return
  }
  addToolError.value = ''
  addDialogOpen.value = true
  loadTaxonomy()
}

const closeAddDialog = () => {
  if (addingTool.value) return
  addDialogOpen.value = false
  addToolError.value = ''
}

const openEditDialog = (repo: GitHubProjectItem) => {
  if (!canEditCard(repo)) return
  editTarget.value = repo
  editError.value = ''
  editDialogOpen.value = true
  loadTaxonomy()
}

const closeEditDialog = () => {
  if (savingEdit.value) return
  editDialogOpen.value = false
  editError.value = ''
  editTarget.value = null
}

const submitEditWebsite = async (
  websiteId: string | number,
  payload: ToolWebsiteUpdatePayload,
) => {
  savingEdit.value = true
  editError.value = ''
  successMsg.value = ''
  try {
    const result = await updateMyToolWebsite(websiteId, payload)
    if (result.item) {
      upsertProjectItem(result.item)
      mergePersonalTagsFromItems([result.item])
    }
    successMsg.value = result.message || '网页收藏信息已更新。'
    editDialogOpen.value = false
    editTarget.value = null
    await Promise.all([loadPersonalTags(), loadProjects({ clearSuccess: false })])
  } catch (error: any) {
    editError.value = error?.response?.data?.detail || error?.message || String(error)
  } finally {
    savingEdit.value = false
  }
}

const refreshAfterWebsiteMutation = async () => {
  if (source.value !== 'website') {
    source.value = 'website'
    sort.value = defaultSortForSource('website')
  }
  resetScopeToAll()
  selectedCategory.value = 'all'
  selectedSubcategory.value = 'all'
  selectedLanguage.value = ''
  selectedTag.value = ''
  searchQuery.value = ''
  debouncedQuery.value = ''
  page.value = 1
  void replaceRouteFromState(true)
  await Promise.all([loadCategories(), loadPersonalTags(), loadProjects({ clearSuccess: false })])
}

const reloadAfterCollectionRemoval = async () => {
  if (!isMyCollection.value) return
  const maxPage = Math.max(1, Math.ceil(total.value / pageSize.value))
  if (page.value > maxPage) {
    page.value = maxPage
    void replaceRouteFromState()
  }
  await Promise.all([loadCategories(), loadPersonalTags(), loadProjects({ clearSuccess: false })])
}

const recommendProject = async (repo: GitHubProjectItem) => {
  if (!canRecommendCard(repo)) return
  const key = projectKey(repo)
  if (recommendBusyKey.value) return
  const wasRecommended = Boolean(repo.is_recommended)
  if (wasRecommended && !window.confirm(`确定取消「${repoName(repo)}」的站长推荐吗？`)) return
  recommendBusyKey.value = key
  errorMsg.value = ''
  successMsg.value = ''
  try {
    const payload = { repo_id: repo.repo_id, full_name: repo.full_name }
    const result = wasRecommended
      ? await unrecommendGitHubProject(payload)
      : await recommendGitHubProject(payload)
    repo.is_recommended = result.is_recommended
    repo.recommended_at = result.recommended_at ?? null
    successMsg.value = result.message || (wasRecommended ? '已取消站长推荐。' : '已加入站长推荐。')
    if (wasRecommended && selectedScope.value === 'recommended') {
      projects.value = projects.value.filter((item) => projectKey(item) !== key)
      total.value = Math.max(0, total.value - 1)
    }
    await loadCategories()
  } catch (error: any) {
    errorMsg.value = error?.response?.data?.detail || String(error)
  } finally {
    recommendBusyKey.value = ''
  }
}

const toggleFavorite = async (repo: GitHubProjectItem) => {
  if (!authStore.isLoggedIn) {
    router.push({ path: '/login', query: { redirect: currentProjectsRedirect() } })
    return
  }
  if (!canFavorite(repo)) return
  const key = projectKey(repo)
  if (favoriteBusyKey.value) return
  const previous = Boolean(repo.is_favorited)
  const previousAt = repo.favorited_at ?? null
  favoriteBusyKey.value = key
  errorMsg.value = ''
  successMsg.value = ''
  repo.is_favorited = !previous
  repo.favorited_at = previous ? null : new Date().toISOString()
  try {
    const payload = favoritePayload(repo)
    const result = previous ? await unfavoriteProject(payload) : await favoriteProject(payload)
    repo.is_favorited = result.is_favorited
    repo.favorited_at = result.favorited_at ?? repo.favorited_at ?? null
    successMsg.value = result.message
    if (isMyCollection.value && previous) {
      projects.value = projects.value.filter((item) => projectKey(item) !== key)
      total.value = Math.max(0, total.value - 1)
      await reloadAfterCollectionRemoval()
    }
  } catch (error: any) {
    repo.is_favorited = previous
    repo.favorited_at = previousAt
    errorMsg.value = error?.response?.data?.detail || String(error)
  } finally {
    favoriteBusyKey.value = ''
  }
}

const submitToolWebsite = async (
  request: string | ManualToolWebsitePayload,
) => {
  addingTool.value = true
  addToolError.value = ''
  successMsg.value = ''
  try {
    const result = typeof request === 'string'
      ? await addMyToolWebsite(request)
      : await addMyToolWebsiteManual(request)
    if (result.item) mergePersonalTagsFromItems([result.item])
    successMsg.value = result.message || (result.duplicate ? '网页收藏已存在。' : '网页收藏已添加。')
    addDialogOpen.value = false
    await refreshAfterWebsiteMutation()
  } catch (error: any) {
    addToolError.value = error?.response?.data?.detail || error?.message || String(error)
  } finally {
    addingTool.value = false
  }
}

const removeToolWebsite = async (repo: GitHubProjectItem) => {
  if (!isWebsite(repo) || !repo.website_id || deletingWebsiteId.value) return
  const name = repoName(repo) || '这个工具网页'
  const message = `确定把「${name}」移出你的个人网页收藏吗？不会影响其他用户。`
  if (!window.confirm(message)) return
  deletingWebsiteId.value = repo.website_id
  errorMsg.value = ''
  successMsg.value = ''
  try {
    const result = await removeMyToolWebsite(repo.website_id)
    successMsg.value = result.message || '已移出我的收藏。'
    projects.value = projects.value.filter((item) => projectKey(item) !== projectKey(repo))
    total.value = Math.max(0, total.value - 1)
    await reloadAfterCollectionRemoval()
  } catch (error: any) {
    errorMsg.value = error?.response?.data?.detail || String(error)
  } finally {
    deletingWebsiteId.value = null
  }
}

watch([selectedScope, selectedCategory, selectedSubcategory, selectedLanguage, selectedTag, debouncedQuery, sort], resetAndLoad)
watch(
  () => route.query,
  () => {
    if (!isViewActive.value || route.name !== 'github-projects' || isReplacingRoute.value) return
    if (!applyRouteState()) return
    loadCategories()
    loadPersonalTags()
    loadProjects()
  },
  { deep: true },
)
watch(() => authStore.isLoggedIn, (loggedIn) => {
  if (!loggedIn && isPersonalView.value) {
    currentRequestId.value += 1
    tagRequestId.value += 1
    projects.value = []
    personalTags.value = []
    total.value = 0
    loading.value = false
    tagsLoading.value = false
    errorMsg.value = ''
    successMsg.value = ''
    addDialogOpen.value = false
    editDialogOpen.value = false
    editTarget.value = null
    return
  }
  loadCategories()
  loadPersonalTags()
  loadProjects()
  if (loggedIn) loadTaxonomy()
})

const stopViewReads = () => {
  if (searchTimer) {
    window.clearTimeout(searchTimer)
    searchTimer = undefined
  }
  currentRequestId.value += 1
  categoryRequestId.value += 1
  tagRequestId.value += 1
}

const refreshProjectsInBackground = async () => {
  await Promise.all([
    loadCategories(),
    loadPersonalTags(),
    loadProjects({ clearSuccess: false, preserveContent: true }),
  ])
  if (authStore.isLoggedIn) await loadTaxonomy()
}

onMounted(() => {
  if (!applyRouteState()) return
  loadCategories()
  loadPersonalTags()
  loadProjects()
  if (authStore.isLoggedIn) loadTaxonomy()
})

onActivated(() => {
  isViewActive.value = true
  if (!hasActivatedOnce) {
    hasActivatedOnce = true
    return
  }
  if (searchQuery.value !== debouncedQuery.value) {
    searchTimer = window.setTimeout(() => {
      debouncedQuery.value = searchQuery.value
    }, 280)
  }
  if (Date.now() - lastSuccessfulFetchAt >= VIEW_REFRESH_INTERVAL) {
    void refreshProjectsInBackground()
  }
})

onDeactivated(() => {
  isViewActive.value = false
  stopViewReads()
})

onBeforeUnmount(stopViewReads)
</script>

<template>
  <div class="projects-page">
    <section class="projects-hero glass-card">
      <div class="projects-hero__text">
        <p class="projects-kicker">AI TOOL ATLAS</p>
        <h1>{{ t('navigation.projects') }}</h1>
        <p>{{ t('projects.publicLibrary') }}</p>
      </div>

      <div class="projects-hero__side">
        <div class="projects-hero__stats" :aria-label="t('projects.results', { count: total })">
          <span>{{ t('projects.results', { count: total }) }}</span>
          <span>{{ sourceLabel }}</span>
          <span v-if="starsBadgeLabel">{{ starsBadgeLabel }}</span>
          <span>{{ activeFilterLabel }}</span>
        </div>
        <button
          v-if="isWebsiteOnlyView && !requiresPersonalLogin"
          type="button"
          class="projects-add-btn"
          :title="isMyCollection && !authStore.isLoggedIn ? t('projects.loginAction') : ''"
          @click="openAddDialog"
        >
          <span>＋</span>
          {{ t('projects.addWebsite') }}
        </button>
      </div>
    </section>

    <ProjectFiltersPanel
      v-model:search-query="searchQuery"
      v-model:sort="sort"
      :source-options="sourceOptions"
      :source="source"
      :requires-personal-login="requiresPersonalLogin"
      :selected-language="selectedLanguage"
      :selected-scope="selectedScope"
      :is-website-only-view="isWebsiteOnlyView"
      :is-personal-view="isPersonalView"
      :categories-loading="categoriesLoading"
      :tags-loading="tagsLoading"
      :all-scope="allScope"
      :recommended-scope="recommendedScope"
      :today-scope="todayScope"
      :semantic-categories="semanticCategories"
      :active-category="activeCategory"
      :visible-subcategories="visibleSubcategories"
      :selected-category="selectedCategory"
      :selected-subcategory="selectedSubcategory"
      :personal-tags="personalTags"
      :selected-tag="selectedTag"
      @change-source="changeSource"
      @clear-language="clearLanguageFilter"
      @select-scope="selectScope"
      @select-category="selectCategory"
      @select-subcategory="selectSubcategory"
      @select-personal-tag="selectPersonalTag"
      @clear-personal-tag="clearPersonalTag"
    />

    <section v-if="successMsg && !requiresPersonalLogin" class="projects-toast projects-toast--success glass-card">
      {{ successMsg }}
    </section>

    <section v-if="requiresPersonalLogin" class="projects-login-prompt glass-card" aria-labelledby="personal-login-title">
      <div class="projects-login-prompt__mark" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
          <rect x="4" y="10" width="16" height="11" rx="3" />
          <path d="M8 10V7a4 4 0 0 1 8 0v3" />
          <path d="M12 14v3" />
        </svg>
      </div>
      <div class="projects-login-prompt__copy">
        <p class="projects-kicker">{{ personalLoginCopy.kicker }}</p>
        <h2 id="personal-login-title">{{ personalLoginCopy.title }}</h2>
        <p>{{ personalLoginCopy.description }}</p>
        <div class="projects-login-prompt__notes" aria-label="登录后可用功能">
          <span>{{ isWebsiteOnlyView ? '私人收藏夹' : '收藏同步' }}</span>
          <span>标签整理</span>
          <span>跨设备访问</span>
        </div>
      </div>
      <button type="button" class="projects-login-prompt__action" @click="goToPersonalLogin">
        {{ t('projects.loginAction') }}
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M5 12h14" />
          <path d="m14 7 5 5-5 5" />
        </svg>
      </button>
    </section>

    <template v-else>
    <section v-if="errorMsg" class="projects-toast projects-toast--error glass-card">
      {{ errorMsg }}
    </section>

    <section v-if="loading" class="projects-grid" :aria-label="t('common.loading')">
      <article v-for="index in 9" :key="index" class="project-card project-card--skeleton glass-card">
        <div class="h-4 w-2/3 rounded-full bg-stone-200/80" />
        <div class="space-y-2">
          <div class="h-3 w-full rounded-full bg-stone-100" />
          <div class="h-3 w-4/5 rounded-full bg-stone-100" />
          <div class="h-3 w-3/5 rounded-full bg-stone-100" />
        </div>
        <div class="flex flex-wrap gap-2">
          <div class="h-6 w-20 rounded-full bg-stone-100" />
          <div class="h-6 w-16 rounded-full bg-stone-100" />
        </div>
        <div class="mt-auto h-9 rounded-full bg-stone-100" />
      </article>
    </section>

    <section v-else-if="projects.length === 0 && !errorMsg" class="empty-state glass-card">
      <p class="projects-kicker">EMPTY COLLECTION</p>
      <h2>{{ searchQuery || hasActiveFilter ? '没有找到匹配条目' : (isWebsiteOnlyView ? '你的网页收藏还空着' : (source === 'favorites' ? '你的 GitHub 收藏还空着' : '项目库正在等待收录')) }}</h2>
      <p>{{ searchQuery || hasActiveFilter ? '试试清空关键词、切换来源或切换分类。' : (isWebsiteOnlyView ? '点击右上角添加你自己的网页收藏。' : (source === 'favorites' ? '点击 GitHub 项目卡片上的收藏按钮加入这里。' : 'GitHub 项目会自动回填分类；登录后可以维护自己的网页收藏。')) }}</p>
    </section>

    <section v-else class="projects-grid" :aria-label="t('navigation.projects')">
      <ProjectResultCard
        v-for="(repo, index) in projects"
        :key="repo.id ?? repo.repo_id ?? repo.website_id ?? repo.full_name ?? index"
        :repo="repo"
        :index="index"
        :is-personal-view="isPersonalView"
        :can-favorite="canFavorite(repo)"
        :can-recommend="canRecommendCard(repo)"
        :can-edit="canEditCard(repo)"
        :show-delete="isPersonalView && isWebsite(repo)"
        :is-logged-in="authStore.isLoggedIn"
        :favorite-busy="favoriteBusyKey === projectKey(repo)"
        :favorite-actions-busy="Boolean(favoriteBusyKey)"
        :recommend-busy="recommendBusyKey === projectKey(repo)"
        :recommend-actions-busy="Boolean(recommendBusyKey)"
        :saving-edit="savingEdit && editTarget?.website_id === repo.website_id"
        :deleting="deletingWebsiteId === repo.website_id"
        :logo-loaded="isWebsiteLogoLoaded(repo)"
        :logo-broken="brokenLogoKeys.has(projectLogoKey(repo))"
        :sort="sort"
        :scope="selectedScope"
        @chip-click="handleChipClick"
        @favorite="toggleFavorite"
        @recommend="recommendProject"
        @edit="openEditDialog"
        @delete="removeToolWebsite"
        @logo-loaded="markWebsiteLogoLoaded"
        @logo-broken="hideBrokenLogo"
      />
    </section>

    <ProjectPagination
      v-if="total > pageSize && !loading"
      v-model:page-jump="pageJump"
      :page="page"
      :total-pages="totalPages"
      :total="total"
      :has-prev="hasPrev"
      :has-next="hasNext"
      @go-page="goPage"
      @jump-to-page="jumpToPage"
    />
    </template>

    <ToolWebsiteAddDialog
      :open="addDialogOpen"
      :active="isViewActive"
      :is-my-collection="isMyCollection"
      :taxonomy="taxonomy"
      :taxonomy-loading="taxonomyLoading"
      :busy="addingTool"
      :error="addToolError"
      @close="closeAddDialog"
      @submit-auto="submitToolWebsite"
      @submit-manual="submitToolWebsite"
    />
    <ToolWebsiteEditDialog
      :open="editDialogOpen"
      :active="isViewActive"
      :target="editTarget"
      :taxonomy="taxonomy"
      :taxonomy-loading="taxonomyLoading"
      :busy="savingEdit"
      :error="editError"
      @close="closeEditDialog"
      @submit="submitEditWebsite"
    />
  </div>
</template>

<style scoped>
.projects-page {
  --projects-accent: #0e7490;
  --projects-accent-soft: rgba(6, 182, 212, 0.10);
  --projects-accent-border: rgba(6, 182, 212, 0.20);
  --projects-warm: #a16207;
  --projects-warm-soft: rgba(245, 158, 11, 0.12);
  --projects-success: #047857;
  --projects-error: #be123c;
  position: relative;
  height: 100%;
  overflow-y: auto;
  padding: 24px 24px 96px;
}

.projects-page::before {
  content: '';
  position: fixed;
  inset: auto 14% 10% auto;
  width: 320px;
  height: 320px;
  pointer-events: none;
  background:
    radial-gradient(circle at 30% 30%, var(--projects-accent-soft), transparent 62%),
    radial-gradient(circle at 70% 70%, rgba(68, 64, 60, 0.07), transparent 58%);
  filter: blur(28px);
  opacity: 0.8;
}

.projects-hero {
  position: relative;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  overflow: hidden;
  margin-bottom: 16px;
  padding: 18px 20px;
}

.projects-hero::after {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0.46;
  background-image:
    linear-gradient(rgba(168, 162, 158, 0.09) 1px, transparent 1px),
    linear-gradient(90deg, rgba(168, 162, 158, 0.09) 1px, transparent 1px);
  background-size: 28px 28px;
  mask-image: linear-gradient(90deg, transparent, #000 18%, #000 82%, transparent);
}

.projects-hero__text {
  position: relative;
  z-index: 1;
  max-width: 660px;
}

.projects-kicker {
  margin-bottom: 8px;
  color: var(--projects-accent);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.22em;
}

.projects-hero h1,
.empty-state h2 {
  font-family: 'Playfair Display', serif;
  color: #292524;
  line-height: 1;
}

.projects-hero h1 {
  font-size: clamp(30px, 4vw, 48px);
  font-weight: 600;
  letter-spacing: -0.04em;
}

.projects-hero p:not(.projects-kicker),
.empty-state p:not(.projects-kicker) {
  margin-top: 12px;
  color: #78716c;
  font-size: 14px;
  line-height: 1.8;
}

.projects-hero__side {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: flex-end;
  flex-direction: column;
  gap: 12px;
}

.projects-hero__stats {
  position: relative;
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  max-width: 300px;
}

.projects-hero__stats span {
  border-radius: 999px;
  padding: 8px 12px;
  color: #57534e;
  background: rgba(255, 255, 255, 0.76);
  border: 1px solid rgba(168, 162, 158, 0.20);
  font-size: 12px;
  font-weight: 700;
}

.projects-add-btn,
.projects-add-submit {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 0;
  border-radius: 999px;
  padding: 11px 16px;
  color: #fff;
  background: #44403c;
  box-shadow: 0 10px 24px rgba(0, 0, 0, 0.10);
  font-size: 13px;
  font-weight: 800;
  cursor: pointer;
  transition: transform 160ms ease, box-shadow 160ms ease, opacity 160ms ease, background 160ms ease;
}

.projects-add-btn:hover,
.projects-add-submit:hover {
  background: #292524;
  transform: translateY(-1px);
  box-shadow: 0 14px 28px rgba(0, 0, 0, 0.14);
}

.projects-add-btn span {
  font-size: 16px;
  line-height: 1;
}

.projects-add-submit:disabled,
.projects-add-btn:disabled {
  cursor: wait;
  opacity: 0.68;
  transform: none;
}

.projects-login-prompt {
  position: relative;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 24px;
  min-height: 250px;
  overflow: hidden;
  padding: 34px;
  background:
    linear-gradient(120deg, rgba(255, 255, 255, 0.92), rgba(245, 245, 244, 0.78)),
    radial-gradient(circle at 84% 20%, var(--projects-accent-soft), transparent 34%);
}

.projects-login-prompt::before {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0.52;
  background-image:
    linear-gradient(rgba(168, 162, 158, 0.10) 1px, transparent 1px),
    linear-gradient(90deg, rgba(168, 162, 158, 0.10) 1px, transparent 1px);
  background-size: 28px 28px;
  mask-image: linear-gradient(90deg, #000, transparent 72%);
}

.projects-login-prompt > * {
  position: relative;
  z-index: 1;
}

.projects-login-prompt__mark {
  display: grid;
  width: 74px;
  height: 74px;
  place-items: center;
  border: 1px solid var(--projects-accent-border);
  border-radius: 26px;
  color: var(--projects-accent);
  background: rgba(236, 254, 255, 0.72);
  box-shadow: 0 18px 45px var(--projects-accent-soft);
  transform: rotate(-3deg);
}

.projects-login-prompt__mark svg {
  width: 32px;
  height: 32px;
}

.projects-login-prompt__copy {
  max-width: 660px;
}

.projects-login-prompt__copy h2 {
  color: #292524;
  font-family: 'Playfair Display', serif;
  font-size: clamp(28px, 4vw, 42px);
  font-weight: 600;
  line-height: 1.08;
  letter-spacing: -0.035em;
}

.projects-login-prompt__copy > p:not(.projects-kicker) {
  max-width: 620px;
  margin-top: 12px;
  color: #78716c;
  font-size: 14px;
  line-height: 1.8;
}

.projects-login-prompt__notes {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 18px;
}

.projects-login-prompt__notes span {
  border: 1px solid rgba(168, 162, 158, 0.22);
  border-radius: 999px;
  padding: 6px 10px;
  color: #57534e;
  background: rgba(255, 255, 255, 0.68);
  font-size: 11px;
  font-weight: 800;
}

.projects-login-prompt__action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  border: 0;
  border-radius: 999px;
  padding: 13px 19px;
  color: #fff;
  background: #292524;
  box-shadow: 0 16px 34px rgba(41, 37, 36, 0.16);
  font-size: 13px;
  font-weight: 800;
  white-space: nowrap;
  transition: transform 160ms ease, box-shadow 160ms ease, background 160ms ease;
}

.projects-login-prompt__action:hover {
  background: var(--projects-accent);
  box-shadow: 0 18px 38px rgba(14, 116, 144, 0.20);
  transform: translateY(-2px);
}

.projects-login-prompt__action svg {
  width: 16px;
  height: 16px;
}

.projects-grid {
  position: relative;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
}

.project-card {
  position: relative;
  display: flex;
  min-height: 248px;
  flex-direction: column;
  gap: 18px;
  overflow: hidden;
  padding: 22px;
}

.project-card::before {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  background:
    linear-gradient(135deg, rgba(255, 255, 255, 0.88), transparent 42%),
    radial-gradient(circle at 14% 0%, rgba(168, 162, 158, 0.10), transparent 34%);
  opacity: 0.92;
}

.project-card--skeleton {
  min-height: 248px;
  animation: pulse 1.5s ease-in-out infinite;
}

.empty-state {
  padding: 42px;
  text-align: center;
}

.empty-state h2 {
  font-size: 34px;
  font-weight: 600;
}

.projects-toast {
  margin: -2px 0 14px;
  padding: 12px 16px;
  font-size: 13px;
  font-weight: 700;
}

.projects-toast--success,
.projects-toast--error {
  color: #44403c;
  background: rgba(255, 255, 255, 0.82);
  border: 1px solid rgba(168, 162, 158, 0.24);
  border-left-width: 3px;
}

.projects-toast--success {
  border-left-color: var(--projects-success);
}

.projects-toast--error {
  border-left-color: var(--projects-error);
}

@media (max-width: 720px) {
  .projects-page {
    padding: 16px 16px 96px;
  }

  .projects-grid {
    grid-template-columns: minmax(0, 1fr);
  }


  .projects-hero,
  .projects-login-prompt {
    align-items: flex-start;
    flex-direction: column;
  }

  .projects-hero {
    padding: 18px;
  }

  .projects-login-prompt {
    grid-template-columns: 1fr;
    min-height: 0;
    padding: 26px 22px;
  }

  .projects-login-prompt__mark {
    width: 62px;
    height: 62px;
    border-radius: 22px;
  }

  .projects-login-prompt__action {
    width: 100%;
  }

  .projects-hero__stats {
    justify-content: flex-start;
    max-width: none;
  }

  .projects-hero__side {
    width: 100%;
  }
}

/* Warm editorial migration: paper surfaces, hard rules, acid signal. */
.projects-page {
  --projects-accent: #11110f;
  --projects-accent-soft: rgba(199, 244, 50, .28);
  --projects-accent-border: #11110f;
  --projects-warm: #11110f;
  --projects-warm-soft: rgba(199, 244, 50, .22);
  --projects-paper: #f3f0e6;
  --projects-paper-light: #fffdf5;
  --projects-acid: #c7f432;
  --projects-acid-soft: #f1f8d2;
  color: #11110f;
  background: var(--projects-paper);
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
}

.projects-page::before { display: none; }
.projects-page :deep(.glass-card) {
  border: 1px solid #11110f;
  border-radius: 6px;
  background: var(--projects-paper-light);
  box-shadow: 4px 4px 0 #11110f;
  backdrop-filter: none;
}

.projects-hero::after { opacity: .22; mask-image: none; }
.projects-kicker { color: #11110f; }
.projects-kicker::before { content: '■'; margin-right: 8px; color: var(--projects-acid); -webkit-text-stroke: 1px #11110f; }
.projects-hero h1,
.empty-state h2,
.projects-login-prompt__copy h2 {
  color: #11110f;
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
  font-weight: 900;
  letter-spacing: -.055em;
}

.projects-hero__stats span,
.projects-login-prompt__notes span {
  border-color: #11110f;
  border-radius: 4px;
  background: var(--projects-paper-light);
  box-shadow: none;
}

.projects-add-btn,
.projects-add-submit,
.projects-login-prompt__action {
  border: 1px solid #11110f;
  border-radius: 4px;
  color: #11110f;
  background: var(--projects-acid);
  box-shadow: none;
}
.projects-add-btn:hover,
.projects-add-submit:hover,
.projects-login-prompt__action:hover {
  color: var(--projects-paper-light);
  background: #11110f;
  box-shadow: none;
  transform: none;
}

.projects-login-prompt { background: var(--projects-paper-light); }
.projects-login-prompt__mark { border-color: #11110f; border-radius: 6px; color: #11110f; background: var(--projects-acid); box-shadow: 4px 4px 0 #11110f; transform: none; }
.projects-grid { gap: 12px; }
@media (prefers-reduced-motion: reduce) {
  .projects-page *, .projects-page *::before, .projects-page *::after { scroll-behavior: auto !important; transition-duration: .01ms !important; animation-duration: .01ms !important; }
}
</style>
