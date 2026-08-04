import type { TopDoc } from '@/features/dashboard/dashboardViewModel'

export interface XBoardSection {
  /** 小写 handle；URL 无法解析时为 ''（渲染层兜底标签，数据不静默丢弃） */
  handle: string
  tweets: TopDoc[]
  maxScore: number
}

// D12：推文 URL 形如 https://x.com/{handle}/status/{id}；兼容 twitter.com 历史链接
export const X_HANDLE_URL_RE = /^(?:https?:\/\/)?(?:www\.)?(?:x|twitter)\.com\/([^/?\s]+)\/status\//

export const extractXHandle = (url?: string): string => {
  const handle = url?.match(X_HANDLE_URL_RE)?.[1] ?? ''
  return handle.toLowerCase()
}

export const tweetScore = (doc: TopDoc): number => {
  const value = Number(doc.raw_score ?? doc.score ?? 0)
  return Number.isFinite(value) ? value : 0
}

export const tweetTimestamp = (doc: TopDoc): string => (
  doc.published_at || doc.created_at || doc.published_date || ''
)

const sortTweets = (tweets: TopDoc[]): TopDoc[] => (
  [...tweets].sort((a, b) => (
    tweetScore(b) - tweetScore(a) || tweetTimestamp(b).localeCompare(tweetTimestamp(a))
  ))
)

/**
 * 按 handle 分组：区内按互动分降序（同分按时间新到旧），区间按组内最高分降序、
 * 同分按 handle 字典序；未识别 handle 的分组固定沉底。
 */
export const groupTweetsByHandle = (docs: TopDoc[]): XBoardSection[] => {
  const byHandle = new Map<string, TopDoc[]>()
  for (const doc of docs) {
    const handle = extractXHandle(doc.url)
    const list = byHandle.get(handle)
    if (list) list.push(doc)
    else byHandle.set(handle, [doc])
  }
  const sections: XBoardSection[] = [...byHandle.entries()].map(([handle, tweets]) => ({
    handle,
    tweets: sortTweets(tweets),
    maxScore: tweets.reduce((max, doc) => Math.max(max, tweetScore(doc)), 0),
  }))
  return sections.sort((a, b) => {
    if (!a.handle !== !b.handle) return a.handle ? -1 : 1
    return b.maxScore - a.maxScore || a.handle.localeCompare(b.handle)
  })
}

export const countTweets = (sections: XBoardSection[]): number => (
  sections.reduce((total, section) => total + section.tweets.length, 0)
)
