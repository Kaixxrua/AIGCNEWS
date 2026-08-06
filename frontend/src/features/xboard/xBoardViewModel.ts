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
  doc.published_at || doc.published_date || ''
)

export const authorAvatarUrl = (doc: TopDoc): string | undefined => {
  if (doc.author_avatar_url) return doc.author_avatar_url
  const handle = extractXHandle(doc.url)
  if (handle) return `https://unavatar.io/x/${handle}`
  return undefined
}

export const tweetText = (doc: TopDoc): string => (
  doc.summary || doc.title || ''
)

export const hasMedia = (doc: TopDoc): boolean =>
  Array.isArray(doc.media) && doc.media.length > 0

const X_MEDIA_PROXY_PATH = '/api/media/x/proxy'
const X_MEDIA_POSTER_PATH = '/api/media/x/poster'
const X_MEDIA_HOSTS = new Set(['pbs.twimg.com', 'video.twimg.com', 'abs.twimg.com'])

const isTwimgUrl = (url: string): boolean => {
  try {
    return X_MEDIA_HOSTS.has(new URL(url).hostname)
  } catch {
    return false
  }
}

/**
 * twimg CDN 在部分网络不可达（video.twimg.com 常被单独封锁，图片能加载
 * 但视频无法播放）；经服务端同源流式代理转发兜底。非 twimg 或非法 URL
 * 原样透传（后端代理另有主机白名单校验，此处只做渲染层改写）。
 */
export const proxiedMediaUrl = (url: string): string => {
  if (!isTwimgUrl(url)) return url
  return `${X_MEDIA_PROXY_PATH}?url=${encodeURIComponent(url)}`
}

/** 视频封面：服务端抽帧端点（仅 twimg 视频 URL 有意义，其余返回空串由模板兜底）。 */
export const posterMediaUrl = (url: string): string => {
  if (!isTwimgUrl(url)) return ''
  return `${X_MEDIA_POSTER_PATH}?url=${encodeURIComponent(url)}`
}

/**
 * 视频/GIF 封面优先级：采集期落库的 X 官方封面（poster_url，经代理同源化）
 * > 服务端抽帧端点（存量数据无 poster_url 时兜底，见 routes_x_media.py）。
 */
const resolvePosterUrl = (item: { url: string; poster_url?: string }): string => {
  if (item.poster_url) return proxiedMediaUrl(item.poster_url)
  return posterMediaUrl(item.url)
}

export const mediaItems = (doc: TopDoc): NonNullable<TopDoc['media']> =>
  (doc.media ?? []).map((item) => ({
    ...item,
    url: proxiedMediaUrl(item.url),
    ...(item.type === 'video' || item.type === 'animated_gif'
      ? { poster_url: resolvePosterUrl(item) }
      : {}),
  }))

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

/**
 * 把分组后的推文按分数/时间顺序摊平为单列表，供瀑布流直接渲染。
 * 顺序：先按 section 最高分降序，section 内再按推文分降序（与 groupTweetsByHandle 一致）。
 */
export const flattenTweets = (sections: XBoardSection[]): TopDoc[] => (
  sections.flatMap((section) => section.tweets)
)

export const countTweets = (sections: XBoardSection[]): number => (
  sections.reduce((total, section) => total + section.tweets.length, 0)
)

/**
 * 时间线排序：最新推文排最前（行主序瀑布流的数据源）。
 * 缺时间戳的条目沉底不丢弃；同一时刻按互动分降序。
 */
export const timelineTweets = (docs: TopDoc[]): TopDoc[] => (
  [...docs].sort((a, b) => {
    const ta = tweetTimestamp(a)
    const tb = tweetTimestamp(b)
    if (!ta !== !tb) return ta ? -1 : 1
    return tb.localeCompare(ta) || tweetScore(b) - tweetScore(a)
  })
)

/**
 * 行主序分列：第 i 条进第 i % columnCount 列——跨列横读仍是连续顺序，
 * 满足「左上 = 最新一条，从左到右、从上到下」。CSS columns 是列主序
 * （先填满一列再下一列），无法用纯 CSS 满足该排序，只能 JS 分列。
 */
export const distributeColumns = <T>(items: T[], columnCount: number): T[][] => {
  const count = Math.max(1, Math.floor(columnCount) || 1)
  const columns: T[][] = Array.from({ length: count }, () => [])
  items.forEach((item, index) => columns[index % count]?.push(item))
  return columns
}
