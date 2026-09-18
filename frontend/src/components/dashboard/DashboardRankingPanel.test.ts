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
  it('keeps one board status in the toolbar instead of a duplicate banner', async () => {
    const panel = await render()
    expect(panel.findAll('[role="status"]')).toHaveLength(1)
    expect(panel.get('.ranking-toolbar [role="status"]').text()).toContain('实时初榜')
    await panel.setProps({ isFinalized: true })
    expect(panel.get('[role="status"]').text()).toContain('定稿')
  })
  it('preserves ten ordered links and actual summaries with three featured entries', async () => {
    viewport.mobile = false
    const panel = await render()
    const docs = Array.from({ length: 10 }, (_, i) => ({
      id: i, source: 'github', title: `owner/project-${i}`,
      url: `https://github.com/owner/project-${i}`, summary: `Project description ${i}`, stars: 1000 + i,
    }))
    await panel.setProps({ activeTab: 'github', tabList: docs })
    expect(panel.findAll('.ranking-row--featured')).toHaveLength(3)
    expect(panel.findAll('.ranking-link').map(link => link.attributes('href'))).toEqual(docs.map(doc => doc.url))
    expect(panel.findAll('.ranking-summary').map(el => el.text())).toEqual(docs.map(doc => doc.summary))
    const avatar = panel.get('.ranking-avatar img')
    expect(avatar.attributes('src')).toBe('https://github.com/owner.png?size=128')
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
    await sources[0]!.trigger('click')
    expect(panel.emitted('selectSource')).toEqual([['github']])
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
