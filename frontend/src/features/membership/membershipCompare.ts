// 会员页桌面对比表：一行一项权益，三档各占一格。这里只排行与格子，文案都在 i18n 的 membership.compare 下。

export type CompareTier = 'guest' | 'free' | 'member'

/** 对比表从左到右的档位顺序，越往右给得越多。 */
export const COMPARE_TIERS: readonly CompareTier[] = ['guest', 'free', 'member']

export type CompareRowKey = 'browse' | 'tracking' | 'digest' | 'website' | 'uiCopy' | 'quota' | 'briefing' | 'rss'

/**
 * 一格写什么：true 为含（只画 ✓），false 为不含（画 ✗）；
 * 字符串或数组为含，✓ 后面写出说明，取 membership.compare.cells 下的键，一个键一行。
 */
export type CompareCell = boolean | string | readonly string[]

export interface CompareRow {
  key: CompareRowKey
  cells: Readonly<Record<CompareTier, CompareCell>>
}

/**
 * 行序跟 vip 卡一致：先摆网页上就能用到的（追踪、个人简报、网页收藏、UI 灵感库复制），再摆接 AI 客户端才用得上的 MCP/API 额度，
 * 免费档另有的简报和 RSS 排在最后。
 */
export const COMPARE_ROWS: readonly CompareRow[] = [
  { key: 'browse', cells: { guest: true, free: true, member: true } },
  { key: 'tracking', cells: { guest: false, free: 'trackingFree', member: ['trackingMember', 'trackingMcp'] } },
  { key: 'digest', cells: { guest: false, free: true, member: ['digestMember', 'digestSurge', 'digestExport'] } },
  { key: 'website', cells: { guest: false, free: 'websiteFree', member: 'websiteMember' } },
  { key: 'uiCopy', cells: { guest: false, free: 'uiCopyFree', member: 'uiCopyMember' } },
  {
    key: 'quota',
    cells: {
      guest: ['quotaGuestDay', 'quotaGuestScope'],
      free: ['quotaFreeDay', 'quotaFreeMonth'],
      member: ['quotaMemberDay', 'quotaMemberMonth'],
    },
  },
  { key: 'briefing', cells: { guest: false, free: 'briefingAll', member: 'briefingAll' } },
  { key: 'rss', cells: { guest: false, free: 'rssAll', member: 'rssAll' } },
]

export interface CompareEntry {
  row: CompareRowKey
  included: boolean
  /** 说明文案的 i18n 键，一个键一行；只画 ✓ 或 ✗ 的格子为空。 */
  lines: readonly string[]
  /**
   * 左边一档也有这项，这一档给得更多（条数、次数更多，或多了说明里的功能）：说明文字划上荧光笔。
   * 左边一档没有的（✗ 到 ✓）不划，左边那格的 ✗ 已经把差别摆出来了。
   */
  upgrade: boolean
  /** 三档这一行完全一样：整行淡一点，让眼睛落在有差别的行上。 */
  same: boolean
}

const includes = (cell: CompareCell) => cell !== false
const linesOf = (cell: CompareCell): readonly string[] => (typeof cell === 'boolean' ? [] : typeof cell === 'string' ? [cell] : cell)
const sameCell = (a: CompareCell, b: CompareCell) => {
  const [left, right] = [linesOf(a), linesOf(b)]
  return includes(a) === includes(b) && left.length === right.length && left.every((line, index) => line === right[index])
}

/** 三档在这一行写的完全一样（目前只有「浏览」）。 */
export function sameAcrossTiers({ cells }: CompareRow): boolean {
  return COMPARE_TIERS.every((tier) => sameCell(cells[tier], cells.guest))
}

/** 一档在对比表里的那一列：按行序给出含不含、写什么，和左边一档比是不是给得更多。 */
export function compareColumn(tier: CompareTier, rows: readonly CompareRow[] = COMPARE_ROWS): CompareEntry[] {
  const left = COMPARE_TIERS[COMPARE_TIERS.indexOf(tier) - 1]
  return rows.map((row) => {
    const cell = row.cells[tier]
    const before = left ? row.cells[left] : false
    return {
      row: row.key,
      included: includes(cell),
      lines: [...linesOf(cell)],
      upgrade: includes(cell) && includes(before) && !sameCell(cell, before),
      same: sameAcrossTiers(row),
    }
  })
}
