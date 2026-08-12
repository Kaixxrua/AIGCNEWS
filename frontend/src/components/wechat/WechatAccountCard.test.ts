import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { describe, expect, it, vi } from 'vitest'
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
        fullTextRedirect: '本站仅提供摘要，全文请前往公众号原文阅读。',
        fullTextLoading: '全文加载中…',
        retry: '重试',
        backToArticleTop: '回到文章顶部',
        skipToArticleEnd: '跳到文章末尾',
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
  created_at: null,
  updated_at: null,
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

const mountCard = (entry: WeChatFeedEntry, expandedKeys: Set<string>, isAdmin = false) =>
  mount(WechatAccountCard, {
    global: { plugins: [i18n] },
    props: {
      entry,
      isAdmin,
      expandedArticleKeys: expandedKeys,
      articleKey: (accountId: number, articleId: number | null, stableKey: string) =>
        `${accountId}:${articleId ?? stableKey}`,
      articleDetails: new Map(),
      articleDetailLoading: new Set<string>(),
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

  it('admin hides the digest when full text is available, shows it otherwise', () => {
    const withContent = mountCard(makeEntry(makeArticle({ has_content: true })), new Set(['1:11']), true)
    expect(withContent.find('.article-digest').exists()).toBe(false)

    const withoutContent = mountCard(makeEntry(makeArticle({ has_content: false })), new Set(['1:11']), true)
    expect(withoutContent.find('.article-digest').exists()).toBe(true)
  })

  it('non-admin always sees the digest plus the full-text redirect hint, never the body', () => {
    const card = mountCard(
      makeEntry(makeArticle({ has_content: true })),
      new Set(['1:11']),
      false,
    )
    expect(card.find('.article-digest').exists()).toBe(true)
    expect(card.find('.article-fulltext-hint').exists()).toBe(true)
    expect(card.find('.wechat-article-content').exists()).toBe(false)
    expect(card.find('.article-nav').exists()).toBe(false)
  })

  it('non-admin summary click toggles the panel without requesting the article body', async () => {
    const card = mountCard(
      makeEntry(makeArticle({ has_content: true })),
      new Set(),
      false,
    )
    await card.find('.article-summary').trigger('click')
    const events = card.emitted('toggleArticle')
    expect(events).toEqual([['1:11']])
  })

  it('admin summary click carries the article so the controller fetches the body', async () => {
    const article = makeArticle({ has_content: true })
    const card = mountCard(makeEntry(article), new Set(), true)
    await card.find('.article-summary').trigger('click')
    const events = card.emitted('toggleArticle')
    expect(events).toEqual([['1:11', 1, article]])
  })

  it('admin sees in-article jump buttons only when the article is expanded', () => {
    const collapsed = mountCard(makeEntry(makeArticle({ has_content: true })), new Set(), true)
    expect(collapsed.find('.article-nav').exists()).toBe(false)

    const expanded = mountCard(makeEntry(makeArticle({ has_content: true })), new Set(['1:11']), true)
    expect(expanded.find('.article-detail-shell').exists()).toBe(true)
    const buttons = expanded.findAll('.article-nav-btn')
    expect(buttons).toHaveLength(2)
    const [topButton, bottomButton] = buttons
    expect(topButton?.attributes('aria-label')).toBe('回到文章顶部')
    expect(bottomButton?.attributes('aria-label')).toBe('跳到文章末尾')
  })

  it('scrolls to the article summary on top jump and to the end sentinel on bottom jump', async () => {
    // jsdom 未实现 scrollIntoView，测试环境手动装/卸桩
    const spy = vi.fn()
    const original = Element.prototype.scrollIntoView
    Element.prototype.scrollIntoView = spy
    try {
      const card = mountCard(makeEntry(makeArticle({ has_content: true })), new Set(['1:11']), true)
      const [topButton, bottomButton] = card.findAll('.article-nav-btn')

      await topButton?.trigger('click')
      expect(spy).toHaveBeenCalledTimes(1)
      expect(spy).toHaveBeenLastCalledWith({ behavior: 'smooth', block: 'start' })
      expect(spy.mock.instances[0]).toBe(card.find('.article-summary').element)

      await bottomButton?.trigger('click')
      expect(spy).toHaveBeenCalledTimes(2)
      expect(spy).toHaveBeenLastCalledWith({ behavior: 'smooth', block: 'end' })
      expect(spy.mock.instances[1]).toBe(card.find('.article-detail-end').element)
    } finally {
      if (original) {
        Element.prototype.scrollIntoView = original
      } else {
        delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView
      }
    }
  })
})
