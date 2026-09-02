import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { describe, expect, it, vi } from 'vitest'
import DashboardView from './DashboardView.vue'

vi.mock('@/composables/useDashboardData', async () => {
  const { ref } = await import('vue')
  return {
    useDashboardData: () => ({
      activeTab: ref('github'),
      tabList: ref([]),
      stats: ref({}),
      loading: ref(false),
      tabLoading: ref(false),
      errorMsg: ref(''),
      currentDate: ref('2026-08-19'),
      availableDates: ref([]),
      isViewingHistory: ref(false),
      isFinalized: ref(false),
      isEmbargoed: ref(false),
      sourceStatus: ref({}),
      selectSourceTab: vi.fn(),
      onDateChange: vi.fn(),
      hasData: ref(true),
      refreshLiveStats: vi.fn(),
    }),
  }
})

vi.mock('@/composables/useDashboardStats', async () => {
  const { ref } = await import('vue')
  return {
    useDashboardStats: () => ({
      statValues: ref([]),
      visitorValues: ref([]),
      mcpTotalCalls: ref(0),
      mcpDshCalls: ref(0),
      updateStatSources: vi.fn(),
      updateVisitorSources: vi.fn(),
    }),
  }
})

const messages = {
  dashboard: {
    title: '仪表盘', previousMonth: '上个月', nextMonth: '下个月',
    digest: { title: '每日 AI 简报', description: '每天早上把榜单摘要发到你的邮箱。', cta: '订阅简报' },
    mcpCalls: { title: 'MCP 总调用次数' }, dshCalls: { title: 'dsh 插件调用' },
  },
}

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })

const buildQuery = (query?: Record<string, string>): string => {
  if (!query) return ''
  const params = new URLSearchParams(query)
  const qs = params.toString()
  return qs ? `?${qs}` : ''
}

const mountView = async () => {
  const wrapper = mount(DashboardView, {
    global: {
      plugins: [i18n],
      components: {
        RouterLink: {
          props: ['to'],
          setup(props: { to: string | { path?: string; query?: Record<string, string> } }) {
            const href = typeof props.to === 'string' ? props.to : `${props.to.path ?? '/'}${buildQuery(props.to.query)}`
            return { href }
          },
          template: '<a :href="href"><slot /></a>',
        },
      },
      stubs: {
        GlassCalendar: { template: '<div />' },
        DashboardOverviewPanel: { template: '<div />' },
        DashboardRankingPanel: { template: '<div />' },
        DashboardEmptyState: { template: '<div />' },
        RollingNumber: { template: '<span />' },
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('DashboardView', () => {
  it('renders a single digest CTA that opens the report subscription wizard', async () => {
    const wrapper = await mountView()

    expect(wrapper.text()).toContain(messages.dashboard.digest.title)
    expect(wrapper.text()).not.toContain('免费订阅全部来源的摘要；vip 解锁中文译文、全文与 7 天完整归档。')
    expect(wrapper.find('a[href="/wechat"]').exists()).toBe(false)
    expect(wrapper.get('aside').classes()).toContain('min-h-0')
    // MCP/dsh 两张计数卡 flex-1 平分侧栏剩余高度：既不留大片空白，又使 dsh 底线与排行榜下边缘对齐
    expect(wrapper.get('a[href="/mcp"]').classes()).toContain('flex-1')
    expect(wrapper.get('a[href="/mcp"]').classes()).not.toContain('mt-auto')
    expect(wrapper.get('a[href="/dsh"]').classes()).toContain('flex-1')
    expect(wrapper.get('a[href="/dsh"]').classes()).toContain('items-center')

    const digestCta = wrapper.get('a[href="/report?subscribe=1"]')
    expect(digestCta.text()).toContain(messages.dashboard.digest.cta)

    // 只保留一个订阅入口，RSS 在简报向导内复制；Dashboard 不暴露 feed token
    expect(wrapper.find('a[href="/api/feeds/briefing.xml"]').exists()).toBe(false)
    expect(wrapper.html()).not.toContain('/api/feeds/member.xml?token=')
    expect(wrapper.find('a[href="/subscriptions"]').exists()).toBe(false)
    expect(wrapper.find('a[href="/membership"]').exists()).toBe(false)
  })
})
