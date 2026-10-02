// 本机收藏的简报条目：收下时连同哪一期、原在哪一节、在那一期里排第几一起存下；看收藏时按期排成一份大报，
// 交给 ReportBroadsheet 照原样排版。存在本机的 HTML 拿出来上版前再消毒一遍。
import { sanitizeRenderedMarkdown } from '@/composables/useLatexRenderer'
import { broadsheetItemReadId, type Broadsheet, type BroadsheetItem } from '@/features/report/reportBroadsheet'
import { REPORT_TYPES } from '@/features/report/reportViewModel'
import type { SavedEntry } from '@/composables/useSavedItems'

export interface SavedBriefingItem {
  /** 哪一期：简报类型（all、arxiv…）与日期（YYYY-MM-DD）。 */
  type: string
  date: string
  /** 原在哪一节：h2 的内部 HTML；刊头导语里的条目为空串。 */
  section: string
  /** 在那一期里排第几（按版面顺序）：同一期收了几条时照原来的先后排。 */
  order: number
  item: BroadsheetItem
}

/** 一条简报条目的收藏标识：哪一期加条目内容。同一条在不同的两期里算两条。 */
export const briefingSaveId = (type: string, date: string, item: Pick<BroadsheetItem, 'lead' | 'note' | 'body'>): string =>
  `${type}/${date}/${broadsheetItemReadId(item)}`

const isText = (value: unknown): value is string => typeof value === 'string'

export function isSavedBriefingItem(data: unknown): data is SavedBriefingItem {
  if (!data || typeof data !== 'object') return false
  const { type, date, section, order, item } = data as Partial<SavedBriefingItem>
  if (!isText(type) || !type || !isText(date) || !/^\d{4}-\d{2}-\d{2}$/.test(date) || !isText(section) || typeof order !== 'number') return false
  if (!item || typeof item !== 'object') return false
  const { number, lead, note, body, source } = item as Partial<BroadsheetItem>
  return (number === null || typeof number === 'number') && isText(lead) && isText(note) && isText(body) && isText(source)
    && Boolean(lead || body)
}

// 条目不带序号：跨了节、隔了条，原来的序号接不上。
const clean = (item: BroadsheetItem): BroadsheetItem => ({
  number: null,
  lead: sanitizeRenderedMarkdown(item.lead),
  note: sanitizeRenderedMarkdown(item.note),
  body: sanitizeRenderedMarkdown(item.body),
  source: sanitizeRenderedMarkdown(item.source),
})

const escapeHtml = (text: string) => text.replace(/[&<>"']/g, (char) => `&#${char.charCodeAt(0)};`)

export interface SavedBriefingSheet {
  sheet: Broadsheet
  /** 版面上每一条对应的那条收藏。 */
  entryOf: ReadonlyMap<BroadsheetItem, SavedEntry<SavedBriefingItem>>
}

const typeRank = (type: string) => {
  const rank = REPORT_TYPES.findIndex((report) => report.key === type)
  return rank < 0 ? REPORT_TYPES.length : rank
}

/** 收藏的条目排成一份大报：每期一节，新的一期在前，同一天的按简报栏目的先后；节标题是「日期 · 简报名」，节里照条目在那一期里的先后。 */
export function savedBriefingSheet(
  entries: readonly SavedEntry<SavedBriefingItem>[],
  issueTitle: (type: string, date: string) => string,
): SavedBriefingSheet {
  const issues = new Map<string, SavedEntry<SavedBriefingItem>[]>()
  for (const entry of entries) {
    const key = `${entry.data.date}/${entry.data.type}`
    const issue = issues.get(key)
    if (issue) issue.push(entry)
    else issues.set(key, [entry])
  }
  const entryOf = new Map<BroadsheetItem, SavedEntry<SavedBriefingItem>>()
  const sections = [...issues.values()]
    .map((issue) => ({ ...issue[0]!.data, issue }))
    .sort((a, b) => (a.date === b.date ? typeRank(a.type) - typeRank(b.type) : a.date < b.date ? 1 : -1))
    .map(({ type, date, issue }) => {
      const items = [...issue]
        .sort((a, b) => a.data.order - b.data.order)
        .map((entry) => {
          const item = clean(entry.data.item)
          entryOf.set(item, entry)
          return item
        })
      return { heading: escapeHtml(issueTitle(type, date)), blocks: [{ kind: 'items' as const, ordered: false, items }] }
    })
  return { sheet: { intro: [], sections, dateline: '' }, entryOf }
}
