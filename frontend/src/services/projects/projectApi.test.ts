import { beforeEach, describe, expect, it, vi } from 'vitest'

const transport = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), delete: vi.fn() }))
vi.mock('../http/apiClient', () => ({ api: transport }))

import {
  addMyToolWebsite,
  favoriteProject,
  fetchMyProjectTags,
  fetchProjectCategories,
  fetchProjectPeek,
  fetchProjectTrends,
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

  it('asks for one page of trends at once and keeps missing gains and ranks empty', async () => {
    const signal = new AbortController().signal
    transport.get.mockResolvedValueOnce({
      data: {
        metric_date: '2026-10-02',
        previous_date: '2026-10-01',
        days: '14',
        items: {
          'acme/alpha': {
            points: [{ date: '2026-10-01', stars: '1158', gain: null }, { date: '2026-10-02', stars: 1200, gain: '42' }, { stars: 3 }],
            previous_rank: 3,
          },
          'acme/beta': { points: 'nope', previous_rank: null },
          'acme/gamma': {},
        },
      },
    })

    await expect(fetchProjectTrends(['acme/alpha', 'acme/beta', 'acme/gamma'], { ranks: true, signal })).resolves.toEqual({
      metric_date: '2026-10-02',
      previous_date: '2026-10-01',
      days: 14,
      items: {
        'acme/alpha': {
          points: [{ date: '2026-10-01', stars: 1158, gain: null }, { date: '2026-10-02', stars: 1200, gain: 42 }],
          previous_rank: 3,
        },
        'acme/beta': { points: [], previous_rank: null },
        'acme/gamma': { points: [], previous_rank: null },
      },
    })
    expect(transport.get).toHaveBeenLastCalledWith('/projects/github/trends', {
      params: { repos: 'acme/alpha,acme/beta,acme/gamma', days: 14, ranks: true },
      signal,
    })

    transport.get.mockResolvedValueOnce({ data: null })
    await expect(fetchProjectTrends(['acme/alpha'], { days: 30 })).resolves.toEqual({
      metric_date: '', previous_date: null, days: 30, items: {},
    })
    expect(transport.get).toHaveBeenLastCalledWith('/projects/github/trends', {
      params: { repos: 'acme/alpha', days: 30 },
      signal: undefined,
    })
  })

  it('asks for one repository at a time for the quick look and keeps only what the card can show', async () => {
    const signal = new AbortController().signal
    const commit = {
      sha: 'abcdef1234567890',
      message: 'Fix the parser',
      author: 'octo',
      committed_at: '2026-10-01T08:00:00Z',
      url: 'https://github.com/acme/alpha/commit/abcdef1234567890',
    }
    transport.get.mockResolvedValueOnce({
      data: { repo_id: 'acme/alpha', status: 'ok', has_readme: 1, readme: ['First.', '  ', 42, null, 'Second.'], readme_more: true, commit },
    })
    await expect(fetchProjectPeek('acme/alpha', { signal })).resolves.toEqual({
      repo_id: 'acme/alpha', status: 'ok', has_readme: true, readme: ['First.', 'Second.'], readme_more: true, commit,
    })
    expect(transport.get).toHaveBeenLastCalledWith('/projects/github/peek', { params: { repo: 'acme/alpha' }, signal })

    // 不认识的状态当成读不到；提交链接不是 GitHub 上的页面、或者没有 sha，都不摆
    transport.get.mockResolvedValueOnce({ data: { status: 'stale', commit: { ...commit, url: 'https://github.com.example.test/acme/beta' } } })
    await expect(fetchProjectPeek('acme/beta')).resolves.toEqual({
      repo_id: 'acme/beta', status: 'unavailable', has_readme: false, readme: [], readme_more: false, commit: null,
    })
    expect(transport.get).toHaveBeenLastCalledWith('/projects/github/peek', { params: { repo: 'acme/beta' }, signal: undefined })
    transport.get.mockResolvedValueOnce({ data: { status: 'ok', commit: { ...commit, sha: '' } } })
    await expect(fetchProjectPeek('acme/gamma')).resolves.toMatchObject({ status: 'ok', commit: null })
    transport.get.mockResolvedValueOnce({ data: { status: 'ok', commit: { ...commit, url: 'http://github.com/acme/delta/commit/1' } } })
    await expect(fetchProjectPeek('acme/delta')).resolves.toMatchObject({ commit: null })

    // 提交的其余字段缺了留空，sha 和链接在就摆
    transport.get.mockResolvedValueOnce({ data: { status: 'ok', commit: { sha: 'f00', url: 'https://github.com/a/b/commit/f00', message: 7 } } })
    await expect(fetchProjectPeek('a/b')).resolves.toMatchObject({
      commit: { sha: 'f00', message: '', author: '', committed_at: '', url: 'https://github.com/a/b/commit/f00' },
    })
    transport.get.mockResolvedValueOnce({ data: null })
    await expect(fetchProjectPeek('acme/epsilon')).resolves.toEqual({
      repo_id: 'acme/epsilon', status: 'unavailable', has_readme: false, readme: [], readme_more: false, commit: null,
    })
  })
})
