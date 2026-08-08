import { beforeEach, describe, expect, it, vi } from 'vitest'

const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), delete: vi.fn() }))
vi.mock('../http/apiClient', () => ({ api: transport }))

import {
  addMyToolWebsite,
  favoriteProject,
  fetchMyProjectTags,
  fetchProjectCategories,
  fetchProjects,
  recommendGitHubProject,
  unfavoriteProject,
  unrecommendGitHubProject,
} from './projectApi'

describe('Project API transport contract', () => {
  beforeEach(() => {
    transport.get.mockReset()
    transport.post.mockReset()
    transport.delete.mockReset()
  })

  it('preserves representative body, delete, and timeout request shapes', async () => {
    transport.post.mockResolvedValueOnce({ data: {} })
    await favoriteProject({ source: 'github', repo_id: 42 })
    expect(transport.post).toHaveBeenLastCalledWith('/projects/me/favorites', { source: 'github', repo_id: 42 })

    transport.delete.mockResolvedValueOnce({ data: {} })
    await unfavoriteProject({ source: 'website', website_id: 9 })
    expect(transport.delete).toHaveBeenLastCalledWith('/projects/me/favorites', {
      params: { source: 'website', website_id: 9 },
    })

    transport.delete.mockResolvedValueOnce({ data: {} })
    await unrecommendGitHubProject({ repo_id: 42, full_name: 'owner/repo' })
    expect(transport.delete).toHaveBeenLastCalledWith('/ops/github-projects/recommendations', {
      data: { repo_id: 42, full_name: 'owner/repo' },
    })

    transport.post.mockResolvedValueOnce({ data: {} })
    await addMyToolWebsite('https://example.test')
    expect(transport.post).toHaveBeenLastCalledWith(
      '/projects/me/tool-websites',
      { url: 'https://example.test' },
      { timeout: 120_000 },
    )
  })

  it('normalizes project list defaults and numeric DTO fields', async () => {
    transport.get.mockResolvedValueOnce({ data: { total: '12', page_size: '5', min_stars: '800', has_next: 1 } })

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
    expect(transport.get).toHaveBeenCalledWith('/projects', {
      params: { page: 3, category: 'agents', tag: 'mcp', source: 'website' },
    })
  })

  it('normalizes category, tag, favorite, and recommendation DTOs', async () => {
    transport.get.mockResolvedValueOnce({ data: { total: '2', today_count: '1', recommended_count: null } })
    await expect(fetchProjectCategories('github')).resolves.toMatchObject({
      items: [], total: 2, today_count: 1, recommended_count: 0, min_stars: 500, source: 'github',
    })

    transport.get.mockResolvedValueOnce({ data: { items: [{ value: 'Vue', label: '  Vue  ', label_zh: 'Vue', label_en: 'Vue', tags_origin: 'system', count: '3' }, { label: '   ', count: 8 }] } })
    await expect(fetchMyProjectTags('website')).resolves.toEqual({
      items: [{ value: 'Vue', label: 'Vue', label_zh: 'Vue', label_en: 'Vue', tags_origin: 'system', count: 3 }], total: 1, source: 'website',
    })

    transport.post.mockResolvedValueOnce({ data: { deleted: 1 } })
    await expect(favoriteProject({ source: 'website', website_id: '7' })).resolves.toMatchObject({
      status: 'succeeded', source: 'website', website_id: '7', is_favorited: true, deleted: true,
    })

    transport.post.mockResolvedValueOnce({ data: { repo_id: 123, is_recommended: 1 } })
    await expect(recommendGitHubProject({ full_name: 'owner/repo' })).resolves.toMatchObject({
      status: 'succeeded', repo_id: '123', full_name: 'owner/repo', is_recommended: true, removed: false,
    })
  })
})
