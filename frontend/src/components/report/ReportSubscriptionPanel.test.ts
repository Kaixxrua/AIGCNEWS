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
  isMember: false,
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

  it('uses visible secondary controls for public RSS copying and going back', async () => {
    const wrapper = mount(ReportSubscriptionPanel, {
      props: props(),
      global: {
        plugins: [i18n],
        stubs: { RouterLink: { template: '<a><slot /></a>' } },
      },
    })

    const secondaryButtons = wrapper.findAll('button.btn-secondary')
    expect(secondaryButtons.length).toBeGreaterThanOrEqual(2)

    await secondaryButtons[0]!.trigger('click')
    await secondaryButtons[secondaryButtons.length - 1]!.trigger('click')
    expect(wrapper.emitted('copyRss')).toEqual([[false]])
    expect(wrapper.emitted('goBack')).toHaveLength(1)
  })

  it('uses the token-protected RSS copy action for members', async () => {
    const wrapper = mount(ReportSubscriptionPanel, {
      props: props({ isMember: true }),
      global: {
        plugins: [i18n],
        stubs: { RouterLink: { template: '<a><slot /></a>' } },
      },
    })

    const copyButton = wrapper.findAll('button.btn-secondary')[0]!
    expect(copyButton.text()).toBe(i18n.global.t('report.wizard.delivery.copyMember'))

    await copyButton.trigger('click')

    expect(wrapper.emitted('copyRss')).toEqual([[true]])
  })
})
