import { flushPromises, mount, type DOMWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '@/i18n'
import type { McpDailyUsageResponse, McpUsageAudienceStats, McpUsageDay } from '@/features/monitor/monitorModel'
import { monitorApi } from '@/services/monitor/monitorApi'
import McpDailyUsagePanel from './McpDailyUsagePanel.vue'

vi.mock('@/services/monitor/monitorApi', () => ({
  monitorApi: { fetchMcpDailyUsage: vi.fn() },
}))

const fetchMock = vi.mocked(monitorApi.fetchMcpDailyUsage)

const stats = (
  anonymous: [number, number, number, number],
  free: [number, number, number, number],
  member: [number, number, number, number],
  total: [number, number, number, number],
): McpUsageAudienceStats => {
  const row = ([clients, connections, calls, limited]: [number, number, number, number]) => ({
    clients,
    connections,
    calls,
    limited,
  })
  return { anonymous: row(anonymous), free: row(free), member: row(member), total: row(total) }
}

const ZERO: [number, number, number, number] = [0, 0, 0, 0]

const untracked = (date: string): McpUsageDay => ({ date, tracked: false, ...stats(ZERO, ZERO, ZERO, ZERO) })

// 14 天窗口，10-04 起才开始统计：窗口前 12 天是 tracked=false 的零值行
const usage = (overrides: Partial<McpDailyUsageResponse> = {}): McpDailyUsageResponse => ({
  available: true,
  timezone: 'Asia/Shanghai',
  days: 14,
  start_date: '2026-09-22',
  end_date: '2026-10-05',
  since: '2026-10-04',
  summary: stats([2, 1, 2, 0], [1, 1, 3, 1], [1, 1, 1, 0], [4, 3, 6, 1]),
  daily: [
    { date: '2026-10-05', tracked: true, ...stats([2, 1, 2, 0], [1, 1, 2, 1], [0, 0, 0, 0], [3, 2, 4, 1]) },
    { date: '2026-10-04', tracked: true, ...stats([0, 0, 0, 0], [1, 0, 1, 0], [1, 1, 1, 0], [2, 1, 2, 0]) },
    ...Array.from({ length: 12 }, (_, index) => untracked(`2026-10-${String(3 - index).padStart(2, '0')}`)),
  ],
  tools: [
    { tool: 'search_papers', anonymous: 2, free: 1, member: 0, total: 3 },
    { tool: '__unknown__', anonymous: 0, free: 2, member: 1, total: 3 },
  ],
  client_names: [
    {
      name: 'cursor',
      connections: { anonymous: 1, free: 1, member: 0, total: 2 },
      clients: { anonymous: 1, free: 1, member: 0, total: 2 },
    },
    {
      name: '__unknown__',
      connections: { anonymous: 0, free: 0, member: 1, total: 1 },
      clients: { anonymous: 0, free: 0, member: 1, total: 1 },
    },
    {
      name: '__other__',
      connections: { anonymous: 0, free: 0, member: 0, total: 0 },
      clients: { anonymous: 0, free: 0, member: 0, total: 0 },
    },
  ],
  client_names_truncated: false,
  limited: [
    { kind: 'burst', anonymous: 0, free: 1, member: 0, total: 1 },
    { kind: 'daily', anonymous: 0, free: 0, member: 0, total: 0 },
    { kind: 'monthly', anonymous: 0, free: 0, member: 0, total: 0 },
  ],
  ...overrides,
})

const zeroUsage = (overrides: Partial<McpDailyUsageResponse> = {}): McpDailyUsageResponse =>
  usage({
    since: null,
    summary: stats(ZERO, ZERO, ZERO, ZERO),
    daily: [],
    tools: [],
    client_names: [],
    limited: [],
    ...overrides,
  })

const mountPanel = () => mount(McpDailyUsagePanel, { global: { plugins: [i18n] } })

const cellTexts = (row: DOMWrapper<Element>) => row.findAll('th, td').map((cell) => cell.text())

describe('McpDailyUsagePanel', () => {
  beforeEach(() => {
    fetchMock.mockReset()
    i18n.global.locale.value = 'zh-CN'
  })

  it('loads the 14-day window on mount and renders the audience matrix with totals', async () => {
    fetchMock.mockResolvedValue(usage())
    const wrapper = mountPanel()
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledWith(14)
    expect(wrapper.text()).toContain('MCP 每日用量')
    expect(wrapper.text()).toContain('2026-09-22 至 2026-10-05')

    const headers = wrapper.findAll('table.mcp-usage-summary thead th').map((cell) => cell.text())
    expect(headers).toEqual(['指标', '匿名', '免费', '会员', '合计'])
    const rows = wrapper.findAll('table.mcp-usage-summary tbody tr')
    expect(rows.map(cellTexts)).toEqual([
      ['去重客户端', '2', '1', '1', '4'],
      ['连接次数', '1', '1', '1', '3'],
      ['工具调用', '2', '3', '1', '6'],
      ['429 次数', '0', '1', '0', '1'],
    ])
    // 口径说明挂在行首的 title 上：多天去重是并集，不是逐日相加
    expect(rows[0]!.find('th').attributes('title')).toContain('并集')
  })

  it('refetches with the selected window when a tab is clicked', async () => {
    fetchMock.mockResolvedValue(usage())
    const wrapper = mountPanel()
    await flushPromises()

    fetchMock.mockResolvedValue(usage({ days: 7, start_date: '2026-09-29', daily: usage().daily.slice(0, 7) }))
    const tabs = wrapper.findAll('[role=group]')[0]!.findAll('button')
    expect(tabs.map((tab) => tab.text())).toEqual(['近 7 天', '近 14 天', '近 30 天'])
    await tabs[0]!.trigger('click')
    await flushPromises()

    expect(fetchMock).toHaveBeenLastCalledWith(7)
    expect(tabs[0]!.attributes('aria-pressed')).toBe('true')
    expect(tabs[1]!.attributes('aria-pressed')).toBe('false')
    expect(wrapper.text()).toContain('2026-09-29 至 2026-10-05')
  })

  it('hides days before tracking started and says when tracking began', async () => {
    fetchMock.mockResolvedValue(usage())
    const wrapper = mountPanel()
    await flushPromises()

    const dates = wrapper.findAll('table.mcp-usage-daily tbody tr').map((row) => row.find('td').text())
    expect(dates).toEqual(['2026-10-05', '2026-10-04'])
    expect(wrapper.text()).toContain('自 2026-10-04 起统计')
  })

  it('switches the daily table between metrics and scales the bar to the window peak', async () => {
    fetchMock.mockResolvedValue(usage())
    const wrapper = mountPanel()
    await flushPromises()

    const dailyRows = () => wrapper.findAll('table.mcp-usage-daily tbody tr').map(cellTexts)
    // 默认显示工具调用
    expect(dailyRows()).toEqual([
      ['2026-10-05', '2', '2', '0', '4'],
      ['2026-10-04', '0', '1', '1', '2'],
    ])
    const bars = wrapper.findAll('table.mcp-usage-daily .mcp-usage-bar')
    expect(bars[0]!.attributes('style')).toContain('width: 100%')
    expect(bars[1]!.attributes('style')).toContain('width: 50%')

    const metricTabs = wrapper.findAll('button.mcp-usage-metric-tab')
    expect(metricTabs.map((tab) => tab.text())).toEqual(['去重客户端', '连接次数', '工具调用', '429 次数'])
    expect(metricTabs[2]!.attributes('aria-pressed')).toBe('true')
    await metricTabs[0]!.trigger('click')

    expect(metricTabs[0]!.attributes('aria-pressed')).toBe('true')
    expect(dailyRows()).toEqual([
      ['2026-10-05', '2', '1', '0', '3'],
      ['2026-10-04', '0', '1', '1', '2'],
    ])
    // 切指标只换显示，不重新请求
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('labels fallback buckets and limit kinds in words instead of raw keys', async () => {
    fetchMock.mockResolvedValue(usage())
    const wrapper = mountPanel()
    await flushPromises()

    const tools = wrapper.findAll('table.mcp-usage-tools tbody tr').map(cellTexts)
    expect(tools).toEqual([
      ['search_papers', '2', '1', '0', '3'],
      ['未知工具名', '0', '2', '1', '3'],
    ])
    // 工具名只在下划线后留断行点
    const toolCells = wrapper.findAll('table.mcp-usage-tools td.mcp-usage-tool')
    expect(toolCells.map((cell) => cell.findAll('wbr').length)).toEqual([1, 0])

    const clientRows = wrapper.findAll('table.mcp-usage-clients tbody tr')
    expect(clientRows.map((row) => row.find('.mcp-usage-name-label').text())).toEqual([
      'cursor',
      '未上报名称',
      '其他（名字不合规，或当天超过 64 个后的新名字）',
    ])
    expect(clientRows.map((row) => row.findAll('td').slice(1).map((cell) => cell.text()))).toEqual([
      ['2', '2'],
      ['1', '1'],
      ['0', '0'],
    ])
    // 名字下的小字只列有数的受众，全为 0 时不出现
    expect(clientRows.map((row) => row.find('.mcp-usage-split').exists() && row.find('.mcp-usage-split').text())).toEqual([
      '匿名 1、免费 1',
      '会员 1',
      false,
    ])

    const limited = wrapper.findAll('table.mcp-usage-limited tbody tr').map(cellTexts)
    expect(limited).toEqual([
      ['分钟突发', '0', '1', '0', '1'],
      ['24 小时配额', '0', '0', '0', '0'],
      ['30 天额度', '0', '0', '0', '0'],
    ])
    expect(wrapper.text()).not.toContain('__unknown__')
    expect(wrapper.text()).not.toContain('__other__')
    expect(wrapper.text()).not.toContain('只列连接次数最多')
  })

  it('lists landings from 429 links under the limit table with source and page in words', async () => {
    fetchMock.mockResolvedValue(
      usage({
        landings: {
          available: true,
          rows: [
            { source: 'mcp-429-anon', path: '/mcp', landings: 3 },
            { source: 'api-429-monthly', path: '/membership', landings: 2 },
            { source: 'mcp-429-daily', path: 'other', landings: 1 },
          ],
        },
      }),
    )
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.text()).toContain('从 429 提示点进网站')
    const headers = wrapper.findAll('table.mcp-usage-landings thead th').map((cell) => cell.text())
    expect(headers).toEqual(['来源', '落地页', '次数'])
    const rows = wrapper.findAll('table.mcp-usage-landings tbody tr')
    expect(rows.map(cellTexts)).toEqual([
      ['MCP · 匿名 24 小时配额', '/mcp', '3'],
      ['API · 免费 30 天额度', '/membership', '2'],
      ['MCP · 免费 24 小时配额', '其他页面', '1'],
    ])
    // 真实路径用等宽字，「其他页面」是文案不是路径
    expect(rows.map((row) => row.findAll('td')[0]!.classes('font-mono'))).toEqual([true, true, false])
    // 落地表跟限流表在同一个分区里
    expect(wrapper.find('table.mcp-usage-limited').element.closest('section')).toBe(
      wrapper.find('table.mcp-usage-landings').element.closest('section'),
    )
  })

  it('says so when no 429 link brought a visit in the window', async () => {
    fetchMock.mockResolvedValue(usage({ landings: { available: true, rows: [] } }))
    const wrapper = mountPanel()
    await flushPromises()

    const rows = wrapper.findAll('table.mcp-usage-landings tbody tr').map(cellTexts)
    expect(rows).toEqual([['这段时间还没有从 429 提示点进来的访问']])
  })

  it('notes unreadable landing records without hiding the usage tables', async () => {
    fetchMock.mockResolvedValue(usage({ landings: { available: false, rows: [] } }))
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.text()).toContain('暂时读不到落地记录')
    expect(wrapper.find('table.mcp-usage-landings').exists()).toBe(false)
    expect(wrapper.find('table.mcp-usage-limited').exists()).toBe(true)
  })

  it('draws no landing block for a backend that does not report landings yet', async () => {
    fetchMock.mockResolvedValue(usage())
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.find('table.mcp-usage-limited').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('从 429 提示点进网站')
    expect(wrapper.find('table.mcp-usage-landings').exists()).toBe(false)
  })

  it('notes when the client list is cut to the top rows', async () => {
    fetchMock.mockResolvedValue(usage({ client_names_truncated: true }))
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.text()).toContain('只列连接次数最多的前 50 个客户端')
  })

  it('shows the unavailable note instead of zero tables when Redis is not connected', async () => {
    fetchMock.mockResolvedValue(zeroUsage({ available: false }))
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.text()).toContain('Redis 未连接')
    expect(wrapper.find('table').exists()).toBe(false)
  })

  it('shows the empty note when the window has no usage', async () => {
    fetchMock.mockResolvedValue(zeroUsage())
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.text()).toContain('这段时间还没有 MCP 用量记录')
    expect(wrapper.find('table').exists()).toBe(false)
  })

  it('shows the spinner only while the first load is in flight', async () => {
    let resolveFetch: (value: McpDailyUsageResponse) => void = () => {}
    fetchMock.mockReturnValue(new Promise((resolve) => { resolveFetch = resolve }))
    const wrapper = mountPanel()

    expect(wrapper.find('table').exists()).toBe(false)

    resolveFetch(usage())
    await flushPromises()
    expect(wrapper.find('table.mcp-usage-summary').exists()).toBe(true)
  })

  it('surfaces the load failure message', async () => {
    fetchMock.mockRejectedValue(new Error('network down'))
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.text()).toContain('network down')
    expect(wrapper.find('table').exists()).toBe(false)
  })

  it('falls back to the localized failure text when the error has no message', async () => {
    fetchMock.mockRejectedValue({})
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.text()).toContain('加载 MCP 用量失败')
  })

  it('ignores stale responses after a faster tab switch wins the race', async () => {
    const pending = new Map<number, (value: McpDailyUsageResponse) => void>()
    fetchMock.mockImplementation((days: number) => new Promise((resolve) => {
      pending.set(days, resolve)
    }))
    const wrapper = mountPanel()
    const tabs = wrapper.findAll('[role=group]')[0]!.findAll('button')

    // mount 的 14 天请求仍在途时切到 30 天：晚到的 14 天响应必须被丢弃
    await tabs[2]!.trigger('click')
    pending.get(30)?.(usage({ days: 30, start_date: '2026-09-06' }))
    await flushPromises()
    pending.get(14)?.(usage())
    await flushPromises()

    expect(wrapper.text()).toContain('2026-09-06 至 2026-10-05')
    expect(wrapper.text()).not.toContain('2026-09-22 至 2026-10-05')
  })

  it('renders in English when the locale is en-US', async () => {
    i18n.global.locale.value = 'en-US'
    fetchMock.mockResolvedValue(usage())
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.text()).toContain('MCP daily usage')
    expect(wrapper.text()).toContain('Unknown tool name')
    expect(wrapper.find('table.mcp-usage-clients .mcp-usage-split').text()).toBe('Anonymous 1, Free 1')
    expect(wrapper.find('button.mcp-usage-metric-tab:last-child').text()).toBe('429s')
  })

  it('labels landing sources in English when the locale is en-US', async () => {
    i18n.global.locale.value = 'en-US'
    fetchMock.mockResolvedValue(
      usage({
        landings: {
          available: true,
          rows: [
            { source: 'api-429-anon', path: '/mcp', landings: 2 },
            { source: 'mcp-429-monthly', path: 'other', landings: 1 },
          ],
        },
      }),
    )
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.text()).toContain('Visits from 429 links')
    const rows = wrapper.findAll('table.mcp-usage-landings tbody tr').map(cellTexts)
    expect(rows).toEqual([
      ['API · anonymous 24-hour quota', '/mcp', '2'],
      ['MCP · free 30-day allowance', 'Other page', '1'],
    ])
  })
})
