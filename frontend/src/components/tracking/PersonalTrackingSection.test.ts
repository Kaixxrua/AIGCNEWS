import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import PersonalTrackingSection from './PersonalTrackingSection.vue'
import { trackingZh } from '@/i18n/locales/tracking'
import { trackingApi } from '@/services/tracking/trackingApi'
import type { TrackingOverview } from '@/features/tracking/trackingModel'

vi.mock('@/services/tracking/trackingApi', () => ({
  trackingApi: { load: vi.fn(), saveRule: vi.fn(), settings: vi.fn(), deleteRule: vi.fn(), preview: vi.fn() },
}))
vi.mock('@/stores/trackingUnreadStore', () => ({ useTrackingUnreadStore: () => ({ markRead: vi.fn() }) }))
vi.mock('@/stores/authStore', () => ({ useAuthStore: () => ({ token: 'preview-account' }) }))

const snapshot = (): TrackingOverview => ({
  limit: 1,
  rules: [],
  digests: [],
  settings: { enabled: true, delivery_hour: 8, channel_id: null },
})
const saved = () => ({
  id: 1,
  kind: 'keyword' as const,
  query: 'RAG',
  source: 'all' as const,
  excludes: [],
  enabled: true,
  active: true,
  star_threshold: 50,
  created_at: '2026-09-10T00:00:00Z',
})
async function render(data = snapshot()) {
  vi.mocked(trackingApi.load).mockResolvedValue(data)
  const wrapper = mount(PersonalTrackingSection, {
    props: { channels: [] },
    global: {
      plugins: [
        createI18n({
          legacy: false,
          locale: 'zh-CN',
          messages: {
            'zh-CN': {
              tracking: trackingZh,
              common: {
                save: '保存',
                edit: '编辑',
                cancel: '取消',
                delete: '删除',
                confirm: '确认',
                refresh: '刷新',
                processing: '处理中',
                loading: '加载中',
              },
              subscriptions: {
                sources: {
                  all: '全部',
                  github: 'GitHub',
                  news: '新闻',
                  arxiv: '论文',
                  producthunt: '产品',
                  hackernews: '社区',
                  x: 'X',
                  dailyhot: '热榜',
                },
              },
            },
          },
        }),
      ],
      stubs: { RouterLink: RouterLinkStub },
    },
  })
  await flushPromises()
  return wrapper
}

describe('personal tracking', () => {
  beforeEach(() => vi.clearAllMocks())

  it('shows the free limit and defaults to in-app delivery', async () => {
    const wrapper = await render()
    expect(wrapper.text()).toContain('已保存 0 / 1 条规则')
    vi.mocked(trackingApi.settings).mockResolvedValue(snapshot())
    await wrapper.get('.tracking-delivery').trigger('submit')
    await flushPromises()
    expect(trackingApi.settings).toHaveBeenCalledWith({ enabled: true, delivery_hour: 8, channel_id: null })
    expect(wrapper.text()).toContain('仅在本站查看')
    expect(wrapper.text()).toContain('还没有简报')
    expect(wrapper.getComponent(RouterLinkStub).props('to')).toBe('/membership')
    expect(wrapper.text()).toContain('FREE 方案')
    expect(wrapper.text()).toContain('让雷达覆盖更多方向')
  })

  it('shows the active VIP experience from the server-authoritative limit', async () => {
    const wrapper = await render({ ...snapshot(), limit: 10, rules: [saved()] })
    expect(wrapper.text()).toContain('VIP 方案')
    expect(wrapper.text()).toContain('VIP 情报雷达已启动')
    expect(wrapper.text()).toContain('VIP 情报能力已解锁')
    expect(wrapper.text()).toContain('已保存 1 / 10 条规则')
    expect(wrapper.text()).not.toContain('解锁 VIP 情报能力')
  })

  it('saves a usable rule then reflects the server quota', async () => {
    const wrapper = await render()
    vi.mocked(trackingApi.saveRule).mockResolvedValue({ ...snapshot(), rules: [saved()] })
    await wrapper
      .findAll('button')
      .find((button) => button.text() === '添加追踪')!
      .trigger('click')
    await wrapper.get('#tracking-query').setValue('RAG')
    await wrapper.get('#tracking-excludes').setValue('demo, 招聘, demo')
    await wrapper.get('.tracking-rule-form').trigger('submit')
    await flushPromises()
    expect(trackingApi.saveRule).toHaveBeenCalledWith(
      {
        kind: 'keyword',
        query: 'RAG',
        source: 'all',
        excludes: ['demo', '招聘'],
        star_threshold: 50,
        enabled: true,
      },
      undefined,
    )
    expect(wrapper.find('.tracking-rule-form').exists()).toBe(false)
    expect(wrapper.text()).toContain('已保存 1 / 1 条规则')
    expect(
      wrapper
        .findAll('button')
        .find((button) => button.text() === '添加追踪')!
        .attributes('disabled'),
    ).toBeDefined()
  })

  it('preserves expired member rules and disables their preview', async () => {
    const wrapper = await render({
      ...snapshot(),
      rules: [saved(), { ...saved(), id: 2, query: 'agents', active: false }],
    })
    const rows = wrapper.findAll('.tracking-rules > li')
    expect(rows).toHaveLength(2)
    expect(rows[1]!.text()).toContain('超出当前额度，暂停执行')
    expect(rows[1]!.findAll('button')[0]!.attributes('disabled')).toBeDefined()
  })

  it('shows server errors without discarding the rule form', async () => {
    const wrapper = await render()
    vi.mocked(trackingApi.saveRule).mockRejectedValue({
      isAxiosError: true,
      response: { data: { detail: 'rule_limit' } },
    })
    await wrapper
      .findAll('button')
      .find((button) => button.text() === '添加追踪')!
      .trigger('click')
    await wrapper.get('#tracking-query').setValue('RAG')
    await wrapper.get('.tracking-rule-form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('规则上限')
    expect(wrapper.get('#tracking-query').element).toHaveProperty('value', 'RAG')
  })

  it('keeps a rule until deletion is explicitly confirmed', async () => {
    const wrapper = await render({ ...snapshot(), rules: [saved()] })
    const remove = () => wrapper.findAll('button').find((button) => button.text() === '删除')!
    await remove().trigger('click')
    expect(trackingApi.deleteRule).not.toHaveBeenCalled()
    await wrapper.get('[role="alertdialog"]').findAll('button')[1]!.trigger('click')
    expect(wrapper.find('[role="alertdialog"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('已保存 1 / 1 条规则')
    await remove().trigger('click')
    vi.mocked(trackingApi.deleteRule).mockResolvedValue(snapshot())
    await wrapper.get('[role="alertdialog"]').findAll('button')[0]!.trigger('click')
    await flushPromises()
    expect(trackingApi.deleteRule).toHaveBeenCalledWith(1)
    expect(wrapper.text()).toContain('已保存 0 / 1 条规则')
  })

  it('previews matches without requesting delivery', async () => {
    const wrapper = await render({ ...snapshot(), rules: [saved()] })
    vi.mocked(trackingApi.preview).mockResolvedValue({ items: [], truncated: false })
    await wrapper
      .findAll('button')
      .find((button) => button.text() === '预览匹配')!
      .trigger('click')
    await flushPromises()
    expect(trackingApi.preview).toHaveBeenCalledWith(1)
    expect(wrapper.text()).toContain('最近 24 小时暂无匹配')
    expect(trackingApi.settings).not.toHaveBeenCalled()
  })
})
