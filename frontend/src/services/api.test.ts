import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => {
  const requestUse = vi.fn()
  const responseUse = vi.fn()
  const get = vi.fn()
  const post = vi.fn()
  const patch = vi.fn()
  const del = vi.fn()
  const apiClient = {
    get,
    post,
    patch,
    delete: del,
    interceptors: {
      request: { use: requestUse },
      response: { use: responseUse },
    },
  }
  return {
    apiClient,
    create: vi.fn(() => apiClient),
    requestUse,
    responseUse,
    get,
    post,
    patch,
    del,
    routerPush: vi.fn(),
    useAuthStore: vi.fn(),
    getActivePinia: vi.fn(),
  }
})

vi.mock('axios', () => ({ default: { create: mocks.create } }))
vi.mock('../stores/authStore', () => ({ useAuthStore: mocks.useAuthStore }))
vi.mock('pinia', () => ({ getActivePinia: mocks.getActivePinia }))
vi.mock('../router/index', () => ({ default: { push: mocks.routerPush } }))

import {
  addMyToolWebsite,
  api,
  favoriteProject,
  fetchGitHubHotRepos,
  fetchMyProjectTags,
  fetchPaperDetail,
  fetchProjectCategories,
  fetchProjects,
  fetchSnapshotDates,
  recommendGitHubProject,
  unfavoriteProject,
  unrecommendGitHubProject,
  uploadImageAttachment,
} from './api'

type RejectedInterceptor = (error: any) => Promise<never>
type RequestInterceptor = (config: any) => any

const requestInterceptor = mocks.requestUse.mock.calls[0]![0] as RequestInterceptor
const responseRejectedInterceptor = mocks.responseUse.mock.calls[0]![1] as RejectedInterceptor

describe('frontend API transport contract', () => {
  beforeEach(() => {
    mocks.get.mockReset()
    mocks.post.mockReset()
    mocks.patch.mockReset()
    mocks.del.mockReset()
    mocks.routerPush.mockReset()
    mocks.useAuthStore.mockReset()
    mocks.getActivePinia.mockReset()
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('creates one JSON Axios client rooted at /api with a 60 second timeout', () => {
    expect(api).toBe(mocks.apiClient)
    expect(mocks.create).toHaveBeenCalledOnce()
    expect(mocks.create).toHaveBeenCalledWith({
      baseURL: '/api',
      timeout: 60_000,
      headers: { 'Content-Type': 'application/json' },
    })
  })

  it('adds the current bearer token while preserving unauthenticated requests', () => {
    const anonymous = { headers: { Accept: 'application/json' } }
    expect(requestInterceptor(anonymous)).toBe(anonymous)
    expect(anonymous.headers).toEqual({ Accept: 'application/json' })

    localStorage.setItem('auth_token', 'current-token')
    const authenticated: { headers?: Record<string, string> } = {}
    expect(requestInterceptor(authenticated)).toBe(authenticated)
    expect(authenticated.headers).toEqual({ Authorization: 'Bearer current-token' })
  })

  it('redacts MCP token response data from API error logging', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const error = {
      message: 'request failed',
      config: { url: '/auth/me/mcp-tokens', method: 'post' },
      response: { status: 500, data: { token: 'must-not-be-logged' } },
    }

    await expect(responseRejectedInterceptor(error)).rejects.toBe(error)

    expect(errorSpy).toHaveBeenCalledWith('[API Error]', {
      status: 500,
      message: 'request failed',
      url: '/auth/me/mcp-tokens',
      method: 'post',
    })
    expect(JSON.stringify(errorSpy.mock.calls)).not.toContain('must-not-be-logged')
  })

  it('single-flights non-auth 401 navigation and releases the guard after navigation settles', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => undefined)
    const authStore = { token: 'old-token', user: { id: 1 } as unknown }
    const pinia = {}
    mocks.getActivePinia.mockReturnValue(pinia)
    mocks.useAuthStore.mockReturnValue(authStore)
    localStorage.setItem('auth_token', 'old-token')

    let finishNavigation!: () => void
    mocks.routerPush.mockImplementationOnce(() => new Promise<void>((resolve) => { finishNavigation = resolve }))
    const firstError = { config: { url: '/projects' }, response: { status: 401 } }
    const first = responseRejectedInterceptor(firstError)
    await vi.waitFor(() => expect(mocks.routerPush).toHaveBeenCalledOnce())

    const concurrentError = { config: { url: '/papers/search' }, response: { status: 401 } }
    await expect(responseRejectedInterceptor(concurrentError)).rejects.toBe(concurrentError)
    expect(alertSpy).toHaveBeenCalledOnce()
    expect(mocks.routerPush).toHaveBeenCalledOnce()
    expect(localStorage.getItem('auth_token')).toBeNull()
    expect(authStore).toEqual({ token: null, user: null })

    finishNavigation()
    await expect(first).rejects.toBe(firstError)

    mocks.routerPush.mockResolvedValueOnce(undefined)
    const laterError = { config: { url: '/dashboard' }, response: { status: 401 } }
    await expect(responseRejectedInterceptor(laterError)).rejects.toBe(laterError)
    expect(alertSpy).toHaveBeenCalledTimes(2)
    expect(mocks.routerPush).toHaveBeenCalledTimes(2)
  })

  it.each(['/auth/login', '/auth/me', '/auth/me/mcp-tokens'])('cleans auth state but suppresses login navigation for %s', async (url) => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => undefined)
    const authStore = { token: 'old-token', user: { id: 1 } as unknown }
    mocks.getActivePinia.mockReturnValue({})
    mocks.useAuthStore.mockReturnValue(authStore)
    localStorage.setItem('auth_token', 'old-token')
    const error = { config: { url }, response: { status: 401 } }

    await expect(responseRejectedInterceptor(error)).rejects.toBe(error)

    expect(localStorage.getItem('auth_token')).toBeNull()
    expect(authStore).toEqual({ token: null, user: null })
    expect(alertSpy).not.toHaveBeenCalled()
    expect(mocks.routerPush).not.toHaveBeenCalled()
  })
})

describe('frontend API endpoint and DTO contract', () => {
  beforeEach(() => {
    mocks.get.mockReset()
    mocks.post.mockReset()
    mocks.patch.mockReset()
    mocks.del.mockReset()
  })

  it('preserves representative query, body, delete, signal, and timeout request shapes', async () => {
    const signal = new AbortController().signal
    mocks.get.mockResolvedValueOnce({ data: { dates: ['2026-07-25'] } })
    await expect(fetchSnapshotDates(7, 'github', 'daily', signal)).resolves.toEqual(['2026-07-25'])
    expect(mocks.get).toHaveBeenLastCalledWith('/dashboard/snapshot-dates', {
      params: { limit: 7, source: 'github', period: 'daily' },
      signal,
    })

    mocks.post.mockResolvedValueOnce({ data: {} })
    await favoriteProject({ source: 'github', repo_id: 42 })
    expect(mocks.post).toHaveBeenLastCalledWith('/projects/me/favorites', { source: 'github', repo_id: 42 })

    mocks.del.mockResolvedValueOnce({ data: {} })
    await unfavoriteProject({ source: 'website', website_id: 9 })
    expect(mocks.del).toHaveBeenLastCalledWith('/projects/me/favorites', {
      params: { source: 'website', website_id: 9 },
    })

    mocks.del.mockResolvedValueOnce({ data: {} })
    await unrecommendGitHubProject({ repo_id: 42, full_name: 'owner/repo' })
    expect(mocks.del).toHaveBeenLastCalledWith('/ops/github-projects/recommendations', {
      data: { repo_id: 42, full_name: 'owner/repo' },
    })

    mocks.post.mockResolvedValueOnce({ data: {} })
    await addMyToolWebsite('https://example.test')
    expect(mocks.post).toHaveBeenLastCalledWith(
      '/projects/me/tool-websites',
      { url: 'https://example.test' },
      { timeout: 120_000 },
    )

    mocks.post.mockResolvedValueOnce({ data: { id: 'attachment' } })
    await uploadImageAttachment('base64-data', 'image/png', 'image.png')
    expect(mocks.post).toHaveBeenLastCalledWith('/chat/attachments/image', {
      image_base64: 'base64-data',
      mime_type: 'image/png',
      filename: 'image.png',
    })
  })

  it('normalizes project list defaults and numeric DTO fields', async () => {
    mocks.get.mockResolvedValueOnce({ data: { total: '12', page_size: '5', min_stars: '800', has_next: 1 } })

    await expect(fetchProjects({ page: 3, category: 'agents', tag: 'mcp', source: 'website' })).resolves.toEqual({
      items: [],
      total: 12,
      page: 3,
      page_size: 5,
      has_next: true,
      min_stars: 800,
      scope: 'all',
      category: 'agents',
      subcategory: '',
      q: '',
      tag: 'mcp',
      sort: 'stars',
      source: 'website',
    })
    expect(mocks.get).toHaveBeenCalledWith('/projects', {
      params: { page: 3, category: 'agents', tag: 'mcp', source: 'website' },
    })
  })

  it('normalizes category, tag, hot-repository, favorite, and recommendation DTOs', async () => {
    mocks.get.mockResolvedValueOnce({ data: { total: '2', today_count: '1', recommended_count: null } })
    await expect(fetchProjectCategories('github')).resolves.toMatchObject({
      items: [], total: 2, today_count: 1, recommended_count: 0, min_stars: 500, source: 'github',
    })

    mocks.get.mockResolvedValueOnce({ data: { items: [{ label: '  Vue  ', count: '3' }, { label: '   ', count: 8 }] } })
    await expect(fetchMyProjectTags('website')).resolves.toEqual({
      items: [{ label: 'Vue', count: 3 }], total: 1, source: 'website',
    })

    mocks.get.mockResolvedValueOnce({ data: { period: '', items: null, total: 0 } })
    await expect(fetchGitHubHotRepos('weekly', 8)).resolves.toEqual({
      period: '', window_days: undefined, items: [], total: 0, snapshot_count: undefined,
    })

    mocks.post.mockResolvedValueOnce({ data: { deleted: 1 } })
    await expect(favoriteProject({ source: 'website', website_id: '7' })).resolves.toMatchObject({
      status: 'succeeded', source: 'website', website_id: '7', is_favorited: true, deleted: true,
    })

    mocks.post.mockResolvedValueOnce({ data: { repo_id: 123, is_recommended: 1 } })
    await expect(recommendGitHubProject({ full_name: 'owner/repo' })).resolves.toMatchObject({
      status: 'succeeded', repo_id: '123', full_name: 'owner/repo', is_recommended: true, removed: false,
    })
  })

  it('returns paper data on success and null for empty or failed detail requests', async () => {
    const paper = { id: 'paper-1', source: 'arxiv', title: 'Paper' }
    mocks.get.mockResolvedValueOnce({ data: paper })
    await expect(fetchPaperDetail('paper-1')).resolves.toEqual(paper)
    expect(mocks.get).toHaveBeenLastCalledWith('/papers/paper-1')

    mocks.get.mockResolvedValueOnce({ data: undefined })
    await expect(fetchPaperDetail('missing')).resolves.toBeNull()

    mocks.get.mockRejectedValueOnce(new Error('network unavailable'))
    await expect(fetchPaperDetail('failed')).resolves.toBeNull()
  })
})
