import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '@/i18n'
import { activityApi, type EmailMonitoring, type ReturnVisits } from '@/services/monitor/activityApi'
import AccountReturnVisitsPanel from './AccountReturnVisitsPanel.vue'
import EmailMonitorPanel from './EmailMonitorPanel.vue'

vi.mock('@/services/monitor/activityApi', async (original) => {
  const actual = await original<typeof import('@/services/monitor/activityApi')>()
  return { ...actual, activityApi: { returnVisits: vi.fn(), email: vi.fn() } }
})

describe('monitoring activity panels', () => {
  beforeEach(() => { vi.useFakeTimers(); vi.resetAllMocks(); i18n.global.locale.value = 'zh-CN' })
  afterEach(() => { vi.useRealTimers() })

  it('defaults to seven days and shows browser returns independently of same-day registrations', async () => {
    const data: ReturnVisits = {
      timezone: 'Asia/Shanghai', tracking_started_at: '2026-10-10T01:00:00Z', as_of: '2026-10-12T08:00:00Z',
      days: [
        { day: '2026-10-12', coverage: 'partial', total_visitors: 10, active_users: 4, returning_users: 1, new_users: 3, return_rate: 1 / 7, registration_rate: 3 / 9 },
      ],
      visitor_returns: {
        timezone: 'Asia/Shanghai', tracking_started_at: '2026-10-10T01:00:00Z', as_of: '2026-10-12T08:00:00Z',
        days: [
          { day: '2026-10-12', coverage: 'partial', total_visitors: 10, returning_visitors: 5, return_rate: .5 },
          { day: '2026-10-11', coverage: 'complete', total_visitors: 2, returning_visitors: 0, return_rate: 0 },
          { day: '2026-10-10', coverage: 'partial', total_visitors: 4, returning_visitors: null, return_rate: null },
          { day: '2026-10-09', coverage: 'unavailable', total_visitors: null, returning_visitors: null, return_rate: null },
        ],
      },
    }
    vi.mocked(activityApi.returnVisits).mockResolvedValue(data)
    const wrapper = mount(AccountReturnVisitsPanel, { global: { plugins: [i18n] } })
    await flushPromises()
    expect(activityApi.returnVisits).toHaveBeenCalledWith(7)
    expect(wrapper.find('select').element.value).toBe('7')
    const browser = wrapper.find('.visitor-return-stats')
    expect(browser.text()).toContain('包括未注册访客和当日新注册用户')
    expect(browser.text()).toContain('此前任一日期来过')
    expect(browser.text()).toContain('当天首次到访后注册不算回访')
    expect(browser.text()).toContain('此前历史无法补算')
    expect(browser.text()).toContain('5 / 10')
    expect(browser.findAll('tbody tr').map(row => row.findAll('td').slice(0, 3).map(cell => cell.text())))
      .toEqual([['10', '5', '50.00%'], ['2', '0', '0.00%'], ['4', '—', '—']])
    const daily = wrapper.find('.account-return-stats')
    expect(daily.find('h4').text()).toBe('每日访客与账号统计')
    expect(daily.find('table').element.closest('details')).toBeNull()
    expect(daily.find('.metric-card').element.closest('details')).toBeNull()
    expect(daily.find('.metric-card').text()).toContain('今日全部访客')
    await wrapper.find('select').setValue('30')
    await flushPromises()
    expect(activityApi.returnVisits).toHaveBeenLastCalledWith(30)
    wrapper.unmount()
    const calls = vi.mocked(activityApi.returnVisits).mock.calls.length
    await vi.advanceTimersByTimeAsync(120_000)
    expect(activityApi.returnVisits).toHaveBeenCalledTimes(calls)
  })

  it('keeps full daily visitors and historical registrations visible while new return history is collecting', async () => {
    vi.mocked(activityApi.returnVisits).mockResolvedValue({
      timezone: 'Asia/Shanghai', tracking_started_at: '2026-10-10T01:00:00Z', as_of: '2026-10-15T09:15:00Z',
      days: [
        { day: '2026-10-15', coverage: 'partial', total_visitors: 153, active_users: 44, returning_users: 27, new_users: 17, return_rate: 27 / 136, registration_rate: 17 / 126 },
        { day: '2026-10-12', coverage: 'complete', total_visitors: 453, active_users: 105, returning_users: 9, new_users: 96, return_rate: 9 / 357, registration_rate: 96 / 444 },
      ],
      visitor_returns: {
        timezone: 'Asia/Shanghai', tracking_started_at: '2026-10-15T08:59:31Z', as_of: '2026-10-15T09:15:00Z',
        days: [
          { day: '2026-10-15', coverage: 'partial', total_visitors: 4, returning_visitors: null, return_rate: null },
          { day: '2026-10-12', coverage: 'unavailable', total_visitors: null, returning_visitors: null, return_rate: null },
        ],
      },
    })
    const wrapper = mount(AccountReturnVisitsPanel, { global: { plugins: [i18n] } })
    await flushPromises()
    const daily = wrapper.find('.account-return-stats')
    expect(daily.find('.metric-card').text()).toContain('153')
    expect(daily.findAll('tbody tr').map(row => row.findAll('td').slice(0, 4).map(cell => cell.text())))
      .toEqual([['153', '44', '27', '17'], ['453', '105', '9', '96']])
    expect(daily.find('table').element.closest('details')).toBeNull()
    const browser = wrapper.find('.visitor-return-stats')
    expect(browser.find('[role="status"]').text()).toContain('首日已采集 4 位访客')
    expect(browser.text()).toContain('今日全部访客见上方')
    expect(browser.find('table').exists()).toBe(false)
    expect(browser.find('.metric-card').exists()).toBe(false)
    wrapper.unmount()
  })

  it('shows both adjusted daily rates and their formulas without inventing historical zeroes', async () => {
    const data: ReturnVisits = {
      timezone: 'Asia/Shanghai', tracking_started_at: '2026-10-10T01:00:00Z', as_of: '2026-10-12T08:00:00Z',
      days: [
        { day: '2026-10-12', coverage: 'partial', total_visitors: 453, active_users: 105, returning_users: 9, new_users: 96, return_rate: 9 / 357, registration_rate: 96 / 444 },
        { day: '2026-10-09', coverage: 'unavailable', total_visitors: null, active_users: null, returning_users: null, new_users: null, return_rate: null, registration_rate: null },
      ],
    }
    vi.mocked(activityApi.returnVisits).mockResolvedValue(data)
    const wrapper = mount(AccountReturnVisitsPanel, { global: { plugins: [i18n] } })
    await flushPromises()
    expect(wrapper.text()).toContain('今日注册率')
    expect(wrapper.text()).toContain('全站访客回访数据暂不可用')
    expect(wrapper.text()).toContain('9 / (453 − 96)')
    expect(wrapper.text()).toContain('96 / (453 − 9)')
    expect(wrapper.text()).toContain('两个比例均为估算')
    expect(wrapper.text()).toContain('不等于全部注册数')
    expect(wrapper.findAll('thead th').map(cell => cell.text())).toContain('每日注册率')
    const cells = wrapper.findAll('tbody tr')[0]!.findAll('td')
    expect(cells.slice(0, 6).map(cell => cell.text())).toEqual(['453', '105', '9', '96', '2.52%', '21.62%'])
    expect(cells[4]!.attributes('title')).toBe('9 / (453 − 96)')
    expect(cells[5]!.attributes('title')).toBe('96 / (453 − 9)')
    expect(wrapper.findAll('tbody tr')[0]!.text()).toContain('部分时段')
    const history = wrapper.findAll('tbody tr')[1]!
    expect(history.text()).toContain('未开始采集')
    expect(history.findAll('td').slice(0, 6).map(cell => cell.text())).toEqual(['—', '—', '—', '—', '—', '—'])
    wrapper.unmount()
  })

  it('shows unavailable rates as dashes, keeps valid zeroes, and tolerates an older API response', async () => {
    vi.mocked(activityApi.returnVisits).mockResolvedValue({
      timezone: 'Asia/Shanghai', tracking_started_at: '2026-10-10T01:00:00Z', as_of: '2026-10-12T08:00:00Z',
      days: [
        { day: '2026-10-12', coverage: 'partial', total_visitors: 3, active_users: 3, returning_users: 0, new_users: 3, return_rate: null, registration_rate: 1 },
        { day: '2026-10-11', coverage: 'complete', total_visitors: 10, active_users: 0, returning_users: 0, new_users: 0, return_rate: 0, registration_rate: 0 },
        { day: '2026-10-10', coverage: 'partial', total_visitors: 3, active_users: 3, returning_users: 3, new_users: 0, return_rate: 1, registration_rate: null },
      ],
    })
    const wrapper = mount(AccountReturnVisitsPanel, { global: { plugins: [i18n] } })
    await flushPromises()
    expect(wrapper.findAll('tbody tr').map(row => row.findAll('td').slice(4, 6).map(cell => cell.text())))
      .toEqual([['—', '100.00%'], ['0.00%', '0.00%'], ['100.00%', '—']])
    const older = await activityApi.returnVisits()
    const { registration_rate: _rate, ...day } = older.days[0]!
    vi.mocked(activityApi.returnVisits).mockResolvedValue({ ...older, days: [day] } as ReturnVisits)
    await wrapper.find('button').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('tbody tr')[0]!.findAll('td')[5]!.text()).toBe('—')
    expect(wrapper.text()).not.toContain('NaN')
    wrapper.unmount()
  })

  it('labels stale data and unconfirmed notifications instead of claiming healthy delivery', async () => {
    const data: EmailMonitoring = {
      stale: true, tracking_started_at: '2026-10-10T01:00:00Z', checked_at: '2026-10-10T01:10:00Z',
      recipient: 'o***@example.test', local: { accepted_24h: 8, failed_24h: 1, failed_15m: 1 },
      providers: [{ name: 'resend', host: 'smtp.resend.com', port: 2587, smtp: { status: 'ok' },
        usage: { daily: { used: 95, limit: 100, resets_at: '2026-10-11T00:00:00Z' },
          monthly: { used: 224, limit: 3000, resets_at: '2026-10-17T10:04:59Z' } },
        usage_error: null, events_error: null, recent: { count: 8, has_more: false, statuses: { delivered: 8 } } }],
      alerts: [{ id: '1', key: 'daily', level: 95, active: true, detail: 'quota', opened_at: '2026-10-10T01:10:00Z',
        notified_at: null, notification_error: 'HTTP 429' }],
    }
    vi.mocked(activityApi.email).mockResolvedValue(data)
    const wrapper = mount(EmailMonitorPanel, { global: { plugins: [i18n] } })
    await flushPromises()
    expect(wrapper.text()).toContain('95 / 100')
    expect(wrapper.text()).toContain('224 / 3000')
    expect(wrapper.text()).toContain('以下是旧数据')
    expect(wrapper.text()).toContain('告警尚未确认发送')
    expect(wrapper.text()).toContain('HTTP 429')
    expect(wrapper.text()).toContain('已送达 8')
    expect(wrapper.text()).toContain('不是当天投递总量')
    expect(wrapper.text()).toContain('不代表收件方已送达')
    wrapper.unmount()
  })

  it('does not invent zero totals before the first check and releases polling on unmount', async () => {
    vi.mocked(activityApi.email).mockResolvedValue({ stale: true, tracking_started_at: '2026-10-10T01:00:00Z' })
    const wrapper = mount(EmailMonitorPanel, { global: { plugins: [i18n] } })
    await flushPromises()
    expect(wrapper.text()).toContain('等待后台首次检查')
    expect(wrapper.findAll('.metric-card header p:last-child').map(item => item.text())).toEqual(['—', '—', '—'])
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(120_000)
    expect(activityApi.email).toHaveBeenCalledTimes(1)
  })
})
