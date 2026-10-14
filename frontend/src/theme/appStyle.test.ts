import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import {
  applyAppStyle,
  applyDocumentStyle,
  DEFAULT_STYLE,
  installAppStyle,
  persistAppStyle,
  resolveAppStyle,
  setAppStyle,
  STYLE_ATTRIBUTE,
  STYLE_STORAGE_KEY,
  useAppStyle,
} from './index'
import { consumeStyleParam } from './appStyle'
import { ensureSimpleStyles, resetSimpleStylesForTest } from './simpleStyles'

const simpleLinks = () => document.head.querySelectorAll<HTMLLinkElement>('link[data-app-style="simple"]')

// jsdom 不下载样式表，加载完成或失败由测试来报。
const finishLoading = (type: 'load' | 'error' = 'load') => {
  const links = simpleLinks()
  links[links.length - 1]?.dispatchEvent(new Event(type))
}

const forgetStylesheet = () => {
  simpleLinks().forEach((link) => link.remove())
  resetSimpleStylesForTest()
}

describe('application style contract', () => {
  beforeEach(() => {
    applyAppStyle('comic')
    localStorage.clear()
    forgetStylesheet()
    window.history.replaceState(null, '', '/')
  })

  afterEach(() => {
    applyAppStyle('comic')
    forgetStylesheet()
  })

  it('opens in the comic style unless something chose the simple one', () => {
    expect(DEFAULT_STYLE).toBe('comic')
    expect(resolveAppStyle({ storage: localStorage, search: '' })).toBe('comic')
    expect(resolveAppStyle({ storage: null, search: '' })).toBe('comic')
  })

  it('prefers a valid stored style and ignores an invalid one', () => {
    localStorage.setItem(STYLE_STORAGE_KEY, 'simple')
    expect(resolveAppStyle({ storage: localStorage, search: '' })).toBe('simple')
    localStorage.setItem(STYLE_STORAGE_KEY, 'neon')
    expect(resolveAppStyle({ storage: localStorage, search: '' })).toBe('comic')
  })

  it('lets a shared link pick the style over the stored one', () => {
    localStorage.setItem(STYLE_STORAGE_KEY, 'comic')
    expect(resolveAppStyle({ storage: localStorage, search: '?style=simple' })).toBe('simple')
    expect(resolveAppStyle({ storage: localStorage, search: '?style=fancy' })).toBe('comic')
  })

  it('persists the choice and swallows storage errors', () => {
    persistAppStyle('simple', localStorage)
    expect(localStorage.getItem(STYLE_STORAGE_KEY)).toBe('simple')
    const blocked: Pick<Storage, 'setItem'> = { setItem: () => { throw new Error('blocked') } }
    expect(() => persistAppStyle('comic', blocked)).not.toThrow()
  })

  it('marks the document only for the simple style', () => {
    applyDocumentStyle('simple', document.documentElement)
    expect(document.documentElement.getAttribute(STYLE_ATTRIBUTE)).toBe('simple')
    applyDocumentStyle('comic', document.documentElement)
    expect(document.documentElement.hasAttribute(STYLE_ATTRIBUTE)).toBe(false)
  })

  it('takes ?style= out of the address and keeps everything else', () => {
    window.history.replaceState({ keep: 1 }, '', '/projects?q=rag&style=simple&page=2#top')
    expect(consumeStyleParam()).toBe('simple')
    expect(`${location.pathname}${location.search}${location.hash}`).toBe('/projects?q=rag&page=2#top')
    expect(history.state).toEqual({ keep: 1 })
  })

  it('leaves the address alone when the parameter is missing or invalid', () => {
    window.history.replaceState(null, '', '/x?style=fancy')
    expect(consumeStyleParam()).toBeNull()
    expect(`${location.pathname}${location.search}`).toBe('/x?style=fancy')
  })

  it('opens a shared ?style=simple link in the simple style once its stylesheet is in', async () => {
    window.history.replaceState(null, '', '/?style=simple')
    let ready = false
    const install = installAppStyle().then(() => { ready = true })

    expect(location.search).toBe('')
    expect(localStorage.getItem(STYLE_STORAGE_KEY)).toBe('simple')
    expect(document.documentElement.getAttribute(STYLE_ATTRIBUTE)).toBe('simple')
    expect(useAppStyle().style.value).toBe('simple')
    expect(simpleLinks()).toHaveLength(1)
    await Promise.resolve()
    expect(ready).toBe(false)

    finishLoading()
    await install
    expect(ready).toBe(true)
  })

  it('opens in the stored style when the address does not say', async () => {
    localStorage.setItem(STYLE_STORAGE_KEY, 'simple')
    const install = installAppStyle()
    expect(document.documentElement.getAttribute(STYLE_ATTRIBUTE)).toBe('simple')
    finishLoading()
    await install
    expect(useAppStyle().style.value).toBe('simple')
  })

  it('opens in the comic style without downloading the simple stylesheet', async () => {
    await installAppStyle()
    expect(document.documentElement.hasAttribute(STYLE_ATTRIBUTE)).toBe(false)
    expect(useAppStyle().style.value).toBe('comic')
    expect(simpleLinks()).toHaveLength(0)
  })

  it('switches to the simple style only after its stylesheet is in, and back without unloading it', async () => {
    const switching = setAppStyle('simple')
    expect(document.documentElement.hasAttribute(STYLE_ATTRIBUTE)).toBe(false)
    finishLoading()
    await switching
    expect(document.documentElement.getAttribute(STYLE_ATTRIBUTE)).toBe('simple')
    expect(localStorage.getItem(STYLE_STORAGE_KEY)).toBe('simple')

    await setAppStyle('comic')
    expect(document.documentElement.hasAttribute(STYLE_ATTRIBUTE)).toBe(false)
    expect(localStorage.getItem(STYLE_STORAGE_KEY)).toBe('comic')
    expect(simpleLinks()).toHaveLength(1)
  })

  it('adds the stylesheet once and retries after a failed download', async () => {
    const first = ensureSimpleStyles('/simple.css')
    expect(ensureSimpleStyles('/simple.css')).toBe(first)
    expect(simpleLinks()).toHaveLength(1)
    expect(simpleLinks().item(0).getAttribute('href')).toBe('/simple.css')

    finishLoading('error')
    await first
    expect(simpleLinks()).toHaveLength(0)

    const retry = ensureSimpleStyles('/simple.css')
    expect(retry).not.toBe(first)
    expect(simpleLinks()).toHaveLength(1)
    finishLoading()
    await retry
    expect(simpleLinks()).toHaveLength(1)
  })
})
