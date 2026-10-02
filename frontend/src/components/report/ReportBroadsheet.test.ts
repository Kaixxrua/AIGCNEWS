import { mount, type VueWrapper } from '@vue/test-utils'
import { nextTick, reactive, ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ReportBroadsheet, { type BroadsheetSaves } from './ReportBroadsheet.vue'
import { i18n } from '@/i18n'
import { renderMarkdown } from '@/composables/useLatexRenderer'
import { useReportPeek } from '@/composables/useReportPeek'
import { broadsheetItemReadId, parseBroadsheet, type BroadsheetBlock, type BroadsheetItem } from '@/features/report/reportBroadsheet'
import type { PaperItem } from '@/services/papers/paperApi'

const sheet = parseBroadsheet(renderMarkdown([
  '## 本期明星项目 `#github`',
  '',
  '1. **dots**（feder-cr/dots）：这是一个面向网页的开源 AI Agent。[来源](https://github.com/feder-cr/dots)',
  '2. **HowToLiveBetter**：这是按性价比排序的循证生活指南。',
].join('\n')))

// 每张都在 afterEach 卸掉：留着的会接着在 window 上接键
const mounted: VueWrapper[] = []
const mountSheet = (generating = false, extra: { saves?: BroadsheetSaves; dimRead?: boolean } = {}) => {
  const wrapper = mount(ReportBroadsheet, {
    props: { sheet, mode: 'lead', generating, ...extra },
    global: { plugins: [i18n] },
  })
  mounted.push(wrapper)
  return wrapper
}
const itemsBlock = sheet.sections[0]!.blocks[0] as Extract<BroadsheetBlock, { kind: 'items' }>
const remember = (...ids: string[]) =>
  localStorage.setItem('read_marks_briefing', JSON.stringify(Object.fromEntries(ids.map((id) => [id, Math.floor(Date.now() / 60_000)]))))
// 收藏：一份记着收下了哪几条的假收藏
const fakeSaves = () => {
  const items = reactive(new Set<BroadsheetItem>())
  const toggle = vi.fn((item: BroadsheetItem) => {
    if (!items.delete(item)) items.add(item)
  })
  return { items, saves: { has: (item: BroadsheetItem) => items.has(item), toggle } satisfies BroadsheetSaves }
}
const press = async (key: string) => {
  const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true })
  window.dispatchEvent(event)
  await nextTick()
  return event
}
// jsdom 不排版：每条都算整条在视野里
const everyItemInView = () => vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(
  { top: 10, bottom: 90, left: 0, right: 300, width: 300, height: 80, x: 0, y: 10, toJSON: () => ({}) } as DOMRect,
)

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

  it('leads every item foot with a bookmark when it can save, and saves with the item place on a click or on s', async () => {
    everyItemInView()
    const { items, saves } = fakeSaves()
    const wrapper = mountSheet(false, { saves })
    const [dots, guide] = wrapper.findAll('.report-broadsheet__item')
    // 没有出处的那条也有底行，只放书签
    expect(dots!.get('.report-broadsheet__foot > :first-child').classes()).toContain('report-broadsheet__save')
    expect(guide!.get('.report-broadsheet__foot').element.children).toHaveLength(1)

    await dots!.get('.report-broadsheet__save').trigger('click')
    expect(saves.toggle).toHaveBeenLastCalledWith(itemsBlock.items[0], { section: sheet.sections[0]!.heading, order: 0 })
    expect(dots!.get('.report-broadsheet__save').attributes('aria-pressed')).toBe('true')
    expect(dots!.get('.report-broadsheet__save').classes()).toContain('is-saved')
    // 点书签不会展开条目
    expect(dots!.classes()).not.toContain('is-open')

    await press('j')
    await press('j')
    expect(guide!.classes()).toContain('is-cursor')
    expect((await press('s')).defaultPrevented).toBe(true)
    expect(saves.toggle).toHaveBeenLastCalledWith(itemsBlock.items[1], { section: sheet.sections[0]!.heading, order: 1 })
    expect(items.size).toBe(2)
    expect(guide!.get('.report-broadsheet__save').attributes('aria-pressed')).toBe('true')
    await press('s')
    expect(guide!.get('.report-broadsheet__save').attributes('aria-pressed')).toBe('false')

    await press('?')
    expect(document.body.querySelector('.list-keys-sheet')?.textContent).toContain('收藏或取消收藏')
  })

  it('has no bookmark without saves or while the issue is still being written, and leaves s alone without saves', async () => {
    everyItemInView()
    const { saves } = fakeSaves()
    expect(mountSheet(true, { saves }).find('.report-broadsheet__save').exists()).toBe(false)

    const plain = mountSheet()
    expect(plain.find('.report-broadsheet__save').exists()).toBe(false)
    await press('j')
    expect(plain.get('.report-broadsheet__item').classes()).toContain('is-cursor')
    expect((await press('s')).defaultPrevented).toBe(false)
    await press('?')
    expect(document.body.querySelector('.list-keys-sheet')?.textContent).not.toContain('收藏或取消收藏')
  })

  it('neither dims nor records read items with dimRead off (the saved view)', async () => {
    remember(broadsheetItemReadId(itemsBlock.items[1]!))
    const saved = mountSheet(false, { dimRead: false })
    expect(saved.findAll('.report-broadsheet__item.is-read')).toHaveLength(0)
    const source = saved.find('.report-broadsheet__source a')
    source.element.addEventListener('click', (event) => event.preventDefault())
    await source.trigger('click')
    expect(saved.findAll('.report-broadsheet__item.is-read')).toHaveLength(0)
    saved.unmount()

    const [dots, guide] = mountSheet().findAll('.report-broadsheet__item')
    expect(dots!.classes()).not.toContain('is-read')
    expect(guide!.classes()).toContain('is-read')
  })

  it('keeps the keys off while the issue is still being written', async () => {
    const wrapper = mountSheet(true)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'j', bubbles: true, cancelable: true }))
    await nextTick()
    expect(wrapper.find('.report-broadsheet__item.is-cursor').exists()).toBe(false)
  })
})

// 宽屏的论文详情栏：第一条讲两篇、第二条没讲论文、第三条讲一篇
const paperSheet = parseBroadsheet(renderMarkdown([
  '## 本期研究热点 `#arxiv`',
  '',
  '1. **Raven 与 Omni-IO Skills**：都给智能体加了一层任务分解。[Raven来源](https://hf-mirror.com/papers/2609.33439) [Omni-IO Skills来源](https://hf-mirror.com/papers/2609.31847)',
  '2. **综述**：没有论文，只有[项目主页](https://github.com/acme/agent)。',
  '3. **MaLiang-Harness**：补上可执行程序违背用户意图的缺口。[论文来源](https://hf-mirror.com/papers/2609.34309)',
].join('\n')))
const mountWithPeek = (generating = false) => {
  const peek = useReportPeek({
    available: ref(true),
    load: async (arxivId): Promise<PaperItem> => ({ id: `doc-${arxivId}`, source: 'arxiv', title: `Paper ${arxivId}`, arxiv_id: arxivId }),
  })
  const wrapper = mount(ReportBroadsheet, {
    props: { sheet: paperSheet, mode: 'lead', generating, peek: peek.broadsheet },
    global: { plugins: [i18n] },
  })
  mounted.push(wrapper)
  const items = wrapper.findAll('.report-broadsheet__item')
  return { wrapper, peek, items, keys: items.map((item) => item.attributes('data-list-key')!) }
}

describe('ReportBroadsheet with the paper pane', () => {
  it('opens a paper an item cites in the pane on a click on its headline or a paper link, and leaves other clicks alone', async () => {
    const { wrapper, peek, items, keys } = mountWithPeek()
    expect(items.map((item) => item.classes('is-peekable'))).toEqual([true, false, true])
    expect(peek.entries.value.map((entry) => entry.key)).toEqual([keys[0], keys[2]])

    await items[0]!.get('.report-broadsheet__lead').trigger('click')
    expect(peek.target.value).toEqual({ key: keys[0], arxivId: '2609.33439' })
    expect(items.map((item) => item.classes('is-peeked'))).toEqual([true, false, false])

    // 点论文链接：不离开简报，在右侧看这一篇；别的链接、带修饰键的点击照常
    const prevented: boolean[] = []
    wrapper.element.addEventListener('click', (event: Event) => {
      prevented.push(event.defaultPrevented)
      event.preventDefault()
    })
    await items[0]!.get('a[href="https://hf-mirror.com/papers/2609.31847"]').trigger('click')
    expect(peek.target.value).toEqual({ key: keys[0], arxivId: '2609.31847' })
    await items[2]!.get('a').trigger('click')
    expect(peek.target.value).toEqual({ key: keys[2], arxivId: '2609.34309' })
    expect(items.map((item) => item.classes('is-peeked'))).toEqual([false, false, true])
    await items[1]!.get('a').trigger('click')
    await items[0]!.get('a').trigger('click', { metaKey: true })
    expect(prevented).toEqual([true, true, false, false])
    expect(peek.target.value?.key).toBe(keys[2])
  })

  it('opens the pane on o and the paper on a second o, walks only items that cite a paper while it is open, and closes it on Esc first', async () => {
    everyItemInView()
    const opened = vi.spyOn(window, 'open').mockReturnValue(null)
    const { peek, items, keys } = mountWithPeek()
    const cursor = () => items.map((item) => item.classes('is-cursor'))

    await press('j')
    await press('o')
    expect(peek.target.value).toEqual({ key: keys[0], arxivId: '2609.33439' })
    expect(opened).not.toHaveBeenCalled()
    await press('o')
    expect(opened).toHaveBeenCalledWith('https://hf-mirror.com/papers/2609.33439', '_blank', 'noopener')

    // 开着时 j / k 跳过没讲论文的那条，右侧跟着换
    await press('j')
    expect(cursor()).toEqual([false, false, true])
    expect(peek.target.value).toEqual({ key: keys[2], arxivId: '2609.34309' })
    await press('k')
    expect(peek.target.value).toEqual({ key: keys[0], arxivId: '2609.33439' })

    await press('Escape')
    expect(peek.target.value).toBeNull()
    expect(cursor()).toEqual([true, false, false])
    await press('Escape')
    expect(cursor()).toEqual([false, false, false])

    // 收起后照常走每一条
    await press('j')
    await press('j')
    expect(cursor()).toEqual([false, true, false])

    await press('?')
    expect(document.body.querySelector('.list-keys-sheet')?.textContent).toContain('在右侧看论文详情，再按一次打开出处')
  })

  it('offers nothing while the issue is still being written, and hands its items back when it goes', async () => {
    const writing = mountWithPeek(true)
    expect(writing.peek.entries.value).toEqual([])
    expect(writing.wrapper.find('.report-broadsheet__item.is-peekable').exists()).toBe(false)
    await writing.items[0]!.get('.report-broadsheet__lead').trigger('click')
    expect(writing.peek.target.value).toBeNull()

    const { wrapper, peek } = mountWithPeek()
    expect(peek.entries.value).toHaveLength(2)
    wrapper.unmount()
    expect(peek.entries.value).toEqual([])
  })
})
