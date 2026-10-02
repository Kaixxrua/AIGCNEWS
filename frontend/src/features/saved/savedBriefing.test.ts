import { describe, expect, it } from 'vitest'
import { briefingSaveId, isSavedBriefingItem, savedBriefingSheet, type SavedBriefingItem } from './savedBriefing'
import { broadsheetItemReadId, type BroadsheetBlock, type BroadsheetItem } from '@/features/report/reportBroadsheet'
import type { SavedEntry } from '@/composables/useSavedItems'

const item = (lead: string, extra: Partial<BroadsheetItem> = {}): BroadsheetItem =>
  ({ number: 3, lead, note: '', body: `${lead} 的正文`, source: '', ...extra })
const saved = (type: string, date: string, order: number, lead: string, extra?: Partial<BroadsheetItem>): SavedEntry<SavedBriefingItem> => {
  const piece = item(lead, extra)
  return { id: briefingSaveId(type, date, piece), at: 0, data: { type, date, section: '本期明星项目', order, item: piece } }
}
const itemsOf = (blocks: BroadsheetBlock[]) => (blocks[0] as Extract<BroadsheetBlock, { kind: 'items' }>).items

describe('briefingSaveId', () => {
  it('是哪一期加条目内容：同一条在两期里算两条', () => {
    const dots = item('dots')
    expect(briefingSaveId('github', '2026-10-01', dots)).toBe(`github/2026-10-01/${broadsheetItemReadId(dots)}`)
    expect(briefingSaveId('github', '2026-10-02', dots)).not.toBe(briefingSaveId('github', '2026-10-01', dots))
    expect(briefingSaveId('all', '2026-10-01', dots)).not.toBe(briefingSaveId('github', '2026-10-01', dots))
  })
})

describe('isSavedBriefingItem', () => {
  const good: SavedBriefingItem = { type: 'github', date: '2026-10-01', section: '', order: 0, item: item('dots') }

  it('认哪一期、原在哪一节、排第几与条目都齐全的', () => {
    expect(isSavedBriefingItem(good)).toBe(true)
    expect(isSavedBriefingItem({ ...good, item: item('', { number: null, body: '只有正文' }) })).toBe(true)
  })

  it.each([
    ['没有简报类型', { ...good, type: '' }],
    ['日期不是年月日', { ...good, date: '10/01/2026' }],
    ['没有节', { ...good, section: undefined }],
    ['没有先后', { ...good, order: '0' }],
    ['没有条目', { ...good, item: null }],
    ['条目缺出处', { ...good, item: { ...item('dots'), source: undefined } }],
    ['序号不是数', { ...good, item: { ...item('dots'), number: '1' } }],
    ['条目空空', { ...good, item: item('', { body: '' }) }],
    ['不是对象', 'github/2026-10-01'],
  ])('不认%s的', (_, data) => {
    expect(isSavedBriefingItem(data)).toBe(false)
  })
})

describe('savedBriefingSheet', () => {
  it('每期一节，新的一期在前、同一天按简报栏目先后；节里照条目在那一期里的先后，不带序号', () => {
    const entries = [
      saved('github', '2026-09-30', 7, 'B'),
      saved('github', '2026-10-01', 2, 'D'),
      saved('all', '2026-10-01', 5, 'C'),
      saved('github', '2026-09-30', 1, 'A'),
    ]
    const { sheet, entryOf } = savedBriefingSheet(entries, (type, date) => `${date} · ${type}`)

    expect(sheet.intro).toEqual([])
    expect(sheet.dateline).toBe('')
    expect(sheet.sections.map((section) => section.heading)).toEqual(['2026-10-01 · all', '2026-10-01 · github', '2026-09-30 · github'])
    expect(sheet.sections.map((section) => itemsOf(section.blocks).map((piece) => piece.lead))).toEqual([['C'], ['D'], ['A', 'B']])
    const pieces = sheet.sections.flatMap((section) => itemsOf(section.blocks))
    expect(pieces.every((piece) => piece.number === null)).toBe(true)
    expect(sheet.sections.every((section) => section.blocks.length === 1 && section.blocks[0]!.kind === 'items' && !section.blocks[0]!.ordered)).toBe(true)
    // 版面上每一条都对得回它那条收藏
    expect(pieces.map((piece) => entryOf.get(piece)?.data.item.lead)).toEqual(['C', 'D', 'A', 'B'])
    expect(entryOf.get(pieces[0]!)).toBe(entries[2])
  })

  it('节标题当文字转义，存在本机的条目 HTML 上版前再消毒一遍', () => {
    const entries = [saved('all', '2026-10-01', 0, '<img src="x" onerror="alert(1)">名称', {
      note: '（<b onclick="alert(1)">owner/repo</b>）',
      body: '正文<script>alert(1)</script><a href="javascript:void(0)">链接</a>',
      source: '<a href="https://example.com/post">来源</a>',
    })]
    const { sheet } = savedBriefingSheet(entries, () => '<b>2026-10-01</b> & 综合')
    expect(sheet.sections[0]!.heading).toBe('&#60;b&#62;2026-10-01&#60;/b&#62; &#38; 综合')

    const [piece] = itemsOf(sheet.sections[0]!.blocks)
    expect(piece!.lead).toContain('名称')
    expect(piece!.lead).not.toContain('onerror')
    expect(piece!.note).toBe('（<b>owner/repo</b>）')
    expect(piece!.body).not.toContain('<script')
    expect(piece!.body).not.toContain('javascript:')
    expect(piece!.body).toContain('链接')
    expect(piece!.source).toBe('<a href="https://example.com/post">来源</a>')
  })
})
