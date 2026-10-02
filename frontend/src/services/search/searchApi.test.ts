import { beforeEach, describe, expect, it, vi } from 'vitest'

const transport = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../http/apiClient', () => ({ api: transport }))

import { fetchQuickSearch } from './searchApi'

describe('Quick search API contract', () => {
  beforeEach(() => {
    transport.get.mockReset()
  })

  it('asks for every group in one request and maps the wire groups to camelCase', async () => {
    const signal = new AbortController().signal
    transport.get.mockResolvedValueOnce({
      data: {
        q: 'agent',
        groups: {
          projects: {
            total: 42,
            items: [{ full_name: 'acme/agent', url: 'https://github.com/acme/agent', description: 'raw', description_zh: '中文', description_en: 'English', stars: 1234, language: 'Python' }],
          },
          papers: {
            total: 3,
            items: [{ id: '2501.00001', title: 'Agents', summary: 'About agents', date: '2026-09-30', authors: ['Ada', 'Bo'], author_count: 7 }],
          },
          briefings: {
            total: 1,
            items: [{ id: 9, date: '2026-09-30', type: 'github', title: 'GitHub 简报', lead: 'acme/agent', snippet: '…agent…' }],
          },
          tweets: {
            total: 1,
            items: [{ id: 't1', text: 'hello agent', url: 'https://x.com/ada/status/1', author: 'ada', date: '2026-09-30' }],
          },
        },
        failed: [],
      },
    })

    await expect(fetchQuickSearch('agent', { locale: 'zh-CN', signal })).resolves.toEqual({
      q: 'agent',
      projects: {
        total: 42,
        items: [{ fullName: 'acme/agent', url: 'https://github.com/acme/agent', description: 'raw', descriptionZh: '中文', descriptionEn: 'English', stars: 1234, language: 'Python' }],
      },
      papers: { total: 3, items: [{ id: '2501.00001', title: 'Agents', summary: 'About agents', date: '2026-09-30', authors: ['Ada', 'Bo'], authorCount: 7 }] },
      briefings: { total: 1, items: [{ date: '2026-09-30', type: 'github', title: 'GitHub 简报', lead: 'acme/agent', snippet: '…agent…' }] },
      tweets: { total: 1, items: [{ id: 't1', text: 'hello agent', url: 'https://x.com/ada/status/1', author: 'ada', date: '2026-09-30' }] },
      failed: [],
    })
    expect(transport.get).toHaveBeenLastCalledWith('/search', { params: { q: 'agent', limit: 5, locale: 'zh-CN' }, signal })
  })

  it('keeps a missing group as null and lists only known failed groups', async () => {
    transport.get.mockResolvedValueOnce({
      data: { q: 'rag', groups: { projects: { total: 0, items: [] }, briefings: { total: 2, items: [] } }, failed: ['papers', 'bogus', 3] },
    })

    const result = await fetchQuickSearch('rag', { locale: 'en-US', limit: 8 })

    expect(result.projects).toEqual({ total: 0, items: [] })
    expect(result.papers).toBeNull()
    expect(result.tweets).toBeNull()
    expect(result.briefings).toEqual({ total: 2, items: [] })
    expect(result.failed).toEqual(['papers'])
    expect(transport.get).toHaveBeenLastCalledWith('/search', { params: { q: 'rag', limit: 8, locale: 'en-US' }, signal: undefined })
  })

  it('drops items without the fields a row needs and never reports fewer than it lists', async () => {
    transport.get.mockResolvedValueOnce({
      data: {
        groups: {
          projects: { total: 0, items: [{ full_name: '' }, null, { full_name: 'a/b', stars: -3 }] },
          papers: { items: [{ title: 'no id' }, { id: 'p1', authors: ['A', 7, ' '], author_count: 0 }] },
          briefings: { total: 5, items: [{ date: '2026-9-1', type: 'all' }, { date: '2026-09-01', type: '' }, { date: '2026-09-01', type: 'all' }] },
          tweets: { total: 1, items: [{ text: 'orphan' }, { url: 'https://x.com/a/status/2' }] },
        },
      },
    })

    const result = await fetchQuickSearch('ab', { locale: 'zh-CN' })

    expect(result.q).toBe('ab')
    expect(result.projects).toEqual({ total: 1, items: [{ fullName: 'a/b', url: '', description: '', descriptionZh: '', descriptionEn: '', stars: 0, language: '' }] })
    expect(result.papers).toEqual({ total: 1, items: [{ id: 'p1', title: '', summary: '', date: '', authors: ['A'], authorCount: 1 }] })
    expect(result.briefings).toEqual({ total: 5, items: [{ date: '2026-09-01', type: 'all', title: '', lead: '', snippet: '' }] })
    expect(result.tweets?.items).toEqual([{ id: '', text: '', url: 'https://x.com/a/status/2', author: '', date: '' }])
    expect(result.failed).toEqual([])
  })

  it('treats an empty body as no groups at all', async () => {
    transport.get.mockResolvedValueOnce({ data: null })

    await expect(fetchQuickSearch('ab', { locale: 'zh-CN' })).resolves.toEqual({
      q: 'ab', projects: null, papers: null, briefings: null, tweets: null, failed: [],
    })
  })
})
