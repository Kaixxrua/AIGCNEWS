import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '@/i18n'
import type { RevenueStatsResponse } from '@/features/monitor/monitorModel'
import { monitorApi } from '@/services/monitor/monitorApi'
import RevenueStatsPanel from './RevenueStatsPanel.vue'
import SpinnerLoader from '@/components/SpinnerLoader.vue'

vi.mock('@/services/monitor/monitorApi', () => ({
  monitorApi: { fetchRevenueStats: vi.fn() },
}))

const fetchMock = vi.mocked(monitorApi.fetchRevenueStats)
const stats: RevenueStatsResponse = {
  today: { cny_amount_cents: 1900, usd_amount_cents: 490 },
  week: { cny_amount_cents: 0, usd_amount_cents: 1 },
  month: { cny_amount_cents: 12345, usd_amount_cents: 678 },
  year: { cny_amount_cents: 100, usd_amount_cents: 200 },
}

const mountPanel = () => mount(RevenueStatsPanel, { global: { plugins: [i18n] } })

describe('RevenueStatsPanel', () => {
  beforeEach(() => {
    fetchMock.mockReset()
    i18n.global.locale.value = 'zh-CN'
  })

  it('loads on mount and renders four periods with separate currencies', async () => {
    fetchMock.mockResolvedValue(stats)
    const wrapper = mountPanel()
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledOnce()
    expect(wrapper.findAll('.revenue-stat-tile')).toHaveLength(4)
    expect(wrapper.text()).toContain('本日')
    expect(wrapper.text()).toContain('本周')
    expect(wrapper.text()).toContain('本月')
    expect(wrapper.text()).toContain('本年')
    expect(wrapper.text()).toContain('人民币')
    expect(wrapper.text()).toContain('美元')
    expect(wrapper.text()).toContain('¥19.00')
    expect(wrapper.text()).toContain('$4.90')
    expect(wrapper.text()).toContain('¥0.00')
    expect(wrapper.text()).toContain('$0.01')
    expect(wrapper.text()).toContain('¥123.45')
  })

  it('shows the spinner while the first request is pending', async () => {
    let resolve: (value: RevenueStatsResponse) => void = () => {}
    fetchMock.mockReturnValue(new Promise((done) => { resolve = done }))
    const wrapper = mountPanel()
    await nextTick()
    expect(wrapper.findComponent(SpinnerLoader).exists()).toBe(true)

    resolve(stats)
    await flushPromises()
    expect(wrapper.findAll('.revenue-stat-tile')).toHaveLength(4)
  })

  it('shows and dismisses load errors', async () => {
    fetchMock.mockRejectedValue(new Error('network down'))
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.text()).toContain('network down')
    await wrapper.find('button').trigger('click')
    expect(wrapper.text()).not.toContain('network down')
  })
})
