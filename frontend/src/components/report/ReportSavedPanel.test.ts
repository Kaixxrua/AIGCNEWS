import { mount, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ReportSavedPanel from './ReportSavedPanel.vue'
import { i18n } from '@/i18n'
import { forgetSavedItems, type SavedEntry } from '@/composables/useSavedItems'
import { briefingSaveId, type SavedBriefingItem } from '@/features/saved/savedBriefing'
import { broadsheetItemReadId, type BroadsheetItem } from '@/features/report/reportBroadsheet'

vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))

const item = (lead: string): BroadsheetItem =>
  ({ number: 2, lead, note: '', body: `${lead} 的正文`, source: '<a href="https://example.com/post">来源</a>' })
const entry = (type: string, date: string, order: number, lead: string, at: number): SavedEntry<SavedBriefingItem> => {
  const piece = item(lead)
  return { id: briefingSaveId(type, date, piece), at, data: { type, date, section: '本期明星项目', order, item: piece } }
}
const seed = (...entries: SavedEntry<SavedBriefingItem>[]) => localStorage.setItem('saved_items_briefing', JSON.stringify(entries))
const stored = () => (JSON.parse(localStorage.getItem('saved_items_briefing') ?? '[]') as SavedEntry<SavedBriefingItem>[]).map((saved) => saved.data.item.lead)

// 每张都在 afterEach 卸掉：留着的会接着在 window 上接键
const mounted: VueWrapper[] = []
const mountPanel = () => {
  const wrapper = mount(ReportSavedPanel, { props: { mode: 'lead' }, global: { plugins: [i18n] } })
  mounted.push(wrapper)
  return wrapper
}
const leads = (wrapper: VueWrapper) => wrapper.findAll('.report-broadsheet__lead').map((lead) => lead.text())

beforeEach(() => {
  localStorage.clear()
  forgetSavedItems()
})
afterEach(() => {
  for (const wrapper of mounted.splice(0)) if (!wrapper.vm.$.isUnmounted) wrapper.unmount()
  vi.restoreAllMocks()
})

describe('ReportSavedPanel', () => {
  it('没收过时说怎么收', () => {
    const wrapper = mountPanel()
    expect(wrapper.find('.report-broadsheet').exists()).toBe(false)
    expect(wrapper.text()).toContain('还没有收藏')
    expect(wrapper.text()).toContain('按 s 收藏')
  })

  it('每期一节，节标题是日期加简报名；条目照那一期里的先后，看过的也不淡', () => {
    const older = entry('github', '2026-09-30', 4, 'dots', 1)
    seed(entry('all', '2026-10-01', 0, 'HowToLiveBetter', 3), entry('github', '2026-09-30', 1, 'openclaw', 2), older)
    localStorage.setItem('read_marks_briefing', JSON.stringify({ [broadsheetItemReadId(older.data.item)]: Math.floor(Date.now() / 60_000) }))
    const wrapper = mountPanel()

    expect(wrapper.findAll('.report-broadsheet h2').map((heading) => heading.text())).toEqual(['2026-10-01 · 综合简报', '2026-09-30 · 工程报告'])
    expect(leads(wrapper)).toEqual(['HowToLiveBetter', 'openclaw', 'dots'])
    expect(wrapper.findAll('.report-broadsheet__save').every((save) => save.attributes('aria-pressed') === 'true')).toBe(true)
    expect(wrapper.find('.report-broadsheet .is-read').exists()).toBe(false)
  })

  it('在这里取消的那条留在版面上、书签变空，再点收回来；重新进来才撤下', async () => {
    seed(entry('all', '2026-10-01', 0, 'HowToLiveBetter', 2), entry('github', '2026-09-30', 1, 'dots', 1))
    const wrapper = mountPanel()

    const dots = () => wrapper.findAll('.report-broadsheet__item')[1]!
    await dots().get('.report-broadsheet__save').trigger('click')
    await nextTick()
    expect(dots().get('.report-broadsheet__save').attributes('aria-pressed')).toBe('false')
    expect(leads(wrapper)).toEqual(['HowToLiveBetter', 'dots'])
    expect(stored()).toEqual(['HowToLiveBetter'])

    await dots().get('.report-broadsheet__save').trigger('click')
    await nextTick()
    expect(dots().get('.report-broadsheet__save').attributes('aria-pressed')).toBe('true')
    expect(stored()).toEqual(['dots', 'HowToLiveBetter'])

    await dots().get('.report-broadsheet__save').trigger('click')
    wrapper.unmount()
    expect(leads(mountPanel())).toEqual(['HowToLiveBetter'])
  })
})
