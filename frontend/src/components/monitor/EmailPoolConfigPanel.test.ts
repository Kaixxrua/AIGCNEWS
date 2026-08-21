import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'
import EmailPoolConfigPanel from './EmailPoolConfigPanel.vue'
import i18n, { setAppLocale } from '@/i18n'
import {
  createEmailPoolForm,
  type EmailDeliveryDayStat,
  type EmailPoolConfig,
} from '@/features/monitor/monitorModel'

// 与组件内 todayStat 同一时区公式：后端按 Asia/Shanghai 自然日归日
const shanghaiToday = () =>
  new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date())

const mountPanel = (
  props: {
    config?: EmailPoolConfig | null
    stats?: EmailDeliveryDayStat[]
    statsLoading?: boolean
  } = {},
) => {
  const wrapper = mount(EmailPoolConfigPanel, {
    global: { plugins: [i18n] },
    props: {
      config: null,
      form: createEmailPoolForm(),
      loading: false,
      saving: false,
      testing: false,
      stats: [],
      statsLoading: false,
      ...props,
    },
  })
  return { wrapper }
}

describe('EmailPoolConfigPanel delivery stats', () => {
  beforeEach(() => {
    setAppLocale('zh-CN')
  })

  it('shows today sent/failed badges and per-day rows from the stats list', () => {
    const today = shanghaiToday()
    const { wrapper } = mountPanel({
      stats: [
        { date: today, sent: 12, failed: 1 },
        { date: '2026-08-20', sent: 9, failed: 0 },
      ],
    })
    const text = wrapper.text()
    expect(text).toContain('发送统计')
    expect(text).toContain('今日已发 12 封')
    expect(text).toContain('失败 1 封')
    // 昨日行：成功数展示，failed=0 不出失败段
    expect(text).toContain('08-20 · 成功 9')
    expect(text).not.toContain('08-20 · 成功 9 · 失败')
  })

  it('shows the empty-today hint when stats have no row for today', () => {
    const { wrapper } = mountPanel({
      stats: [{ date: '2026-08-19', sent: 5, failed: 0 }],
    })
    const text = wrapper.text()
    expect(text).toContain('今日暂无发送记录')
    expect(text).toContain('08-19 · 成功 5')
  })

  it('shows the 7-day empty hint when no deliveries exist at all', () => {
    const { wrapper } = mountPanel({ stats: [] })
    const text = wrapper.text()
    expect(text).toContain('今日暂无发送记录')
    expect(text).toContain('近 7 天（按北京时间自然日）暂无邮件投递记录。')
  })

  it('suppresses empty hints while stats are still loading', () => {
    const { wrapper } = mountPanel({ stats: [], statsLoading: true })
    const text = wrapper.text()
    expect(text).toContain('发送统计')
    expect(text).not.toContain('今日暂无发送记录')
    expect(text).not.toContain('近 7 天')
  })

  it('renders English labels under en-US locale', () => {
    setAppLocale('en-US')
    const today = shanghaiToday()
    const { wrapper } = mountPanel({
      stats: [{ date: today, sent: 3, failed: 2 }],
    })
    const text = wrapper.text()
    expect(text).toContain('Sent today: 3')
    expect(text).toContain('Failed: 2')
  })
})
