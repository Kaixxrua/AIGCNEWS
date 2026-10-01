import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ReportBroadsheet from './ReportBroadsheet.vue'
import { i18n } from '@/i18n'
import { renderMarkdown } from '@/composables/useLatexRenderer'
import { parseBroadsheet } from '@/features/report/reportBroadsheet'

const sheet = parseBroadsheet(renderMarkdown([
  '## 本期明星项目 `#github`',
  '',
  '1. **dots**（feder-cr/dots）：这是一个面向网页的开源 AI Agent。[来源](https://github.com/feder-cr/dots)',
  '2. **HowToLiveBetter**：这是按性价比排序的循证生活指南。',
].join('\n')))

describe('ReportBroadsheet', () => {
  it('sets an item source in its foot, beside where the toggle goes, and gives an item without one no foot', () => {
    const wrapper = mount(ReportBroadsheet, {
      props: { sheet, mode: 'lead', generating: false },
      global: { plugins: [i18n] },
    })

    const [dots, guide] = wrapper.findAll('.report-broadsheet__item')
    expect(dots!.find('.report-broadsheet__body').text()).toBe('这是一个面向网页的开源 AI Agent。')
    const source = dots!.find('.report-broadsheet__foot .report-broadsheet__source a')
    expect(source.attributes('href')).toBe('https://github.com/feder-cr/dots')
    expect(source.text()).toBe('来源')
    // jsdom 不排版，量不出溢出：没有「展开全文」，只有出处。
    expect(dots!.find('.report-broadsheet__toggle').exists()).toBe(false)
    expect(guide!.find('.report-broadsheet__foot').exists()).toBe(false)
  })
})
