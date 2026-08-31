import { describe, expect, it, vi } from 'vitest'
import type { RevenueStatsResponse } from '@/features/monitor/monitorModel'
import { useRevenueStatsController } from './useRevenueStatsController'

const stats: RevenueStatsResponse = {
  today: { cny_amount_cents: 1900, usd_amount_cents: 490 },
  week: { cny_amount_cents: 3800, usd_amount_cents: 980 },
  month: { cny_amount_cents: 5700, usd_amount_cents: 1470 },
  year: { cny_amount_cents: 7600, usd_amount_cents: 1960 },
}

describe('useRevenueStatsController', () => {
  it('starts idle and stores a successful response', async () => {
    const api = { fetchRevenueStats: vi.fn().mockResolvedValue(stats) }
    const controller = useRevenueStatsController({ api })

    expect(controller.data.value).toBeNull()
    expect(controller.loading.value).toBe(false)
    expect(controller.errorMsg.value).toBe('')

    await controller.load()
    expect(controller.data.value).toEqual(stats)
    expect(controller.loading.value).toBe(false)
    expect(api.fetchRevenueStats).toHaveBeenCalledOnce()
  })

  it('exposes Error messages and translated fallback messages', async () => {
    const translate = vi.fn().mockReturnValue('加载失败')
    const api = { fetchRevenueStats: vi.fn().mockRejectedValueOnce(new Error('network down')).mockRejectedValueOnce({}) }
    const controller = useRevenueStatsController({ api, translate })

    await controller.load()
    expect(controller.errorMsg.value).toBe('network down')
    await controller.load()
    expect(controller.errorMsg.value).toBe('加载失败')
    expect(translate).toHaveBeenCalledWith('monitor.revenue.loadFailed')
  })

  it('uses an Axios response detail when available', async () => {
    const api = { fetchRevenueStats: vi.fn().mockRejectedValue({ isAxiosError: true, response: { data: { detail: 'forbidden' } } }) }
    const controller = useRevenueStatsController({ api })

    await controller.load()
    expect(controller.errorMsg.value).toBe('forbidden')
  })

  it('ignores a response or error after disposal', async () => {
    let resolve: (value: RevenueStatsResponse) => void = () => {}
    const api = { fetchRevenueStats: vi.fn().mockReturnValue(new Promise<RevenueStatsResponse>((done) => { resolve = done })) }
    const controller = useRevenueStatsController({ api })
    const pending = controller.load()
    controller.dispose()
    resolve(stats)
    await pending

    expect(controller.data.value).toBeNull()
    expect(controller.loading.value).toBe(false)
  })
})
