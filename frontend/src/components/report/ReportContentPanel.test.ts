import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ReportContentPanel from './ReportContentPanel.vue'
import { i18n } from '@/i18n'

const mountPanel = (props: Record<string, unknown> = {}) => mount(ReportContentPanel, {
  props: {
    reportContent: '',
    isGenerating: false,
    currentTypeLabel: '综合简报',
    autoScroll: true,
    renderMarkdown: (content: string) => `<p>${content}</p>`,
    ...props,
  },
  global: { plugins: [i18n] },
})

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date('2026-10-04T00:30:00Z'))
})

afterEach(() => {
  vi.useRealTimers()
})

describe('ReportContentPanel without a briefing', () => {
  it('only says it is loading while the briefing is on its way', () => {
    const wrapper = mountPanel()
    const status = wrapper.get('[role="status"]')

    expect(status.text()).toContain('正在载入简报…')
    expect(status.attributes('aria-busy')).toBe('true')
    expect(wrapper.text()).not.toContain('选择类型')
    expect(wrapper.find('button').exists()).toBe(false)
  })

  it('says today’s issue is not out yet', () => {
    const wrapper = mountPanel({ loadState: 'pending', issueDate: '2026-10-04' })

    expect(wrapper.text()).toContain('今天的综合简报还没发布')
    expect(wrapper.text()).toContain('简报每天早上 8 点多生成')
    expect(wrapper.get('[role="status"]').attributes('aria-busy')).toBeUndefined()
  })

  it('names the day that has no issue', () => {
    const wrapper = mountPanel({ loadState: 'missing', issueDate: '2026-10-01', currentTypeLabel: '学术报告' })

    expect(wrapper.text()).toContain('10月1日没有学术报告')
    expect(wrapper.text()).toContain('换个日期或分区看看')
  })

  it('offers a retry when the briefing failed to load', async () => {
    const wrapper = mountPanel({ loadState: 'failed', issueDate: '2026-10-04' })

    expect(wrapper.text()).toContain('简报没加载出来')
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
  })
})

describe('ReportContentPanel with an earlier issue', () => {
  it('explains above the briefing that today’s is not out yet', () => {
    const wrapper = mountPanel({ reportContent: 'yesterday', loadState: 'ready', issueDate: '2026-10-03', fallbackFrom: '2026-10-04' })

    expect(wrapper.get('.report-fallback-notice').text())
      .toBe('今天的综合简报还没发布（每天早上 8 点多更新），先看 10月3日 这一期。')
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('yesterday')
  })

  it('shows no notice for today’s issue', () => {
    const wrapper = mountPanel({ reportContent: 'today', loadState: 'ready', issueDate: '2026-10-04', fallbackFrom: '' })

    expect(wrapper.find('.report-fallback-notice').exists()).toBe(false)
  })
})
