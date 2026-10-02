import { mount, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
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

// 每张都在 afterEach 卸掉：留着的会接着在 window 上接键
const mounted: VueWrapper[] = []
const mountSheet = (generating = false) => {
  const wrapper = mount(ReportBroadsheet, {
    props: { sheet, mode: 'lead', generating },
    global: { plugins: [i18n] },
  })
  mounted.push(wrapper)
  return wrapper
}
const itemsBlock = sheet.sections[0]!.blocks[0] as Extract<BroadsheetBlock, { kind: 'items' }>
const remember = (...ids: string[]) =>
  localStorage.setItem('read_marks_briefing', JSON.stringify(Object.fromEntries(ids.map((id) => [id, Math.floor(Date.now() / 60_000)]))))

afterEach(() => {
  for (const wrapper of mounted.splice(0)) if (!wrapper.vm.$.isUnmounted) wrapper.unmount()
  localStorage.clear()
  vi.restoreAllMocks()
})

describe('ReportBroadsheet', () => {
  it('sets an item source in its foot, beside where the toggle goes, and gives an item without one no foot', () => {
    const wrapper = mountSheet()

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

  it('walks its items with j and k, opens the source in a new tab on o, and lists the keys on ?', async () => {
    // jsdom 不排版：每条都算整条在视野里
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(
      { top: 10, bottom: 90, left: 0, right: 300, width: 300, height: 80, x: 0, y: 10, toJSON: () => ({}) } as DOMRect,
    )
    const wrapper = mountSheet()
    const press = async (key: string) => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))
      await nextTick()
    }
    const cursor = () => wrapper.findAll('.report-broadsheet__item').map((item) => item.classes('is-cursor'))

    await press('j')
    expect(cursor()).toEqual([true, false])
    await press('j')
    expect(cursor()).toEqual([false, true])
    await press('k')
    expect(cursor()).toEqual([true, false])

    // 出处在新标签页打开，简报留在这里；这条立刻变淡
    const opened = vi.spyOn(window, 'open').mockReturnValue(null)
    await press('o')
    expect(opened).toHaveBeenCalledWith('https://github.com/feder-cr/dots', '_blank', 'noopener')
    expect(wrapper.get('.report-broadsheet__item').classes()).toContain('is-read')

    await press('?')
    expect(document.body.querySelector('.list-keys-sheet')?.textContent).toContain('在新标签页打开出处')
  })

  it('keeps the keys off while the issue is still being written', async () => {
    const wrapper = mountSheet(true)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'j', bubbles: true, cancelable: true }))
    await nextTick()
    expect(wrapper.find('.report-broadsheet__item.is-cursor').exists()).toBe(false)
  })
})
