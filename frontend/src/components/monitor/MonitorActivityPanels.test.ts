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

  it('shows the precise numerator and denominator, not invented historical zeroes', async () => {
    const data: ReturnVisits = {
      timezone: 'Asia/Shanghai', tracking_started_at: '2026-10-10T01:00:00Z', as_of: '2026-10-10T08:00:00Z',
      days: [
        { day: '2026-10-10', coverage: 'partial', active_users: 3, returning_users: 2, new_users: 1, return_rate: 2 / 3 },
        { day: '2026-10-09', coverage: 'unavailable', active_users: null, returning_users: null, new_users: null, return_rate: null },
      ],
    }
    vi.mocked(activityApi.returnVisits).mockResolvedValue(data)
    const wrapper = mount(AccountReturnVisitsPanel, { global: { plugins: [i18n] } })
    await flushPromises()
    expect(wrapper.text()).toContain('66.67%')
    expect(wrapper.findAll('tbody tr')[0]!.text()).toContain('部分时段')
    const history = wrapper.findAll('tbody tr')[1]!
    expect(history.text()).toContain('未开始采集')
    expect(history.findAll('td').slice(0, 4).map(cell => cell.text())).toEqual(['—', '—', '—', '—'])
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
