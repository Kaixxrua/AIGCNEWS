import { describe, expect, it } from 'vitest'
import { isSavedTweet } from './savedTweet'

const tweet = { title: 'Tweet', summary: 'body', url: 'https://x.com/alice/status/1' }

describe('isSavedTweet', () => {
  it('认推文地址是网页地址的；引用与链接卡缺了不碍事，有就也得是网页地址', () => {
    expect(isSavedTweet(tweet)).toBe(true)
    expect(isSavedTweet({ ...tweet, url: 'HTTP://x.com/alice/status/1' })).toBe(true)
    expect(isSavedTweet({
      ...tweet,
      quote: { url: 'https://x.com/bob/status/2', text: 'quoted' },
      link_card: { url: 'http://example.com/post', title: 'Example' },
    })).toBe(true)
    expect(isSavedTweet({ ...tweet, quote: null, link_card: undefined })).toBe(true)
  })

  it('别的协议、缺地址、内容不是一条推文的都不认', () => {
    expect(isSavedTweet({ ...tweet, url: 'javascript:void(0)' })).toBe(false)
    expect(isSavedTweet({ ...tweet, url: '' })).toBe(false)
    expect(isSavedTweet({ title: 'Tweet' })).toBe(false)
    expect(isSavedTweet({ ...tweet, quote: { url: 'data:text/html,quoted', text: 'quoted' } })).toBe(false)
    expect(isSavedTweet({ ...tweet, link_card: { title: 'no address' } })).toBe(false)
    expect(isSavedTweet({ ...tweet, quote: 'quoted' })).toBe(false)
    expect(isSavedTweet(null)).toBe(false)
    expect(isSavedTweet([tweet])).toBe(false)
    expect(isSavedTweet(tweet.url)).toBe(false)
  })
})
