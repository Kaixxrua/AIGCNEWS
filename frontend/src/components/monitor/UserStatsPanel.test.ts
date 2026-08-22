import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '@/i18n'
import type { UserStatsResponse } from '@/features/monitor/monitorModel'
import { monitorApi } from '@/services/monitor/monitorApi'
import UserStatsPanel from './UserStatsPanel.vue'

vi.mock('@/services/monitor/monitorApi', () => ({
  monitorApi: { fetchUserStats: vi.fn() },
}))

const fetchMock = vi.mocked(monitorApi.fetchUserStats)

const stats = (overrides: Partial<UserStatsResponse> = {}): UserStatsResponse => ({
  total_users: 120,
  member_users: 7,
  ...overrides,
})

const mountPanel = () => mount(UserStatsPanel, { global: { plugins: [i18n] } })

describe('UserStatsPanel', () => {
  beforeEach(() => {
    fetchMock.mockReset()
    i18n.global.locale.value = 'zh-CN'
  })

  it('loads on mount and renders both counts with the VIP share badge', async () => {
    fetchMock.mockResolvedValue(stats())
    const wrapper = mountPanel()
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const tiles = wrapper.findAll('.user-stat-tile')
    expect(tiles).toHaveLength(2)
    expect(tiles[0]!.text()).toContain('120')
    expect(tiles[0]!.text()).toContain('总用户')
    expect(tiles[1]!.text()).toContain('7')
    expect(tiles[1]!.text()).toContain('VIP')
    // 7/120 = 5.833… → 5.8%
    expect(wrapper.text()).toContain('VIP 占比 5.8%')
  })

  it('shows 0.0% share instead of NaN when there are no users', async () => {
    fetchMock.mockResolvedValue(stats({ total_users: 0, member_users: 0 }))
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.text()).toContain('VIP 占比 0.0%')
    expect(wrapper.text()).not.toContain('NaN')
  })

  it('shows the spinner while the first load is in flight', async () => {
    let resolveFetch: (value: UserStatsResponse) => void = () => {}
    fetchMock.mockReturnValue(new Promise((resolve) => { resolveFetch = resolve }))
    const wrapper = mountPanel()

    expect(wrapper.find('.user-stats-tiles').exists()).toBe(false)

    resolveFetch(stats())
    await flushPromises()
    expect(wrapper.find('.user-stats-tiles').exists()).toBe(true)
  })

  it('surfaces the load failure message and keeps the tiles hidden', async () => {
    fetchMock.mockRejectedValue(new Error('network down'))
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.text()).toContain('network down')
    expect(wrapper.find('.user-stats-tiles').exists()).toBe(false)
  })
})
