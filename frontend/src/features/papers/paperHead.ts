// 论文阅读页版头与「同一天的论文」的纯数据整理：接口原样给什么，这里就只整理成页面要显示的样子。

export type PaperBoard = 'daily' | 'weekly' | 'monthly'

export interface PaperBoardRank {
  board: PaperBoard
  rank: number
}

export interface SameDayPaper {
  id: string
  title: string
  upvotes: number | null
  rank: number
  current: boolean
}

interface PaperRankFields {
  source_channel?: string | null
  rank_in_period?: number | string | null
}

interface PaperScoreFields extends PaperRankFields {
  raw_score?: number | string | null
}

interface SameDaySource extends PaperScoreFields {
  id?: number | string | null
  title?: string | null
}

/** 作者列表超过这个数才折叠，折叠后只露前三位；正好四位时全列出来，省得「等 4 人」只藏一个名字。 */
export const AUTHORS_SHOWN = 3

const BOARD_CHANNEL = /^huggingface_(daily|weekly|monthly)_html$/

/** 作者在接口里是 JSON 字符串（'["Hao Li", "MeiJia Chen"]'），也兼容数组；读不出来的一律当作没有作者。 */
export function parsePaperAuthors(value: unknown): string[] {
  let list: unknown = value
  if (typeof value === 'string') {
    const text = value.trim()
    if (!text) return []
    if (!text.startsWith('[')) return [text]
    try {
      list = JSON.parse(text)
    } catch {
      return []
    }
  }
  if (!Array.isArray(list)) return []
  return list.map((name) => (typeof name === 'string' ? name.trim() : '')).filter(Boolean)
}

export function splitAuthors(authors: string[], shown = AUTHORS_SHOWN): { visible: string[]; hidden: string[] } {
  if (authors.length <= shown + 1) return { visible: authors, hidden: [] }
  return { visible: authors.slice(0, shown), hidden: authors.slice(shown) }
}

/** 论文最近一次上榜的榜单与名次（详情接口记的是最后抓到它的那张 Hugging Face 榜）。 */
export function paperBoardRank(paper: PaperRankFields): PaperBoardRank | null {
  const match = BOARD_CHANNEL.exec(paper.source_channel ?? '')
  const rank = Number(paper.rank_in_period)
  if (!match || !Number.isInteger(rank) || rank < 1) return null
  return { board: match[1] as PaperBoard, rank }
}

/** Hugging Face 点赞数只对 Hugging Face 榜单来的论文有意义；没有或为零时不显示。 */
export function paperUpvotes(paper: PaperScoreFields): number | null {
  if (!BOARD_CHANNEL.test(paper.source_channel ?? '')) return null
  const value = Number(paper.raw_score)
  return Number.isFinite(value) && value > 0 ? Math.round(value) : null
}

/** 论文发布那天（YYYY-MM-DD），也就是它所在那张日榜的日期。 */
export function paperDay(publishedDate: string | null | undefined): string | null {
  const day = (publishedDate ?? '').slice(0, 10)
  return /^\d{4}-\d{2}-\d{2}$/.test(day) ? day : null
}

/** 同一天日榜上的论文，名次按榜单顺序，当前这篇标出来。 */
export function sameDayEntries(items: SameDaySource[], currentId: string): SameDayPaper[] {
  return items.flatMap((item, index) => {
    const id = item.id == null ? '' : String(item.id)
    const title = (item.title ?? '').trim()
    if (!id || !title) return []
    return [{ id, title, upvotes: paperUpvotes(item), rank: index + 1, current: id === currentId }]
  })
}
