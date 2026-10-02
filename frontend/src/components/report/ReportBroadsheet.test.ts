import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import ReportBroadsheet from './ReportBroadsheet.vue'
import { i18n } from '@/i18n'
import { renderMarkdown } from '@/composables/useLatexRenderer'
import { broadsheetItemReadId, parseBroadsheet, type BroadsheetBlock } from '@/features/report/reportBroadsheet'

const sheet = parseBroadsheet(renderMarkdown([
  '## 本期明星项目 `#github`',
  '',
  '1. **dots**（feder-cr/dots）：这是一个面向网页的开源 AI Agent。[来源](https://github.com/feder-cr/dots)',
  '2. **HowToLiveBetter**：这是按性价比排序的循证生活指南。',
].join('\n')))

const mountSheet = (generating = false) => mount(ReportBroadsheet, {
  props: { sheet, mode: 'lead', generating },
  global: { plugins: [i18n] },
})
const itemsBlock = sheet.sections[0]!.blocks[0] as Extract<BroadsheetBlock, { kind: 'items' }>
const remember = (...ids: string[]) =>
  localStorage.setItem('read_marks_briefing', JSON.stringify(Object.fromEntries(ids.map((id) => [id, Math.floor(Date.now() / 60_000)]))))

afterEach(() => localStorage.clear())

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

  it('dims the items read on an earlier visit, but not while the issue is still being written', () => {
    remember(broadsheetItemReadId(itemsBlock.items[1]!))
    const [dots, guide] = mountSheet().findAll('.report-broadsheet__item')
    expect(dots!.classes()).not.toContain('is-read')
    expect(guide!.classes()).toContain('is-read')

    const [, writing] = mountSheet(true).findAll('.report-broadsheet__item')
    expect(writing!.classes()).not.toContain('is-read')
  })

  it('dims an item at once when one of its links is followed, and remembers it', async () => {
    const first = mountSheet()
    const source = first.find('.report-broadsheet__source a')
    source.element.addEventListener('click', (event) => event.preventDefault())
    await source.trigger('click')
    const [dots, guide] = first.findAll('.report-broadsheet__item')
    expect(dots!.classes()).toContain('is-read')
    expect(guide!.classes()).not.toContain('is-read')
    first.unmount()

    const [again] = mountSheet().findAll('.report-broadsheet__item')
    expect(again!.classes()).toContain('is-read')
  })
})
