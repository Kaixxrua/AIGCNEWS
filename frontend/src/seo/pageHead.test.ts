/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { flushPromises, mount } from '@vue/test-utils'
import { KeepAlive, defineComponent, h, nextTick, ref, type VNode } from 'vue'
import { RouterView, createMemoryHistory, createRouter, type RouteLocationNormalizedLoaded } from 'vue-router'
import { afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'
import { i18n } from '@/i18n'
import { installSeoMessages } from '@/i18n/locales/seo'
import { __resetPageHeadForTest, applyPageHead, installPageHead, resolvePageHead, usePageHead } from './pageHead'

// vitest 从 frontend 根目录运行（与 cspHashContract.test.ts 相同）。
const frontendRoot = process.cwd()
const t = (key: string) => i18n.global.t(key)

const at = (name: string | undefined, path: string, query: Record<string, string> = {}) =>
  ({ name, path, query, params: {}, hash: '', fullPath: path, matched: [], meta: {}, redirectedFrom: undefined }) as unknown as RouteLocationNormalizedLoaded

const headTag = (selector: string) => document.head.querySelector(selector)

beforeAll(() => installSeoMessages())

beforeEach(() => {
  i18n.global.locale.value = 'zh-CN'
  document.head.innerHTML = '<meta name="description" content="static"><meta property="og:url" content="https://aigcnews.cn">'
  document.title = 'static'
})

afterEach(() => {
  __resetPageHeadForTest()
  i18n.global.locale.value = 'zh-CN'
})

describe('resolvePageHead', () => {
  it('gives every named route its own title in both languages, and the home title matches index.html', () => {
    const routerSource = readFileSync(`${frontendRoot}/src/router/index.ts`, 'utf-8')
    const names = [...routerSource.matchAll(/name: '([^']+)'/g)].map((match) => match[1]!)
    expect(names.length).toBeGreaterThan(15)
    for (const locale of ['zh-CN', 'en-US'] as const) {
      i18n.global.locale.value = locale
      const titles = names.map((name) => resolvePageHead(at(name, '/'), null, t).title)
      titles.forEach((title, index) => {
        expect(title, names[index]).not.toContain('seo.')
        if (names[index] !== 'dashboard') expect(title, names[index]).toMatch(/^.+ · AIGCNEWS$/)
      })
      // 两个 OAuth 回调页同为「登录」，其余各不相同。
      expect(new Set(titles).size).toBe(names.length - 1)
    }
    i18n.global.locale.value = 'zh-CN'
    const indexTitle = /<title>([^<]+)<\/title>/.exec(readFileSync(`${frontendRoot}/index.html`, 'utf-8'))?.[1]
    expect(resolvePageHead(at('dashboard', '/'), null, t).title).toBe(indexTitle)
  })

  it('falls back to the brand title and the default description', () => {
    const unknown = resolvePageHead(at(undefined, '/somewhere'), null, t)
    expect(unknown.title).toBe(t('seo.titles.home'))
    expect(unknown.description).toBe(t('seo.descriptions.default'))
    expect(resolvePageHead(at('register', '/register'), null, t).description).toBe(t('seo.descriptions.default'))
    expect(resolvePageHead(at('mcp-connect', '/mcp'), null, t).description).toBe(t('seo.descriptions.mcp'))
  })

  it('points the canonical URL at the main site and keeps only the query params that change the content', () => {
    expect(resolvePageHead(at('dashboard', '/'), null, t).canonical).toBe('https://aigcnews.cn/')
    expect(resolvePageHead(at('github-projects', '/projects/', { q: 'agent', channel: 'weekly' }), null, t).canonical)
      .toBe('https://aigcnews.cn/projects')
    const websites = resolvePageHead(at('github-projects', '/projects', { source: 'website', q: 'ai' }), null, t)
    expect(websites.title).toBe('我的网页收藏 · AIGCNEWS')
    expect(websites.canonical).toBe('https://aigcnews.cn/projects?source=website')
    const briefing = resolvePageHead(
      at('report', '/report', { date: '2026-10-03', subscribe: '1' }),
      { canonicalQuery: { date: '2026-10-03', type: null } },
      t,
    )
    expect(briefing.canonical).toBe('https://aigcnews.cn/report?date=2026-10-03')
  })

  it('uses the page’s own title, and a compacted description clipped to 160 characters', () => {
    const paperPage = at('paper-read', '/papers/1/read')
    const head = resolvePageHead(paperPage, { title: '  Attention \n Is All  You Need ', description: `${'长摘要'.repeat(60)}\n\n  tail` }, t)
    expect(head.title).toBe('Attention Is All You Need · AIGCNEWS')
    expect([...head.description]).toHaveLength(160)
    expect(head.description.endsWith('…')).toBe(true)
    expect(resolvePageHead(paperPage, { description: 'Short\n  summary.' }, t).description).toBe('Short summary.')
    // 空标题、空摘要沿用路由级的默认值。
    expect(resolvePageHead(paperPage, { title: '  ', description: '' }, t)).toMatchObject({
      title: '论文 · AIGCNEWS',
      description: t('seo.descriptions.default'),
    })
  })

  it('marks missing content noindex and gives it no canonical', () => {
    expect(resolvePageHead(at('paper-read', '/papers/404/read'), { noindex: true }, t))
      .toMatchObject({ title: '论文 · AIGCNEWS', noindex: true, canonical: null })
    // 未知地址的兜底页本身就是「没有这一页」，不用页面另外声明。
    expect(resolvePageHead(at('not-found', '/no-such-page'), null, t))
      .toMatchObject({ title: '页面不存在 · AIGCNEWS', noindex: true, canonical: null })
    // MCP OAuth 同意页只给客户端跳转用，带着一次性的授权参数，不该被收录。
    expect(resolvePageHead(at('oauth-authorize', '/oauth/authorize'), null, t))
      .toMatchObject({ title: '授权 MCP 客户端 · AIGCNEWS', noindex: true, canonical: null })
    expect(resolvePageHead(at('wechat-login', '/oauth/wechat', { redirect: '/membership' }), null, t))
      .toMatchObject({ title: '微信扫码登录 · AIGCNEWS', noindex: true, canonical: null })
  })
})

describe('applyPageHead', () => {
  it('updates the static tags in place and adds or removes robots and canonical', () => {
    applyPageHead(document, resolvePageHead(at('paper-read', '/papers/404/read'), { noindex: true }, t))
    expect(document.title).toBe('论文 · AIGCNEWS')
    expect(document.head.querySelectorAll('meta[name="description"]')).toHaveLength(1)
    expect(headTag('meta[name="robots"]')?.getAttribute('content')).toBe('noindex')
    expect(headTag('link[rel="canonical"]')).toBeNull()
    expect(headTag('meta[property="og:url"]')?.getAttribute('content')).toBe('https://aigcnews.cn/')

    const library = resolvePageHead(at('ui-library', '/ui-library'), null, t)
    applyPageHead(document, library)
    applyPageHead(document, library)
    expect(headTag('meta[name="robots"]')).toBeNull()
    expect(headTag('meta[name="description"]')?.getAttribute('content')).toBe(t('seo.descriptions.uiLibrary'))
    expect(headTag('meta[property="og:title"]')?.getAttribute('content')).toBe('UI 灵感库 · AIGCNEWS')
    expect(headTag('meta[property="og:url"]')?.getAttribute('content')).toBe('https://aigcnews.cn/ui-library')
    expect(document.head.querySelectorAll('link[rel="canonical"]')).toHaveLength(1)
    expect(headTag('link[rel="canonical"]')?.getAttribute('href')).toBe('https://aigcnews.cn/ui-library')
  })
})

describe('installPageHead', () => {
  it('follows the route, the language and the open view’s own head, and drops that head when the view goes away', async () => {
    const paperTitle = ref<string | null>(null)
    const PaperStub = defineComponent({
      name: 'PaperStub',
      setup() {
        usePageHead(() => (paperTitle.value ? { title: paperTitle.value } : null))
        return () => h('article')
      },
    })
    const PlainStub = defineComponent({ name: 'PlainStub', setup: () => () => h('div') })
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'dashboard', component: PlainStub },
        { path: '/report', name: 'report', component: PlainStub },
        { path: '/papers/:id/read', name: 'paper-read', component: PaperStub },
      ],
    })
    // 与 LayoutView 一样把视图放进 KeepAlive：离开的页面只是停用，没有卸载。
    const showViews = ref(true)
    const App = defineComponent({
      setup: () => () => showViews.value
        ? h(RouterView, null, { default: ({ Component }: { Component?: VNode }) => h(KeepAlive, null, { default: () => Component }) })
        : h('p'),
    })
    await router.push('/papers/1/read')
    const stop = installPageHead(router, document)
    const wrapper = mount(App, { global: { plugins: [router, i18n] } })
    await flushPromises()
    expect(document.title).toBe('论文 · AIGCNEWS')

    paperTitle.value = 'Attention Is All You Need'
    await nextTick()
    expect(document.title).toBe('Attention Is All You Need · AIGCNEWS')
    expect(headTag('link[rel="canonical"]')?.getAttribute('href')).toBe('https://aigcnews.cn/papers/1/read')

    await router.push('/report')
    await flushPromises()
    expect(document.title).toBe('每日 AIGC 简报 · AIGCNEWS')
    expect(headTag('link[rel="canonical"]')?.getAttribute('href')).toBe('https://aigcnews.cn/report')

    i18n.global.locale.value = 'en-US'
    await nextTick()
    expect(document.title).toBe('Daily AIGC Briefing · AIGCNEWS')

    // 缓存着的论文页回到前台，它自己的标题跟着回来。
    await router.push('/papers/1/read')
    await flushPromises()
    expect(document.title).toBe('Attention Is All You Need · AIGCNEWS')

    // 视图卸载（路由不变）：撤掉它登记的标题，回到路由级的默认值。
    showViews.value = false
    await flushPromises()
    expect(document.title).toBe('Paper · AIGCNEWS')
    stop()
    wrapper.unmount()
  })
})
