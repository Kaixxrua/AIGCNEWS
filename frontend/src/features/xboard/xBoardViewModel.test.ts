import { describe, expect, it } from 'vitest'
import {
  authorAvatarUrl,
  authorDisplayName,
  clampPage,
  countTweets,
  displayTweetText,
  distributeColumns,
  emptyStateCopyKeys,
  estimateTweetCardHeight,
  extractXHandle,
  flattenTweets,
  formatLocalTime,
  groupTweetsByHandle,
  hasMedia,
  hasLinkCard,
  hasQuote,
  linkCardImageUrl,
  mediaItems,
  pageCount,
  paginateItems,
  photoVariantUrl,
  posterMediaUrl,
  proxiedMediaUrl,
  quoteAsDoc,
  quoteAvatarUrl,
  quoteMediaItems,
  quoteTextSegments,
  retweetedByHandle,
  mergePagedTweets,
  timelineTweets,
  tweetLinkCard,
  tweetQuote,
  tweetScore,
  tweetText,
  tweetTextSegments,
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

  it('proxies only twimg avatars same-origin and drops third-party fallbacks', () => {
    const avatar = 'https://pbs.twimg.com/profile_images/a.jpg'
    expect(authorAvatarUrl({ author_avatar_url: avatar })).toBe(
      `/api/media/x/img/pbs.twimg.com/profile_images/a.jpg`,
    )
    // 非 twimg 地址不直连（中国大陆不可达/白名单外主机），回退本地 𝕏 占位
    expect(authorAvatarUrl({ author_avatar_url: 'https://x.com/a.jpg' })).toBeUndefined()
    // 无落库头像同样回退占位（历史 unavatar.io 回退已移除）
    expect(authorAvatarUrl({ url: 'https://x.com/openai/status/1' })).toBeUndefined()
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

  it('normalizes retweeted_by handle and blanks absent/bad values', () => {
    expect(retweetedByHandle({ retweeted_by: 'watcher' })).toBe('watcher')
    expect(retweetedByHandle({ retweeted_by: '  @Watcher ' })).toBe('Watcher')
    expect(retweetedByHandle({ retweeted_by: '' })).toBe('')
    expect(retweetedByHandle({ retweeted_by: '   ' })).toBe('')
    expect(retweetedByHandle({ retweeted_by: null })).toBe('')
    expect(retweetedByHandle({ retweeted_by: 42 as unknown as string })).toBe('')
    expect(retweetedByHandle({})).toBe('')
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
        url: `/api/media/x/img/pbs.twimg.com/a.jpg`,
        width: 100,
        height: 100,
      },
    ])
    expect(mediaItems({})).toEqual([])
  })

  it('rewrites twimg media urls to the path-style same-origin proxy and passes others through', () => {
    const video = 'https://video.twimg.com/amplify_video/1/vid/avc1/1920x1080/a.mp4?tag=29'
    expect(proxiedMediaUrl(video)).toBe('/api/media/x/img/video.twimg.com/amplify_video/1/vid/avc1/1920x1080/a.mp4?tag=29')
    expect(proxiedMediaUrl('https://pbs.twimg.com/a.jpg')).toBe('/api/media/x/img/pbs.twimg.com/a.jpg')
    expect(proxiedMediaUrl('https://abs.twimg.com/hash.png')).toBe('/api/media/x/img/abs.twimg.com/hash.png')
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
    expect(items[0]?.url).toContain('/api/media/x/img/')
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
    // 采集期落库的官方封面：经代理同源化，不再走抽帧端点；封面仅播放前展示，
    // 支持变体的路径降载为 small（原图无消费场景）
    expect(items[0]?.poster_url).toBe(`/api/media/x/img/pbs.twimg.com/amplify_video_thumb/1/img/x.jpg?name=small`)
    expect(items[1]?.poster_url).toBe(`/api/media/x/img/pbs.twimg.com/amplify_video_thumb/1/img/x.jpg?name=small`)
    // url 改写不受影响
    expect(items[0]?.url).toBe(`/api/media/x/img/video.twimg.com/a.mp4`)
  })

  it('photoVariantUrl rewrites the name param only on supported twimg image paths', () => {
    expect(photoVariantUrl('https://pbs.twimg.com/media/a.jpg', 'small'))
      .toBe('https://pbs.twimg.com/media/a.jpg?name=small')
    // 已有 name 参数时覆盖，其余查询参数保留
    expect(photoVariantUrl('https://pbs.twimg.com/media/a.jpg?format=jpg&name=large', 'small'))
      .toBe('https://pbs.twimg.com/media/a.jpg?format=jpg&name=small')
    expect(photoVariantUrl('https://pbs.twimg.com/ext_tw_video_thumb/1/pu/img/x.jpg', 'small'))
      .toBe('https://pbs.twimg.com/ext_tw_video_thumb/1/pu/img/x.jpg?name=small')
    // 头像/视频文件/外站路径不支持变体（下发只会 404），回退空串
    expect(photoVariantUrl('https://pbs.twimg.com/profile_images/a.jpg', 'small')).toBe('')
    expect(photoVariantUrl('https://video.twimg.com/a.mp4', 'small')).toBe('')
    expect(photoVariantUrl('https://example.com/media/a.jpg', 'small')).toBe('')
    expect(photoVariantUrl('not-a-url', 'small')).toBe('')
    expect(photoVariantUrl('', 'small')).toBe('')
  })

  it('mediaItems derives small thumbnails for photos while keeping originals for the lightbox', () => {
    const photo = 'https://pbs.twimg.com/media/abc.jpg'
    const doc = tweet('openai', '1', {
      media: [
        { type: 'photo', url: photo, width: 2048, height: 1152 },
        // 变体不可派生的照片路径：不注入 thumb_url，内联渲染回退原图
        { type: 'photo', url: 'https://pbs.twimg.com/a.jpg' },
      ],
    })
    const items = mediaItems(doc)
    expect(items[0]?.url).toBe(`/api/media/x/img/pbs.twimg.com/media/abc.jpg`)
    expect(items[0]?.thumb_url).toBe(
      `/api/media/x/img/pbs.twimg.com/media/abc.jpg?name=small`,
    )
    expect(items[0]?.width).toBe(2048)
    expect(items[1]?.thumb_url).toBeUndefined()
    // 视频不出 thumb_url（封面已降载在 poster_url 上）
    const videoDoc = tweet('openai', '2', { media: [{ type: 'video', url: 'https://video.twimg.com/a.mp4' }] })
    expect(mediaItems(videoDoc)[0]?.thumb_url).toBeUndefined()
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

  it('mergePagedTweets flattens pages, dedupes by id, and sorts newest first', () => {
    const older = tweet('a', '10', { id: 'x:10', published_at: '2026-08-04T01:00:00Z' })
    const newest = tweet('a', '12', { id: 'x:12', published_at: '2026-08-04T03:00:00Z' })
    const middle = tweet('b', '11', { id: 'x:11', published_at: '2026-08-04T02:00:00Z', raw_score: 3 })
    const middleDup = tweet('b', '11', { id: 'x:11', published_at: '2026-08-04T02:00:00Z', raw_score: 99 })

    const merged = mergePagedTweets([[newest, middle], [middleDup, older]])

    expect(merged.map((item) => item.id)).toEqual(['x:12', 'x:11', 'x:10'])
    // 重叠条目以先到的版本为准（不替换为后页的同 id 行）
    expect(merged[1]?.raw_score).toBe(3)
    expect(mergePagedTweets([])).toEqual([])
  })

  it('timelineTweets sorts by publication instant, then tweet ID, and sinks invalid timestamps', () => {
    const docs = [
      tweet('openai', 'old', { published_at: '2026-08-01T01:00:00Z', raw_score: 999 }),
      tweet('openai', 'new', { published_at: '2026-08-04T01:00:00Z', raw_score: 1 }),
      tweet('openai', 'no-ts', { raw_score: 500 }),
      tweet('openai', 'same-hi', { published_at: '2026-08-04T01:00:00+00:00', raw_score: 50 }),
      tweet('openai', 'bad', { published_at: 'not-a-date', raw_score: 9999 }),
    ]
    const ordered = timelineTweets(docs)
    expect(ordered.map((doc) => doc.url)).toEqual([
      'https://x.com/openai/status/same-hi',
      'https://x.com/openai/status/new',
      'https://x.com/openai/status/old',
      'https://x.com/openai/status/bad',
      'https://x.com/openai/status/no-ts',
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

  it('tweetTextSegments splits urls into clickable segments', () => {
    const doc = tweet('openai', '1', {
      summary: 'read https://openai.com/a and https://example.org/b now',
    })
    expect(tweetTextSegments(doc, 'en-US')).toEqual([
      { text: 'read ', isUrl: false },
      { text: 'https://openai.com/a', isUrl: true },
      { text: ' and ', isUrl: false },
      { text: 'https://example.org/b', isUrl: true },
      { text: ' now', isUrl: false },
    ])
  })

  it('tweetTextSegments returns trailing punctuation to the text segment', () => {
    const doc = tweet('openai', '1', { summary: 'see https://openai.com/a, then reply.' })
    expect(tweetTextSegments(doc, 'en-US')).toEqual([
      { text: 'see ', isUrl: false },
      { text: 'https://openai.com/a', isUrl: true },
      { text: ', then reply.', isUrl: false },
    ])
  })

  it('tweetTextSegments works on translation text and url-only bodies', () => {
    const zhDoc = tweet('openai', '1', {
      summary: 'orig',
      translation_zh: '更多资格信息：\nhttps://gemini.google/eligibility',
    })
    expect(tweetTextSegments(zhDoc, 'zh-CN')).toEqual([
      { text: '更多资格信息：\n', isUrl: false },
      { text: 'https://gemini.google/eligibility', isUrl: true },
    ])
    expect(tweetTextSegments(tweet('openai', '1', { summary: 'no links here' }), 'en-US'))
      .toEqual([{ text: 'no links here', isUrl: false }])
  })

  it('tweetTextSegments marks @mentions as linkable segments', () => {
    const doc = tweet('openai', '1', { summary: '@VictorSuOrtiz @alexinexxx RSVP here' })
    expect(tweetTextSegments(doc, 'en-US')).toEqual([
      { text: '@VictorSuOrtiz', isUrl: false, isMention: true, mentionHandle: 'VictorSuOrtiz' },
      { text: ' ', isUrl: false },
      { text: '@alexinexxx', isUrl: false, isMention: true, mentionHandle: 'alexinexxx' },
      { text: ' RSVP here', isUrl: false },
    ])
  })

  it('tweetTextSegments keeps mentions inside urls and emails as plain text', () => {
    const doc = tweet('openai', '1', { summary: 'see https://x.com/@openai or mail a@b.com' })
    expect(tweetTextSegments(doc, 'en-US')).toEqual([
      { text: 'see ', isUrl: false },
      { text: 'https://x.com/@openai', isUrl: true },
      { text: ' or mail a@b.com', isUrl: false },
    ])
  })

  const quotedTweet = (overrides: Partial<NonNullable<TopDoc['quote']>> = {}) =>
    tweet('minimax_ai', '2001', {
      quote: {
        url: 'https://x.com/comfyui/status/2000',
        author: 'comfyui',
        author_name: 'ComfyUI',
        author_avatar_url: 'https://pbs.twimg.com/profile_images/q.jpg',
        text: 'Livestream update https://example.com/live see you',
        media: [
          { type: 'photo', url: 'https://pbs.twimg.com/media/q.jpg', width: 800, height: 450 },
        ],
        published_at: '2026-08-07T01:00:00+00:00',
        ...overrides,
      },
    })

  it('hasQuote requires url plus text or media, rejecting malformed data', () => {
    expect(hasQuote(quotedTweet())).toBe(true)
    expect(hasQuote(tweet('openai', '1'))).toBe(false)
    expect(hasQuote(tweet('openai', '1', { quote: null }))).toBe(false)
    expect(hasQuote(quotedTweet({ url: '' }))).toBe(false)
    expect(hasQuote(quotedTweet({ text: '', media: [] }))).toBe(false)
    // 仅媒体无正文仍可成卡
    expect(hasQuote(quotedTweet({ text: '' }))).toBe(true)
    expect(tweetQuote(tweet('openai', '1'))).toBeNull()
    expect(tweetQuote(quotedTweet())?.author).toBe('comfyui')
  })

  const linkedTweet = (overrides: Partial<NonNullable<TopDoc['link_card']>> = {}): TopDoc =>
    tweet('minimax_ai', '2086', {
      link_card: {
        url: 'https://www.youtube.com/watch?v=S9O3FPumX4Q',
        title: 'MiniMax H3: A New Open-Weight Video Model',
        description: 'MiniMax H3 is an open-weight video model',
        domain: 'youtube.com',
        image_url: 'https://pbs.twimg.com/card_img/2085/orig.jpg?format=jpg&name=orig',
        image_width: 1280,
        image_height: 720,
        card_type: 'player',
        ...overrides,
      },
    })

  it('hasLinkCard requires url plus title, rejecting malformed data', () => {
    expect(hasLinkCard(linkedTweet())).toBe(true)
    expect(hasLinkCard(tweet('openai', '1'))).toBe(false)
    expect(hasLinkCard(tweet('openai', '1', { link_card: null }))).toBe(false)
    expect(hasLinkCard(linkedTweet({ url: '' }))).toBe(false)
    expect(hasLinkCard(linkedTweet({ title: '' }))).toBe(false)
    // 缩略图缺失仍可成卡（渲染层降级为纯文本卡）
    expect(hasLinkCard(linkedTweet({ image_url: null }))).toBe(true)
    expect(tweetLinkCard(tweet('openai', '1'))).toBeNull()
    expect(tweetLinkCard(linkedTweet())?.domain).toBe('youtube.com')
  })

  it('linkCardImageUrl proxies only twimg card images and skips name variants', () => {
    // card_img 是 pbs.twimg.com 路径：走同源路径式代理；不做 ?name= 变体
    // （card_img 不支持派生尺寸，原样透传落库 URL 的既有 query）
    expect(linkCardImageUrl(linkedTweet().link_card!)).toBe(
      '/api/media/x/img/pbs.twimg.com/card_img/2085/orig.jpg?format=jpg&name=orig',
    )
    // 非 twimg 镜像（异常上游数据）不直连，回退纯文本卡
    expect(linkCardImageUrl(linkedTweet({ image_url: 'https://evil.com/x.jpg' }).link_card!)).toBeUndefined()
    expect(linkCardImageUrl(linkedTweet({ image_url: null }).link_card!)).toBeUndefined()
    expect(linkCardImageUrl(linkedTweet({ image_url: undefined }).link_card!)).toBeUndefined()
  })

  it('quoteTextSegments splits quote text with the same url rules', () => {
    expect(quoteTextSegments(quotedTweet().quote!, 'en-US')).toEqual([
      { text: 'Livestream update ', isUrl: false },
      { text: 'https://example.com/live', isUrl: true },
      { text: ' see you', isUrl: false },
    ])
    expect(quoteTextSegments(quotedTweet({ text: '' }).quote!, 'en-US')).toEqual([])
  })

  it('quoteTextSegments marks @mentions for highlighted spans', () => {
    expect(quoteTextSegments(quotedTweet({ text: '@AnthropicAI congrats!' }).quote!, 'en-US')).toEqual([
      { text: '@AnthropicAI', isUrl: false, isMention: true, mentionHandle: 'AnthropicAI' },
      { text: ' congrats!', isUrl: false },
    ])
  })

  it('quoteTextSegments prefers the stored zh translation under zh locale only', () => {
    const translated = quotedTweet({ translation_zh: '直播更新 https://example.com/live 不见不散' })
    // zh 系界面语言：展示被引译文（链接分段规则不变）
    expect(quoteTextSegments(translated.quote!, 'zh-CN')).toEqual([
      { text: '直播更新 ', isUrl: false },
      { text: 'https://example.com/live', isUrl: true },
      { text: ' 不见不散', isUrl: false },
    ])
    // 非 zh 界面语言：仍展示被引原文
    expect(quoteTextSegments(translated.quote!, 'en-US')[0]).toEqual({ text: 'Livestream update ', isUrl: false })
    // zh 界面语言但无译文落库（旧数据）：回退被引原文
    expect(quoteTextSegments(quotedTweet().quote!, 'zh-CN')[0]).toEqual({ text: 'Livestream update ', isUrl: false })
    // 译文为空白串视为无译文
    expect(quoteTextSegments(quotedTweet({ translation_zh: '  ' }).quote!, 'zh-CN')[0]).toEqual({ text: 'Livestream update ', isUrl: false })
  })

  it('quoteMediaItems rewrites twimg urls through the proxy like outer media', () => {
    const items = quoteMediaItems(quotedTweet().quote!)
    expect(items).toHaveLength(1)
    expect(items[0]?.url).toBe(`/api/media/x/img/pbs.twimg.com/media/q.jpg`)
    expect(items[0]?.width).toBe(800)
    expect(quoteMediaItems(quotedTweet({ media: [] }).quote!)).toEqual([])
  })

  it('quoteAvatarUrl proxies the stored twimg avatar and drops unavatar fallback', () => {
    expect(quoteAvatarUrl(quotedTweet().quote!)).toBe(
      `/api/media/x/img/pbs.twimg.com/profile_images/q.jpg`,
    )
    expect(quoteAvatarUrl(quotedTweet({ author_avatar_url: '' }).quote!)).toBeUndefined()
    expect(quoteAvatarUrl(quotedTweet({ author_avatar_url: 'https://elsewhere.cdn/q.jpg' }).quote!)).toBeUndefined()
    expect(quoteAvatarUrl(quotedTweet({ author_avatar_url: '', author: '' }).quote!)).toBeUndefined()
  })

  it('quoteAsDoc projects a quote into a detail-renderable doc without score or nested quote', () => {
    const doc = quoteAsDoc(quotedTweet().quote!)
    expect(doc).toEqual({
      url: 'https://x.com/comfyui/status/2000',
      author_name: 'ComfyUI',
      author_avatar_url: 'https://pbs.twimg.com/profile_images/q.jpg',
      summary: 'Livestream update https://example.com/live see you',
      media: [{ type: 'photo', url: 'https://pbs.twimg.com/media/q.jpg', width: 800, height: 450 }],
      published_at: '2026-08-07T01:00:00+00:00',
    })
    // 投影只存一层：下钻后的 doc 无嵌套引用，不再渲染引用卡
    expect(hasQuote(doc)).toBe(false)
    // 下钻结果直接过详情渲染管线：昵称缺失回退 @handle，URL 段与媒体照常出
    expect(authorDisplayName(quoteAsDoc(quotedTweet({ author_name: '' }).quote!))).toBe('@comfyui')
    expect(tweetTextSegments(doc, 'en-US')).toContainEqual({ text: 'https://example.com/live', isUrl: true })
    expect(mediaItems(doc)).toHaveLength(1)
    expect(formatLocalTime(doc.published_at ?? '')).not.toBe('')
    // 被引译文一并投影：下钻详情经 tweetTextSegments 获得与外推一致的中文切换
    const translatedDoc = quoteAsDoc(quotedTweet({ translation_zh: '直播更新，不见不散' }).quote!)
    expect(translatedDoc.translation_zh).toBe('直播更新，不见不散')
    expect(tweetTextSegments(translatedDoc, 'zh-CN')).toEqual([{ text: '直播更新，不见不散', isUrl: false }])
    expect(tweetTextSegments(translatedDoc, 'en-US')).not.toEqual([{ text: '直播更新，不见不散', isUrl: false }])
  })

  it('distributeColumns without an estimator falls back to round-robin (equal-height assumption)', () => {
    expect(distributeColumns([0, 1, 2, 3, 4, 5, 6], 3)).toEqual([[0, 3, 6], [1, 4], [2, 5]])
    expect(distributeColumns([], 4)).toEqual([[], [], [], []])
    // 非法列数兜底为 1；小数为取整
    expect(distributeColumns([1, 2], 0)).toEqual([[1, 2]])
    expect(distributeColumns([1, 2, 3], 2.7)).toEqual([[1, 3], [2]])
  })

  it('distributeColumns with an estimator greedily fills the shortest column', () => {
    // 一高多矮：高卡独占一列，后续矮卡集中填其余两列——列内顺序仍保持传入序
    const heights: Record<string, number> = { a: 1000, b: 200, c: 200, d: 200, e: 200 }
    const estimate = (id: string) => heights[id] ?? 0
    expect(distributeColumns(['a', 'b', 'c', 'd', 'e'], 3, estimate)).toEqual([
      ['a'], ['b', 'd'], ['c', 'e'],
    ])
    // 同高并列取最左列：等高条目退化为轮询
    expect(distributeColumns([1, 2, 3, 4], 2, () => 100)).toEqual([[1, 3], [2, 4]])
    // 非法估高按 0 处理，不产生 NaN 污染后续比较
    expect(distributeColumns([1, 2], 2, () => Number.NaN)).toEqual([[1], [2]])
    expect(distributeColumns([1, 2], 2, () => -50)).toEqual([[1], [2]])
  })

  it('estimateTweetCardHeight ranks media-heavy cards far above text-only ones', () => {
    const column = 300
    const plain = tweet('openai', '1', { summary: 'short update' })
    const withPhoto = tweet('openai', '2', {
      summary: 'short update',
      media: [{ type: 'photo', url: 'https://pbs.twimg.com/media/a.jpg', width: 1600, height: 900 }],
    })
    const withTallVideo = tweet('openai', '3', {
      summary: 'short update',
      media: [{ type: 'video', url: 'https://video.twimg.com/ext_tw_video/v.mp4', width: 720, height: 1280 }],
    })
    const longText = tweet('openai', '4', { summary: '很长的更新'.repeat(80) })
    const hPlain = estimateTweetCardHeight(plain, column, 'en-US')
    const hPhoto = estimateTweetCardHeight(withPhoto, column, 'en-US')
    const hVideo = estimateTweetCardHeight(withTallVideo, column, 'en-US')
    const hLong = estimateTweetCardHeight(longText, column, 'en-US')
    // 真实宽高比是估高主项：16:9 图 > 纯文字；9:16 竖视频 > 16:9 图
    expect(hPhoto).toBeGreaterThan(hPlain)
    expect(hVideo).toBeGreaterThan(hPhoto)
    expect(hLong).toBeGreaterThan(hPlain)
    // 估高随列宽单调增长（媒体随列宽等比放大）
    expect(estimateTweetCardHeight(withPhoto, 500, 'en-US')).toBeGreaterThan(hPhoto)
    // 引用卡/链接卡/转贴行都增加估高
    const withQuote = tweet('openai', '5', {
      summary: 'short update',
      quote: { url: 'https://x.com/a/status/9', text: 'quoted', author_name: 'A', author: 'A' },
    })
    expect(estimateTweetCardHeight(withQuote, column, 'en-US')).toBeGreaterThan(hPlain)
    const withLink = tweet('openai', '6', {
      summary: 'short update',
      link_card: { url: 'https://example.com', title: 'Example' },
    })
    expect(estimateTweetCardHeight(withLink, column, 'en-US')).toBeGreaterThan(hPlain)
    const reposted = tweet('openai', '7', { summary: 'short update', retweeted_by: 'someone' })
    expect(estimateTweetCardHeight(reposted, column, 'en-US')).toBeGreaterThan(hPlain)
    // 中文界面用译文折行：译文明显更长（多折一行）时估高更高
    const translated = tweet('openai', '8', {
      summary: 'ok',
      translation_zh: '好的，这是一条明显更长的中文译文内容，用来验证中文界面按译文折行后估高随之增加',
    })
    expect(estimateTweetCardHeight(translated, column, 'zh-CN')).toBeGreaterThan(
      estimateTweetCardHeight(translated, column, 'en-US'),
    )
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

  it('emptyStateCopyKeys picks the recent copy for today', () => {
    // 早于最早数据日的标记在今天不参与判定
    expect(emptyStateCopyKeys({
      isToday: true, hasSnapshotDates: true, isBeforeEarliest: true,
    })).toEqual({ titleKey: 'xboard.emptyRecent', hintKey: 'xboard.emptyRecentHint' })
  })

  it('emptyStateCopyKeys flags dates earlier than the earliest data date', () => {
    expect(emptyStateCopyKeys({
      isToday: false, hasSnapshotDates: true, isBeforeEarliest: true,
    })).toEqual({ titleKey: 'xboard.emptyNoSnapshot', hintKey: 'xboard.emptyNoSnapshotHint' })
  })

  it('emptyStateCopyKeys falls back to the generic copy when the listing is unavailable or the date is within range', () => {
    // 清单加载失败（空）时无法判定早于最早数据日，回退通用空态，避免误报
    expect(emptyStateCopyKeys({
      isToday: false, hasSnapshotDates: false, isBeforeEarliest: true,
    })).toEqual({ titleKey: 'xboard.empty', hintKey: 'xboard.emptyHint' })
    // 选中日期在数据覆盖范围内但仍为空（该日窗口确实没有推文）→ 通用空态
    expect(emptyStateCopyKeys({
      isToday: false, hasSnapshotDates: true, isBeforeEarliest: false,
    })).toEqual({ titleKey: 'xboard.empty', hintKey: 'xboard.emptyHint' })
  })
})
