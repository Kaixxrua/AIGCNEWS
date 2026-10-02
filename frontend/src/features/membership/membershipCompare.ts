// 会员页桌面对比表：一行一项权益，三档各占一格。这里只排行与格子，文案都在 i18n 的 membership.compare 下。

export type CompareTier = 'guest' | 'free' | 'member'

export type CompareRowKey = 'browse' | 'tracking' | 'digest' | 'quota' | 'website' | 'briefing' | 'rss'

/**
 * 一格写什么：true 为含（只画 ✓），false 为不含（画 ✗）；
 * 字符串或数组为含，✓ 后面写出说明，取 membership.compare.cells 下的键，一个键一行。
 */
export type CompareCell = boolean | string | readonly string[]

export interface CompareRow {
  key: CompareRowKey
  cells: Readonly<Record<CompareTier, CompareCell>>
}

/** 行序沿用 vip 卡原来的顺序（追踪、个人简报、额度、网页收藏），免费档另有的简报和 RSS 排在后面。 */
export const COMPARE_ROWS: readonly CompareRow[] = [
  { key: 'browse', cells: { guest: true, free: true, member: true } },
  { key: 'tracking', cells: { guest: false, free: 'trackingFree', member: 'trackingMember' } },
  { key: 'digest', cells: { guest: false, free: true, member: 'digestMember' } },
  {
    key: 'quota',
    cells: {
      guest: ['quotaGuestDay', 'quotaGuestScope'],
      free: ['quotaFreeDay', 'quotaFreeMonth'],
      member: ['quotaMemberDay', 'quotaMemberMonth'],
    },
  },
  { key: 'website', cells: { guest: false, free: 'websiteFree', member: 'websiteMember' } },
  { key: 'briefing', cells: { guest: false, free: 'briefingAll', member: 'briefingAll' } },
  { key: 'rss', cells: { guest: false, free: 'rssAll', member: 'rssAll' } },
]

export interface CompareEntry {
  row: CompareRowKey
  included: boolean
  /** 说明文案的 i18n 键，一个键一行；只画 ✓ 或 ✗ 的格子为空。 */
  lines: readonly string[]
}

/** 一档在对比表里的那一列：按行序给出含不含、写什么。 */
export function compareColumn(tier: CompareTier, rows: readonly CompareRow[] = COMPARE_ROWS): CompareEntry[] {
  return rows.map(({ key, cells }) => {
    const cell = cells[tier]
    if (typeof cell === 'boolean') return { row: key, included: cell, lines: [] }
    return { row: key, included: true, lines: typeof cell === 'string' ? [cell] : [...cell] }
  })
}
