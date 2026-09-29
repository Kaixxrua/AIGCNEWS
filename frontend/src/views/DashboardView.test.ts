import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { describe, expect, it, vi } from 'vitest'
import DashboardView from './DashboardView.vue'
import { loadCatalog } from '@/features/ui-library/catalog'

const layout = vi.hoisted(() => ({ desktop: false }))
vi.mock('@vueuse/core', async (original) => {
  const actual = await original<typeof import('@vueuse/core')>()
  const { ref } = await import('vue')
  return { ...actual, useElementVisibility: () => ref(true), useMediaQuery: () => ref(layout.desktop) }
})

vi.mock('@/features/ui-library/catalog', () => ({
  loadCatalog: vi.fn().mockResolvedValue([
    { id: 'example', name: { zh: '示例组件', en: 'Example' }, poster_url: '/ui-library/posters/example.webp' },
    { id: 'featured', name: { zh: '精选组件', en: 'Featured' }, clip_url: '/ui-library/clips/featured.mp4', poster_url: '/ui-library/posters/featured.webp', editorial: { status: 'approved' } },
  ]),
}))

vi.mock('@/composables/useLiveStatsStream', () => ({ subscribeLiveStats: vi.fn() }))

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
      applyLiveStats: vi.fn(),
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
    editorial: { digestTitle: '每日 AI 简报' },
    digest: { title: '每日 AI 简报', description: '每天早上把榜单摘要发到你的邮箱。', cta: '订阅简报',
      featureSchedule: '每天 08:00 更新', featureEmailRss: '邮件、RSS 订阅', featureChat: 'Telegram、Discord', featureWebhook: 'Webhook 推送' },
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
        DashboardOverviewPanel: { props: ['uiCount', 'uiLoading'], template: '<div class="overview-stub" :data-count="uiCount" :data-loading="uiLoading" />' },
        DashboardRankingPanel: { template: '<div />' },
        DashboardEmptyState: { template: '<div />' },
        DigestGeometry: { template: '<div />' },
        RollingNumber: { template: '<span />' },
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('DashboardView', () => {
  it('loads the total catalog count and selects a real editorial preview', async () => {
    const wrapper = await mountView()
    expect(wrapper.get('.overview-stub').attributes('data-count')).toBe('2')
    expect(wrapper.get('.ui-inspiration video').attributes('src')).toBe('/ui-library/clips/featured.mp4')
    await wrapper.get('.ui-inspiration video').trigger('error')
    expect(wrapper.get('.ui-inspiration img').attributes('src')).toBe('/ui-library/posters/featured.webp')
    await wrapper.get('.ui-inspiration img').trigger('error')
    expect(wrapper.find('.ui-inspiration img').exists()).toBe(false)
    expect(wrapper.find('.ui-inspiration__fallback').exists()).toBe(true)
    wrapper.unmount()
  })

  it('keeps the dashboard usable when the UI catalog is unavailable', async () => {
    vi.mocked(loadCatalog).mockRejectedValueOnce(new Error('Unavailable'))
    const wrapper = await mountView()
    expect(wrapper.get('.overview-stub').attributes('data-count')).toBeUndefined()
    expect(wrapper.get('.overview-stub').attributes('data-loading')).toBe('false')
    expect(wrapper.find('.ui-inspiration').exists()).toBe(true)
    wrapper.unmount()
  })
  it('renders a single digest CTA that opens the report subscription wizard', async () => {
    const wrapper = await mountView()

    expect(wrapper.find('.daily-ui').exists()).toBe(false)
    expect(wrapper.text()).toContain(messages.dashboard.digest.title)
    expect(wrapper.text()).not.toContain('免费订阅全部来源的摘要；vip 解锁中文译文、全文与 7 天完整归档。')
    expect(wrapper.get('aside').classes()).toContain('min-h-0')
    // MCP/dsh 两张计数卡为紧凑单行卡：自然高度，不再 flex-1 撑满侧栏
    expect(wrapper.get('a[href="/mcp"]').classes()).not.toContain('flex-1')
    expect(wrapper.get('a[href="/mcp"]').classes()).not.toContain('mt-auto')
    expect(wrapper.get('a[href="/dsh"]').classes()).not.toContain('flex-1')
    expect(wrapper.get('a[href="/dsh"]').classes()).toContain('items-center')

    expect(wrapper.find('.radar-card').exists()).toBe(false)
    expect(wrapper.get('aside').find('.ui-inspiration').exists()).toBe(true)
    expect(wrapper.find('.ui-inspiration').exists()).toBe(true)

    const digestCta = wrapper.get('a[href="/report?subscribe=1"]')
    expect(digestCta.text()).toContain(messages.dashboard.digest.cta)

    // 只保留一个订阅入口，RSS 在简报向导内复制；Dashboard 不暴露 feed token
    expect(wrapper.find('a[href="/api/feeds/briefing.xml"]').exists()).toBe(false)
    expect(wrapper.html()).not.toContain('/api/feeds/member.xml?token=')
    expect(wrapper.find('a[href="/subscriptions"]').exists()).toBe(false)
    expect(wrapper.find('a[href="/membership"]').exists()).toBe(false)
  })

  it('states only verifiable delivery facts in the desktop digest card', async () => {
    layout.desktop = true
    try {
      const wrapper = await mountView()
      // 08:00 生成（daily_briefing）+ 订阅向导里实际可选的投递渠道
      expect(wrapper.findAll('.digest-features li').map(item => item.text())).toEqual([
        '每天 08:00 更新', '邮件、RSS 订阅', 'Telegram、Discord', 'Webhook 推送',
      ])
      wrapper.unmount()
    } finally {
      layout.desktop = false
    }
  })
})
