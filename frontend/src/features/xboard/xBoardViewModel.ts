import type { TopDoc } from '@/features/dashboard/dashboardViewModel'
import { pageHostname, X_MEDIA_IMG_PATH, xMediaOrigin } from '@/features/xboard/xMediaCdn'
import { distributeColumns, estimateTextLines } from '@/utils/masonry'
export { distributeColumns }

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

const tweetTimeMs = (doc: TopDoc): number => {
  const value = new Date(tweetTimestamp(doc)).getTime()
  return Number.isFinite(value) ? value : Number.NaN
}

const tweetId = (doc: TopDoc): string => (
  doc.url?.match(/\/status\/(\d+)(?:[/?#]|$)/)?.[1] ?? ''
)

/** 已读记录里的推文标识：推文编号；链接里没有编号的旧数据退回整条链接，再没有就用正文。 */
export const tweetReadId = (doc: TopDoc): string => tweetId(doc) || doc.url || doc.title || ''

/** 时间线比较器：新时间优先；非法时间沉底；同刻按 tweet ID 稳定降序。 */
export const compareTweetTimeDescending = (a: TopDoc, b: TopDoc): number => {
  const ta = tweetTimeMs(a)
  const tb = tweetTimeMs(b)
  const aValid = Number.isFinite(ta)
  const bValid = Number.isFinite(tb)
  if (aValid !== bValid) return aValid ? -1 : 1
  if (aValid && bValid && ta !== tb) return tb - ta

  const aId = tweetId(a)
  const bId = tweetId(b)
  if (aId && bId && aId !== bId) {
    try {
      const byNumericId = BigInt(bId) - BigInt(aId)
      if (byNumericId < 0n) return -1
      if (byNumericId > 0n) return 1
    } catch {
      // 非标准 ID 回退到字符串比较。
    }
    return bId.localeCompare(aId)
  }
  if (aId !== bId) return aId ? -1 : 1
  return tweetScore(b) - tweetScore(a)
}

/**
 * 作者头像：仅落库的 twimg 地址经同源代理返回——pbs.twimg.com 在中国大陆
 * 不可直连，浏览器直连会让看板头像整块挂掉；缺失或非白名单主机的地址一律
 * 返回 undefined，由渲染层回退本地 𝕏 占位。
 * 历史 unavatar.io 回退已移除：它是第三方 302 重定向服务，与媒体代理的
 * 禁止重定向策略不兼容（经代理只会 502），且自身在国内稳定性差。
 */
export const avatarVariantUrl = (value: string): string => {
  try {
    const url = new URL(value)
    if (url.hostname === 'pbs.twimg.com' && url.pathname.startsWith('/profile_images/')) {
      url.pathname = url.pathname.replace(/_(?:normal|bigger|mini)(\.[a-zA-Z0-9]+)$/, '_400x400$1')
      return url.href
    }
  } catch { /* Invalid URLs retain the existing placeholder behavior. */ }
  return value
}

export const authorAvatarUrl = (doc: TopDoc): string | undefined => {
  const url = typeof doc.author_avatar_url === 'string' ? doc.author_avatar_url : ''
  return isTwimgUrl(url) ? proxiedMediaUrl(avatarVariantUrl(url)) : undefined
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
 * 纯转贴的转贴者 handle：采集期落库 retweeted_by（parser 产出的 screen_name）。
 * 卡片顶部据此渲染「@xxx 转发了」行，原作者仍由 authorDisplayName 呈现——
 * 与 X 原生 UI（转发者一行在上、原作者在下）对齐。trim + 去前导 @ 归一；
 * 缺失/空白/非字符串返回空串，渲染层不渲染该行。
 */
export const retweetedByHandle = (doc: TopDoc): string => {
  const raw = typeof doc.retweeted_by === 'string' ? doc.retweeted_by.trim() : ''
  return raw.replace(/^@+/, '')
}

/**
 * 推文在关注筛选里的归属账号。纯转贴仍属于采集它的关注账号，而不是
 * 被转贴的原作者；普通推文则按 URL 中的作者 handle 归属。
 */
export const followedAccountHandle = (doc: TopDoc): string => (
  retweetedByHandle(doc).toLowerCase() || extractXHandle(doc.url)
)

/** 关注筛选优先显示 X 本人的昵称；转贴不能借用原作者的昵称。 */
export const followedAccountDisplayName = (doc: TopDoc): string => {
  const handle = followedAccountHandle(doc)
  if (!handle) return ''
  const nickname = typeof doc.author_name === 'string' ? doc.author_name.trim() : ''
  if (handle === extractXHandle(doc.url) && nickname) return nickname
  const configured = typeof doc.followed_account_name === 'string'
    ? doc.followed_account_name.trim()
    : ''
  if (configured) return configured
  if (handle === extractXHandle(doc.url)) {
    return authorDisplayName(doc) || `@${handle}`
  }
  return `@${handle}`
}

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
  /** 提及段：@handle → 渲染为 x.com/<handle> 锚点（wall）或高亮 span（quote 内） */
  isMention?: boolean
  /** isMention 时的 handle（不含 @），供锚点拼目标地址 */
  mentionHandle?: string
}

const URL_IN_TEXT_RE = /https?:\/\/[^\s]+/g
// URL 匹配贪心吃掉句读时的回退字符集（不含括号/引号，避免误裁合法路径）
const URL_TRAILING_PUNCT_RE = /[.,;:!?，。！？、；：]+$/
// @提及：handle 为 X 合法字符集；左边界排除字母数字/下划线防误吃邮箱前缀
const MENTION_IN_TEXT_RE = /(?<![A-Za-z0-9_])@([A-Za-z0-9_]+)/g

/** 紧凑排版（桌面推文墙）把正文里的空行并掉：段与段只换行不空一行，限行的那几行都留给字。 */
export const collapseBlankLines = (text: string): string => text.replace(/\n(?:[ \t]*\n)+/g, '\n')

/**
 * 正文分段渲染：URL 段独立锚点跳真实地址，文本段保持跳推文。
 * 整个文本块不再是单一锚点（嵌套 a 非法）， sibling 分段各自成链。
 * compact：紧凑排版，空行并掉（详情浮层照原样）。
 */
export const tweetTextSegments = (doc: TopDoc, locale: string, compact = false): TweetTextSegment[] => {
  const text = displayTweetText(doc, locale)
  return splitTextSegments(compact ? collapseBlankLines(text) : text)
}

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
  // 二次分段：纯文本段内识别 @提及（X 上可点跳主页）；URL 段已含 @ 的不动
  const out: TweetTextSegment[] = []
  for (const seg of merged) {
    if (seg.isUrl) {
      out.push(seg)
      continue
    }
    let cursor = 0
    for (const match of seg.text.matchAll(MENTION_IN_TEXT_RE)) {
      const index = match.index ?? 0
      if (index > cursor) out.push({ text: seg.text.slice(cursor, index), isUrl: false })
      out.push({ text: match[0], isUrl: false, isMention: true, mentionHandle: match[1] })
      cursor = index + match[0].length
    }
    if (cursor === 0) out.push(seg)
    else if (cursor < seg.text.length) out.push({ text: seg.text.slice(cursor), isUrl: false })
  }
  return out
}

export const hasMedia = (doc: TopDoc): boolean =>
  Array.isArray(doc.media) && doc.media.length > 0

/** 引用卡片存在性：要求至少 url +（正文或媒体），坏数据不渲染。 */
export const hasQuote = (doc: TopDoc): boolean => {
  const quote = doc.quote
  if (!quote || typeof quote.url !== 'string' || !quote.url) return false
  return Boolean(quote.text) || (Array.isArray(quote.media) && quote.media.length > 0)
}

/** 链接卡片存在性：要求至少 url + title（与采集期投影同口径），坏数据不渲染。 */
export const hasLinkCard = (doc: TopDoc): boolean => {
  const card = doc.link_card
  if (!card || typeof card.url !== 'string' || !card.url) return false
  return typeof card.title === 'string' && Boolean(card.title)
}

/** 链接卡片的展示对象：仅经 hasLinkCard 判定后调用，坏数据回退 null。 */
export const tweetLinkCard = (doc: TopDoc): TopDoc['link_card'] => (hasLinkCard(doc) ? (doc.link_card ?? null) : null)

/**
 * 链接卡片缩略图：仅落库的 twimg 镜像（pbs.twimg.com/card_img/）经同源
 * 代理返回——与头像同一策略，非 twimg 或缺失返回 undefined，由渲染层
 * 降级为纯文本卡。不走 photoVariantUrl：card_img 路径不支持 ?name=
 * 派生尺寸（变体请求会 404）。
 */
export const linkCardImageUrl = (card: NonNullable<TopDoc['link_card']>): string | undefined => {
  const url = typeof card.image_url === 'string' ? card.image_url : ''
  return isTwimgUrl(url) ? proxiedMediaUrl(url) : undefined
}

/** 引用卡片的展示对象：仅经 hasQuote 判定后调用，坏数据回退 null。 */
export const tweetQuote = (doc: TopDoc): TopDoc['quote'] => (hasQuote(doc) ? (doc.quote ?? null) : null)

/**
 * 引用投影 → 详情浮层展示用 TopDoc：quote 落库字段与详情渲染所需字段
 * 一一对应（URL/昵称/头像/正文/媒体/时间），下钻纯本地切换零请求。
 * 不带 score（被引推文无本站互动分，渲染层隐藏徽章）与 quote（投影只
 * 存一层，不递归下钻——与 X 只渲染一层引用一致）。translation_zh 一并
 * 投影：下钻详情复用 tweetTextSegments(doc, locale) 的中文切换。
 */
export const quoteAsDoc = (quote: NonNullable<TopDoc['quote']>): TopDoc => ({
  url: quote.url,
  author_name: quote.author_name,
  author_avatar_url: quote.author_avatar_url,
  summary: quote.text,
  media: quote.media,
  published_at: quote.published_at,
  translation_zh: quote.translation_zh,
})

/** 引用作者头像：与外推同一策略——仅 twimg 落库地址经同源代理，其余回退占位。 */
export const quoteAvatarUrl = (quote: NonNullable<TopDoc['quote']>): string | undefined => {
  const url = typeof quote.author_avatar_url === 'string' ? quote.author_avatar_url : ''
  return isTwimgUrl(url) ? proxiedMediaUrl(avatarVariantUrl(url)) : undefined
}

/**
 * 引用正文按界面语言切换：zh 系界面语言优先展示采集期落库的被引译文
 * （quote.translation_zh，与外推 translation_zh 同一 X translateTweet 来源），
 * 其余语言或无译文（含旧数据）回退被引原文。
 */
export const displayQuoteText = (quote: NonNullable<TopDoc['quote']>, locale: string): string => {
  const translation = typeof quote.translation_zh === 'string' ? quote.translation_zh.trim() : ''
  if (translation && locale.toLowerCase().startsWith('zh')) return translation
  return quote.text ?? ''
}

/**
 * 引用正文分段：复用正文同一 URL 正则做链接识别，但引用卡片整体已是
 * 锚点（跳被引推文），嵌套锚点非法——故引用正文只做纯文本分段输出，
 * 链接样式由渲染层以 span 呈现，点击仍跳被引推文（与 X 行为一致）。
 */
export const quoteTextSegments = (quote: NonNullable<TopDoc['quote']>, locale: string, compact = false): TweetTextSegment[] => {
  const text = displayQuoteText(quote, locale)
  return splitTextSegments(compact ? collapseBlankLines(text) : text)
}

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
 * 但视频无法播放）；经同源代理兜底。非 twimg 或非法 URL 原样透传（后端
 * 代理另有主机白名单校验，此处只做渲染层改写）。
 *
 * 路径式形态 /api/media/x/img/<host>/<path>?<query>（2026-08-10 起）：
 * 查询形态 ?url= 的目标地址是 percent-encoded，边缘 nginx 无法解码
 * （$arg_* 不解码、rewrite 不解变量、无 lua/njs），只能绕家里全链路
 * 回源（实测 MISS 6.6s/56KB）；路径段经 nginx 请求解析原生解码，白名单
 * 正则直接匹配主机字面量，边缘节点可直连 twimg（东京→twimg ~47ms），
 * 且路径以 .jpg/.mp4 结尾可被 CDN 按路径缓存（查询形态必回源）。
 * 后端 /media/x/img 端点与查询形态同一校验与转发。
 *
 * pbs.twimg.com 图片在主入口改走独立媒体域名（见 X_MEDIA_CDN_ORIGIN），
 * 路径与同源形态逐字节一致，边缘缓存与后端预热共用同一键。
 */
export const proxiedMediaUrl = (url: string): string => {
  if (!isTwimgUrl(url)) return url
  const parsed = new URL(url) // isTwimgUrl 已校验可解析
  const path = `${X_MEDIA_IMG_PATH}/${parsed.hostname}${parsed.pathname}${parsed.search}`
  return `${xMediaOrigin(parsed.hostname, pageHostname())}${path}`
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
 * 支持 ?name= 派生尺寸（约束框，长边缩到框内，见 TWIMG_BOX_VARIANTS）。
 * 已有 name 参数时覆盖；主机/路径不支持或 URL 非法时返回空串（调用方回退
 * 原图，不变体即 404 的路径绝不下发）。
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
 * twimg 具名尺寸是「长边约束框」而非宽度：small 把长边缩到 680，1316×4096
 * 的长图只剩 218px 宽，铺满卡片即糊。按 [框边长, name] 升序排列（实测
 * 900x900/4096x4096 同为约束框；4096 是 X 照片上限，等同 orig）。
 */
const TWIMG_BOX_VARIANTS: ReadonlyArray<readonly [number, string]> = [
  [680, 'small'],
  [900, '900x900'],
  [1200, 'medium'],
  [2048, 'large'],
  [4096, '4096x4096'],
]

/** 看板内联目标宽（small 对横图/方图的既有宽度，横图变体与缓存键保持不变）。 */
export const PHOTO_INLINE_TARGET_WIDTH = 680
/** lightbox 目标宽：横图取 large，长图取到原图宽。 */
export const PHOTO_LIGHTBOX_TARGET_WIDTH = 2048

/**
 * 选最小的约束框，使缩放后宽度 ≥ min(原宽, 目标宽)；尺寸缺失或非法时
 * 按目标宽取框（存量无宽高数据退回原口径）。算式与后端
 * x_media_urls.photo_box_variant_name 逐运算对齐，浮点结果一致。
 */
export const photoBoxVariantName = (targetWidth: number, width?: number, height?: number): string => {
  const valid = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n) && n > 0
  const needed = valid(width) && valid(height)
    ? Math.min(width, targetWidth) * Math.max(width, height) / width
    : targetWidth
  const hit = TWIMG_BOX_VARIANTS.find(([box]) => box >= needed) ?? TWIMG_BOX_VARIANTS[TWIMG_BOX_VARIANTS.length - 1]!
  return hit[1]
}

/** 长图：lightbox 按高度等比缩放会把宽压到不可读，改为限宽纵向滚动。 */
export const LONG_PHOTO_RATIO = 2.5
export const isLongPhoto = (item: { width?: number; height?: number }): boolean => (
  !!item.width && !!item.height && item.height / item.width >= LONG_PHOTO_RATIO
)

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
    // 看板降载：照片内联渲染按宽高选约束框（横图 small，长图升框保住 680px
    // 宽）；item.url 换成 lightbox 变体（横图 large、长图原图宽）——不带 name
    // 时 twimg 默认给 medium，长图同样糊。变体不可派生时不注入 thumb_url、url 保持原样。
    const isPhoto = item.type === 'photo'
    const thumb = isPhoto
      ? photoVariantUrl(item.url, photoBoxVariantName(PHOTO_INLINE_TARGET_WIDTH, item.width, item.height))
      : ''
    const full = isPhoto
      ? photoVariantUrl(item.url, photoBoxVariantName(PHOTO_LIGHTBOX_TARGET_WIDTH, item.width, item.height))
      : ''
    // 视频官方封面只在播放前展示，同样降载为 small（原图无消费场景）；
    // 变体不可派生时回退原封面/抽帧端点。
    const posterThumb = item.type !== 'photo' && item.poster_url
      ? photoVariantUrl(item.poster_url, 'small')
      : ''
    return {
      ...item,
      url: proxiedMediaUrl(full || item.url),
      ...(item.playback_url ? { playback_url: proxiedMediaUrl(item.playback_url) } : {}),
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
    tweetScore(b) - tweetScore(a) || compareTweetTimeDescending(a, b)
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
  [...docs].sort(compareTweetTimeDescending)
)

/**
 * keyset 多页合并：把 x/recent 续页拍平到同一时间线。
 * 按文档 id 去重（keyset 严格递减，正常不会重叠；重叠说明窗口在两次
 * 请求之间被新推文推挤，以先到的版本为准），再按时间线比较器统一排序。
 */
export const mergePagedTweets = (pages: TopDoc[][]): TopDoc[] => {
  const seen = new Set<string>()
  const merged: TopDoc[] = []
  for (const page of pages) {
    for (const doc of page) {
      const id = String(doc.id ?? doc.url ?? '')
      if (id && seen.has(id)) continue
      if (id) seen.add(id)
      merged.push(doc)
    }
  }
  return timelineTweets(merged)
}

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

type TweetMedia = NonNullable<TopDoc['media']>[number]

/** 单件媒体渲染高度：有落库尺寸按真实宽高比；视频占位缺省 16/9（与模板一致），照片按 4:3 估 */
const estimateMediaHeight = (item: TweetMedia, widthPx: number): number => {
  if (item.width && item.height && item.width > 0) return widthPx * (item.height / item.width)
  return widthPx * (item.type === 'photo' ? 0.75 : 9 / 16)
}

/** 紧凑排版的横排链接卡：缩略图占卡宽四成、最宽 144px，按分享图常见的 1.91:1（与 TweetLinkCard 的横排样式一致） */
const LINK_ROW_THUMB_SHARE = 0.4
const LINK_ROW_THUMB_MAX_PX = 144
const LINK_ROW_THUMB_RATIO = 1.91

/** 胶片里相邻两帧的间距：推文配图 8px（与媒体区 gap 一致），引用配图 6px */
export const TWEET_STRIP_GAP_PX = 8
export const QUOTE_STRIP_GAP_PX = 6

/**
 * 限高排版下一组媒体的高：单件按真实宽高比，高过上限就裁掉；多件排成一行等宽的方帧（胶片），
 * 帧宽撑不满上限时帧高随帧宽。
 */
const estimateCappedMediaHeight = (items: TweetMedia[], widthPx: number, maxPx: number, gapPx: number): number => {
  const [first] = items
  if (!first) return 0
  if (items.length === 1) return Math.min(maxPx, estimateMediaHeight(first, widthPx))
  return Math.min(maxPx, (widthPx - (items.length - 1) * gapPx) / items.length)
}

/**
 * 推文卡渲染高度估算（瀑布流分列用）：按模板结构逐项累加——头部行、
 * 正文折行（按字宽）、媒体真实宽高比、引用卡、链接卡、时间行。
 * 只需列间相对比较准确：媒体项用落库真实宽高比，是估高的主项。
 * 返回值已把列间距（16px）折进每卡，可直接累加比较。
 * 正文默认按 text-sm leading-5 折行；页面放大正文时（桌面漫画版）传入实际字号与行高。
 */
export interface TweetTextMetrics { fontSize: number; lineHeight: number }
const DEFAULT_TWEET_TEXT: TweetTextMetrics = { fontSize: 14, lineHeight: 20 }

/**
 * 桌面推文墙的紧凑排版（数值由漫画版 CSS 变量声明在主栏上，见 comic-pages.css）：正文与引用限行，
 * 配图限高、多图排成一行胶片；纯文字时收起配图、链接卡与引用配图。不传时按完整排版估高。
 */
export interface TweetCardLayout {
  /** 正文最多几行，其余点开看全文 */
  textClamp: number
  /** 配图限高（px）；链接卡在紧凑排版下横排，缩略图按自身比例缩在左边 */
  mediaMax: number
  /** 引用正文字号、行高与最多几行 */
  quoteSize: number
  quoteLine: number
  quoteClamp: number
  /** 引用配图限高（px） */
  quoteMediaMax: number
  /** 纯文字：不排配图、链接卡与引用配图 */
  textOnly: boolean
}

export const estimateTweetCardHeight = (
  doc: TopDoc, columnWidth: number, locale: string, text: TweetTextMetrics = DEFAULT_TWEET_TEXT,
  layout?: TweetCardLayout,
): number => {
  const cardWidth = Math.max(120, columnWidth)
  const bodyWidth = cardWidth - 34 // 卡边框 1px×2 + 正文块 px-4
  let height = 2 // 卡上下边框
  if (retweetedByHandle(doc)) height += 25 // 转贴标注行（pt-2.5 + 文字行）
  height += 48 // 卡头（py-3 + h-6 头像行）
  const media = doc.media ?? []
  if (media.length > 0 && !layout?.textOnly) {
    const mediaWidth = cardWidth - 26 // 媒体区 padding 12px×2 + 卡边框
    if (layout) {
      height += 12 + estimateCappedMediaHeight(media, mediaWidth, layout.mediaMax, TWEET_STRIP_GAP_PX)
    } else {
      height += 12 + (media.length - 1) * 8 // 媒体区顶距 + 件间 gap
      for (const item of media) height += estimateMediaHeight(item, mediaWidth)
    }
  }
  height += 24 // 正文块 py-3
  // 紧凑排版并掉空行再折行（与墙上渲染同一口径）
  const bodyText = displayTweetText(doc, locale)
  const textLines = estimateTextLines(layout ? collapseBlankLines(bodyText) : bodyText, bodyWidth, text.fontSize)
  height += (layout ? Math.min(layout.textClamp, textLines) : textLines) * text.lineHeight
  const quote = tweetQuote(doc)
  if (quote) {
    const quoteInnerWidth = bodyWidth - 34 // mx-1 + 引用卡边框 + px-3
    height += 42 // mt-2 + 引用卡边框 + 引用头（pt-2 + 头像行）+ 卡底余量
    // 默认 text-2xs leading-4
    const quoteText = displayQuoteText(quote, locale)
    const quoteLines = estimateTextLines(layout ? collapseBlankLines(quoteText) : quoteText, quoteInnerWidth, layout?.quoteSize ?? 11)
    height += (layout ? Math.min(layout.quoteClamp, quoteLines) : quoteLines) * (layout?.quoteLine ?? 16)
    const quoteMedia = quote.media ?? []
    if (quoteMedia.length > 0 && !layout?.textOnly) {
      height += 14 // 媒体块 pt-1.5 + pb-2
      if (layout) height += estimateCappedMediaHeight(quoteMedia, quoteInnerWidth, layout.quoteMediaMax, QUOTE_STRIP_GAP_PX)
      else for (const item of quoteMedia) height += estimateMediaHeight(item, quoteInnerWidth)
    }
  }
  const card = layout?.textOnly ? null : tweetLinkCard(doc)
  if (card && layout) {
    // 横排：缩略图与文字并排，卡高取两边较高的一边
    const cardInnerWidth = bodyWidth - 12 // mx-1 + 卡边框
    const thumb = card.image_url ? Math.min(LINK_ROW_THUMB_MAX_PX, cardInnerWidth * LINK_ROW_THUMB_SHARE) : 0
    const textWidth = cardInnerWidth - (thumb ? thumb + 8 : 0) - 20 // 缩略图左边距 + 文字区 px
    let body = 12 + 16 // 文字区 py + 标题行
    if (card.description) body += 2 + Math.min(2, estimateTextLines(card.description, textWidth, 11)) * 16
    if (card.domain) body += 18
    height += 10 + Math.max(thumb ? thumb / LINK_ROW_THUMB_RATIO + 16 : 0, body) // mt-2 + 卡边框；缩略图上下各留 8px
  } else if (card) {
    const cardInnerWidth = bodyWidth - 12 // mx-1 + 卡边框
    height += 50 // mt-2 + 卡边框 + body py-2 + 标题行
    if (card.image_url) {
      height += card.image_width && card.image_height && card.image_width > 0
        ? Math.min(260, cardInnerWidth * (card.image_height / card.image_width)) // 模板限高 260px
        : 150 // 无尺寸元数据按常见缩略图高度估
    }
    if (card.description) {
      // 描述限两行（-webkit-line-clamp: 2）
      height += Math.min(2, estimateTextLines(card.description, cardInnerWidth - 24, 11)) * 16 + 2
    }
    if (card.domain) height += 16
  }
  // mt-2 + 时间行；纯文字时收起了配图或链接卡的推文，时间行里多一枚提示钮，没有时间也照样占这一行
  if (tweetTimestamp(doc) || (layout?.textOnly && hasCollapsedMedia(doc))) height += 23
  return height + 16 // 列间距 gap-4 折进每卡
}

/** 纯文字模式收起的内容：照片件数、视频（含 GIF）件数、有没有链接卡。时间行的提示钮按它显示。 */
export interface CollapsedMedia { photos: number; videos: number; link: boolean }

export const collapsedMedia = (doc: TopDoc): CollapsedMedia => {
  const media = doc.media ?? []
  const videos = media.filter((item) => item.type === 'video' || item.type === 'animated_gif').length
  return { photos: media.length - videos, videos, link: hasLinkCard(doc) }
}

export const hasCollapsedMedia = (doc: TopDoc): boolean => (doc.media?.length ?? 0) > 0 || hasLinkCard(doc)

/** 同一页里一个账号达到这么多条，就只留第一条，其余收进它底下的一行。 */
export const TWEET_FOLD_THRESHOLD = 3
/** 折叠行的高（px）：与漫画版 .tweet-fold 的高一致，估高时加在留下的那条上。 */
export const TWEET_FOLD_BAR_PX = 36

export interface TweetFold {
  /** 归属账号（与关注筛选同一口径：纯转贴归转贴者） */
  handle: string
  /** 账号展示名 */
  name: string
  /** 收起的推文（不含留下的第一条），按页内顺序 */
  rest: TopDoc[]
  expanded: boolean
}

export interface FoldedTweets {
  /** 墙上要排的推文：收起的组只留第一条；展开的组其余各条紧跟在第一条之后 */
  visible: TopDoc[]
  /** 留下的第一条的 key → 它底下收着的那组 */
  folds: Map<string, TweetFold>
}

/**
 * 同账号折叠：一页里同一账号达到 threshold 条时只留最新的第一条，其余收进它底下的「＋N 条 某某 的推文」，
 * 瀑布流按剩下的重新分列。展开的组其余各条紧跟在第一条之后排进瀑布流，挨着第一条出现，不散回各自的时间位置。
 * 认不出账号的推文不折叠。expanded 里放留下那条的 key。
 */
export const foldTweetsByAccount = (
  tweets: TopDoc[],
  keyOf: (doc: TopDoc) => string,
  expanded: ReadonlySet<string>,
  threshold = TWEET_FOLD_THRESHOLD,
): FoldedTweets => {
  const groups = new Map<string, TopDoc[]>()
  for (const doc of tweets) {
    const handle = followedAccountHandle(doc)
    if (!handle) continue
    const group = groups.get(handle)
    if (group) group.push(doc)
    else groups.set(handle, [doc])
  }
  const folds = new Map<string, TweetFold>()
  const folded = new Set<TopDoc>()
  for (const [handle, [first, ...rest]] of groups) {
    if (!first || rest.length + 1 < threshold) continue
    const key = keyOf(first)
    folds.set(key, { handle, name: followedAccountDisplayName(first), rest, expanded: expanded.has(key) })
    for (const doc of rest) folded.add(doc)
  }
  const visible: TopDoc[] = []
  for (const doc of tweets) {
    if (folded.has(doc)) continue
    visible.push(doc)
    const fold = folds.get(keyOf(doc))
    if (fold?.expanded) visible.push(...fold.rest)
  }
  return { visible, folds }
}

/**
 * 按卡位分页（桌面推文墙）：每页排满 pageSize 张卡。一页里同账号达到 threshold 条就只占一张卡（其余收进折叠行，
 * 见 foldTweetsByAccount），刷屏的账号不挤掉别人，一页收进的推文因此可以多于 pageSize 条。
 * 各页按原顺序给出推文；没有推文时给一个空页。
 */
export const paginateFoldedTweets = (tweets: TopDoc[], pageSize: number, threshold = TWEET_FOLD_THRESHOLD): TopDoc[][] => {
  const size = Math.max(1, Math.floor(pageSize) || 1)
  // 这一条进来本页多占几张卡：没到门槛各占一张；正好到门槛时连同前面除第一条外的一起收起；过了门槛不占
  const cardsAdded = (handle: string, count: number) => (!handle || count < threshold ? 1 : count === threshold ? 2 - threshold : 0)
  const pages: TopDoc[][] = []
  let page: TopDoc[] = []
  let counts = new Map<string, number>()
  let cards = 0
  for (const doc of tweets) {
    const handle = followedAccountHandle(doc)
    let count = (counts.get(handle) ?? 0) + 1
    let added = cardsAdded(handle, count)
    if (page.length > 0 && cards + added > size) {
      pages.push(page)
      page = []
      counts = new Map()
      cards = 0
      count = 1
      added = 1
    }
    if (handle) counts.set(handle, count)
    page.push(doc)
    cards += added
  }
  if (page.length > 0 || pages.length === 0) pages.push(page)
  return pages
}

export interface SeenSplit {
  /** 墙上排在线上面的：上回之后新来的 */
  fresh: TopDoc[]
  /** 排在线下面的：从上回看过的第一条起 */
  earlier: TopDoc[]
  /** 这一页画不画「上次看到这里」 */
  rule: boolean
}

/**
 * 「上次看到这里」：boundary 是时间线上第一条上回就看过的推文的位置，它前面的都是这之后新来的（至少有一条才画线）。
 * 这一页墙上的推文按它分成线上、线下两块，分界落在这一页里、或者正好落在这一页开头时画线；不在这一页就整页照旧排。
 * page 是这一页收进的全部推文（含折叠收起的），folded 是它折叠后的结果，indexOf 给时间线位置。
 * 展开的折叠组跟着留下的第一条走，不拆到线的两边。
 */
export const splitAtSeen = (
  page: TopDoc[],
  folded: FoldedTweets,
  boundary: number,
  indexOf: (doc: TopDoc) => number,
  keyOf: (doc: TopDoc) => string,
): SeenSplit => {
  const whole: SeenSplit = { fresh: folded.visible, earlier: [], rule: false }
  const first = page[0]
  if (boundary <= 0 || !first) return whole
  const above = new Set<TopDoc>()
  const placed = new Set<TopDoc>()
  for (const doc of folded.visible) {
    if (placed.has(doc)) continue
    const isFresh = indexOf(doc) < boundary
    const fold = folded.folds.get(keyOf(doc))
    for (const member of [doc, ...(fold?.expanded ? fold.rest : [])]) {
      placed.add(member)
      if (isFresh) above.add(member)
    }
  }
  const fresh = folded.visible.filter((doc) => above.has(doc))
  const earlier = folded.visible.filter((doc) => !above.has(doc))
  return earlier.length && (fresh.length || indexOf(first) === boundary) ? { fresh, earlier, rule: true } : whole
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

export interface XBoardEmptyCopyOptions {
  /** 选中的就是今天（最近 24h 滚动窗口） */
  isToday: boolean
  /** 快照日期清单已成功加载（清单为空时无法判定「早于最早数据日」，回退通用空态） */
  hasSnapshotDates: boolean
  /** 选中日期早于清单里有数据的最早日期（再往前翻也不会有数据） */
  isBeforeEarliest: boolean
}

/**
 * 空态文案选择：区分「今天窗口暂无」「早于最早数据日」「该日窗口真空」三种
 * 空列表。滑动窗口语义下不再有静默期/无快照日：任何过去日期的窗口都有定义。
 */
export const emptyStateCopyKeys = (options: XBoardEmptyCopyOptions): { titleKey: string; hintKey: string } => {
  if (options.isToday) return { titleKey: 'xboard.emptyRecent', hintKey: 'xboard.emptyRecentHint' }
  if (options.hasSnapshotDates && options.isBeforeEarliest) {
    return { titleKey: 'xboard.emptyNoSnapshot', hintKey: 'xboard.emptyNoSnapshotHint' }
  }
  return { titleKey: 'xboard.empty', hintKey: 'xboard.emptyHint' }
}
