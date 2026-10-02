import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchRecommendedWebsites, type RecommendedWebsite } from '@/services/site/recommendedWebsiteApi'
import {
  __resetRecommendedWebsitesSnapshotForTest,
  ensureRecommendedWebsites,
  rememberRecommendedWebsites,
  useRecommendedWebsitesSnapshot,
} from './recommendedWebsitesSnapshot'

vi.mock('@/services/site/recommendedWebsiteApi', () => ({ fetchRecommendedWebsites: vi.fn() }))

const site: RecommendedWebsite = {
  id: 1, title: 'Example', url: 'https://example.com/', description: 'Why', category: 'Tools', sort_order: 10,
  created_at: '2026-10-02T00:00:00Z', updated_at: '2026-10-02T00:00:00Z',
}

beforeEach(() => {
  vi.mocked(fetchRecommendedWebsites).mockReset()
  __resetRecommendedWebsitesSnapshotForTest()
})

describe('recommended websites snapshot', () => {
  it('sends one request for concurrent callers and keeps the answer', async () => {
    vi.mocked(fetchRecommendedWebsites).mockResolvedValue([site])

    const [first, second] = await Promise.all([ensureRecommendedWebsites(), ensureRecommendedWebsites()])

    expect(first).toEqual([site])
    expect(second).toEqual([site])
    expect(await ensureRecommendedWebsites()).toEqual([site])
    expect(fetchRecommendedWebsites).toHaveBeenCalledOnce()
    expect(useRecommendedWebsitesSnapshot().value).toEqual([site])
  })

  it('answers null when the request fails and asks again next time', async () => {
    vi.mocked(fetchRecommendedWebsites).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce([])

    expect(await ensureRecommendedWebsites()).toBeNull()
    expect(useRecommendedWebsitesSnapshot().value).toBeNull()
    expect(await ensureRecommendedWebsites()).toEqual([])
    expect(fetchRecommendedWebsites).toHaveBeenCalledTimes(2)
  })

  it('answers from a list the page already loaded without fetching', async () => {
    rememberRecommendedWebsites([site])

    expect(await ensureRecommendedWebsites()).toEqual([site])
    expect(fetchRecommendedWebsites).not.toHaveBeenCalled()
  })
})
