import { describe, expect, it, vi } from 'vitest'
import type { DashboardApi, DashboardTop, DashboardTopParams } from '@/services/dashboard/dashboardContracts'
import { createDashboardHistoryCache } from './dashboardHistoryCache'

const setup = (timestamp = '2026-07-27T12:00:00+08:00') => {
  let time = Date.parse(timestamp)
  const api = { fetchTop: vi.fn(async (_params: DashboardTopParams): Promise<DashboardTop> => ({ items: [], sourceStatus: {}, isEmbargoed: false })) }
  const cache = createDashboardHistoryCache(api as unknown as DashboardApi, () => time)
  return { api, cache, advance: (ms: number) => { time += ms } }
}
const params: DashboardTopParams = { source: 'github', date: '2026-07-26', period: 'daily', limit: 10 }

describe('dashboard history reuse', () => {
  it('isolates dates, sources, and limits, and keeps the default date live', async () => {
    const { api, cache } = setup()
    await cache.fetchTop(params)
    await cache.fetchTop(params)
    expect(api.fetchTop).toHaveBeenCalledTimes(1)
    await cache.fetchTop({ ...params, source: 'news' })
    await cache.fetchTop({ ...params, date: '2026-07-25' })
    await cache.fetchTop({ ...params, limit: 500 })
    await cache.fetchTop({ ...params, date: undefined })
    await cache.fetchTop({ ...params, date: undefined })
    expect(api.fetchTop).toHaveBeenCalledTimes(6)
  })

  it.each([
    ['2026-07-27T12:00:00+08:00', 60_000],
    ['2026-07-27T23:59:59+08:00', 1_000],
    ['2026-07-27T16:59:59+08:00', 1_000],
  ])('expires at the TTL, CST midnight, or source close (%s)', async (time, delay) => {
    const { api, cache, advance } = setup(time)
    api.fetchTop.mockResolvedValue({ items: [], sourceStatus: { github: { finalize_hour: 17 } }, isEmbargoed: false })
    await cache.fetchTop(params)
    advance(delay - 1)
    await cache.fetchTop(params)
    expect(api.fetchTop).toHaveBeenCalledTimes(1)
    advance(1)
    await cache.fetchTop(params)
    expect(api.fetchTop).toHaveBeenCalledTimes(2)
  })

  it('keeps a fresh manual refresh when an older prefetch resolves late', async () => {
    const { api, cache } = setup()
    let finish!: (top: DashboardTop) => void
    api.fetchTop.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const pending = cache.fetchTop(params)
    api.fetchTop.mockResolvedValue({ items: [{ id: 'fresh' }], sourceStatus: {}, isEmbargoed: false })
    await cache.fetchTop({ ...params, cacheBuster: 123 })
    finish({ items: [{ id: 'old' }], sourceStatus: {}, isEmbargoed: false })
    await pending
    expect((await cache.fetchTop(params)).items).toEqual([{ id: 'fresh' }])
    expect(api.fetchTop).toHaveBeenCalledTimes(2)
  })

  it('retries aborted requests even when the transport later resolves them', async () => {
    const { api, cache } = setup()
    let finish!: (top: DashboardTop) => void
    api.fetchTop.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const controller = new AbortController()
    const pending = cache.fetchTop({ ...params, signal: controller.signal })
    controller.abort()
    await cache.fetchTop(params)
    finish({ items: [{ id: 'aborted' }], sourceStatus: {}, isEmbargoed: false })
    await pending
    expect((await cache.fetchTop(params)).items).toEqual([])
    expect(api.fetchTop).toHaveBeenCalledTimes(2)
  })

  it('does not retain a slow prefetch across the source close', async () => {
    const { api, cache, advance } = setup('2026-07-27T16:59:59+08:00')
    let finish!: (top: DashboardTop) => void
    api.fetchTop.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const pending = cache.fetchTop(params)
    advance(2_000)
    finish({ items: [], sourceStatus: { github: { finalize_hour: 17 } }, isEmbargoed: false })
    await pending
    await cache.fetchTop(params)
    expect(api.fetchTop).toHaveBeenCalledTimes(2)
  })

  it('bounds retained history', async () => {
    const { api, cache } = setup()
    await cache.fetchTop(params)
    for (let day = 0; day < 36; day += 1) {
      const date = new Date(Date.UTC(2026, 4, day + 1)).toISOString().slice(0, 10)
      await cache.fetchTop({ ...params, date })
    }
    await cache.fetchTop(params)
    expect(api.fetchTop).toHaveBeenCalledTimes(38)
  })
})
