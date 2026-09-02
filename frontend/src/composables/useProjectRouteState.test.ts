import { nextTick, reactive, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { RouteLocationNormalizedLoaded, Router } from 'vue-router'
import { defaultProjectScopeForQuery, defaultProjectSortForQuery, useProjectRouteState } from './useProjectRouteState'
import type {
  GitHubProjectSort,
  ProjectScope,
  ProjectViewSource,
} from '@/services/projects/projectApi'

const createHarness = (query: Record<string, unknown> = {}, fullPath = '/projects') => {
  const route = reactive({
    path: '/projects',
    fullPath,
    query,
  }) as unknown as RouteLocationNormalizedLoaded
  const replace = vi.fn().mockResolvedValue(undefined)
  const router = { replace } as unknown as Router
  const state = {
    source: ref<ProjectViewSource>('all'),
    selectedScope: ref<ProjectScope>('all'),
    selectedCategory: ref('all'),
    selectedSubcategory: ref('all'),
    searchQuery: ref(''),
    debouncedQuery: ref(''),
    selectedLanguage: ref(''),
    selectedTag: ref(''),
    sort: ref<GitHubProjectSort>('stars'),
    page: ref(1),
  }
  return {
    route,
    replace,
    state,
    routeState: useProjectRouteState(route, router, state),
  }
}

describe('project route state contract', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('applies a complete personal route and normalizes array and page values', () => {
    const harness = createHarness({
      source: ['favorites', 'all'],
      scope: 'recommended',
      category: 'agents',
      subcategory: 'coding',
      q: ' mcp ',
      language: 'TypeScript',
      tag: 'research',
      sort: 'updated',
      page: '3.8',
    })

    expect(harness.routeState.applyRouteState()).toBe(true)
    expect(harness.state.source.value).toBe('favorites')
    expect(harness.state.selectedScope.value).toBe('recommended')
    expect(harness.state.selectedCategory.value).toBe('agents')
    expect(harness.state.selectedSubcategory.value).toBe('coding')
    expect(harness.state.searchQuery.value).toBe('mcp')
    expect(harness.state.debouncedQuery.value).toBe('mcp')
    expect(harness.state.selectedLanguage.value).toBe('TypeScript')
    expect(harness.state.selectedTag.value).toBe('research')
    expect(harness.state.sort.value).toBe('updated')
    expect(harness.state.page.value).toBe(3)
    expect(harness.routeState.isApplyingRouteState.value).toBe(true)

    vi.runAllTimers()
    expect(harness.routeState.isApplyingRouteState.value).toBe(false)
  })

  it('rejects invalid and source-incompatible route values', () => {
    const invalid = createHarness({
      source: 'invalid',
      scope: 'invalid',
      sort: 'hot',
      tag: 'private',
      page: '-4',
    })
    invalid.routeState.applyRouteState()
    expect(invalid.state.source.value).toBe('all')
    expect(invalid.state.selectedScope.value).toBe('recommended')
    expect(invalid.state.sort.value).toBe('hot')
    expect(invalid.state.selectedTag.value).toBe('')
    expect(invalid.state.page.value).toBe(1)

    const personal = createHarness({ source: 'website', sort: 'hot', tag: 'tools' })
    personal.routeState.applyRouteState()
    expect(personal.state.sort.value).toBe('recent')
    expect(personal.state.selectedTag.value).toBe('tools')

    const today = createHarness({ scope: 'today', sort: 'name' })
    today.routeState.applyRouteState()
    expect(today.state.sort.value).toBe('hot')
  })

  it('lands on the recommended scope with recent sort when no route state is present', async () => {
    const landing = createHarness()
    landing.routeState.applyRouteState()
    expect(landing.state.selectedScope.value).toBe('recommended')
    expect(landing.state.sort.value).toBe('recent')
    vi.runAllTimers()

    await landing.routeState.replaceRouteFromState()
    expect(landing.replace).not.toHaveBeenCalled()

    landing.state.selectedScope.value = 'all'
    landing.state.sort.value = 'stars'
    await landing.routeState.replaceRouteFromState()
    expect(landing.replace).toHaveBeenCalledWith({
      path: '/projects',
      query: { scope: 'all' },
    })
  })

  it('falls back to the all scope for public searches and personal sources', () => {
    const search = createHarness({ q: 'mcp' })
    search.routeState.applyRouteState()
    expect(search.state.selectedScope.value).toBe('all')
    expect(search.state.sort.value).toBe('relevance')

    const personal = createHarness({ source: 'favorites' })
    personal.routeState.applyRouteState()
    expect(personal.state.selectedScope.value).toBe('all')
  })

  it('serializes only canonical non-default values', async () => {
    const harness = createHarness()
    harness.state.source.value = 'favorites'
    harness.state.selectedScope.value = 'recommended'
    harness.state.selectedCategory.value = 'agents'
    harness.state.selectedSubcategory.value = 'coding'
    harness.state.debouncedQuery.value = 'mcp'
    harness.state.selectedLanguage.value = 'Python'
    harness.state.selectedTag.value = 'research'
    harness.state.sort.value = 'updated'
    harness.state.page.value = 4

    await harness.routeState.replaceRouteFromState()

    expect(harness.replace).toHaveBeenCalledWith({
      path: '/projects',
      query: {
        source: 'favorites',
        scope: 'recommended',
        category: 'agents',
        subcategory: 'coding',
        q: 'mcp',
        language: 'Python',
        tag: 'research',
        sort: 'updated',
        page: '4',
      },
    })
    expect(harness.routeState.isReplacingRoute.value).toBe(true)
    vi.runAllTimers()
    expect(harness.routeState.isReplacingRoute.value).toBe(false)
  })

  it('suppresses equivalent and route-application replacements unless forced', async () => {
    const equivalent = createHarness({ source: 'favorites', tag: 'research' })
    equivalent.state.source.value = 'favorites'
    equivalent.state.selectedTag.value = 'research'
    equivalent.state.sort.value = 'recent'
    await equivalent.routeState.replaceRouteFromState()
    expect(equivalent.replace).not.toHaveBeenCalled()

    const applying = createHarness({ source: 'favorites' })
    applying.routeState.applyRouteState()
    applying.state.selectedTag.value = 'new'
    await applying.routeState.replaceRouteFromState()
    expect(applying.replace).not.toHaveBeenCalled()

    await applying.routeState.replaceRouteFromState(true)
    expect(applying.replace).toHaveBeenCalledTimes(1)
    await nextTick()
  })

  it('defaults public query sort to relevance and preserves explicit choices', async () => {
    const harness = createHarness({ q: 'langchain' })
    harness.routeState.applyRouteState()
    expect(harness.state.sort.value).toBe('relevance')
    vi.runAllTimers()

    harness.state.sort.value = 'stars'
    await harness.routeState.replaceRouteFromState()
    expect(harness.replace).toHaveBeenCalledWith({
      path: '/projects',
      query: { q: 'langchain', sort: 'stars' },
    })
  })

  it('drops relevance for personal sources and empty public queries', () => {
    const personal = createHarness({ source: 'favorites', q: 'mcp', sort: 'relevance' })
    personal.routeState.applyRouteState()
    expect(personal.state.sort.value).toBe('recent')

    const emptyPublic = createHarness({ sort: 'relevance' })
    emptyPublic.routeState.applyRouteState()
    expect(emptyPublic.state.selectedScope.value).toBe('recommended')
    expect(emptyPublic.state.sort.value).toBe('recent')
  })

  it('suppresses relevance sort from URL when it matches the query default', async () => {
    const harness = createHarness({ q: 'langchain', sort: 'relevance' })
    harness.routeState.applyRouteState()
    vi.runAllTimers()
    harness.state.page.value = 2
    await harness.routeState.replaceRouteFromState()
    expect(harness.replace).toHaveBeenCalledWith({
      path: '/projects',
      query: { q: 'langchain', page: '2' },
    })
  })

  it('exposes the query-aware default helper', () => {
    expect(defaultProjectSortForQuery('all', 'all', 'langchain')).toBe('relevance')
    expect(defaultProjectSortForQuery('all', 'all', '')).toBe('stars')
    expect(defaultProjectSortForQuery('today', 'all', 'langchain')).toBe('hot')
    expect(defaultProjectSortForQuery('all', 'favorites', 'mcp')).toBe('recent')
  })

  it('exposes the query-aware default scope helper', () => {
    expect(defaultProjectScopeForQuery('all', '')).toBe('recommended')
    expect(defaultProjectScopeForQuery('all', '  ')).toBe('recommended')
    expect(defaultProjectScopeForQuery('all', 'mcp')).toBe('all')
    expect(defaultProjectScopeForQuery('favorites', '')).toBe('all')
    expect(defaultProjectScopeForQuery('website', '')).toBe('all')
  })
})
