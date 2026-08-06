import { describe, expect, it } from 'vitest'
import {
  authorAvatarUrl,
  countTweets,
  extractXHandle,
  flattenTweets,
  groupTweetsByHandle,
  hasMedia,
  mediaItems,
  posterMediaUrl,
  proxiedMediaUrl,
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
})
