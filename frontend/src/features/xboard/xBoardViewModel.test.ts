import { describe, expect, it } from 'vitest'
import {
  countTweets,
  extractXHandle,
  flattenTweets,
  groupTweetsByHandle,
  hasMedia,
  mediaItems,
  tweetScore,
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
    expect(tweetTimestamp({ created_at: 'c', published_date: 'p' })).toBe('c')
    expect(tweetTimestamp({})).toBe('')
  })

  it('detects and lists media items safely', () => {
    expect(hasMedia({})).toBe(false)
    expect(hasMedia({ media: [] })).toBe(false)
    const doc = tweet('openai', '1', {
      media: [{ type: 'photo', url: 'https://pbs.twimg.com/a.jpg', width: 100, height: 100 }],
    })
    expect(hasMedia(doc)).toBe(true)
    expect(mediaItems(doc)).toEqual([{ type: 'photo', url: 'https://pbs.twimg.com/a.jpg', width: 100, height: 100 }])
    expect(mediaItems({})).toEqual([])
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
