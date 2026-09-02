import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { i18n } from '@/i18n'
import ReportSubscriptionPanel from './ReportSubscriptionPanel.vue'
import type {
  PlanDeliveryCapability,
  ReportKey,
} from '@/features/report/reportViewModel'

const capabilities: PlanDeliveryCapability[] = [
  {
    key: 'rss:briefing',
    kind: 'rss',
    feed: 'briefing',
    selectable: true,
    active: true,
    verified: true,
    status: 'active',
  },
  {
    key: 'push:42',
    kind: 'push_channel',
    channel_id: 42,
    channel_type: 'telegram',
    target: '@daily',
    selectable: true,
    active: false,
    verified: true,
    status: 'active',
  },
  {
    key: 'push:wechat',
    kind: 'push_channel',
    channel_type: 'wechat',
    selectable: false,
    active: false,
    verified: false,
    status: 'coming_soon',
    disabled_reason: 'coming_soon',
  },
]

const props = (overrides: Record<string, unknown> = {}) => ({
  showLoginPrompt: false,
  showSubscribePanel: true,
  isSubscribing: false,
  isLoadingPlan: false,
  isRssBusy: false,
  rssNotice: '',
  userEmail: 'reader@example.com',
  step: 2 as const,
  selectedSources: ['github'] as ReportKey[],
  selectedDeliveryKeys: ['rss:briefing'],
  deliveryCapabilities: capabilities,
  canSelectMultipleSources: false,
  hasExistingPlan: true,
  ...overrides,
})

describe('ReportSubscriptionPanel delivery controls', () => {
  it('renders delivery choices as visible cards and keeps unavailable providers disabled', () => {
    const wrapper = mount(ReportSubscriptionPanel, {
      props: props(),
      global: {
        plugins: [i18n],
        stubs: { RouterLink: { template: '<a><slot /></a>' } },
      },
    })

    const cards = wrapper.findAll('.delivery-option')
    expect(cards).toHaveLength(3)
    expect(cards[0]!.classes()).toContain('delivery-option--selected')
    expect(cards[0]!.find('.delivery-option__toggle').attributes('aria-pressed')).toBe('true')
    expect(cards[2]!.find('.delivery-option__toggle').attributes('disabled')).toBeDefined()
  })

  it('uses visible secondary controls for digest RSS copying and going back', async () => {
    const wrapper = mount(ReportSubscriptionPanel, {
      props: props(),
      global: {
        plugins: [i18n],
        stubs: { RouterLink: { template: '<a><slot /></a>' } },
      },
    })

    const secondaryButtons = wrapper.findAll('button.btn-secondary')
    expect(secondaryButtons.length).toBeGreaterThanOrEqual(2)

    // 速览 RSS 已对所有注册用户免费开放：复制按钮统一为 copyDigest，emit 不带会员标记
    expect(secondaryButtons[0]!.text()).toBe(i18n.global.t('report.wizard.delivery.copyDigest'))

    await secondaryButtons[0]!.trigger('click')
    await secondaryButtons[secondaryButtons.length - 1]!.trigger('click')
    expect(wrapper.emitted('copyRss')).toEqual([[]])
    expect(wrapper.emitted('goBack')).toHaveLength(1)
  })

  it('disables confirm only when sources are picked without any delivery', () => {
    const wrapper = mount(ReportSubscriptionPanel, {
      props: props({ selectedDeliveryKeys: [] }),
      global: {
        plugins: [i18n],
        stubs: { RouterLink: { template: '<a><slot /></a>' } },
      },
    })

    const confirmButton = wrapper.findAll('button.btn-primary').pop()!
    expect(confirmButton.attributes('disabled')).toBeDefined()

    // 全清（连来源也不选）= 退订路径，confirm 可用
    const clearing = mount(ReportSubscriptionPanel, {
      props: props({ selectedSources: [], selectedDeliveryKeys: [] }),
      global: {
        plugins: [i18n],
        stubs: { RouterLink: { template: '<a><slot /></a>' } },
      },
    })
    expect(clearing.findAll('button.btn-primary').pop()!.attributes('disabled')).toBeUndefined()
  })
})
