import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '@/i18n'
import type { VisitPlatformStatsResponse, VisitStatsWindow } from '@/features/monitor/monitorModel'
import { monitorApi } from '@/services/monitor/monitorApi'
import VisitStatsPanel from './VisitStatsPanel.vue'

vi.mock('@/services/monitor/monitorApi', () => ({
  monitorApi: { fetchVisitPlatformStats: vi.fn() },
}))

const fetchMock = vi.mocked(monitorApi.fetchVisitPlatformStats)

const stats = (overrides: Partial<VisitPlatformStatsResponse> = {}): VisitPlatformStatsResponse => ({
  window: '7d',
  start_date: '2026-08-16',
  end_date: '2026-08-22',
  total_visits: 40,
  platforms: [
    { platform: 'ios', visits: 30, share: 75 },
    { platform: 'android', visits: 5, share: 12.5 },
    { platform: 'windows', visits: 4, share: 10 },
    { platform: 'macos', visits: 1, share: 2.5 },
    { platform: 'linux', visits: 0, share: 0 },
    { platform: 'other', visits: 0, share: 0 },
  ],
  automated_visits: 0,
  ...overrides,
})

const mountPanel = () => mount(VisitStatsPanel, { global: { plugins: [i18n] } })

describe('VisitStatsPanel', () => {
  beforeEach(() => {
    fetchMock.mockReset()
    i18n.global.locale.value = 'zh-CN'
  })

  it('loads the default 7d window on mount and renders the six-bucket legend', async () => {
    fetchMock.mockResolvedValue(stats())
    const wrapper = mountPanel()
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledWith('7d')

    const donut = wrapper.find('svg.visit-donut')
    expect(donut.exists()).toBe(true)
    expect(donut.attributes('role')).toBe('img')
    expect(donut.attributes('aria-label')).toContain('75.0%')

    const items = wrapper.findAll('.visit-legend-item')
    expect(items).toHaveLength(6)
    expect(items[0]!.text()).toContain('iOS')
    expect(items[0]!.text()).toContain('30')
    expect(items[0]!.text()).toContain('75.0%')
    expect(items[4]!.text()).toContain('Linux')
    expect(items[5]!.text()).toContain('其他')
    // 分段用固定槽位色：iOS → slot 1，颜色跟随实体而非排名
    const segments = wrapper.findAll('circle.visit-donut-segment')
    expect(segments).toHaveLength(6)
    expect(segments[0]!.attributes('style')).toContain('--visit-series-1')
    expect(segments[4]!.attributes('style')).toContain('--visit-series-6')
    expect(wrapper.text()).toContain('共 40 次访问')
    expect(wrapper.text()).toContain('2026-08-16 至 2026-08-22')
  })

  it('shows the spinner while the first load is in flight', async () => {
    let resolveFetch: (value: VisitPlatformStatsResponse) => void = () => {}
    fetchMock.mockReturnValue(new Promise((resolve) => { resolveFetch = resolve }))
    const wrapper = mountPanel()

    expect(wrapper.find('.visit-donut').exists()).toBe(false)

    resolveFetch(stats())
    await flushPromises()
    expect(wrapper.find('.visit-donut').exists()).toBe(true)
  })

  it('refetches with the selected window when a tab is clicked', async () => {
    fetchMock.mockResolvedValue(stats())
    const wrapper = mountPanel()
    await flushPromises()

    fetchMock.mockResolvedValue(stats({ window: '30d' }))
    const tabs = wrapper.findAll('button.visit-window-tab')
    expect(tabs).toHaveLength(4)
    await tabs[2]!.trigger('click')
    await flushPromises()

    expect(fetchMock).toHaveBeenLastCalledWith('30d')
    expect(tabs[2]!.attributes('aria-pressed')).toBe('true')
    expect(tabs[0]!.attributes('aria-pressed')).toBe('false')
  })

  it('renders the gray empty ring and hint instead of segments when the window has no visits', async () => {
    fetchMock.mockResolvedValue(stats({ total_visits: 0, platforms: [] }))
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.find('circle.visit-donut-empty-ring').exists()).toBe(true)
    expect(wrapper.findAll('circle.visit-donut-segment')).toHaveLength(0)
    expect(wrapper.findAll('.visit-legend-item')).toHaveLength(0)
    expect(wrapper.text()).toContain('该时间窗口内暂无访问记录')
  })

  it('lists automated visits outside the ring without adding them to the total', async () => {
    fetchMock.mockResolvedValue(stats({ automated_visits: 392 }))
    const wrapper = mountPanel()
    await flushPromises()

    const row = wrapper.find('.visit-automated-row')
    expect(row.exists()).toBe(true)
    expect(row.text()).toContain('爬虫 / 自动化（未计入）')
    expect(row.text()).toContain('392')
    expect(row.attributes('title')).toContain('无头浏览器')
    // 总访问与环图只算六个计数桶
    expect(wrapper.text()).toContain('共 40 次访问')
    expect(wrapper.find('.visit-donut-total').text()).toBe('40')
    expect(wrapper.findAll('.visit-legend-item')).toHaveLength(6)
  })

  it('still shows the automated count when the window has no counted visits', async () => {
    fetchMock.mockResolvedValue(stats({ total_visits: 0, platforms: [], automated_visits: 12 }))
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.find('circle.visit-donut-empty-ring').exists()).toBe(true)
    expect(wrapper.find('.visit-automated-row').text()).toContain('12')
  })

  it('treats a response without automated_visits as zero', async () => {
    const legacy = stats()
    delete legacy.automated_visits
    fetchMock.mockResolvedValue(legacy)
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.find('.visit-automated-value').text()).toBe('0')
  })

  it('shows the range-all copy when the backend reports a null start date', async () => {
    fetchMock.mockResolvedValue(stats({ window: 'all', start_date: null }))
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.text()).toContain('功能上线以来，截至 2026-08-22')
  })

  it('surfaces the load failure message and keeps the chart hidden', async () => {
    fetchMock.mockRejectedValue(new Error('network down'))
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.text()).toContain('network down')
    expect(wrapper.find('.visit-donut').exists()).toBe(false)
  })

  it('ignores stale responses after a faster tab switch wins the race', async () => {
    const pending = new Map<VisitStatsWindow, (value: VisitPlatformStatsResponse) => void>()
    fetchMock.mockImplementation((window: VisitStatsWindow) => new Promise((resolve) => {
      pending.set(window, resolve)
    }))
    const wrapper = mountPanel()
    const tabs = wrapper.findAll('button.visit-window-tab')

    // mount 的 7d 请求仍在途时切到 30d：两请求竞态，晚到的 7d 响应必须被丢弃
    await tabs[2]!.trigger('click')
    pending.get('30d')?.(stats({ window: '30d', total_visits: 30 }))
    await flushPromises()
    pending.get('7d')?.(stats({ window: '7d', total_visits: 7 }))
    await flushPromises()

    expect(wrapper.text()).toContain('共 30 次访问')
    expect(wrapper.text()).not.toContain('共 7 次访问')
  })
})
