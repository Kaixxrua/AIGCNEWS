import { ref, type Ref } from 'vue'
import type { RouteLocationNormalizedLoaded, Router } from 'vue-router'
import type {
  GitHubProjectSort,
  ProjectScope,
  ProjectViewSource,
} from '@/services/projects/projectApi'

type ProjectRouteQuery = Record<string, string>

type ProjectRouteState = {
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

const validSources: ProjectViewSource[] = ['all', 'website', 'favorites']
const validScopes: ProjectScope[] = ['all', 'today', 'recommended']
const validSorts: GitHubProjectSort[] = ['hot', 'stars', 'updated', 'recent', 'name', 'relevance']

const queryValue = (value: unknown) => {
  if (Array.isArray(value)) return String(value[0] ?? '').trim()
  return String(value ?? '').trim()
}

const parseRoutePage = (value: unknown) => {
  const parsed = Number(queryValue(value) || 1)
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : 1
}

export const defaultProjectSortForSource = (value: ProjectViewSource): GitHubProjectSort => (
  value === 'favorites' || value === 'website' ? 'recent' : 'stars'
)

export const defaultProjectScopeForQuery = (
  source: ProjectViewSource,
  query: string,
): ProjectScope => (
  source === 'all' && !query.trim() ? 'today' : 'all'
)

export const defaultProjectSortForScope = (
  scope: ProjectScope,
  source: ProjectViewSource,
): GitHubProjectSort => {
  if (scope === 'today' && source === 'all') return 'hot'
  if (scope === 'recommended' && source === 'all') return 'recent'
  return defaultProjectSortForSource(source)
}

export const defaultProjectSortForQuery = (
  scope: ProjectScope,
  source: ProjectViewSource,
  query: string,
): GitHubProjectSort => {
  if (scope === 'today' && source === 'all') return 'hot'
  if (scope === 'recommended' && source === 'all') return 'recent'
  if (source === 'all' && query.trim()) return 'relevance'
  return defaultProjectSortForSource(source)
}

const sameRouteQuery = (left: Record<string, unknown>, right: ProjectRouteQuery) => {
  const keys = new Set([...Object.keys(left), ...Object.keys(right)])
  for (const key of keys) {
    if (queryValue(left[key]) !== queryValue(right[key])) return false
  }
  return true
}

export const useProjectRouteState = (
  route: RouteLocationNormalizedLoaded,
  router: Router,
  state: ProjectRouteState,
) => {
  const isApplyingRouteState = ref(false)
  const isReplacingRoute = ref(false)

  const endStateBatch = () => {
    window.setTimeout(() => {
      isApplyingRouteState.value = false
    }, 0)
  }

  const currentProjectsRedirect = () => (
    route.fullPath.startsWith('/projects') ? route.fullPath : '/projects'
  )

  const buildRouteQuery = (): ProjectRouteQuery => {
    const query: ProjectRouteQuery = {}
    const cleanQuery = state.debouncedQuery.value.trim()
    if (state.source.value !== 'all') query.source = state.source.value
    if (state.selectedScope.value !== defaultProjectScopeForQuery(state.source.value, cleanQuery)) query.scope = state.selectedScope.value
    if (state.selectedCategory.value !== 'all') query.category = state.selectedCategory.value
    if (state.selectedSubcategory.value !== 'all') query.subcategory = state.selectedSubcategory.value
    if (cleanQuery) query.q = cleanQuery
    if (state.selectedLanguage.value) query.language = state.selectedLanguage.value
    const isPersonalView = state.source.value === 'favorites' || state.source.value === 'website'
    if (isPersonalView && state.selectedTag.value) query.tag = state.selectedTag.value
    const defaultSort = defaultProjectSortForQuery(
      state.selectedScope.value,
      state.source.value,
      cleanQuery,
    )
    if (state.sort.value !== defaultSort && (state.sort.value !== 'hot' || state.source.value === 'all')) {
      query.sort = state.sort.value
    }
    if (state.page.value > 1) query.page = String(state.page.value)
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
    const nextQuery = queryValue(route.query.q)
    const nextScope = validScopes.includes(routeScope as ProjectScope)
      ? routeScope as ProjectScope
      : defaultProjectScopeForQuery(nextSource, nextQuery)
    const routeSort = queryValue(route.query.sort)
    const isPublic = nextSource === 'all'
    const defaultSort = defaultProjectSortForQuery(nextScope, nextSource, nextQuery)
    const routeSortAllowed = validSorts.includes(routeSort as GitHubProjectSort)
      && (routeSort !== 'hot' || nextSource === 'all')
      && (routeSort !== 'relevance' || (isPublic && Boolean(nextQuery)))
    const nextSort = nextScope === 'today'
      ? 'hot'
      : (routeSortAllowed
          ? routeSort as GitHubProjectSort
          : defaultSort)

    isApplyingRouteState.value = true
    state.source.value = nextSource
    state.selectedScope.value = nextScope
    state.selectedCategory.value = queryValue(route.query.category) || 'all'
    state.selectedSubcategory.value = queryValue(route.query.subcategory) || 'all'
    state.selectedLanguage.value = queryValue(route.query.language)
    state.selectedTag.value = nextSource === 'favorites' || nextSource === 'website'
      ? queryValue(route.query.tag)
      : ''
    state.searchQuery.value = nextQuery
    state.debouncedQuery.value = nextQuery
    state.sort.value = nextSort
    state.page.value = parseRoutePage(route.query.page)
    endStateBatch()
    return true
  }

  return {
    applyRouteState,
    currentProjectsRedirect,
    endStateBatch,
    isApplyingRouteState,
    isReplacingRoute,
    replaceRouteFromState,
  }
}
