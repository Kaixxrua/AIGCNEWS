import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useRecommendedWebsites } from './useRecommendedWebsites'
import { __resetRecommendedWebsitesSnapshotForTest, rememberRecommendedWebsites, useRecommendedWebsitesSnapshot } from './recommendedWebsitesSnapshot'
import type { RecommendedWebsite, RecommendedWebsiteInput } from '@/services/site/recommendedWebsiteApi'

const input: RecommendedWebsiteInput = { title: 'Example', url: 'https://example.com/', description: 'A useful site', category: 'Tools', sort_order: 0 }
const site: RecommendedWebsite = { ...input, id: 1, created_at: '2026-09-10T00:00:00Z', updated_at: '2026-09-10T00:00:00Z' }
const setup = (isAdmin = () => true) => {
  const api = {
    fetchRecommendedWebsites: vi.fn().mockResolvedValue([]),
    createRecommendedWebsite: vi.fn().mockResolvedValue(site),
    updateRecommendedWebsite: vi.fn().mockResolvedValue(site),
    deleteRecommendedWebsite: vi.fn().mockResolvedValue(undefined),
  }
  return { api, controller: useRecommendedWebsites({ api, isAdmin, t: key => key }) }
}

beforeEach(() => __resetRecommendedWebsitesSnapshotForTest())

describe('independent recommended website collection', () => {
  it('loads an empty public list without inventing entries', async () => {
    const { api, controller } = setup(() => false)
    await controller.load()
    expect(api.fetchRecommendedWebsites).toHaveBeenCalledOnce()
    expect(controller.websites.value).toEqual([])
    expect(controller.error.value).toBe('')
  })

  it('prevents all writes after the admin role is lost', async () => {
    let admin = true
    const { api, controller } = setup(() => admin)
    admin = false
    expect(await controller.save(null, input)).toBe(false)
    expect(await controller.save(1, input)).toBe(false)
    expect(await controller.remove(1)).toBe(false)
    expect(api.createRecommendedWebsite).not.toHaveBeenCalled()
    expect(api.updateRecommendedWebsite).not.toHaveBeenCalled()
    expect(api.deleteRecommendedWebsite).not.toHaveBeenCalled()
  })

  it('creates, edits, orders and removes only recommendation records', async () => {
    const { api, controller } = setup()
    expect(await controller.save(null, input)).toBe(true)
    api.updateRecommendedWebsite.mockResolvedValue({ ...site, title: 'Edited' })
    expect(await controller.save(1, { ...input, title: 'Edited' })).toBe(true)
    expect(controller.websites.value.map(item => item.title)).toEqual(['Edited'])
    expect(api.updateRecommendedWebsite).toHaveBeenCalledWith(1, { ...input, title: 'Edited' })
    expect(await controller.remove(1)).toBe(true)
    expect(controller.websites.value).toEqual([])
  })

  it('does not let an older read erase a successful addition', async () => {
    const { api, controller } = setup()
    let resolveRead!: (items: RecommendedWebsite[]) => void
    api.fetchRecommendedWebsites.mockImplementation(() => new Promise(resolve => { resolveRead = resolve }))
    const oldRead = controller.load()
    await controller.save(null, input)
    resolveRead([])
    await oldRead
    expect(controller.websites.value).toEqual([site])
  })

  it('preserves existing entries after failed writes and shows a duplicate error', async () => {
    const { api, controller } = setup()
    controller.websites.value = [site]
    api.createRecommendedWebsite.mockRejectedValue({ response: { status: 409 } })
    expect(await controller.save(null, input)).toBe(false)
    expect(controller.editError.value).toBe('recommendedWebsites.duplicate')
    api.deleteRecommendedWebsite.mockRejectedValue(new Error('Unavailable'))
    expect(await controller.remove(1)).toBe(false)
    expect(controller.websites.value).toEqual([site])
    expect(controller.error.value).toBe('recommendedWebsites.deleteError')
  })

  it('allows retry after a failed read and ignores results after disposal', async () => {
    const { api, controller } = setup()
    api.fetchRecommendedWebsites.mockRejectedValueOnce(new Error('Unavailable'))
    await controller.load()
    expect(controller.error.value).toBe('recommendedWebsites.loadError')
    api.fetchRecommendedWebsites.mockResolvedValue([site])
    await controller.load()
    expect(controller.error.value).toBe('')
    controller.dispose()
    api.fetchRecommendedWebsites.mockResolvedValue([])
    await controller.load()
    expect(controller.websites.value).toEqual([site])
  })

  it('shares what it loads and saves with the website tabs and the route guard', async () => {
    const { api, controller } = setup()
    const snapshot = useRecommendedWebsitesSnapshot()
    await controller.load()
    expect(snapshot.value).toEqual([])
    await controller.save(null, input)
    expect(snapshot.value).toEqual([site])
    await controller.remove(1)
    expect(snapshot.value).toEqual([])
    api.fetchRecommendedWebsites.mockRejectedValueOnce(new Error('Unavailable'))
    await controller.load()
    expect(snapshot.value).toEqual([])
  })

  it('starts from the list fetched earlier and then refreshes it', async () => {
    rememberRecommendedWebsites([site])
    const { api, controller } = setup(() => false)
    expect(controller.websites.value).toEqual([site])
    api.fetchRecommendedWebsites.mockResolvedValue([{ ...site, title: 'Fresh' }])
    await controller.load()
    expect(controller.websites.value.map(item => item.title)).toEqual(['Fresh'])
    expect(useRecommendedWebsitesSnapshot().value?.map(item => item.title)).toEqual(['Fresh'])
  })
})
