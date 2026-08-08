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

/**
 * 作者头像：仅落库的 twimg 地址经同源代理返回——pbs.twimg.com 在中国大陆
 * 不可直连，浏览器直连会让看板头像整块挂掉；缺失或非白名单主机的地址一律
 * 返回 undefined，由渲染层回退本地 𝕏 占位。
 * 历史 unavatar.io 回退已移除：它是第三方 302 重定向服务，与媒体代理的
 * 禁止重定向策略不兼容（经代理只会 502），且自身在国内稳定性差。
 */
export const authorAvatarUrl = (doc: TopDoc): string | undefined => {
  const url = typeof doc.author_avatar_url === 'string' ? doc.author_avatar_url : ''
  return isTwimgUrl(url) ? proxiedMediaUrl(url) : undefined
}

/**
 * 卡片作者显示名：优先采集期落库的 X 账号昵称（author_name），
 * 旧推文无昵称时回退 @handle；URL 无法解析时为空串（渲染层兜底标签）。
 */
export const authorDisplayName = (doc: TopDoc): string => {
  const nickname = typeof doc.author_name === 'string' ? doc.author_name.trim() : ''
  if (nickname) return nickname
  const handle = extractXHandle(doc.url)
  return handle ? `@${handle}` : ''
}

export const tweetText = (doc: TopDoc): string => (
  doc.summary || doc.title || ''
)

/**
 * 正文按界面语言切换：zh 系界面语言优先展示采集期落库的 X 中文翻译
 * （translation_zh，来自 X 自带 translateTweet），其余语言或无译文回退原文。
 */
export const displayTweetText = (doc: TopDoc, locale: string): string => {
  const translation = typeof doc.translation_zh === 'string' ? doc.translation_zh.trim() : ''
  if (translation && locale.toLowerCase().startsWith('zh')) return translation
  return tweetText(doc)
}

export interface TweetTextSegment {
  text: string
  isUrl: boolean
}

const URL_IN_TEXT_RE = /https?:\/\/[^\s]+/g
// URL 匹配贪心吃掉句读时的回退字符集（不含括号/引号，避免误裁合法路径）
const URL_TRAILING_PUNCT_RE = /[.,;:!?，。！？、；：]+$/

/**
 * 正文分段渲染：URL 段独立锚点跳真实地址，文本段保持跳推文。
 * 整个文本块不再是单一锚点（嵌套 a 非法）， sibling 分段各自成链。
 */
export const tweetTextSegments = (doc: TopDoc, locale: string): TweetTextSegment[] =>
  splitTextSegments(displayTweetText(doc, locale))

const splitTextSegments = (text: string): TweetTextSegment[] => {
  const segments: TweetTextSegment[] = []
  let last = 0
  for (const match of text.matchAll(URL_IN_TEXT_RE)) {
    const raw = match[0]
    const index = match.index ?? 0
    // 句读回退：URL 后紧跟的中英文句读归还给文本段
    const trimmed = raw.replace(URL_TRAILING_PUNCT_RE, '')
    const urlEnd = index + trimmed.length
    if (index > last) segments.push({ text: text.slice(last, index), isUrl: false })
    if (trimmed) segments.push({ text: trimmed, isUrl: true })
    if (urlEnd < index + raw.length) segments.push({ text: text.slice(urlEnd, index + raw.length), isUrl: false })
    last = index + raw.length
  }
  if (last < text.length) segments.push({ text: text.slice(last), isUrl: false })
  // 合并相邻文本段（句读回退会制造碎片），得到最小分段列表
  const merged: TweetTextSegment[] = []
  for (const seg of segments) {
    if (!seg.text) continue
    const prev = merged[merged.length - 1]
    if (prev && !prev.isUrl && !seg.isUrl) prev.text += seg.text
    else merged.push({ ...seg })
  }
  return merged
}

export const hasMedia = (doc: TopDoc): boolean =>
  Array.isArray(doc.media) && doc.media.length > 0

/** 引用卡片存在性：要求至少 url +（正文或媒体），坏数据不渲染。 */
export const hasQuote = (doc: TopDoc): boolean => {
  const quote = doc.quote
  if (!quote || typeof quote.url !== 'string' || !quote.url) return false
  return Boolean(quote.text) || (Array.isArray(quote.media) && quote.media.length > 0)
}

/** 引用卡片的展示对象：仅经 hasQuote 判定后调用，坏数据回退 null。 */
export const tweetQuote = (doc: TopDoc): TopDoc['quote'] => (hasQuote(doc) ? (doc.quote ?? null) : null)

/**
 * 引用投影 → 详情浮层展示用 TopDoc：quote 落库字段与详情渲染所需字段
 * 一一对应（URL/昵称/头像/正文/媒体/时间），下钻纯本地切换零请求。
 * 不带 score（被引推文无本站互动分，渲染层隐藏徽章）与 quote（投影只
 * 存一层，不递归下钻——与 X 只渲染一层引用一致）。
 */
export const quoteAsDoc = (quote: NonNullable<TopDoc['quote']>): TopDoc => ({
  url: quote.url,
  author_name: quote.author_name,
  author_avatar_url: quote.author_avatar_url,
  summary: quote.text,
  media: quote.media,
  published_at: quote.published_at,
})

/** 引用作者头像：与外推同一策略——仅 twimg 落库地址经同源代理，其余回退占位。 */
export const quoteAvatarUrl = (quote: NonNullable<TopDoc['quote']>): string | undefined => {
  const url = typeof quote.author_avatar_url === 'string' ? quote.author_avatar_url : ''
  return isTwimgUrl(url) ? proxiedMediaUrl(url) : undefined
}

/**
 * 引用正文分段：复用正文同一 URL 正则做链接识别，但引用卡片整体已是
 * 锚点（跳被引推文），嵌套锚点非法——故引用正文只做纯文本分段输出，
 * 链接样式由渲染层以 span 呈现，点击仍跳被引推文（与 X 行为一致）。
 */
export const quoteTextSegments = (quote: NonNullable<TopDoc['quote']>): TweetTextSegment[] =>
  splitTextSegments(quote.text ?? '')

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

/** twimg 支持 ?name= 派生尺寸的图片路径前缀（推文照片与三类视频封面图）。 */
const TWIMG_VARIANT_PATH_RE = /^\/(?:media|ext_tw_video_thumb|amplify_video_thumb|tweet_video_thumb)\//

/**
 * twimg 图片尺寸变体：pbs.twimg.com 的 /media/ 照片与 *_video_thumb 封面
 * 支持 ?name= 派生尺寸（small = 680px 宽，约原图 1/5 体积）；看板内联缩略图
 * 用 small 降载，lightbox 仍取原图。已有 name 参数时覆盖；主机/路径不支持
 * 或 URL 非法时返回空串（调用方回退原图，不变体即 404 的路径绝不下发）。
 */
export const photoVariantUrl = (url: string, name: string): string => {
  try {
    const parsed = new URL(url)
    if (parsed.hostname !== 'pbs.twimg.com' || !TWIMG_VARIANT_PATH_RE.test(parsed.pathname)) return ''
    parsed.searchParams.set('name', name)
    return parsed.toString()
  } catch {
    return ''
  }
}

/**
 * 视频/GIF 封面优先级：采集期落库的 X 官方封面（poster_url，经代理同源化）
 * > 服务端抽帧端点（存量数据无 poster_url 时兜底，见 routes_x_media.py）。
 */
const resolvePosterUrl = (item: { url: string; poster_url?: string }): string => {
  if (item.poster_url) return proxiedMediaUrl(item.poster_url)
  return posterMediaUrl(item.url)
}

const proxyMediaList = (items: NonNullable<TopDoc['media']>): NonNullable<TopDoc['media']> =>
  items.map((item) => {
    // 看板降载：照片内联渲染用 small 变体（680px，约原图 1/5 体积），
    // item.url 保持原图供 lightbox 全尺寸预览；变体不可派生时不注入 thumb_url。
    const thumb = item.type === 'photo' ? photoVariantUrl(item.url, 'small') : ''
    // 视频官方封面只在播放前展示，同样降载为 small（原图无消费场景）；
    // 变体不可派生时回退原封面/抽帧端点。
    const posterThumb = item.type !== 'photo' && item.poster_url
      ? photoVariantUrl(item.poster_url, 'small')
      : ''
    return {
      ...item,
      url: proxiedMediaUrl(item.url),
      ...(thumb ? { thumb_url: proxiedMediaUrl(thumb) } : {}),
      ...(item.type === 'video' || item.type === 'animated_gif'
        ? { poster_url: posterThumb ? proxiedMediaUrl(posterThumb) : resolvePosterUrl(item) }
        : {}),
    }
  })

export const mediaItems = (doc: TopDoc): NonNullable<TopDoc['media']> =>
  proxyMediaList(doc.media ?? [])

/** 引用卡片媒体：与外推同一代理/封面规则。 */
export const quoteMediaItems = (quote: NonNullable<TopDoc['quote']>): NonNullable<TopDoc['media']> =>
  proxyMediaList(quote.media ?? [])

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
 * 发布时间格式化：落库 published_at 是带时区的 ISO（UTC），展示时换算成
 * 用户系统时区（不传 timeZone 时 Intl 默认本地时区）。输出保持旧版
 * 「YYYY-MM-DD HH:mm」形状；无法解析的输入返回空串由模板跳过渲染。
 */
export const formatLocalTime = (iso: string, timeZone?: string): string => {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  try {
    const parts = new Intl.DateTimeFormat('en-CA', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
      ...(timeZone ? { timeZone } : {}),
    }).formatToParts(date)
    const get = (type: string) => parts.find((part) => part.type === type)?.value ?? ''
    return `${get('year')}-${get('month')}-${get('day')} ${get('hour')}:${get('minute')}`
  } catch {
    return ''
  }
}

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

/** 全天推文客户端分页：页数下限 1（空列表也按 1 页算，避免 0 页状态）。 */
export const pageCount = (total: number, pageSize: number): number => {
  const size = Math.max(1, Math.floor(pageSize) || 1)
  return Math.max(1, Math.ceil(Math.max(0, total) / size))
}

/** 页码夹取到 [1, totalPages]；非法输入（NaN/Infinity/小数）先取整再夹。 */
export const clampPage = (page: number, totalPages: number): number => {
  const pages = Math.max(1, Math.floor(totalPages) || 1)
  const value = Number.isFinite(page) ? Math.floor(page) : 1
  return Math.min(pages, Math.max(1, value))
}

/** 取当前页切片；页码越界时内部先夹取，调用方无需预校验。 */
export const paginateItems = <T>(items: T[], page: number, pageSize: number): T[] => {
  const size = Math.max(1, Math.floor(pageSize) || 1)
  const current = clampPage(page, pageCount(items.length, size))
  return items.slice((current - 1) * size, current * size)
}
