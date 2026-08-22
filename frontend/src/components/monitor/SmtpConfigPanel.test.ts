import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'
import SmtpConfigPanel from './SmtpConfigPanel.vue'
import i18n, { setAppLocale } from '@/i18n'
import {
  createSmtpForm,
  type EmailDeliveryDayStat,
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
    stats?: EmailDeliveryDayStat[]
    statsLoading?: boolean
  } = {},
) => {
  const wrapper = mount(SmtpConfigPanel, {
    global: { plugins: [i18n] },
    props: {
      config: null,
      form: createSmtpForm(),
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

describe('SmtpConfigPanel delivery stats', () => {
  beforeEach(() => {
    setAppLocale('zh-CN')
  })

  it('shows today sent/failed badges and per-day rows on the SMTP card', () => {
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
    expect(text).toContain('08-20 · 成功 9')
  })

  it('shows empty hints when no deliveries exist and suppresses them while loading', () => {
    const { wrapper } = mountPanel({ stats: [] })
    expect(wrapper.text()).toContain('今日暂无发送记录')
    expect(wrapper.text()).toContain('近 7 天（按北京时间自然日）暂无邮件投递记录。')

    const loading = mountPanel({ stats: [], statsLoading: true })
    expect(loading.wrapper.text()).toContain('发送统计')
    expect(loading.wrapper.text()).not.toContain('今日暂无发送记录')
  })

  it('renders English labels under en-US locale', () => {
    setAppLocale('en-US')
    const { wrapper } = mountPanel({
      stats: [{ date: shanghaiToday(), sent: 3, failed: 2 }],
    })
    const text = wrapper.text()
    expect(text).toContain('Sent today: 3')
    expect(text).toContain('Failed: 2')
  })
})
