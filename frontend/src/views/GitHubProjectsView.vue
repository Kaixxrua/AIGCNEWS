<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
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
  type ProjectTaxonomyItem,
  type ProjectViewSource,
} from '../services/api'
import router from '../router'
import { useAuthStore } from '../stores/authStore'
import {
  canEditWebsiteProject,
  canFavoriteProject,
  canRecommendProject,
  fallbackProjectDescription,
  favoriteButtonLabel as getFavoriteButtonLabel,
  formattedProjectHotScore,
  formatProjectCount,
  formatProjectShortDate,
  isWebsite,
  projectDailyGrowth,
  projectDailyGrowthTitle,
  projectDisplayTags,
  projectFavoritePayload,
  projectKey,
  projectLinkLabel,
  projectLogoKey,
  projectName,
  projectSourceBadge,
  projectUrl,
  recommendButtonLabel as getRecommendButtonLabel,
  shouldShowProjectHotScore,
  websiteLogoInitial,
  type ProjectChip,
} from '../features/projects/projectPresentation'

defineOptions({ name: 'GitHubProjectsView' })

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
const addMode = ref<'auto' | 'manual'>('auto')
const toolUrl = ref('')
const manualTitle = ref('')
const manualDescription = ref('')
const manualCategory = ref('other')
const manualSubcategory = ref('other_uncategorized')
const manualTags = ref('')
const taxonomy = ref<ProjectTaxonomyItem[]>([])
const taxonomyLoading = ref(false)
const addingTool = ref(false)
const addToolError = ref('')
const editDialogOpen = ref(false)
const editTarget = ref<GitHubProjectItem | null>(null)
const editTitle = ref('')
const editDescription = ref('')
const editCategory = ref('other')
const editSubcategory = ref('other_uncategorized')
const editTags = ref('')
const editImageUrl = ref('')
const editError = ref('')
const savingEdit = ref(false)
const deletingWebsiteId = ref<number | string | null>(null)
const favoriteBusyKey = ref('')
const recommendBusyKey = ref('')
const currentRequestId = ref(0)
const categoryRequestId = ref(0)
const tagRequestId = ref(0)
const isApplyingRouteState = ref(false)
const isReplacingRoute = ref(false)
const isViewActive = ref(true)
const VIEW_REFRESH_INTERVAL = 60_000
let lastSuccessfulFetchAt = 0
let hasActivatedOnce = false
let searchTimer: number | undefined

type SourceOption = { value: ProjectViewSource; label: string; hint: string; authOnly?: boolean }
type ProjectRouteQuery = Record<string, string>

const validSources: ProjectViewSource[] = ['all', 'website', 'favorites']
const validScopes: ProjectScope[] = ['all', 'today', 'recommended']
const validSorts: GitHubProjectSort[] = ['hot', 'stars', 'updated', 'recent', 'name']

const queryValue = (value: unknown) => {
  if (Array.isArray(value)) return String(value[0] ?? '').trim()
  return String(value ?? '').trim()
}

const parseRoutePage = (value: unknown) => {
  const parsed = Number(queryValue(value) || 1)
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : 1
}

const defaultSortForSource = (value: ProjectViewSource): GitHubProjectSort => (
  value === 'favorites' || value === 'website' ? 'recent' : 'stars'
)

const defaultSortForScope = (scopeValue: ProjectScope, sourceValue: ProjectViewSource = source.value): GitHubProjectSort => {
  if (scopeValue === 'today' && sourceValue === 'all') return 'hot'
  if (scopeValue === 'recommended' && sourceValue === 'all') return 'recent'
  return defaultSortForSource(sourceValue)
}

const endStateBatch = () => {
  window.setTimeout(() => {
    isApplyingRouteState.value = false
  }, 0)
}

const currentProjectsRedirect = () => (
  route.fullPath.startsWith('/projects') ? route.fullPath : '/projects'
)

const sameRouteQuery = (left: Record<string, unknown>, right: ProjectRouteQuery) => {
  const keys = new Set([...Object.keys(left), ...Object.keys(right)])
  for (const key of keys) {
    if (queryValue(left[key]) !== queryValue(right[key])) return false
  }
  return true
}

const buildRouteQuery = (): ProjectRouteQuery => {
  const query: ProjectRouteQuery = {}
  if (source.value !== 'all') query.source = source.value
  if (selectedScope.value !== 'all') query.scope = selectedScope.value
  if (selectedCategory.value !== 'all') query.category = selectedCategory.value
  if (selectedSubcategory.value !== 'all') query.subcategory = selectedSubcategory.value
  const cleanQuery = debouncedQuery.value.trim()
  if (cleanQuery) query.q = cleanQuery
  if (selectedLanguage.value) query.language = selectedLanguage.value
  if (isPersonalView.value && selectedTag.value) query.tag = selectedTag.value
  if (sort.value !== defaultSortForScope(selectedScope.value, source.value) && (sort.value !== 'hot' || source.value === 'all')) query.sort = sort.value
  if (page.value > 1) query.page = String(page.value)
  return query
}

const replaceRouteFromState = async (force = false) => {
  if (isApplyingRouteState.value && !force) return
  const query = buildRouteQuery()
  if (route.path === '/projects' && sameRouteQuery(route.query, query)) return
  isReplacingRoute.value = true
  try {
    await router.replace({ path: '/projects', query })
  } finally {
    window.setTimeout(() => {
      isReplacingRoute.value = false
    }, 0)
  }
}

const applyRouteState = () => {
  const routeSource = queryValue(route.query.source)
  const nextSource = validSources.includes(routeSource as ProjectViewSource)
    ? routeSource as ProjectViewSource
    : 'all'
  const routeScope = queryValue(route.query.scope)
  const nextScope = validScopes.includes(routeScope as ProjectScope) ? routeScope as ProjectScope : 'all'
  const routeSort = queryValue(route.query.sort)
  const routeSortAllowed = validSorts.includes(routeSort as GitHubProjectSort)
    && (routeSort !== 'hot' || nextSource === 'all')
  const nextSort = nextScope === 'today'
    ? 'hot'
    : (routeSortAllowed ? routeSort as GitHubProjectSort : defaultSortForScope(nextScope, nextSource))
  const nextQuery = queryValue(route.query.q)

  isApplyingRouteState.value = true
  source.value = nextSource
  selectedScope.value = nextScope
  selectedCategory.value = queryValue(route.query.category) || 'all'
  selectedSubcategory.value = queryValue(route.query.subcategory) || 'all'
  selectedLanguage.value = queryValue(route.query.language)
  selectedTag.value = nextSource === 'favorites' || nextSource === 'website' ? queryValue(route.query.tag) : ''
  searchQuery.value = nextQuery
  debouncedQuery.value = nextQuery
  sort.value = nextSort
  page.value = parseRoutePage(route.query.page)
  endStateBatch()
  return true
}

const sourceOptions = computed<SourceOption[]>(() => [
  { value: 'all', label: 'GitHub 项目', hint: '公共开源项目' },
  { value: 'website', label: '我的网页', hint: '个人网页收藏', authOnly: true },
  { value: 'favorites', label: '我的收藏', hint: 'GitHub 项目收藏', authOnly: true },
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
const sourceLabel = computed(() => sourceOptions.value.find((item) => item.value === source.value)?.label ?? '全部')
const personalLoginCopy = computed(() => (
  isWebsiteOnlyView.value
    ? {
        kicker: 'YOUR PRIVATE WEB SHELF',
        title: '登录后，继续整理你的网页世界',
        description: '保存常用网站、补充中文说明，并把散落在浏览器里的灵感整理成只属于你的收藏夹。',
      }
    : {
        kicker: 'YOUR STARRED PROJECTS',
        title: '登录后，查看你的 GitHub 收藏',
        description: '把感兴趣的开源项目留在这里，按标签、更新时间和收藏顺序快速找回来。',
      }
))
const starsBadgeLabel = computed(() => {
  if (source.value === 'all') return 'GitHub Stars > 500'
  return ''
})
const selectedManualCategory = computed(() => taxonomy.value.find((item) => item.slug === manualCategory.value))
const manualSubcategoryOptions = computed(() => selectedManualCategory.value?.children ?? [])
const selectedEditCategory = computed(() => taxonomy.value.find((item) => item.slug === editCategory.value))
const editSubcategoryOptions = computed(() => selectedEditCategory.value?.children ?? [])
const activeFilterLabel = computed(() => {
  if (selectedTag.value) return `标签：${selectedTag.value}`
  if (selectedLanguage.value) return `语言：${selectedLanguage.value}`
  if (isPersonalView.value) return '未筛选标签'
  if (selectedScope.value === 'recommended') return recommendedScope.value?.name || '站长推荐'
  if (selectedScope.value === 'today') return todayScope.value?.name || '今日暴涨'
  if (activeCategory.value && activeSubcategory.value) {
    return `${activeCategory.value.name} / ${activeSubcategory.value.name}`
  }
  if (activeCategory.value) return activeCategory.value.name
  return '全部分类'
})
const hasActiveFilter = computed(() => (
  selectedScope.value !== 'all'
  || selectedCategory.value !== 'all'
  || selectedSubcategory.value !== 'all'
  || !!selectedLanguage.value
  || !!selectedTag.value
))

const repoName = projectName
const repoUrl = projectUrl
const sourceBadge = projectSourceBadge
const linkLabel = projectLinkLabel
const logoKey = projectLogoKey
const brokenLogoKeys = ref<Set<string>>(new Set())
const loadedLogoKeys = ref<Set<string>>(new Set())
const websiteLogoUrl = (repo: GitHubProjectItem) => {
  const key = logoKey(repo)
  return key && !brokenLogoKeys.value.has(key) ? (repo.image_url || '') : ''
}
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
const favoriteButtonLabel = (repo: GitHubProjectItem) => getFavoriteButtonLabel(
  repo,
  favoriteBusyKey.value === projectKey(repo),
  authStore.isLoggedIn,
)
const recommendButtonLabel = (repo: GitHubProjectItem) => getRecommendButtonLabel(
  repo,
  recommendBusyKey.value === projectKey(repo),
)
const fallbackDescription = fallbackProjectDescription
const displayTags = (repo: GitHubProjectItem): ProjectChip[] => projectDisplayTags(repo, isPersonalView.value)
const formatCount = formatProjectCount
const formatShortDate = formatProjectShortDate
const dailyGrowth = projectDailyGrowth
const dailyGrowthTitle = projectDailyGrowthTitle
const shouldShowHotScore = (repo: GitHubProjectItem) => shouldShowProjectHotScore(repo, sort.value, selectedScope.value)
const formattedHotScore = formattedProjectHotScore

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
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, 'zh-CN'))
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
    const firstCategory = data.items[0]
    if (firstCategory && !data.items.some((item) => item.slug === manualCategory.value)) {
      manualCategory.value = firstCategory.slug
      manualSubcategory.value = firstCategory.children[0]?.slug ?? ''
    }
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
      errorMsg.value = isMyCollection.value ? '我的收藏暂时加载失败，请稍后重试。' : '项目库暂时加载失败，请稍后重试。'
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

const resetManualForm = () => {
  manualTitle.value = ''
  manualDescription.value = ''
  manualTags.value = ''
  const firstCategory = taxonomy.value.find((item) => item.slug === 'other') ?? taxonomy.value[0]
  manualCategory.value = firstCategory?.slug ?? 'other'
  manualSubcategory.value = firstCategory?.children[0]?.slug ?? 'other_uncategorized'
}

const goToPersonalLogin = () => {
  router.push({ path: '/login', query: { redirect: currentProjectsRedirect() } })
}

const openAddDialog = () => {
  if (!authStore.isLoggedIn) {
    router.push({ path: '/login', query: { redirect: '/projects?source=website' } })
    return
  }
  addToolError.value = ''
  toolUrl.value = ''
  addMode.value = 'auto'
  resetManualForm()
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
  editTitle.value = repo.title || repoName(repo)
  editDescription.value = repo.description_zh || repo.description || ''
  editCategory.value = repo.category_slug || 'other'
  editSubcategory.value = repo.subcategory_slug || ''
  editTags.value = (repo.tags ?? []).join(', ')
  editImageUrl.value = repo.image_url || ''
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

const submitEditWebsite = async () => {
  const target = editTarget.value
  if (!target?.website_id) return
  const title = editTitle.value.trim()
  const description = editDescription.value.trim()
  if (!title) {
    editError.value = '请输入工具名称。'
    return
  }
  if (!description) {
    editError.value = '请输入中文说明。'
    return
  }
  savingEdit.value = true
  editError.value = ''
  successMsg.value = ''
  try {
    const result = await updateMyToolWebsite(target.website_id, {
      title,
      description,
      description_zh: description,
      category_slug: editCategory.value,
      subcategory_slug: editSubcategory.value,
      image_url: editImageUrl.value.trim(),
      tags: editTags.value
        .split(/[，,]/)
        .map((item) => item.trim())
        .filter(Boolean),
    })
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

const submitToolWebsite = async () => {
  const url = toolUrl.value.trim()
  if (!url) {
    addToolError.value = '请输入工具网页链接。'
    return
  }
  addingTool.value = true
  addToolError.value = ''
  successMsg.value = ''
  try {
    let result
    if (addMode.value === 'manual') {
      const title = manualTitle.value.trim()
      const description = manualDescription.value.trim()
      if (!title) throw new Error('请输入工具名称。')
      if (!description) throw new Error('请输入中文说明。')
      const payload = {
        url,
        title,
        description_zh: description,
        category_slug: manualCategory.value,
        subcategory_slug: manualSubcategory.value,
        tags: manualTags.value
          .split(/[，,]/)
          .map((item) => item.trim())
          .filter(Boolean),
      }
      result = await addMyToolWebsiteManual(payload)
    } else {
      result = await addMyToolWebsite(url)
    }
    if (result.item) mergePersonalTagsFromItems([result.item])
    successMsg.value = result.message || (result.duplicate ? '网页收藏已存在。' : '网页收藏已添加。')
    addDialogOpen.value = false
    toolUrl.value = ''
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
watch(manualCategory, () => {
  const firstSubcategory = manualSubcategoryOptions.value[0]
  if (!manualSubcategoryOptions.value.some((item) => item.slug === manualSubcategory.value)) {
    manualSubcategory.value = firstSubcategory?.slug ?? ''
  }
})

watch(editCategory, () => {
  const firstSubcategory = editSubcategoryOptions.value[0]
  if (!editSubcategoryOptions.value.some((item) => item.slug === editSubcategory.value)) {
    editSubcategory.value = firstSubcategory?.slug ?? ''
  }
})

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
        <h1>AI 项目与工具库</h1>
        <p>浏览 stars &gt; 500 的 GitHub AI 项目；登录后可建立只属于你的网页收藏夹，自动分类并生成中文短描述。</p>
      </div>

      <div class="projects-hero__side">
        <div class="projects-hero__stats" aria-label="项目库统计">
          <span>{{ total }} 个条目</span>
          <span>{{ sourceLabel }}</span>
          <span v-if="starsBadgeLabel">{{ starsBadgeLabel }}</span>
          <span>{{ activeFilterLabel }}</span>
        </div>
        <button
          v-if="isWebsiteOnlyView && !requiresPersonalLogin"
          type="button"
          class="projects-add-btn"
          :title="isMyCollection && !authStore.isLoggedIn ? '登录后添加个人网站' : ''"
          @click="openAddDialog"
        >
          <span>＋</span>
          添加网页收藏
        </button>
      </div>
    </section>

    <section class="projects-toolbar glass-card">
      <div class="projects-source-tabs" aria-label="来源筛选">
        <button
          v-for="item in sourceOptions"
          :key="item.value"
          type="button"
          class="projects-source-tab"
          :class="source === item.value ? 'projects-source-tab--active' : ''"
          @click="changeSource(item.value)"
        >
          <strong>{{ item.label }}</strong>
          <small>{{ item.hint }}</small>
        </button>
      </div>

      <div v-if="!requiresPersonalLogin" class="projects-search">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <circle cx="11" cy="11" r="7" />
          <path d="m20 20-3.5-3.5" />
        </svg>
        <input
          v-model="searchQuery"
          class="input"
          type="search"
          placeholder="搜索项目名、网站、中文描述、语言或标签"
        />
        <button
          v-if="selectedLanguage"
          type="button"
          class="projects-search__filter"
          @click="clearLanguageFilter"
        >
          {{ selectedLanguage }} ×
        </button>
      </div>

      <label v-if="!requiresPersonalLogin" class="projects-sort">
        <span>排序</span>
        <select v-model="sort" :disabled="selectedScope === 'today'">
          <option v-if="!isWebsiteOnlyView" value="hot">{{ selectedScope === 'today' ? '热度前 50' : '热度优先' }}</option>
          <option value="stars">Stars 优先</option>
          <option value="updated">最近更新</option>
          <option value="recent">最近收录</option>
          <option value="name">名称</option>
        </select>
      </label>
    </section>

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
        登录后查看
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M5 12h14" />
          <path d="m14 7 5 5-5 5" />
        </svg>
      </button>
    </section>

    <template v-else>
    <section v-if="!isPersonalView" class="projects-category-panel glass-card" aria-label="项目分类筛选">
      <div class="projects-categories" aria-label="一级分类筛选">
        <button
          type="button"
          class="projects-category projects-category--scope"
          :class="selectedScope === 'all' && selectedCategory === 'all' ? 'tab-active' : 'tab-inactive'"
          :disabled="categoriesLoading"
          @click="selectScope('all')"
        >
          <span>{{ allScope?.name || '全部' }}</span>
          <small>{{ allScope?.count ?? 0 }}</small>
        </button>
        <button
          type="button"
          class="projects-category projects-category--recommend"
          :class="selectedScope === 'recommended' ? 'tab-active' : 'tab-inactive'"
          :disabled="categoriesLoading"
          @click="selectScope('recommended')"
        >
          <span>{{ recommendedScope?.name || '站长推荐' }}</span>
          <small>{{ recommendedScope?.count ?? 0 }}</small>
        </button>
        <button
          type="button"
          class="projects-category projects-category--today"
          :class="selectedScope === 'today' ? 'tab-active' : 'tab-inactive'"
          :disabled="categoriesLoading"
          @click="selectScope('today')"
        >
          <span>{{ todayScope?.name || '今日暴涨' }}</span>
          <small>{{ todayScope?.count ?? 0 }}</small>
        </button>
        <button
          v-for="category in semanticCategories"
          :key="category.slug"
          type="button"
          class="projects-category"
          :class="selectedScope === 'all' && selectedCategory === category.slug ? 'tab-active' : 'tab-inactive'"
          :disabled="categoriesLoading"
          @click="selectCategory(category.slug)"
        >
          <span>{{ category.name }}</span>
          <small>{{ category.count }}</small>
        </button>
      </div>

      <div
        v-if="visibleSubcategories.length"
        class="projects-subcategories"
        aria-label="二级分类筛选"
      >
        <span class="projects-subcategories__label">{{ activeCategory?.name }} · 二级分类</span>
        <button
          type="button"
          class="projects-category projects-category--sub"
          :class="selectedSubcategory === 'all' ? 'tab-active' : 'tab-inactive'"
          :disabled="categoriesLoading"
          @click="selectSubcategory('all')"
        >
          <span>全部</span>
          <small>{{ activeCategory?.count ?? 0 }}</small>
        </button>
        <button
          v-for="subcategory in visibleSubcategories"
          :key="subcategory.slug"
          type="button"
          class="projects-category projects-category--sub"
          :class="selectedSubcategory === subcategory.slug ? 'tab-active' : 'tab-inactive'"
          :disabled="categoriesLoading"
          @click="selectSubcategory(subcategory.slug)"
        >
          <span>{{ subcategory.name }}</span>
          <small>{{ subcategory.count }}</small>
        </button>
      </div>
    </section>

    <section
      v-else-if="personalTags.length || selectedTag"
      class="projects-category-panel projects-tag-panel glass-card"
      aria-label="个人标签筛选"
    >
      <div class="projects-categories" aria-label="个人标签筛选">
        <button
          v-for="tag in personalTags"
          :key="tag.label"
          type="button"
          class="projects-category projects-category--tag"
          :class="selectedTag === tag.label ? 'tab-active' : 'tab-inactive'"
          :disabled="tagsLoading"
          @click="selectPersonalTag(tag.label)"
        >
          <span>{{ tag.label }}</span>
          <small>{{ tag.count }}</small>
        </button>
        <button
          v-if="selectedTag"
          type="button"
          class="projects-category projects-category--sub"
          :disabled="tagsLoading"
          @click="clearPersonalTag"
        >
          清除标签
        </button>
      </div>
    </section>

    <section v-if="errorMsg" class="projects-toast projects-toast--error glass-card">
      {{ errorMsg }}
    </section>

    <section v-if="loading" class="projects-grid" aria-label="收藏列表加载中">
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

    <section v-else class="projects-grid" aria-label="AI 项目与网页收藏列表">
      <article
        v-for="(repo, index) in projects"
        :key="repo.id ?? repo.repo_id ?? repo.website_id ?? repo.full_name ?? index"
        class="project-card glass-card card-hover stagger-enter"
        :class="{ 'project-card--not-found': !isWebsite(repo) && repo.availability_status === 'not_found' }"
        :style="{ animationDelay: `${Math.min(index, 12) * 36}ms` }"
      >
        <div class="project-card__pin" :class="isWebsite(repo) ? 'project-card__pin--website' : ''" aria-hidden="true" />

        <header class="project-card__header">
          <div class="project-card__identity">
            <div v-if="isWebsite(repo)" class="project-card__logo-shell">
              <span class="project-card__logo-placeholder" aria-hidden="true">
                {{ websiteLogoInitial(repo) }}
              </span>
              <img
                v-if="websiteLogoUrl(repo)"
                class="project-card__logo"
                :class="isWebsiteLogoLoaded(repo) ? 'project-card__logo--loaded' : ''"
                :src="repo.image_url || ''"
                :alt="`${repoName(repo)} 图标`"
                width="42"
                height="42"
                decoding="async"
                :loading="index < 6 ? 'eager' : 'lazy'"
                referrerpolicy="no-referrer"
                @load="markWebsiteLogoLoaded(repo)"
                @error="hideBrokenLogo(repo)"
              />
            </div>
            <div>
              <div class="project-card__source-row">
                <span class="project-card__source">{{ sourceBadge(repo) }}</span>
                <span
                  v-if="!isWebsite(repo) && repo.availability_status === 'not_found'"
                  class="project-card__availability"
                >
                  仓库不可用
                </span>
              </div>
              <h2 :title="repoName(repo)">{{ repoName(repo) }}</h2>
              <p v-if="isWebsite(repo) && repo.domain" class="project-card__domain">{{ repo.domain }}</p>
            </div>
          </div>
          <div class="project-card__actions">
            <a
              v-if="repoUrl(repo)"
              class="project-card__link"
              :href="repoUrl(repo)"
              target="_blank"
              rel="noopener noreferrer"
              :aria-label="isWebsite(repo) ? '打开网页收藏' : '打开 GitHub 仓库'"
            >
              {{ linkLabel(repo) }}
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M7 17L17 7" />
                <path d="M9 7h8v8" />
              </svg>
            </a>
            <button
              v-if="canRecommendCard(repo)"
              type="button"
              class="project-card__recommend"
              :class="repo.is_recommended ? 'project-card__recommend--active' : ''"
              :aria-pressed="Boolean(repo.is_recommended)"
              :disabled="Boolean(recommendBusyKey)"
              @click="recommendProject(repo)"
            >
              {{ recommendButtonLabel(repo) }}
            </button>
            <button
              v-if="!isWebsite(repo)"
              type="button"
              class="project-card__favorite"
              :class="repo.is_favorited ? 'project-card__favorite--active' : ''"
              :aria-pressed="Boolean(repo.is_favorited)"
              :disabled="Boolean(favoriteBusyKey) || !canFavorite(repo)"
              @click="toggleFavorite(repo)"
            >
              <span>{{ repo.is_favorited ? '★' : '☆' }}</span>
              {{ favoriteButtonLabel(repo) }}
            </button>
            <button
              v-if="canEditCard(repo)"
              type="button"
              class="project-card__edit"
              :disabled="savingEdit && editTarget?.website_id === repo.website_id"
              @click="openEditDialog(repo)"
            >
              编辑
            </button>
            <button
              v-if="isPersonalView && isWebsite(repo)"
              type="button"
              class="project-card__delete"
              :disabled="deletingWebsiteId === repo.website_id"
              @click="removeToolWebsite(repo)"
            >
              {{ deletingWebsiteId === repo.website_id ? '处理中' : '删除' }}
            </button>
          </div>
        </header>

        <p class="project-card__description">
          {{ repo.description_zh || repo.description || fallbackDescription(repo) }}
        </p>

        <div class="project-card__tags" aria-label="分类标签">
          <button
            v-for="chip in displayTags(repo)"
            :key="`${chip.type}:${chip.value}`"
            type="button"
            class="badge-default project-chip"
            :class="`project-chip--${chip.type}`"
            @click="handleChipClick(chip)"
          >
            {{ chip.label }}
          </button>
        </div>

        <footer class="project-card__stats" :aria-label="isWebsite(repo) ? '网页收藏信息' : 'GitHub 指标'">
          <template v-if="isWebsite(repo)">
            <span>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <circle cx="12" cy="12" r="9" />
                <path d="M3 12h18" />
                <path d="M12 3a13.5 13.5 0 0 1 0 18" />
                <path d="M12 3a13.5 13.5 0 0 0 0 18" />
              </svg>
              {{ repo.domain || '网页收藏' }}
            </span>
            <span>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M8 2v4" />
                <path d="M16 2v4" />
                <rect x="3" y="4" width="18" height="18" rx="2" />
                <path d="M3 10h18" />
              </svg>
              {{ formatShortDate(repo.first_seen_at) }} 收录
            </span>
          </template>
          <template v-else>
            <span>
              <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <path d="m12 2.2 2.9 5.88 6.5.94-4.7 4.58 1.1 6.47L12 17.02l-5.8 3.05 1.1-6.47-4.7-4.58 6.5-.94L12 2.2Z" />
              </svg>
              {{ formatCount(repo.stars) }} stars
            </span>
            <span :title="dailyGrowthTitle(repo)">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M3 17l6-6 4 4 8-8" />
                <path d="M15 7h6v6" />
              </svg>
              +{{ formatCount(dailyGrowth(repo)) }} 今日
            </span>
            <span v-if="shouldShowHotScore(repo)" title="热度分由规模校正增长、增长加速度、绝对增长、维护活跃和社区参与组成">
              热度 {{ formattedHotScore(repo) }}
            </span>
            <span>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <circle cx="6" cy="5" r="2" />
                <circle cx="18" cy="5" r="2" />
                <circle cx="12" cy="19" r="2" />
                <path d="M6 7v3a5 5 0 0 0 5 5h1" />
                <path d="M18 7v3a5 5 0 0 1-5 5h-1" />
                <path d="M12 15v2" />
              </svg>
              {{ formatCount(repo.forks) }} forks
            </span>
          </template>
        </footer>
      </article>
    </section>

    <nav v-if="total > pageSize && !loading" class="projects-pagination glass-card" aria-label="项目分页">
      <p>第 {{ page }} / {{ totalPages }} 页 · {{ total }} 个条目</p>
      <div class="projects-pagination__controls">
        <button class="btn-secondary" :disabled="!hasPrev" @click="goPage(page - 1)">上一页</button>
        <form class="projects-pagination__jump" aria-label="跳转页码" @submit.prevent="jumpToPage">
          <span>跳至</span>
          <input
            v-model="pageJump"
            type="number"
            inputmode="numeric"
            min="1"
            :max="totalPages"
            :placeholder="String(page)"
            aria-label="输入要跳转的页码"
          />
          <span>页</span>
          <button class="btn-secondary" type="submit">跳转</button>
        </form>
        <button class="btn-secondary" :disabled="!hasNext" @click="goPage(page + 1)">下一页</button>
      </div>
    </nav>
    </template>

    <Teleport to="body">
      <Transition name="tool-modal">
        <div v-if="isViewActive && addDialogOpen" class="tool-modal" role="presentation" @click.self="closeAddDialog">
          <form class="tool-modal__panel" @submit.prevent="submitToolWebsite">
            <button
              type="button"
              class="tool-modal__close"
              :disabled="addingTool"
              aria-label="关闭添加网页收藏弹窗"
              @click="closeAddDialog"
            >
              ×
            </button>
            <p class="projects-kicker">ADD WEB TOOL</p>
            <h2>{{ isMyCollection ? '添加到我的收藏' : '收藏一个网页' }}</h2>
            <p class="tool-modal__hint">
              {{ isMyCollection ? '普通用户添加的网站只进入你的个人收藏夹；自动模式会抓取 metadata 并 AI 富化。' : '自动模式会抓取网页 metadata 并 AI 富化；如果网站拦截爬取或网络不可达，可切换手动模式填写说明。' }}
            </p>

            <div class="tool-modal__tabs" aria-label="添加方式">
              <button
                type="button"
                :class="addMode === 'auto' ? 'tool-modal__tab--active' : ''"
                :disabled="addingTool"
                @click="addMode = 'auto'"
              >
                自动抓取
              </button>
              <button
                type="button"
                :class="addMode === 'manual' ? 'tool-modal__tab--active' : ''"
                :disabled="addingTool"
                @click="addMode = 'manual'"
              >
                手动添加
              </button>
            </div>

            <label class="tool-modal__field">
              <span>工具链接</span>
              <input
                v-model="toolUrl"
                type="text"
                inputmode="url"
                placeholder="https://example.com 或 example.com"
                autocomplete="url"
                :disabled="addingTool"
                autofocus
              />
            </label>

            <div v-if="addMode === 'manual'" class="tool-modal__manual-grid">
              <label class="tool-modal__field">
                <span>工具名称</span>
                <input
                  v-model="manualTitle"
                  type="text"
                  placeholder="例如：Linux.do"
                  :disabled="addingTool"
                />
              </label>
              <label class="tool-modal__field tool-modal__field--wide">
                <span>中文说明</span>
                <textarea
                  v-model="manualDescription"
                  rows="3"
                  placeholder="一句话说明这个网站能解决什么问题、适合什么场景。"
                  :disabled="addingTool"
                />
              </label>
              <label class="tool-modal__field">
                <span>一级分类</span>
                <select v-model="manualCategory" :disabled="addingTool || taxonomyLoading">
                  <option
                    v-for="item in taxonomy"
                    :key="item.slug"
                    :value="item.slug"
                  >
                    {{ item.name }}
                  </option>
                </select>
              </label>
              <label class="tool-modal__field">
                <span>二级分类</span>
                <select v-model="manualSubcategory" :disabled="addingTool || taxonomyLoading">
                  <option
                    v-for="item in manualSubcategoryOptions"
                    :key="item.slug"
                    :value="item.slug"
                  >
                    {{ item.name }}
                  </option>
                </select>
              </label>
              <label class="tool-modal__field tool-modal__field--wide">
                <span>标签（用逗号分隔）</span>
                <input
                  v-model="manualTags"
                  type="text"
                  placeholder="社区, 教程, 效率工具"
                  :disabled="addingTool"
                />
              </label>
            </div>

            <p v-if="addToolError" class="tool-modal__error">{{ addToolError }}</p>
            <div class="tool-modal__actions">
              <button type="button" class="btn-secondary" :disabled="addingTool" @click="closeAddDialog">取消</button>
              <button type="submit" class="projects-add-submit" :disabled="addingTool">
                {{ addingTool ? (addMode === 'manual' ? '保存中…' : '抓取并富化中…') : (addMode === 'manual' ? '手动保存' : '添加并 AI 富化') }}
              </button>
            </div>
          </form>
        </div>
      </Transition>
    </Teleport>

    <Teleport to="body">
      <Transition name="tool-modal">
        <div v-if="isViewActive && editDialogOpen" class="tool-modal" role="presentation" @click.self="closeEditDialog">
          <form class="tool-modal__panel" @submit.prevent="submitEditWebsite">
            <button
              type="button"
              class="tool-modal__close"
              :disabled="savingEdit"
              aria-label="关闭编辑网页收藏弹窗"
              @click="closeEditDialog"
            >
              ×
            </button>
            <p class="projects-kicker">EDIT WEB TOOL</p>
            <h2>编辑网页收藏</h2>
            <p class="tool-modal__hint">
              这些修改只会影响你的个人网页收藏卡片，不会修改其他用户看到的同一网站信息。
            </p>

            <div class="tool-modal__manual-grid">
              <label class="tool-modal__field">
                <span>工具名称</span>
                <input
                  v-model="editTitle"
                  type="text"
                  placeholder="例如：Linux.do"
                  :disabled="savingEdit"
                  autofocus
                />
              </label>
              <label class="tool-modal__field tool-modal__field--wide">
                <span>中文说明</span>
                <textarea
                  v-model="editDescription"
                  rows="3"
                  placeholder="一句话说明这个网站能解决什么问题、适合什么场景。"
                  :disabled="savingEdit"
                />
              </label>
              <label class="tool-modal__field">
                <span>一级分类</span>
                <select v-model="editCategory" :disabled="savingEdit || taxonomyLoading">
                  <option
                    v-for="item in taxonomy"
                    :key="item.slug"
                    :value="item.slug"
                  >
                    {{ item.name }}
                  </option>
                </select>
              </label>
              <label class="tool-modal__field">
                <span>二级分类</span>
                <select v-model="editSubcategory" :disabled="savingEdit || taxonomyLoading">
                  <option
                    v-for="item in editSubcategoryOptions"
                    :key="item.slug"
                    :value="item.slug"
                  >
                    {{ item.name }}
                  </option>
                </select>
              </label>
              <label class="tool-modal__field tool-modal__field--wide">
                <span>标签（用逗号分隔）</span>
                <input
                  v-model="editTags"
                  type="text"
                  placeholder="社区, 教程, 效率工具"
                  :disabled="savingEdit"
                />
              </label>
              <label class="tool-modal__field tool-modal__field--wide">
                <span>图标 URL（可选）</span>
                <input
                  v-model="editImageUrl"
                  type="text"
                  inputmode="url"
                  placeholder="https://example.com/favicon.ico"
                  :disabled="savingEdit"
                />
              </label>
              <p v-if="editTarget?.url" class="tool-modal__readonly">
                原始链接：{{ editTarget.url }}
              </p>
            </div>

            <p v-if="editError" class="tool-modal__error">{{ editError }}</p>
            <div class="tool-modal__actions">
              <button type="button" class="btn-secondary" :disabled="savingEdit" @click="closeEditDialog">取消</button>
              <button type="submit" class="projects-add-submit" :disabled="savingEdit">
                {{ savingEdit ? '保存中…' : '保存修改' }}
              </button>
            </div>
          </form>
        </div>
      </Transition>
    </Teleport>
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
  gap: 24px;
  overflow: hidden;
  margin-bottom: 16px;
  padding: 26px;
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
  font-size: clamp(34px, 5vw, 58px);
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

.projects-toolbar {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 14px;
  padding: 14px;
}

.projects-source-tabs {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.projects-source-tab {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 94px;
  border: 1px solid rgba(168, 162, 158, 0.22);
  border-radius: 18px;
  padding: 9px 12px;
  color: #78716c;
  background: rgba(255, 255, 255, 0.64);
  text-align: left;
  transition: all 160ms ease;
}

.projects-source-tab strong {
  color: #44403c;
  font-size: 13px;
}

.projects-source-tab small {
  font-size: 10px;
  opacity: 0.72;
}

.projects-source-tab:hover,
.projects-source-tab--active {
  border-color: var(--projects-accent-border);
  background: rgba(245, 245, 244, 0.86);
  transform: translateY(-1px);
}

.projects-source-tab--active strong {
  color: var(--projects-accent);
}

.projects-search {
  position: relative;
  flex: 1;
}

.projects-search svg {
  position: absolute;
  left: 16px;
  top: 50%;
  z-index: 1;
  width: 17px;
  height: 17px;
  color: #a8a29e;
  transform: translateY(-50%);
}

.projects-search :deep(.input) {
  padding-left: 44px;
}

.projects-search :deep(.input:focus) {
  border-color: var(--projects-accent-border);
  box-shadow: 0 0 0 3px var(--projects-accent-soft), 0 2px 8px rgba(0, 0, 0, 0.04);
}

.projects-search__filter {
  position: absolute;
  right: 10px;
  top: 50%;
  z-index: 2;
  transform: translateY(-50%);
  border: 1px solid rgba(245, 158, 11, 0.24);
  border-radius: 999px;
  padding: 5px 9px;
  color: var(--projects-warm);
  background: rgba(255, 251, 235, 0.86);
  font-size: 11px;
  font-weight: 800;
}

.projects-sort {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #78716c;
  font-size: 12px;
  font-weight: 700;
}

.projects-sort select {
  border-radius: 999px;
  padding: 10px 34px 10px 14px;
  color: #44403c;
  background: rgba(255, 255, 255, 0.86);
  border: 1px solid rgba(168, 162, 158, 0.25);
  outline: none;
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

.projects-category-panel {
  position: relative;
  display: grid;
  gap: 12px;
  overflow: hidden;
  margin-bottom: 18px;
  padding: 14px;
}

.projects-category-panel::before {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  background:
    radial-gradient(circle at 10% 10%, var(--projects-warm-soft), transparent 26%),
    radial-gradient(circle at 88% 0%, var(--projects-accent-soft), transparent 30%);
}

.projects-category-panel > * {
  position: relative;
  z-index: 1;
}

.projects-categories,
.projects-subcategories {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 3px;
}

.projects-subcategories {
  align-items: center;
  padding-top: 11px;
  border-top: 1px dashed rgba(168, 162, 158, 0.24);
}

.projects-subcategories__label {
  flex-shrink: 0;
  border-radius: 999px;
  padding: 7px 10px;
  color: #78716c;
  background: rgba(255, 255, 255, 0.54);
  border: 1px solid rgba(168, 162, 158, 0.18);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.04em;
}

.projects-category {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  padding: 8px 12px;
  font-size: 13px;
  font-weight: 700;
  transition: all 160ms ease;
}

.projects-category--scope,
.projects-category--recommend,
.projects-category--today {
  box-shadow: inset 0 0 0 1px rgba(168, 162, 158, 0.18);
}

.projects-category--sub {
  padding: 7px 11px;
  font-size: 12px;
}

.projects-category small {
  font-size: 11px;
  opacity: 0.68;
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

.project-card > * {
  position: relative;
  z-index: 1;
}

.project-card__pin {
  position: absolute;
  top: 14px;
  right: 16px;
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: var(--projects-accent);
  box-shadow: 0 0 0 5px var(--projects-accent-soft);
}

.project-card__pin--website {
  background: var(--projects-warm);
  box-shadow: 0 0 0 5px var(--projects-warm-soft);
}

.project-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  padding-right: 14px;
}

.project-card__identity {
  display: flex;
  align-items: flex-start;
  min-width: 0;
  gap: 12px;
}

.project-card__logo-shell {
  position: relative;
  width: 42px;
  height: 42px;
  flex: 0 0 42px;
  overflow: hidden;
  border: 1px solid rgba(168, 162, 158, 0.22);
  border-radius: 14px;
  background: var(--acid-soft);
  box-shadow: 0 10px 24px rgba(41, 37, 36, 0.08);
}

.project-card__logo-placeholder,
.project-card__logo {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.project-card__logo-placeholder {
  display: grid;
  place-items: center;
  color: var(--acid-ink);
  font-size: 16px;
  font-weight: 800;
  line-height: 1;
}

.project-card__logo {
  object-fit: cover;
  background: var(--paper-raised);
  opacity: 0;
  transition: opacity 160ms ease;
}

.project-card__logo--loaded {
  opacity: 1;
}

.project-card__source {
  display: inline-flex;
  width: fit-content;
  margin-bottom: 7px;
  border-radius: 999px;
  padding: 3px 8px;
  color: var(--projects-accent);
  background: rgba(245, 245, 244, 0.82);
  border: 1px solid var(--projects-accent-border);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.08em;
}

.project-card__header h2 {
  color: #292524;
  font-size: 18px;
  font-weight: 700;
  line-height: 1.25;
  letter-spacing: -0.02em;
  overflow-wrap: anywhere;
}

.project-card__domain {
  margin-top: 4px;
  color: var(--projects-warm);
  font-size: 12px;
  font-weight: 700;
}

.project-card__actions {
  display: flex;
  align-items: flex-end;
  flex-direction: column;
  gap: 7px;
  flex-shrink: 0;
}

.project-card__link,
.project-card__favorite,
.project-card__recommend,
.project-card__edit,
.project-card__delete {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  flex-shrink: 0;
  border-radius: 999px;
  padding: 6px 10px;
  font-size: 12px;
  font-weight: 700;
  transition: all 160ms ease;
}

.project-card__link {
  color: #44403c;
  background: rgba(255, 255, 255, 0.74);
  border: 1px solid rgba(168, 162, 158, 0.24);
}

.project-card__favorite {
  color: #a16207;
  background: rgba(255, 251, 235, 0.76);
  border: 1px solid rgba(245, 158, 11, 0.24);
}

.project-card__recommend {
  color: #be123c;
  background: rgba(255, 241, 242, 0.78);
  border: 1px solid rgba(244, 63, 94, 0.24);
}

.project-card__edit {
  color: var(--projects-accent);
  background: rgba(236, 254, 255, 0.76);
  border: 1px solid var(--projects-accent-border);
}

.project-card__favorite--active {
  color: #78350f;
  background: rgba(254, 243, 199, 0.92);
  border-color: rgba(245, 158, 11, 0.42);
  box-shadow: 0 8px 18px rgba(245, 158, 11, 0.12);
}

.project-card__recommend--active {
  color: #9f1239;
  background: rgba(255, 228, 230, 0.95);
  border-color: rgba(244, 63, 94, 0.42);
  box-shadow: 0 8px 18px rgba(244, 63, 94, 0.12);
}

.project-card__delete {
  color: #57534e;
  background: rgba(245, 245, 244, 0.76);
  border: 1px solid rgba(168, 162, 158, 0.24);
}

.project-card__link:hover,
.project-card__favorite:hover,
.project-card__recommend:hover,
.project-card__edit:hover,
.project-card__delete:hover {
  transform: translateY(-1px);
}

.project-card__link:hover {
  color: #292524;
  background: rgba(255, 255, 255, 0.96);
  border-color: rgba(87, 83, 78, 0.30);
}

.project-card__favorite:hover {
  color: #78350f;
  background: rgba(254, 243, 199, 0.98);
  border-color: rgba(245, 158, 11, 0.46);
}

.project-card__recommend:hover {
  color: #9f1239;
  background: rgba(255, 228, 230, 0.98);
  border-color: rgba(244, 63, 94, 0.46);
}

.project-card__edit:hover {
  color: #155e75;
  background: rgba(207, 250, 254, 0.92);
  border-color: rgba(6, 182, 212, 0.36);
}

.project-card__delete:hover {
  color: #292524;
  background: rgba(231, 229, 228, 0.82);
  border-color: rgba(87, 83, 78, 0.30);
}

.project-card__favorite:disabled,
.project-card__recommend:disabled,
.project-card__edit:disabled,
.project-card__delete:disabled {
  cursor: wait;
  opacity: 0.65;
  transform: none;
}

.project-card__link svg {
  width: 13px;
  height: 13px;
}

.project-card__description {
  display: -webkit-box;
  min-height: 60px;
  overflow: hidden;
  color: #57534e;
  font-size: 14px;
  line-height: 1.55;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}

.project-card__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.project-chip {
  cursor: pointer;
  transition: transform 160ms ease, border-color 160ms ease, background 160ms ease, color 160ms ease;
}

.project-chip:hover,
.project-chip:focus-visible {
  color: var(--projects-accent);
  background: rgba(236, 254, 255, 0.76);
  border-color: var(--projects-accent-border);
  transform: translateY(-1px);
  outline: none;
}

.project-chip--language:hover,
.project-chip--language:focus-visible {
  color: var(--projects-warm);
  background: rgba(255, 251, 235, 0.86);
  border-color: rgba(245, 158, 11, 0.28);
}

.project-card__stats {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: auto;
  padding-top: 14px;
  border-top: 1px dashed rgba(168, 162, 158, 0.24);
  color: #78716c;
  font-size: 12px;
  font-weight: 700;
}

.project-card__stats span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.project-card__stats svg {
  width: 14px;
  height: 14px;
  color: var(--projects-warm);
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

.projects-pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 18px;
  padding: 14px 16px;
}

.projects-pagination p {
  color: #78716c;
  font-size: 13px;
  font-weight: 700;
}

.projects-pagination__controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.projects-pagination__jump {
  display: flex;
  align-items: center;
  gap: 7px;
  margin: 0 2px;
  color: #78716c;
  font-size: 12px;
  font-weight: 700;
}

.projects-pagination__jump input {
  width: 58px;
  height: 36px;
  padding: 0 8px;
  color: #44403c;
  font-size: 13px;
  font-weight: 700;
  text-align: center;
  background: rgba(255, 255, 255, 0.78);
  border: 1px solid rgba(168, 162, 158, 0.34);
  border-radius: 10px;
  outline: none;
  transition: border-color 160ms ease, box-shadow 160ms ease, background 160ms ease;
}

.projects-pagination__jump input:focus {
  background: #fff;
  border-color: var(--projects-warm);
  box-shadow: 0 0 0 3px rgba(217, 119, 6, 0.12);
}

.projects-pagination__jump input::-webkit-inner-spin-button,
.projects-pagination__jump input::-webkit-outer-spin-button {
  margin: 0;
  appearance: none;
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

.tool-modal {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: grid;
  place-items: center;
  padding: 24px;
  background:
    radial-gradient(circle at 50% 38%, rgba(168, 162, 158, 0.18), transparent 34%),
    rgba(41, 37, 36, 0.34);
  backdrop-filter: blur(16px);
}

.tool-modal__panel {
  position: relative;
  width: min(640px, 100%);
  max-height: min(86vh, 760px);
  overflow-y: auto;
  border: 1px solid rgba(255, 255, 255, 0.68);
  border-radius: 30px;
  padding: 30px;
  background:
    linear-gradient(145deg, rgba(255, 255, 255, 0.96), rgba(245, 245, 244, 0.90)),
    radial-gradient(circle at 0 0, rgba(168, 162, 158, 0.12), transparent 42%);
  box-shadow: 0 30px 90px rgba(41, 37, 36, 0.24);
}

.tool-modal__panel::before {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0.42;
  background-image:
    linear-gradient(rgba(168, 162, 158, 0.10) 1px, transparent 1px),
    linear-gradient(90deg, rgba(168, 162, 158, 0.10) 1px, transparent 1px);
  background-size: 26px 26px;
}

.tool-modal__panel > * {
  position: relative;
  z-index: 1;
}

.tool-modal__close {
  position: absolute;
  top: 16px;
  right: 16px;
  z-index: 2;
  width: 34px;
  height: 34px;
  border: 1px solid rgba(168, 162, 158, 0.24);
  border-radius: 999px;
  color: #78716c;
  background: rgba(255, 255, 255, 0.72);
  font-size: 22px;
  line-height: 1;
}

.tool-modal__panel h2 {
  color: #292524;
  font-family: 'Playfair Display', serif;
  font-size: 36px;
  font-weight: 600;
  letter-spacing: -0.03em;
}

.tool-modal__hint {
  margin-top: 10px;
  color: #78716c;
  font-size: 14px;
  line-height: 1.75;
}

.tool-modal__tabs {
  display: inline-flex;
  gap: 6px;
  margin-top: 18px;
  border: 1px solid rgba(168, 162, 158, 0.20);
  border-radius: 999px;
  padding: 5px;
  background: rgba(255, 255, 255, 0.62);
}

.tool-modal__tabs button {
  border: 0;
  border-radius: 999px;
  padding: 8px 13px;
  color: #78716c;
  background: transparent;
  font-size: 12px;
  font-weight: 800;
  transition: all 160ms ease;
}

.tool-modal__tabs button:hover,
.tool-modal__tab--active {
  color: var(--projects-accent) !important;
  background: rgba(245, 245, 244, 0.92) !important;
  box-shadow: 0 6px 18px var(--projects-accent-soft);
}

.tool-modal__field {
  display: grid;
  gap: 8px;
  margin-top: 22px;
  color: #57534e;
  font-size: 12px;
  font-weight: 800;
}

.tool-modal__manual-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 12px;
}

.tool-modal__field--wide {
  grid-column: 1 / -1;
}

.tool-modal__field input,
.tool-modal__field select,
.tool-modal__field textarea {
  width: 100%;
  border: 1px solid rgba(168, 162, 158, 0.30);
  border-radius: 18px;
  padding: 14px 16px;
  color: #292524;
  background: rgba(255, 255, 255, 0.78);
  outline: none;
  font-size: 14px;
  transition: border-color 160ms ease, box-shadow 160ms ease;
}

.tool-modal__field textarea {
  resize: vertical;
  min-height: 92px;
  line-height: 1.6;
}

.tool-modal__field input:focus,
.tool-modal__field select:focus,
.tool-modal__field textarea:focus {
  border-color: var(--projects-accent-border);
  box-shadow: 0 0 0 4px var(--projects-accent-soft);
}

.tool-modal__readonly {
  grid-column: 1 / -1;
  margin-top: 12px;
  overflow-wrap: anywhere;
  color: #78716c;
  font-size: 12px;
  line-height: 1.6;
}

.tool-modal__error {
  margin-top: 12px;
  border-radius: 16px;
  padding: 10px 12px;
  color: #57534e;
  background: rgba(245, 245, 244, 0.82);
  border: 1px solid rgba(168, 162, 158, 0.22);
  font-size: 13px;
}

.tool-modal__actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 22px;
}

.tool-modal-enter-active,
.tool-modal-leave-active {
  transition: opacity 180ms ease;
}

.tool-modal-enter-active .tool-modal__panel,
.tool-modal-leave-active .tool-modal__panel {
  transition: transform 180ms ease, opacity 180ms ease;
}

.tool-modal-enter-from,
.tool-modal-leave-to {
  opacity: 0;
}

.tool-modal-enter-from .tool-modal__panel,
.tool-modal-leave-to .tool-modal__panel {
  opacity: 0;
  transform: translateY(10px) scale(0.98);
}

@media (max-width: 720px) {
  .projects-page {
    padding: 16px 16px 96px;
  }

  .projects-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .project-card {
    min-width: 0;
  }

  .projects-hero,
  .projects-toolbar,
  .projects-login-prompt,
  .projects-pagination {
    align-items: flex-start;
    flex-direction: column;
  }

  .projects-pagination__controls {
    width: 100%;
    flex-wrap: wrap;
  }

  .projects-pagination__jump {
    flex: 1;
    justify-content: center;
  }

  .projects-hero {
    padding: 22px;
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

  .projects-hero__side,
  .projects-toolbar,
  .projects-source-tabs,
  .projects-search,
  .projects-sort,
  .projects-sort select {
    width: 100%;
  }

  .projects-source-tabs {
    overflow-x: auto;
  }

  .project-card__header {
    flex-direction: column;
    padding-right: 0;
  }

  .project-card__actions {
    align-items: flex-start;
    flex-direction: row;
    flex-wrap: wrap;
  }

  .project-card__stats {
    flex-wrap: wrap;
  }

  .tool-modal__overlay {
    padding: 10px;
  }

  .tool-modal__panel {
    max-height: calc(100dvh - 20px);
    overflow-y: auto;
    padding: 20px;
  }

  .tool-modal__manual-grid {
    grid-template-columns: 1fr;
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

.projects-hero::after,
.projects-category-panel::before,
.project-card::before,
.tool-modal__panel::before { opacity: .22; mask-image: none; }
.projects-kicker { color: #11110f; }
.projects-kicker::before { content: '■'; margin-right: 8px; color: var(--projects-acid); -webkit-text-stroke: 1px #11110f; }
.projects-hero h1,
.empty-state h2,
.projects-login-prompt__copy h2,
.tool-modal__panel h2 {
  color: #11110f;
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
  font-weight: 900;
  letter-spacing: -.055em;
}

.projects-hero__stats span,
.projects-source-tab,
.projects-sort select,
.projects-search__filter,
.projects-login-prompt__notes span,
.projects-subcategories__label,
.project-card__source,
.project-card__link,
.project-card__favorite,
.project-card__recommend,
.project-card__edit,
.project-card__delete,
.tool-modal__close,
.tool-modal__tabs,
.tool-modal__tabs button,
.tool-modal__field input,
.tool-modal__field select,
.tool-modal__field textarea,
.tool-modal__error,
.projects-pagination__jump input {
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

.projects-source-tab:hover,
.projects-category:hover,
.projects-category:focus-visible,
.projects-page :deep(.tab-inactive:hover) {
  border-color: #11110f;
  color: #11110f;
  background: var(--projects-acid-soft);
  transform: none;
}
.projects-source-tab--active,
.projects-page :deep(.tab-active) {
  border-color: #11110f;
  color: #11110f;
  background: var(--projects-acid);
  box-shadow: inset 0 0 0 1px #11110f;
  transform: none;
}
.projects-source-tab--active strong { color: #11110f; }
.projects-page :deep(.tab-inactive) { border: 1px solid #11110f; border-radius: 4px; background: var(--projects-paper-light); }
.projects-search :deep(.input) { border: 1px solid #11110f; border-radius: 4px; background: var(--projects-paper-light); box-shadow: none; }
.projects-search :deep(.input:focus),
.tool-modal__field input:focus,
.tool-modal__field select:focus,
.tool-modal__field textarea:focus,
.projects-pagination__jump input:focus { border-color: #11110f; box-shadow: 0 0 0 3px var(--projects-acid); }

.projects-login-prompt { background: var(--projects-paper-light); }
.projects-login-prompt__mark { border-color: #11110f; border-radius: 6px; color: #11110f; background: var(--projects-acid); box-shadow: 4px 4px 0 #11110f; transform: none; }
.projects-subcategories { border-top: 1px solid #11110f; }
.projects-category { border-radius: 4px; }
.projects-grid { gap: 12px; }
.project-card { border-radius: 6px; }
.project-card__pin { width: 12px; height: 12px; border: 1px solid #11110f; border-radius: 2px; background: var(--projects-acid); box-shadow: none; }
.project-card__pin--website { background: var(--projects-acid); }
.project-card__logo { border-color: #11110f; border-radius: 4px; box-shadow: none; }
.project-card__source { color: #11110f; background: var(--projects-acid); }
.project-card__stats { border-top: 1px solid #11110f; color: #11110f; }
.project-card__stats svg { color: #11110f; }

.project-card__link:hover,
.project-card__favorite:hover,
.project-card__recommend:hover,
.project-card__edit:hover,
.project-chip:hover,
.project-chip:focus-visible,
.project-chip--language:hover,
.project-chip--language:focus-visible {
  border-color: #11110f;
  color: #11110f;
  background: var(--projects-acid-soft);
  transform: none;
}
.project-card__delete:hover {
  border-color: #991b1b;
  color: #991b1b;
  background: #fef2f2;
  transform: none;
}
.project-card__favorite--active,
.project-card__recommend--active { border-color: #11110f; color: #11110f; background: var(--projects-acid); box-shadow: none; }

.tool-modal {
  --projects-paper: #f3f0e6;
  --projects-paper-light: #fffdf5;
  --projects-acid: #c7f432;
  --projects-acid-soft: #f1f8d2;
  background: rgba(17, 17, 15, .72);
  backdrop-filter: none;
}
.tool-modal__panel { border: 2px solid #11110f; border-radius: 6px; background: var(--projects-paper); box-shadow: 8px 8px 0 var(--projects-acid); }
.tool-modal__tabs button:hover { color: #11110f !important; background: var(--projects-acid-soft) !important; box-shadow: none; }
.tool-modal__tab--active,
.tool-modal__tab--active:hover { color: #11110f !important; background: var(--projects-acid) !important; box-shadow: none; }

.project-card__source-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}
.project-card__availability {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 2px 7px;
  border: 1px solid #666;
  border-radius: 3px;
  color: #444;
  background: #e5e5e5;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .04em;
}
.project-card.project-card--not-found {
  border-color: #8a8a85;
  background: #e7e7e2;
  box-shadow: 5px 5px 0 #a5a5a0;
}
.project-card.project-card--not-found:hover {
  border-color: #666662;
  background: #deded9;
}
.project-card--not-found .project-card__pin,
.project-card--not-found .project-card__source,
.project-card--not-found .project-card__favorite--active,
.project-card--not-found .project-card__recommend--active {
  border-color: #666662;
  color: #333;
  background: #b8b8b3;
}
.project-card--not-found h2,
.project-card--not-found .project-card__description,
.project-card--not-found .project-card__stats,
.project-card--not-found .project-card__stats svg,
.project-card--not-found .project-card__domain {
  color: #555550;
}
.project-card--not-found .project-card__stats {
  border-top-color: #8a8a85;
}
.project-card--not-found .project-chip {
  border-color: #888883;
  color: #555550;
  background: #d6d6d1;
}

@media (prefers-reduced-motion: reduce) {
  .projects-page *, .projects-page *::before, .projects-page *::after { scroll-behavior: auto !important; transition-duration: .01ms !important; animation-duration: .01ms !important; }
}
</style>
