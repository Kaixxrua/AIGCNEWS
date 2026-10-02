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

describe('ReportControlsPanel saved tab', () => {
  it('桌面给了收藏数就有「收藏」签，没收过也在（是 0），带着条数，点了要进收藏', async () => {
    const wrapper = mount(ReportControlsPanel, {
      props: props(),
      global: { plugins: [i18n] },
    })
    expect(wrapper.find('.report-saved-tab').exists()).toBe(false)
    await wrapper.setProps({ savedCount: 0 })
    expect(wrapper.get('.report-saved-tab .report-saved-tab__count').text()).toBe('0')

    await wrapper.setProps({ savedCount: 3 })
    const tab = wrapper.get('.report-saved-tab')
    expect(tab.text()).toContain('收藏')
    expect(tab.get('.report-saved-tab__count').text()).toBe('3')
    expect(tab.attributes('aria-pressed')).toBe('false')
    expect(tab.classes()).not.toContain('tab-active')
    await tab.trigger('click')
    expect(wrapper.emitted('update:savedView')).toEqual([[true]])
  })

  it('在收藏里：标题换成收藏、只有收藏签亮着，缓存、发送与生成都收起；收空了是 0', async () => {
    const wrapper = mount(ReportControlsPanel, {
      props: props({ isAdmin: true, savedCount: 2, savedView: true }),
      global: { plugins: [i18n] },
    })
    expect(wrapper.get('.report-controls__title').text()).toBe('收藏')
    expect(wrapper.text()).toContain('2 条 · 只存在这个浏览器里')
    expect(wrapper.findAll('.report-controls__tabs .tab-active')).toHaveLength(1)
    expect(wrapper.get('.report-saved-tab').classes()).toContain('tab-active')
    expect(wrapper.get('.report-saved-tab').attributes('aria-pressed')).toBe('true')
    expect(wrapper.text()).not.toContain('已缓存')
    expect(wrapper.text()).not.toContain('发送简报')
    expect(wrapper.text()).not.toContain('重新生成')

    await wrapper.setProps({ savedCount: 0 })
    expect(wrapper.get('.report-saved-tab__count').text()).toBe('0')
  })
})
