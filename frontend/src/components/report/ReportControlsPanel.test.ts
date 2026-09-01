import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ReportControlsPanel from './ReportControlsPanel.vue'
import { i18n } from '@/i18n'
import { REPORT_TYPES, type ReportKey } from '@/features/report/reportViewModel'

const props = (overrides: Partial<{ selectedType: ReportKey }> & Record<string, unknown> = {}) => ({
  currentTypeInfo: REPORT_TYPES[0],
  selectedType: 'all' as ReportKey,
  selectedDate: '2026-08-31',
  isCached: true,
  isGenerating: false,
  isLoggedIn: true,
  isAdmin: false,
  isSubscribing: false,
  isSendingEmail: false,
  emailSentMsg: '',
  rssSubscribed: false,
  emailSubscribed: false,
  userEmail: 'reader@example.com',
  isRssBusy: false,
  reportContent: 'briefing',
  autoScroll: false,
  ...overrides,
})

describe('ReportControlsPanel subscription status', () => {
  it('renders active RSS and account email statuses in the controls row', () => {
    const wrapper = mount(ReportControlsPanel, {
      props: props({ rssSubscribed: true, emailSubscribed: true }),
      global: { plugins: [i18n] },
    })

    expect(wrapper.text()).toContain('已订阅：RSS')
    expect(wrapper.text()).toContain('已订阅：reader@example.com')
    expect(wrapper.find('button[title="复制已订阅的 RSS 链接"]').exists()).toBe(true)
  })

  it('hides inactive statuses and emits when the RSS status is clicked', async () => {
    const wrapper = mount(ReportControlsPanel, {
      props: props(),
      global: { plugins: [i18n] },
    })

    expect(wrapper.text()).not.toContain('已订阅：RSS')
    expect(wrapper.text()).not.toContain('已订阅：reader@example.com')

    await wrapper.setProps({ rssSubscribed: true })
    await wrapper.find('button[title="复制已订阅的 RSS 链接"]').trigger('click')
    expect(wrapper.emitted('copySubscribedRss')).toHaveLength(1)
  })

  it('disables the RSS status while copying and keeps cached state independent', () => {
    const wrapper = mount(ReportControlsPanel, {
      props: props({ rssSubscribed: true, isRssBusy: true }),
      global: { plugins: [i18n] },
    })

    expect(wrapper.find('button[title="复制已订阅的 RSS 链接"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('已缓存')
  })
})
