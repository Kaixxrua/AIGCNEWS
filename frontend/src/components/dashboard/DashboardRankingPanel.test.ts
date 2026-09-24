import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import DashboardRankingPanel from './DashboardRankingPanel.vue'
import i18n, { setAppLocale } from '@/i18n'
import type { TopDoc } from '@/features/dashboard/dashboardViewModel'

const viewport = vi.hoisted(() => ({ mobile: true }))
vi.mock('@vueuse/core', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@vueuse/core')>()
  const { ref } = await import('vue')
  return { ...actual, useMediaQuery: () => ref(viewport.mobile) }
})

let wrapper: VueWrapper | undefined
let textHeight = 400
const tweet: TopDoc = {
  id: 'tweet-1', source: 'x', author_name: 'OpenAI',
  url: 'https://x.com/OpenAI/status/123',
  title: 'First paragraph. Second paragraph.',
  summary: 'First paragraph.\n\nSecond paragraph.',
}

beforeEach(() => {
  viewport.mobile = true
  textHeight = 400
  setAppLocale('zh-CN')
  vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockImplementation(function (this: HTMLElement) {
    return this.classList.contains('tweet-preview__text') ? textHeight : 0
  })
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(106)
})
afterEach(() => { wrapper?.unmount(); vi.restoreAllMocks(); setAppLocale('zh-CN') })

const render = async (doc = tweet) => {
  wrapper = mount(DashboardRankingPanel, {
    props: { activeTab: 'x', tabList: [doc], tabLoading: false, isViewingHistory: false, isFinalized: false, sourceStatus: {} },
    global: { plugins: [i18n] },
  })
  await flushPromises()
  return wrapper
}

describe('mobile ranking reading', () => {
  it('shows the stored Chinese translation on desktop and restores the original in English', async () => {
    viewport.mobile = false
    const panel = await render({ ...tweet, translation_zh: '已采集的中文正文。' })
    expect(panel.get('.ranking-title').text()).toBe('已采集的中文正文。')
    expect(panel.find('.ranking-summary').exists()).toBe(false)
    setAppLocale('en-US')
    await flushPromises()
    expect(panel.get('.ranking-title').text()).toBe(tweet.title)
    expect(panel.get('.ranking-link').attributes('href')).toBe(tweet.url)
    setAppLocale('zh-CN')
    await panel.setProps({ tabList: [{ ...tweet, translation_zh: '   ' }] })
    expect(panel.get('.ranking-title').text()).toBe(tweet.title)
  })

  it.each([true, false])('shows the stored tweet avatar (mobile=%s) and recovers after a row changes', async (mobile) => {
    viewport.mobile = mobile
    const panel = await render({ ...tweet, author_avatar_url: 'https://pbs.twimg.com/profile_images/one.jpg' })
    expect(panel.get('.ranking-avatar img').attributes('src')).toBe('/api/media/x/img/pbs.twimg.com/profile_images/one.jpg')
    await panel.get('.ranking-avatar img').trigger('error')
    expect(panel.find('.ranking-avatar img').exists()).toBe(false)
    expect(panel.get('.ranking-avatar').text()).toBe('O')
    await panel.setProps({ tabList: [{ ...tweet, author_avatar_url: 'https://pbs.twimg.com/profile_images/two.jpg' }] })
    expect(panel.get('.ranking-avatar img').attributes('src')).toContain('two.jpg')
  })

  it('shows product thumbnails and falls back when unavailable', async () => {
    const panel = await render()
    const product: TopDoc = { source: 'producthunt', title: 'Product', url: 'https://www.producthunt.com/posts/product',
      link_card: { url: 'https://www.producthunt.com/posts/product', title: 'Product', image_url: 'https://ph-files.imgix.net/product.png' } }
    await panel.setProps({ activeTab: 'producthunt', tabList: [product] })
    expect(panel.get('.ranking-avatar img').attributes('src')).toBe(product.link_card!.image_url)
    await panel.get('.ranking-avatar img').trigger('load')
    expect(panel.get('.ranking-avatar img').classes()).toContain('loaded')
    await panel.get('.ranking-avatar img').trigger('error')
    expect(panel.get('.ranking-avatar').text()).toBe('P')
    await panel.setProps({ tabList: [{ ...product, link_card: null }] })
    expect(panel.find('.ranking-avatar img').exists()).toBe(false)
    await panel.setProps({ tabList: [{ ...product, image_url: 'javascript:alert(1)', link_card: null }] })
    expect(panel.find('.ranking-avatar img').exists()).toBe(false)
  })

  it('keeps one board status in the toolbar instead of a duplicate banner', async () => {
    const panel = await render()
    expect(panel.findAll('[role="status"]')).toHaveLength(1)
    expect(panel.get('.ranking-toolbar [role="status"]').text()).toBe('初榜 · 采集中')
    expect(panel.get('[role="status"]').attributes('title')).toContain('数据仍在采集中')
    await panel.setProps({ isFinalized: true })
    expect(panel.get('[role="status"]').text()).toContain('定稿')
  })
  it('preserves ten ordered links and actual summaries with three featured entries', async () => {
    viewport.mobile = false
    const panel = await render()
    const docs = Array.from({ length: 10 }, (_, i) => ({
      id: i, source: 'github', title: `owner/project-${i}`,
      url: `https://github.com/owner/project-${i}`, summary: `Raw README ${i}`, description_zh: `项目简介 ${i}`, stars: 1000 + i,
    }))
    await panel.setProps({ activeTab: 'github', tabList: docs })
    expect(panel.findAll('.ranking-row--featured')).toHaveLength(3)
    expect(panel.findAll('.ranking-link').map(link => link.attributes('href'))).toEqual(docs.map(doc => doc.url))
    expect(panel.findAll('.ranking-summary').map(el => el.text())).toEqual(docs.map(doc => doc.description_zh))
    const avatar = panel.get('.ranking-avatar img')
    expect(avatar.attributes('src')).toBe('/api/projects/github/logo/owner/project-0')
    await avatar.trigger('error')
    expect(panel.get('.ranking-avatar').text()).toBe('O')
    expect(panel.get('.ranking-number').text()).toBe('01')
  })
  it('renders a tweet once as body text, with independent expand and original-link actions', async () => {
    const panel = await render()
    expect(panel.find('.ranking-title').exists()).toBe(false)
    expect(panel.findAll('.tweet-preview__text')).toHaveLength(1)
    expect(panel.get('.tweet-preview__text').text()).toBe(tweet.summary)
    expect(panel.get('.tweet-preview__author').text()).toContain('OpenAI')
    const expand = panel.get('.tweet-preview__actions button')
    expect(expand.attributes('aria-expanded')).toBe('false')
    await expand.trigger('click')
    expect(expand.attributes('aria-expanded')).toBe('true')
    await expand.trigger('click')
    expect(expand.attributes('aria-expanded')).toBe('false')
    expect(panel.get('.tweet-preview__actions a').attributes('href')).toBe(tweet.url)
    expect(panel.find('a button').exists()).toBe(false)
  })

  it('uses an available translation and resets expansion when the displayed language changes', async () => {
    const panel = await render({ ...tweet, translation_zh: '已采集的中文正文。' })
    expect(panel.get('.tweet-preview__text').text()).toBe('已采集的中文正文。')
    await panel.get('.tweet-preview__actions button').trigger('click')
    setAppLocale('en-US')
    await flushPromises()
    expect(panel.get('.tweet-preview__text').text()).toBe(tweet.summary)
    expect(panel.get('.tweet-preview__actions button').attributes('aria-expanded')).toBe('false')
  })

  it('omits an unnecessary expand action for a short post and exposes all source choices', async () => {
    textHeight = 53
    const panel = await render()
    expect(panel.find('.tweet-preview__actions button').exists()).toBe(false)
    const sources = panel.findAll('[role="tab"]')
    expect(sources).toHaveLength(6)
    expect(sources.map(source => source.attributes('aria-label'))).toEqual([
      'GitHub', '论文', '新闻', 'AI 产品', '极客热议', 'X 推文动态',
    ])
    expect(sources[4]!.attributes('title')).toBe('Hacker News')
    for (const source of sources) await source.trigger('click')
    expect(panel.emitted('selectSource')).toEqual([
      ['github'], ['arxiv'], ['news'], ['producthunt'], ['hackernews'], ['x'],
    ])
  })

  it('preserves desktop links and suppresses a summary that differs only in whitespace', async () => {
    viewport.mobile = false
    const panel = await render()
    await nextTick()
    expect(panel.find('.tweet-preview').exists()).toBe(false)
    expect(panel.get('.ranking-link').attributes('href')).toBe(tweet.url)
    expect(panel.get('.ranking-title').text()).toBe(tweet.title)
    expect(panel.find('.ranking-summary').exists()).toBe(false)
  })
})

describe('enriched GitHub ranking', () => {
  it('switches enriched descriptions with locale and shows daily star growth', async () => {
    const panel = await render({ source: 'github', title: 'owner/repo', summary: 'Raw README',
      description_zh: '富化中文简介', description_en: 'Enriched English summary',
      daily_star_growth: 514, daily_growth_available: true })
    await panel.setProps({ activeTab: 'github' })
    expect(panel.get('.ranking-summary').text()).toBe('富化中文简介')
    expect(panel.get('.ranking-growth').text()).toContain('+514')
    setAppLocale('en-US')
    await nextTick()
    expect(panel.get('.ranking-summary').text()).toBe('Enriched English summary')
    expect(panel.text()).not.toContain('Raw README')
  })
  it('keeps the available enriched language when the requested translation is missing', async () => {
    const panel = await render({ source: 'github', title: 'owner/repo', summary: 'Raw README',
      description_zh: '已有中文简介', description_en: '   ', language: 'Python', tags: ['agents'] })
    await panel.setProps({ activeTab: 'github' })
    setAppLocale('en-US')
    await nextTick()
    expect(panel.get('.ranking-summary').text()).toBe('已有中文简介')
    expect(panel.text()).not.toContain('Raw README')
    expect(panel.text()).not.toContain('Python')
    await panel.setProps({ tabList: [{ source: 'github', description_en: 'Available English' }] })
    setAppLocale('zh-CN')
    await nextTick()
    expect(panel.get('.ranking-summary').text()).toBe('Available English')
  })
  it('uses the catalog English short description before Chinese, while preferring enrichment', async () => {
    const panel = await render({ source: 'github', title: 'latent-spaces/brag', summary: '# Raw README',
      description: 'Turn your project into a short launch video.', description_zh: '中文富化简介' })
    await panel.setProps({ activeTab: 'github' })
    setAppLocale('en-US')
    await nextTick()
    expect(panel.get('.ranking-summary').text()).toBe('Turn your project into a short launch video.')
    await panel.setProps({ tabList: [{ source: 'github', description: 'Repository short description', description_en: 'Enriched English' }] })
    expect(panel.get('.ranking-summary').text()).toBe('Enriched English')
    expect(panel.text()).not.toContain('Raw README')
  })
  it('names heat as the GitHub sort key and leads each row with it', async () => {
    const panel = await render()
    expect(panel.find('.ranking-sort').exists()).toBe(false)
    await panel.setProps({ activeTab: 'github', tabList: [] })
    expect(panel.find('.ranking-sort').exists()).toBe(false)
    await panel.setProps({ tabList: [{ source: 'github', title: 'owner/repo', hot_score: 87.25,
      daily_star_growth: 514, daily_growth_available: true, stars: 1200 }] })
    const sort = panel.get('.ranking-toolbar .ranking-sort')
    expect(sort.text()).toBe('按热度排序')
    expect(sort.attributes('title')).toBe(i18n.global.t('projects.hotScoreTitle'))
    expect(panel.get('.ranking-meta').element.firstElementChild?.classList.contains('ranking-heat')).toBe(true)
    expect(panel.get('.ranking-heat').text()).toContain('87.3')
    await panel.setProps({ activeTab: 'arxiv', tabList: [{ source: 'arxiv', title: 'Paper' }] })
    expect(panel.find('.ranking-sort').exists()).toBe(false)
  })
  it('does not substitute raw README or invent unavailable growth', async () => {
    const panel = await render({ source: 'github', title: 'owner/repo', summary: 'Raw README' })
    await panel.setProps({ activeTab: 'github' })
    expect(panel.text()).not.toContain('Raw README')
    expect(panel.find('.ranking-growth').exists()).toBe(false)
  })
})
