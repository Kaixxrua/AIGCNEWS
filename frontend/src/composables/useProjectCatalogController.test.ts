import { ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import type { GitHubProjectItem, GitHubProjectsResponse } from '../services/projects/projectApi'
import { useProjectCatalogController, type ProjectCatalogApi } from './useProjectCatalogController'

const deferred = <T>() => {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, reject, resolve }
}

const projectsResponse = (items: GitHubProjectItem[], total = items.length): GitHubProjectsResponse => ({
  items,
  total,
  page: 1,
  page_size: 24,
  has_next: false,
  min_stars: 500,
})

const createApi = (): ProjectCatalogApi => ({
  addMyToolWebsite: vi.fn(),
  addMyToolWebsiteManual: vi.fn(),
  favoriteProject: vi.fn(),
  fetchMyProjectCollection: vi.fn(),
  fetchMyProjectTags: vi.fn(),
  fetchProjectCategories: vi.fn(),
  fetchProjects: vi.fn(),
  fetchProjectTaxonomy: vi.fn(),
  recommendGitHubProject: vi.fn(),
  removeMyToolWebsite: vi.fn(),
  unfavoriteProject: vi.fn(),
  unrecommendGitHubProject: vi.fn(),
  updateMyToolWebsite: vi.fn(),
})

const githubItem = (overrides: Partial<GitHubProjectItem> = {}): GitHubProjectItem => ({
  repo_id: 1,
  full_name: 'owner/project',
  is_favorited: false,
  ...overrides,
})

describe('project catalog controller', () => {
  it('uses shared route-state refs when the view provides them', () => {
    const routeState = {
      source: ref<'all' | 'favorites' | 'website'>('all'),
      selectedScope: ref<'all' | 'today' | 'recommended'>('all'),
      selectedCategory: ref('all'),
      selectedSubcategory: ref('all'),
      searchQuery: ref(''),
      debouncedQuery: ref(''),
      selectedLanguage: ref(''),
      selectedTag: ref(''),
      sort: ref<'stars' | 'updated' | 'recent' | 'name' | 'hot'>('stars'),
      page: ref(1),
    }
    const controller = useProjectCatalogController({ api: createApi(), routeState })

    controller.source.value = 'website'
    controller.searchQuery.value = 'shared search'
    controller.page.value = 3

    expect(routeState.source.value).toBe('website')
    expect(routeState.searchQuery.value).toBe('shared search')
    expect(routeState.page.value).toBe(3)
  })

  it('owns public and personal read parameters while rejecting superseded responses', async () => {
    const api = createApi()
    const first = deferred<GitHubProjectsResponse>()
    const second = deferred<GitHubProjectsResponse>()
    vi.mocked(api.fetchProjects)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise)
    vi.mocked(api.fetchMyProjectCollection).mockResolvedValue(projectsResponse([githubItem({ repo_id: 3 })]))

    const controller = useProjectCatalogController({ api, isLoggedIn: () => true })
    controller.selectedCategory.value = 'agents'
    controller.selectedSubcategory.value = 'coding'
    controller.debouncedQuery.value = ' mcp '
    controller.selectedLanguage.value = 'TypeScript'
    controller.selectedTag.value = 'ignored-public-tag'
    controller.sort.value = 'updated'
    controller.page.value = 2

    const staleLoad = controller.loadProjects()
    controller.page.value = 3
    const currentLoad = controller.loadProjects()
    second.resolve(projectsResponse([githubItem({ repo_id: 2, full_name: 'new/result' })], 100))
    await currentLoad
    first.resolve(projectsResponse([githubItem({ repo_id: 1, full_name: 'stale/result' })]))
    await staleLoad

    expect(api.fetchProjects).toHaveBeenNthCalledWith(1, expect.objectContaining({
      source: 'github',
      scope: 'all',
      category: 'agents',
      subcategory: 'coding',
      q: 'mcp',
      language: 'TypeScript',
      tag: '',
      page: 2,
      page_size: 24,
      sort: 'updated',
    }))
    expect(controller.projects.value.map(item => item.full_name)).toEqual(['new/result'])

    controller.source.value = 'favorites'
    controller.selectedTag.value = 'research'
    await controller.loadProjects()
    expect(api.fetchMyProjectCollection).toHaveBeenCalledWith(expect.objectContaining({
      source: 'github',
      tag: 'research',
    }))
  })

  it('invalidates project, category, tag and taxonomy reads when the view deactivates', async () => {
    const api = createApi()
    const projects = deferred<GitHubProjectsResponse>()
    const categories = deferred<Awaited<ReturnType<ProjectCatalogApi['fetchProjectCategories']>>>()
    const tags = deferred<Awaited<ReturnType<ProjectCatalogApi['fetchMyProjectTags']>>>()
    const taxonomy = deferred<Awaited<ReturnType<ProjectCatalogApi['fetchProjectTaxonomy']>>>()
    vi.mocked(api.fetchMyProjectCollection).mockReturnValue(projects.promise)
    vi.mocked(api.fetchProjectCategories).mockReturnValue(categories.promise)
    vi.mocked(api.fetchMyProjectTags).mockReturnValue(tags.promise)
    vi.mocked(api.fetchProjectTaxonomy).mockReturnValue(taxonomy.promise)

    const controller = useProjectCatalogController({ api, isLoggedIn: () => true })
    controller.source.value = 'favorites'
    const projectRead = controller.loadProjects()
    const tagRead = controller.loadPersonalTags()
    const taxonomyRead = controller.loadTaxonomy()
    controller.source.value = 'all'
    const categoryRead = controller.loadCategories()
    controller.deactivate()

    projects.resolve(projectsResponse([githubItem()]))
    categories.resolve({ items: [{ slug: 'agents', name: 'Agents', count: 1 }], total: 1, min_stars: 500 })
    tags.resolve({ items: [{ label: 'research', count: 1 }], total: 1 })
    taxonomy.resolve({ items: [{ slug: 'agents', name: 'Agents', children: [] }] })
    await Promise.all([projectRead, categoryRead, tagRead, taxonomyRead])

    expect(controller.projects.value).toEqual([])
    expect(controller.categories.value).toEqual([])
    expect(controller.personalTags.value).toEqual([])
    expect(controller.taxonomy.value).toEqual([])
  })

  it('prevents stale mutation completions from changing newer view state', async () => {
    const api = createApi()
    const recommendation = deferred<Awaited<ReturnType<ProjectCatalogApi['recommendGitHubProject']>>>()
    const website = deferred<Awaited<ReturnType<ProjectCatalogApi['addMyToolWebsite']>>>()
    vi.mocked(api.recommendGitHubProject).mockReturnValue(recommendation.promise)
    vi.mocked(api.addMyToolWebsite).mockReturnValue(website.promise)
    const replaceRouteFromState = vi.fn()
    const controller = useProjectCatalogController({
      api,
      isAdmin: () => true,
      isLoggedIn: () => true,
      replaceRouteFromState,
    })
    const item = githubItem()

    const recommend = controller.recommendProject(item)
    const add = controller.submitToolWebsite('https://example.com')
    controller.invalidateView()
    controller.successMsg.value = 'newer view message'
    recommendation.resolve({
      status: 'succeeded',
      message: 'recommended',
      repo_id: '1',
      full_name: item.full_name,
      is_recommended: true,
    })
    website.resolve({ status: 'succeeded', message: 'added', duplicate: false, item: null })
    await Promise.all([recommend, add])

    expect(item.is_recommended).toBeUndefined()
    expect(controller.source.value).toBe('all')
    expect(controller.successMsg.value).toBe('newer view message')
    expect(replaceRouteFromState).not.toHaveBeenCalled()
  })

  it('uses localized success messages instead of API response prose', async () => {
    const api = createApi()
    vi.mocked(api.favoriteProject).mockResolvedValue({
      status: 'succeeded',
      source: 'github',
      is_favorited: true,
      favorited_at: '2026-07-29T00:00:00.000Z',
      message: '已加入我的收藏。',
    })
    vi.mocked(api.unfavoriteProject).mockResolvedValue({
      status: 'succeeded',
      source: 'github',
      is_favorited: false,
      favorited_at: null,
      message: '已取消收藏。',
    })
    const t = vi.fn((key: string) => ({
      'projects.favoriteAdded': 'Project added to favorites.',
      'projects.favoriteRemoved': 'Project removed from favorites.',
    }[key] ?? key))
    const controller = useProjectCatalogController({ api, isLoggedIn: () => true, t })
    const item = githubItem()

    await controller.toggleFavorite(item)
    expect(controller.successMsg.value).toBe('Project added to favorites.')
    await controller.toggleFavorite(item)
    expect(controller.successMsg.value).toBe('Project removed from favorites.')
  })

  it('rolls back the initiating favorite item after failure even when its view is stale', async () => {
    const api = createApi()
    const favorite = deferred<Awaited<ReturnType<ProjectCatalogApi['favoriteProject']>>>()
    vi.mocked(api.favoriteProject).mockReturnValue(favorite.promise)
    const controller = useProjectCatalogController({
      api,
      isLoggedIn: () => true,
      now: () => Date.parse('2026-07-28T00:00:00.000Z'),
    })
    const item = githubItem({ favorited_at: null })

    const mutation = controller.toggleFavorite(item)
    expect(item.is_favorited).toBe(true)
    expect(item.favorited_at).toBe('2026-07-28T00:00:00.000Z')
    controller.invalidateView()
    controller.errorMsg.value = 'newer view error'
    favorite.reject(new Error('favorite failed'))
    await mutation

    expect(item.is_favorited).toBe(false)
    expect(item.favorited_at).toBeNull()
    expect(controller.errorMsg.value).toBe('newer view error')
  })
})
