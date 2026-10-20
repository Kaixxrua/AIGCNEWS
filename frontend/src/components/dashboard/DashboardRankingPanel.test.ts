import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import DashboardRankingPanel from './DashboardRankingPanel.vue'
import i18n, { setAppLocale } from '@/i18n'
import type { TopDoc } from '@/features/dashboard/dashboardViewModel'
import { formatLocalTime } from '@/features/xboard/xBoardViewModel'

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

describe('X ranking timestamps', () => {
  const publishedAt = '2026-10-09T12:34:00Z'

  it('replaces likes with local publish time on all desktop rows', async () => {
    viewport.mobile = false
    const panel = await render()
    const docs = Array.from({ length: 10 }, (_, index) => ({
      ...tweet, id: `tweet-${index}`, title: `Tweet ${index}`, likes: 4638,
      published_at: publishedAt,
    }))
    await panel.setProps({ tabList: docs })

    const times = panel.findAll('.ranking-time')
    expect(times).toHaveLength(10)
    expect(panel.findAll('.ranking-row--featured .ranking-time')).toHaveLength(3)
    expect(panel.findAll('.ranking-row:not(.ranking-row--featured) .ranking-time')).toHaveLength(7)
    expect(times.map(time => time.text())).toEqual(Array(10).fill(formatLocalTime(publishedAt)))
    expect(times[0]!.attributes('datetime')).toBe(publishedAt)
    expect(panel.find('.ranking-score').exists()).toBe(false)
  })

  it('shows time on mobile and hides missing or invalid X timestamps without showing likes', async () => {
    const panel = await render({ ...tweet, likes: 4638, published_at: publishedAt })
    expect(panel.get('.tweet-preview__time').text()).toBe(formatLocalTime(publishedAt))
    expect(panel.get('.tweet-preview__time').attributes('datetime')).toBe(publishedAt)
    await panel.setProps({ tabList: [{ ...tweet, likes: 4638, published_at: 'invalid' }] })
    expect(panel.find('.tweet-preview__time').exists()).toBe(false)
    expect(panel.find('.ranking-score').exists()).toBe(false)
  })

  it('retains the score for other sources', async () => {
    viewport.mobile = false
    const panel = await render()
    await panel.setProps({ activeTab: 'github', tabList: [{ source: 'github', title: 'owner/repo', stars: 1200 }] })
    expect(panel.find('.ranking-time').exists()).toBe(false)
    expect(panel.get('.ranking-score').text()).toContain('1,200')
  })
})

describe('paper ranking', () => {
  const paper: TopDoc = {
    id: 'paper-1', source: 'arxiv', url: 'https://hf-mirror.com/papers/2610.00001',
    title: String.raw`\textbf{Aphanta}: Steering--Free Agents`,
    summary: String.raw`We present \emph{The Harness of Harnesses}, cutting cost by 2\%~\cite{x}.`,
  }
  const props = { activeTab: 'arxiv' as const, tabList: [paper], tabLoading: false, isViewingHistory: false, isFinalized: false, sourceStatus: {} }

  it('shows paper titles and summaries without LaTeX on desktop', async () => {
    viewport.mobile = false
    wrapper = mount(DashboardRankingPanel, { props, global: { plugins: [i18n] } })
    await flushPromises()
    expect(wrapper.get('.ranking-title').text()).toBe('Aphanta: Steering–Free Agents')
    expect(wrapper.get('.ranking-summary').text()).toBe('We present The Harness of Harnesses, cutting cost by 2%.')
  })

  it('shows paper titles and summaries without LaTeX on phones', async () => {
    viewport.mobile = true
    wrapper = mount(DashboardRankingPanel, { props, global: { plugins: [i18n] } })
    await flushPromises()
    expect(wrapper.get('.ranking-title').text()).toBe('Aphanta: Steering–Free Agents')
    expect(wrapper.get('.ranking-summary').text()).toBe('We present The Harness of Harnesses, cutting cost by 2%.')
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
    expect(panel.get('.ranking-heat').text()).toContain('96.3')
    await panel.setProps({ activeTab: 'arxiv', tabList: [{ source: 'arxiv', title: 'Paper' }] })
    expect(panel.find('.ranking-sort').exists()).toBe(false)
  })
  it.each([true, false])('prefers unlabeled rolling 24h growth over the daily delta (mobile=%s)', async (mobile) => {
    viewport.mobile = mobile
    const panel = await render({ source: 'github', title: 'owner/newborn',
      daily_star_growth: 0, daily_growth_available: true,
      rolling_24h_star_growth: 1765, rolling_24h_growth_source: 'since_creation' })
    await panel.setProps({ activeTab: 'github' })
    expect(panel.get('.ranking-growth').text()).toBe('+1,765')
    setAppLocale('en-US')
    await nextTick()
    expect(panel.get('.ranking-growth').text()).toBe('+1,765')
    await panel.setProps({ tabList: [{ source: 'github', title: 'owner/repo',
      daily_star_growth: 514, daily_growth_available: true, rolling_24h_star_growth: null }] })
    expect(panel.get('.ranking-growth').text()).toBe('+514 today')
  })
  it('does not substitute raw README or invent unavailable growth', async () => {
    const panel = await render({ source: 'github', title: 'owner/repo', summary: 'Raw README' })
    await panel.setProps({ activeTab: 'github' })
    expect(panel.text()).not.toContain('Raw README')
    expect(panel.find('.ranking-growth').exists()).toBe(false)
  })
})


describe('historical GitHub board quality', () => {
  const project: TopDoc = { id: 'repo', source: 'github', title: 'owner/repo', url: 'https://github.com/owner/repo', stars: 1000 }

  it('exposes crawlable news links and preserves opening a tab in another window', async () => {
    const panel = await render(project)
    const news = panel.get('#ranking-tab-news')
    expect(news.element.tagName).toBe('A')
    expect(news.attributes('href')).toBe('/?tab=news&lang=zh-CN')
    let prevented = true
    news.element.addEventListener('click', event => {
      prevented = event.defaultPrevented
      event.preventDefault() // jsdom cannot open the new document.
    }, { once: true })
    await news.trigger('click', { ctrlKey: true })
    expect(prevented).toBe(false)
    expect(panel.emitted('selectSource')).toBeUndefined()
    await news.trigger('click')
    expect(panel.emitted('selectSource')).toEqual([['news']])
    await news.trigger('keydown', { key: ' ' })
    expect(panel.emitted('selectSource')).toEqual([['news'], ['news']])
  })

  it('hides unavailable rankings, explains why, and keeps the other sources accessible', async () => {
    const panel = await render(project)
    await panel.setProps({ activeTab: 'github', isViewingHistory: true, isFinalized: true,
      sourceStatus: { github: { is_finalized: true, data_quality: { status: 'unavailable', reason: 'backfill_unverified' } } } })
    expect(panel.findAll('.ranking-row')).toHaveLength(0)
    expect(panel.get('.ranking-quality-empty').text()).toContain('补录记录尚不能确认当天的真实增长')
    expect(panel.get('.ranking-toolbar [role="status"]').text()).toBe('暂不可用')
    expect(panel.find('.ranking-sort').exists()).toBe(false)
    await panel.get('#ranking-tab-arxiv').trigger('click')
    expect(panel.emitted('selectSource')).toEqual([['arxiv']])
    await panel.setProps({ activeTab: 'arxiv', tabList: [{ id: 'paper', source: 'arxiv', title: 'Paper', url: 'https://example.org/paper' }] })
    expect(panel.find('.ranking-quality-empty').exists()).toBe(false)
    expect(panel.get('.ranking-title').text()).toBe('Paper')
    expect(panel.get('.ranking-toolbar [role="status"]').text()).toBe('已定稿')
  })

  it('retains partial rankings with a translated notice and clears it after switching dates', async () => {
    const panel = await render(project)
    await panel.setProps({ activeTab: 'github', isFinalized: true,
      sourceStatus: { github: { is_finalized: true, data_quality: { status: 'partial', reason: 'coverage_partial' } } } })
    expect(panel.get('.ranking-title').text()).toBe('owner/repo')
    expect(panel.get('.ranking-quality-notice').text()).toContain('部分项目未采集到')
    expect(panel.get('.ranking-toolbar [role="status"]').text()).toBe('数据不完整')
    setAppLocale('en-US')
    await nextTick()
    expect(panel.get('.ranking-quality-notice').text()).toContain('only the available sample')
    await panel.setProps({ tabLoading: true })
    expect(panel.find('.ranking-quality-notice').exists()).toBe(false)
    await panel.setProps({ tabLoading: false, sourceStatus: { github: { is_finalized: true, data_quality: { status: 'available', reason: null } } } })
    expect(panel.find('.ranking-quality-notice').exists()).toBe(false)
    expect(panel.findAll('.ranking-row')).toHaveLength(1)
    expect(panel.get('.ranking-toolbar [role="status"]').text()).toBe('Finalized')
  })
})
