import { describe, expect, it } from 'vitest'
import {
  authorAvatarUrl,
  authorDisplayName,
  clampPage,
  countTweets,
  displayTweetText,
  distributeColumns,
  extractXHandle,
  flattenTweets,
  formatLocalTime,
  groupTweetsByHandle,
  hasMedia,
  mediaItems,
  pageCount,
  paginateItems,
  posterMediaUrl,
  proxiedMediaUrl,
  timelineTweets,
  tweetScore,
  tweetText,
  tweetTimestamp,
} from './xBoardViewModel'
import type { TopDoc } from '@/features/dashboard/dashboardViewModel'

const tweet = (handle: string, id: string, overrides: Partial<TopDoc> = {}): TopDoc => ({
  title: `tweet ${id}`,
  url: `https://x.com/${handle}/status/${id}`,
  raw_score: 0,
  ...overrides,
})

describe('xBoardViewModel', () => {
  it('extracts lowercase handles from x.com and twitter.com status URLs', () => {
    expect(extractXHandle('https://x.com/OpenAI/status/123')).toBe('openai')
    expect(extractXHandle('https://twitter.com/karpathy/status/456?ref=1')).toBe('karpathy')
    expect(extractXHandle('https://x.com/OpenAI')).toBe('')
    expect(extractXHandle('https://example.com/x.com/foo/status/1')).toBe('')
    expect(extractXHandle(undefined)).toBe('')
  })

  it('resolves score and timestamp with safe fallbacks', () => {
    expect(tweetScore({ raw_score: 12, score: 3 })).toBe(12)
    expect(tweetScore({ score: 7 })).toBe(7)
    expect(tweetScore({})).toBe(0)
    expect(tweetScore({ raw_score: 'NaN-ish' as unknown as number })).toBe(0)
    expect(tweetTimestamp({ published_at: '2026-08-04T01:00:00Z' })).toBe('2026-08-04T01:00:00Z')
    expect(tweetTimestamp({ published_at: 'p', created_at: 'c', published_date: 'd' })).toBe('p')
    expect(tweetTimestamp({ created_at: 'c', published_date: 'd' })).toBe('d')
    expect(tweetTimestamp({})).toBe('')
  })

  it('extracts avatar url and full tweet text', () => {
    expect(authorAvatarUrl({ author_avatar_url: 'https://x.com/a.jpg' })).toBe('https://x.com/a.jpg')
    expect(authorAvatarUrl({ url: 'https://x.com/openai/status/1' })).toBe('https://unavatar.io/x/openai')
    expect(authorAvatarUrl({})).toBeUndefined()
    expect(tweetText({ summary: 'full', title: 'short' })).toBe('full')
    expect(tweetText({ title: 'only' })).toBe('only')
    expect(tweetText({})).toBe('')
  })

  it('prefers stored author nickname and falls back to @handle', () => {
    expect(authorDisplayName({ author_name: 'OpenAI', url: 'https://x.com/openai/status/1' })).toBe('OpenAI')
    expect(authorDisplayName({ url: 'https://x.com/OpenAI/status/1' })).toBe('@openai')
    expect(authorDisplayName({ author_name: '  ', url: 'https://x.com/openai/status/1' })).toBe('@openai')
    expect(authorDisplayName({ author_name: 'Karpathy' })).toBe('Karpathy')
    expect(authorDisplayName({})).toBe('')
  })

  it('detects and lists media items safely', () => {
    expect(hasMedia({})).toBe(false)
    expect(hasMedia({ media: [] })).toBe(false)
    const doc = tweet('openai', '1', {
      media: [{ type: 'photo', url: 'https://pbs.twimg.com/a.jpg', width: 100, height: 100 }],
    })
    expect(hasMedia(doc)).toBe(true)
    expect(mediaItems(doc)).toEqual([
      {
        type: 'photo',
        url: `/api/media/x/proxy?url=${encodeURIComponent('https://pbs.twimg.com/a.jpg')}`,
        width: 100,
        height: 100,
      },
    ])
    expect(mediaItems({})).toEqual([])
  })

  it('rewrites twimg media urls to the same-origin proxy and passes others through', () => {
    const video = 'https://video.twimg.com/amplify_video/1/vid/avc1/1920x1080/a.mp4?tag=29'
    expect(proxiedMediaUrl(video)).toBe(`/api/media/x/proxy?url=${encodeURIComponent(video)}`)
    expect(proxiedMediaUrl('https://pbs.twimg.com/a.jpg')).toContain('/api/media/x/proxy?url=')
    expect(proxiedMediaUrl('https://abs.twimg.com/hash.png')).toContain('/api/media/x/proxy?url=')
    // 白名单外主机 / 非 URL 原样透传（后端代理仍会做二次校验）
    expect(proxiedMediaUrl('https://example.com/a.jpg')).toBe('https://example.com/a.jpg')
    expect(proxiedMediaUrl('not-a-url')).toBe('not-a-url')
    expect(proxiedMediaUrl('')).toBe('')
  })

  it('derives poster urls only for twimg videos', () => {
    const video = 'https://video.twimg.com/amplify_video/1/vid/a.mp4?tag=29'
    expect(posterMediaUrl(video)).toBe(`/api/media/x/poster?url=${encodeURIComponent(video)}`)
    // 非 twimg / 非法 URL 不派生封面，模板回退深色占位
    expect(posterMediaUrl('https://example.com/a.mp4')).toBe('')
    expect(posterMediaUrl('not-a-url')).toBe('')
    expect(posterMediaUrl('')).toBe('')
  })

  it('mediaItems rewrites only url and keeps the rest of the item intact', () => {
    const doc = tweet('openai', '1', {
      media: [
        { type: 'video', url: 'https://video.twimg.com/a.mp4', width: 1920, height: 1080 },
        { type: 'photo', url: 'https://elsewhere.cdn/b.jpg', width: 10, height: 10 },
      ],
    })
    const items = mediaItems(doc)
    expect(items[0]).toMatchObject({ type: 'video', width: 1920, height: 1080 })
    expect(items[0]?.url).toContain('/api/media/x/proxy?url=')
    expect(items[0]?.poster_url).toBe(
      `/api/media/x/poster?url=${encodeURIComponent('https://video.twimg.com/a.mp4')}`,
    )
    expect(items[1]).toEqual({ type: 'photo', url: 'https://elsewhere.cdn/b.jpg', width: 10, height: 10 })
    expect(items[1]?.poster_url).toBeUndefined()
  })

  it('mediaItems prefers the crawled poster_url over the extraction endpoint', () => {
    const poster = 'https://pbs.twimg.com/amplify_video_thumb/1/img/x.jpg'
    const doc = tweet('openai', '1', {
      media: [
        { type: 'video', url: 'https://video.twimg.com/a.mp4', width: 1920, height: 1080, poster_url: poster },
        { type: 'animated_gif', url: 'https://video.twimg.com/g.mp4', poster_url: poster },
      ],
    })
    const items = mediaItems(doc)
    // 采集期落库的官方封面：经代理同源化，不再走抽帧端点
    expect(items[0]?.poster_url).toBe(`/api/media/x/proxy?url=${encodeURIComponent(poster)}`)
    expect(items[1]?.poster_url).toBe(`/api/media/x/proxy?url=${encodeURIComponent(poster)}`)
    // url 改写不受影响
    expect(items[0]?.url).toBe(`/api/media/x/proxy?url=${encodeURIComponent('https://video.twimg.com/a.mp4')}`)
  })

  it('flattens grouped sections into a single ordered list', () => {
    const docs = [
      tweet('openai', '1', { raw_score: 5 }),
      tweet('karpathy', '2', { raw_score: 50 }),
      tweet('openai', '3', { raw_score: 30 }),
    ]
    const sections = groupTweetsByHandle(docs)
    expect(flattenTweets(sections).map((doc) => doc.url)).toEqual([
      'https://x.com/karpathy/status/2',
      'https://x.com/openai/status/3',
      'https://x.com/openai/status/1',
    ])
  })

  it('groups by handle with in-section score ordering and section max-score ordering', () => {
    const docs = [
      tweet('openai', '1', { raw_score: 5 }),
      tweet('karpathy', '2', { raw_score: 50 }),
      tweet('openai', '3', { raw_score: 30 }),
      tweet('AnthropicAI', '4', { raw_score: 40 }),
      tweet('openai', '5', { raw_score: 30, published_at: '2026-08-04T02:00:00Z' }),
    ]
    const sections = groupTweetsByHandle(docs)

    expect(sections.map((section) => section.handle)).toEqual(['karpathy', 'anthropicai', 'openai'])
    const openai = sections.find((section) => section.handle === 'openai')
    expect(openai?.tweets.map((doc) => doc.url)).toEqual([
      'https://x.com/openai/status/5',
      'https://x.com/openai/status/3',
      'https://x.com/openai/status/1',
    ])
    expect(openai?.maxScore).toBe(30)
    expect(countTweets(sections)).toBe(5)
  })

  it('sinks unparseable URLs into a trailing fallback section without dropping them', () => {
    const docs = [
      tweet('openai', '1', { raw_score: 1 }),
      { title: 'no url', raw_score: 999 } as TopDoc,
    ]
    const sections = groupTweetsByHandle(docs)

    expect(sections).toHaveLength(2)
    expect(sections[0]?.handle).toBe('openai')
    expect(sections[1]?.handle).toBe('')
    expect(sections[1]?.tweets[0]?.title).toBe('no url')
    expect(countTweets(sections)).toBe(2)
  })

  it('breaks section score ties by handle name', () => {
    const docs = [tweet('beta', '1', { raw_score: 10 }), tweet('alpha', '2', { raw_score: 10 })]
    expect(groupTweetsByHandle(docs).map((section) => section.handle)).toEqual(['alpha', 'beta'])
  })

  it('timelineTweets sorts newest first, ties by score, sinks docs without timestamps', () => {
    const docs = [
      tweet('openai', 'old', { published_at: '2026-08-01T01:00:00Z', raw_score: 999 }),
      tweet('openai', 'new', { published_at: '2026-08-04T01:00:00Z', raw_score: 1 }),
      tweet('openai', 'no-ts', { raw_score: 500 }),
      tweet('openai', 'same-hi', { published_at: '2026-08-04T01:00:00Z', raw_score: 50 }),
    ]
    const ordered = timelineTweets(docs)
    expect(ordered.map((doc) => doc.url)).toEqual([
      'https://x.com/openai/status/same-hi', // 同一时刻分数高者在前
      'https://x.com/openai/status/new',
      'https://x.com/openai/status/old',
      'https://x.com/openai/status/no-ts', // 无时间戳沉底不丢弃
    ])
    // 不就地修改入参
    expect(docs[0]?.url).toBe('https://x.com/openai/status/old')
  })

  it('formatLocalTime converts UTC ISO into the given timezone', () => {
    const iso = '2026-08-04T13:04:00Z'
    expect(formatLocalTime(iso, 'UTC')).toBe('2026-08-04 13:04')
    expect(formatLocalTime(iso, 'Asia/Shanghai')).toBe('2026-08-04 21:04')
    expect(formatLocalTime(iso, 'America/New_York')).toBe('2026-08-04 09:04') // 8 月 EDT=UTC-4
    // 跨日：UTC 深夜 → 上海已是次日
    expect(formatLocalTime('2026-08-04T16:30:00Z', 'Asia/Shanghai')).toBe('2026-08-05 00:30')
    // +00:00 偏移形式同样可解析
    expect(formatLocalTime('2026-08-04T13:04:00+00:00', 'UTC')).toBe('2026-08-04 13:04')
  })

  it('formatLocalTime returns empty string for unparseable or empty input', () => {
    expect(formatLocalTime('')).toBe('')
    expect(formatLocalTime('not-a-date', 'UTC')).toBe('')
    expect(formatLocalTime('2026-13-99T99:99:99Z', 'UTC')).toBe('')
  })

  it('displayTweetText prefers the crawled X translation under zh locales only', () => {
    const doc = tweet('openai', '1', {
      summary: 'Original English text',
      translation_zh: '中文译文',
    })
    expect(displayTweetText(doc, 'zh-CN')).toBe('中文译文')
    expect(displayTweetText(doc, 'zh-TW')).toBe('中文译文')
    expect(displayTweetText(doc, 'en-US')).toBe('Original English text')
    expect(displayTweetText(doc, 'ja')).toBe('Original English text')
  })

  it('displayTweetText falls back to original when translation missing or blank', () => {
    expect(displayTweetText(tweet('openai', '1', { summary: 'orig' }), 'zh-CN')).toBe('orig')
    expect(displayTweetText(tweet('openai', '1', { summary: 'orig', translation_zh: '   ' }), 'zh-CN')).toBe('orig')
    expect(displayTweetText(tweet('openai', '1', { title: 't', translation_zh: '译' }), 'zh-CN')).toBe('译')
  })

  it('distributeColumns deals items round-robin so cross-column reads stay row-major', () => {
    expect(distributeColumns([0, 1, 2, 3, 4, 5, 6], 3)).toEqual([[0, 3, 6], [1, 4], [2, 5]])
    expect(distributeColumns([], 4)).toEqual([[], [], [], []])
    // 非法列数兜底为 1；小数为取整
    expect(distributeColumns([1, 2], 0)).toEqual([[1, 2]])
    expect(distributeColumns([1, 2, 3], 2.7)).toEqual([[1, 3], [2]])
  })

  it('pageCount floors at 1 page and handles empty, boundary and large totals', () => {
    expect(pageCount(0, 20)).toBe(1) // 空列表按 1 页算，避免 0 页状态
    expect(pageCount(20, 20)).toBe(1)
    expect(pageCount(21, 20)).toBe(2)
    expect(pageCount(500, 20)).toBe(25)
    expect(pageCount(-5, 20)).toBe(1)
    // 非法 pageSize 兜底为每页 1 条
    expect(pageCount(3, 0)).toBe(3)
    expect(pageCount(3, Number.NaN)).toBe(3)
    expect(pageCount(3, 2.9)).toBe(2)
  })

  it('clampPage floors and clamps into [1, totalPages]', () => {
    expect(clampPage(1, 3)).toBe(1)
    expect(clampPage(3, 3)).toBe(3)
    expect(clampPage(0, 3)).toBe(1)
    expect(clampPage(-2, 3)).toBe(1)
    expect(clampPage(99, 3)).toBe(3)
    expect(clampPage(2.9, 3)).toBe(2)
    expect(clampPage(Number.NaN, 3)).toBe(1)
    expect(clampPage(Number.POSITIVE_INFINITY, 3)).toBe(1)
    // 非法 totalPages 兜底 1 页
    expect(clampPage(5, 0)).toBe(1)
  })

  it('paginateItems slices the requested page and clamps out-of-range pages internally', () => {
    const items = Array.from({ length: 45 }, (_, index) => index)
    expect(paginateItems(items, 1, 20)).toEqual(items.slice(0, 20))
    expect(paginateItems(items, 3, 20)).toEqual(items.slice(40, 45))
    // 越界页内部先夹取，调用方无需预校验
    expect(paginateItems(items, 99, 20)).toEqual(items.slice(40, 45))
    expect(paginateItems(items, 0, 20)).toEqual(items.slice(0, 20))
    expect(paginateItems([], 1, 20)).toEqual([])
  })
})
