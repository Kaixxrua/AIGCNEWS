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
    rss: { title: 'RSS 订阅', publicCta: '订阅公开摘要', memberCta: '查看 vip 全文 RSS' },
    mcpCalls: { title: 'MCP 总调用次数' }, dshCalls: { title: 'dsh 插件调用' },
  },
}

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })

const mountView = async () => {
  const wrapper = mount(DashboardView, {
    global: {
      plugins: [i18n],
      components: { RouterLink: { props: ['to'], template: '<a :href="to"><slot /></a>' } },
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
  it('offers a public RSS feed without exposing a member token', async () => {
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('RSS 订阅')
    expect(wrapper.text()).not.toContain('免费订阅全部来源的摘要；vip 解锁中文译文、全文与 7 天完整归档。')
    expect(wrapper.find('a[href="/wechat"]').exists()).toBe(false)
    expect(wrapper.get('aside').classes()).toContain('min-h-0')
    // mt-auto 在 MCP 卡上：MCP/dsh 两张紧凑计数卡作为整体吸附侧栏底线，与排行榜下边缘对齐
    expect(wrapper.get('a[href="/mcp"]').classes()).toContain('mt-auto')
    expect(wrapper.get('a[href="/dsh"]').classes()).not.toContain('mt-auto')
    expect(wrapper.get('a[href="/dsh"]').classes()).toContain('items-center')

    const publicFeed = wrapper.get('a[href="/api/feed.xml"]')
    expect(publicFeed.text()).toContain('订阅公开摘要')
    expect(publicFeed.attributes('target')).toBe('_blank')
    expect(publicFeed.attributes('rel')).toBe('noopener noreferrer')

    const memberCta = wrapper.get('a[href="/membership"]')
    expect(memberCta.text()).toContain('查看 vip 全文 RSS')
    expect(wrapper.html()).not.toContain('/api/feeds/member.xml?token=')
  })
})
