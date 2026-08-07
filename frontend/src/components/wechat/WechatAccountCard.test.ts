import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { describe, expect, it } from 'vitest'
import WechatAccountCard from './WechatAccountCard.vue'
import type { WeChatArticle, WeChatFeedEntry } from '@/features/wechat/wechatModel'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      wechat: {
        unnamedAccount: '未命名公众号',
        untitledArticle: '（无标题）',
        noRecentArticles: '暂无最近消息',
        readOriginal: '阅读原文',
        fullTextLoading: '全文加载中…',
        retry: '重试',
      },
    },
  },
})

const makeArticle = (overrides: Partial<WeChatArticle> = {}): WeChatArticle => ({
  id: 11,
  account_id: 1,
  stable_article_key: 'k-1',
  message_id: 'm-1',
  itemidx: 1,
  title: '标题',
  digest: '摘要：正文开头截断…',
  author: '作者',
  article_url: '',
  cover_url: '',
  source_url: '',
  has_content: false,
  published_at: null,
  ...overrides,
})

const makeEntry = (article: WeChatArticle, avatarUrl = ''): WeChatFeedEntry => ({
  account: {
    id: 1,
    nickname: '某公众号',
    alias: '',
    avatar_url: avatarUrl,
    signature: '',
    sort_order: 0,
    followed: true,
  },
  articles: [article],
})

const mountCard = (entry: WeChatFeedEntry, expandedKeys: Set<string>) =>
  mount(WechatAccountCard, {
    global: { plugins: [i18n] },
    props: {
      entry,
      expandedArticleKeys: expandedKeys,
      articleKey: (accountId: number, articleId: number | null, stableKey: string) =>
        `${accountId}:${articleId ?? stableKey}`,
      articleDetails: new Map(),
      articleDetailLoading: new Set(),
      articleDetailErrors: new Map(),
    },
  })

describe('WechatAccountCard', () => {
  it('routes the account avatar through the media proxy with https upgrade', () => {
    const card = mountCard(
      makeEntry(makeArticle(), 'http://mmbiz.qpic.cn/mmbiz_png/avatar/0?wx_fmt=png'),
      new Set(),
    )
    const avatar = card.find('.account-card-avatar')
    expect(avatar.exists()).toBe(true)
    expect(avatar.attributes('src')).toBe(
      `/api/media/wechat/proxy?url=${encodeURIComponent(
        'https://mmbiz.qpic.cn/mmbiz_png/avatar/0?wx_fmt=png',
      )}`,
    )
  })

  it('routes the article cover through the media proxy', () => {
    const article = makeArticle({ cover_url: 'https://mmbiz.qpic.cn/sz_mmbiz_jpg/c/0?wx_fmt=jpeg' })
    const card = mountCard(makeEntry(article), new Set(['1:11']))
    const cover = card.find('.article-cover')
    expect(cover.exists()).toBe(true)
    expect(cover.attributes('src')).toBe(
      `/api/media/wechat/proxy?url=${encodeURIComponent(article.cover_url)}`,
    )
  })

  it('hides the digest when full text is available, shows it otherwise', () => {
    const withContent = mountCard(makeEntry(makeArticle({ has_content: true })), new Set(['1:11']))
    expect(withContent.find('.article-digest').exists()).toBe(false)

    const withoutContent = mountCard(makeEntry(makeArticle({ has_content: false })), new Set(['1:11']))
    expect(withoutContent.find('.article-digest').exists()).toBe(true)
  })
})
