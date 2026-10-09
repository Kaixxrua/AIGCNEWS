import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { afterEach, describe, expect, it, vi } from 'vitest'
import DashboardView from './DashboardView.vue'
import { loadUiShowcaseCatalog } from '@/features/dashboard/uiShowcase'

enableAutoUnmount(afterEach)

const layout = vi.hoisted(() => ({ desktop: false }))
const dashboardState = vi.hoisted(() => ({ loadError: null as 'network' | 'server' | null, tabList: [] as unknown[], retry: vi.fn() }))
vi.mock('@vueuse/core', async (original) => {
  const actual = await original<typeof import('@vueuse/core')>()
  const { ref } = await import('vue')
  return { ...actual, useElementVisibility: () => ref(true), useMediaQuery: () => ref(layout.desktop) }
})

vi.mock('@/features/dashboard/uiShowcase', async (original) => ({
  ...await original<typeof import('@/features/dashboard/uiShowcase')>(),
  loadUiShowcaseCatalog: vi.fn().mockResolvedValue({ version: 1, total: 240, items: [
    { id: 'example', name: { zh: '示例组件', en: 'Example' }, poster_url: '/ui-library/posters/example.webp' },
    { id: 'eui-shader-worlds', name: { zh: '精选组件', en: 'Featured' }, clip_url: '/ui-library/clips/featured.mp4', poster_url: '/ui-library/posters/featured.webp', editorial: { status: 'approved' } },
  ] }),
}))

vi.mock('@/composables/useLiveStatsStream', () => ({ subscribeLiveStats: vi.fn() }))

vi.mock('@/composables/useDashboardData', async () => {
  const { ref } = await import('vue')
  return {
    useDashboardData: () => ({
      activeTab: ref('github'),
      tabList: ref(dashboardState.tabList),
      stats: ref({}),
      loading: ref(false),
      tabLoading: ref(false),
      loadError: ref(dashboardState.loadError),
      retrying: ref(false),
      retry: dashboardState.retry,
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
  common: { retry: '重试', loading: '加载中…' },
  dashboard: {
    title: '仪表盘', previousMonth: '上个月', nextMonth: '下个月',
    editorial: { digestTitle: '每日 AI 简报' },
    digest: { compactTime: '每日 08:00', compactEmail: '邮件 · RSS 订阅', compactCta: '订阅', title: '每日 AI 简报', description: '每天早上把榜单摘要发到你的邮箱。', cta: '订阅简报',
      featureSchedule: '每天 08:00 更新', featureEmailRss: '邮件、RSS 订阅', featureChat: 'Telegram、Discord', featureWebhook: 'Webhook 推送' },
    mcpCalls: { title: 'MCP 总调用次数' }, dshCalls: { title: 'dsh 插件调用' },
    loadError: { stale: '刷新失败，下面是上次加载的榜单。' },
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
        DashboardNewWords: { template: '<section class="new-words-stub" />' },
        DashboardOverviewPanel: { props: ['uiCount', 'uiLoading'], template: '<div class="overview-stub" :data-count="uiCount" :data-loading="uiLoading" />' },
        DashboardRankingPanel: { template: '<div />' },
        DashboardEmptyState: { props: ['variant', 'error'], emits: ['retry'], template: '<button class="empty-stub" :data-variant="variant" :data-error="error" @click="$emit(\'retry\')" />' },
        RollingNumber: { template: '<span />' },
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('DashboardView', () => {
  afterEach(() => {
    layout.desktop = false
    dashboardState.loadError = null
    dashboardState.tabList = []
    dashboardState.retry.mockClear()
  })

  it('loads the total catalog count and selects a real editorial preview', async () => {
    const wrapper = await mountView()
    expect(wrapper.get('.overview-stub').attributes('data-count')).toBe('240')
    expect(wrapper.get('.ui-inspiration video').attributes('src')).toBe('/ui-library/clips/featured.mp4')
    await wrapper.get('.ui-inspiration video').trigger('error')
    expect(wrapper.get('.ui-inspiration img').attributes('src')).toBe('/ui-library/posters/featured.webp')
    await wrapper.get('.ui-inspiration img').trigger('error')
    expect(wrapper.find('.ui-inspiration img').exists()).toBe(false)
    expect(wrapper.find('.ui-inspiration__fallback').exists()).toBe(true)
    wrapper.unmount()
  })

  it('keeps the dashboard usable when the UI catalog is unavailable', async () => {
    vi.mocked(loadUiShowcaseCatalog).mockRejectedValueOnce(new Error('Unavailable'))
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
    expect(digestCta.text()).toContain(messages.dashboard.digest.compactCta)

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
      expect(wrapper.get('.digest-card').text()).toContain('每日 08:00')
      expect(wrapper.get('.digest-card').text()).toContain('邮件 · RSS 订阅')
      expect(wrapper.get('.digest-card').text()).toContain('Telegram · Discord · Webhook')
      expect(wrapper.find('.digest-card img').exists()).toBe(false)
      expect(wrapper.get('.new-words-stub').element.nextElementSibling).toBe(wrapper.get('.digest-card').element)
      wrapper.unmount()
    } finally {
      layout.desktop = false
    }
  })

  it.each([false, true])('shows a retryable failure instead of “no data” when the board did not load (desktop: %s)', async (desktop) => {
    layout.desktop = desktop
    dashboardState.loadError = 'network'
    const wrapper = await mountView()
    const failure = wrapper.get('.empty-stub')
    expect(failure.attributes('data-variant')).toBe('error')
    expect(failure.attributes('data-error')).toBe('network')
    expect(wrapper.find('.dashboard-error').exists()).toBe(false)
    await failure.trigger('click')
    expect(dashboardState.retry).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it.each([false, true])('keeps the last rankings with a notice and a retry when a refresh fails (desktop: %s)', async (desktop) => {
    layout.desktop = desktop
    dashboardState.loadError = 'server'
    dashboardState.tabList = [{ id: 1, title: 'Top' }]
    const wrapper = await mountView()
    const notice = wrapper.get('.dashboard-error')
    expect(notice.attributes('role')).toBe('alert')
    expect(notice.text()).toContain('刷新失败，下面是上次加载的榜单。')
    expect(notice.text()).not.toContain('Error')
    expect(wrapper.find('.empty-stub').exists()).toBe(false)
    await notice.get('button').trigger('click')
    expect(dashboardState.retry).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
})
