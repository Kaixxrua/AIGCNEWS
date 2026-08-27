import { createApp, nextTick } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'

import FavoritesLink from '@/components/FavoritesLink.vue'
import i18n, { setAppLocale } from '@/i18n'

/** 收藏本站引导气泡契约：
 * - 点击星星切换气泡显隐；Escape / 点击外部关闭；
 * - 桌面非 Mac 提示 Ctrl + D，Mac 桌面提示 ⌘ + D；
 * - 触屏设备没有快捷键语义，改为浏览器菜单指引；
 * - 纯引导交互，不触达任何收藏 API。 */

const ORIGINAL_UA = window.navigator.userAgent
const ORIGINAL_PLATFORM = window.navigator.platform
const ORIGINAL_MAX_TOUCH = window.navigator.maxTouchPoints

const setDevice = (ua: string, platform: string, maxTouchPoints: number) => {
  Object.defineProperty(window.navigator, 'userAgent', { value: ua, configurable: true })
  Object.defineProperty(window.navigator, 'platform', { value: platform, configurable: true })
  Object.defineProperty(window.navigator, 'maxTouchPoints', { value: maxTouchPoints, configurable: true })
}

const restoreDevice = () => setDevice(ORIGINAL_UA, ORIGINAL_PLATFORM, ORIGINAL_MAX_TOUCH)

let unmount: (() => void) | undefined

const mountLink = () => {
  const host = document.createElement('div')
  document.body.appendChild(host)
  const app = createApp(FavoritesLink)
  app.use(i18n)
  app.mount(host)
  unmount = () => { app.unmount(); host.remove() }
  return host
}

const starButton = (host: HTMLElement) =>
  host.querySelector('button.favorites-link') as HTMLButtonElement

// Transition 离场在 jsdom 里走 Vue 的 setTimeout 兜底（时长 +1ms），
// 等 260ms 让离场完成后元素才真正从 DOM 移除。
const flushLeave = () => new Promise((resolve) => setTimeout(resolve, 260))

afterEach(() => {
  unmount?.()
  unmount = undefined
  restoreDevice()
  setAppLocale('zh-CN')
})

describe('FavoritesLink 收藏引导气泡', () => {
  it('初始仅渲染星星按钮，气泡隐藏，aria-label 为「收藏本站」', () => {
    setAppLocale('zh-CN')
    const host = mountLink()
    expect(starButton(host).getAttribute('aria-label')).toBe('收藏本站')
    expect(host.querySelector('.favorite-guide')).toBeNull()
  })

  it('点击展开气泡显示 Ctrl + D（桌面非 Mac），再次点击关闭', async () => {
    setAppLocale('zh-CN')
    const host = mountLink()

    starButton(host).click()
    await nextTick()
    const guide = host.querySelector('.favorite-guide')
    expect(guide).not.toBeNull()
    expect(guide?.querySelector('kbd')?.textContent).toBe('Ctrl + D')
    expect(guide?.textContent).toContain('收藏本站到浏览器书签')
    expect(starButton(host).getAttribute('aria-expanded')).toBe('true')

    starButton(host).click()
    await nextTick()
    await flushLeave()
    expect(host.querySelector('.favorite-guide')).toBeNull()
  })

  it('Escape 关闭气泡', async () => {
    setAppLocale('zh-CN')
    const host = mountLink()

    starButton(host).click()
    await nextTick()
    expect(host.querySelector('.favorite-guide')).not.toBeNull()

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await nextTick()
    await flushLeave()
    expect(host.querySelector('.favorite-guide')).toBeNull()
  })

  it('点击组件外部关闭气泡', async () => {
    setAppLocale('zh-CN')
    const host = mountLink()

    starButton(host).click()
    await nextTick()
    expect(host.querySelector('.favorite-guide')).not.toBeNull()

    document.body.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await nextTick()
    await flushLeave()
    expect(host.querySelector('.favorite-guide')).toBeNull()
  })

  it('Mac 桌面提示 ⌘ + D', async () => {
    setDevice(
      'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15',
      'MacIntel',
      0,
    )
    setAppLocale('zh-CN')
    const host = mountLink()

    starButton(host).click()
    await nextTick()
    expect(host.querySelector('.favorite-guide kbd')?.textContent).toBe('⌘ + D')
  })

  it('触屏设备改为浏览器菜单指引且不显示 kbd', async () => {
    setDevice(
      'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15',
      'iPhone',
      5,
    )
    setAppLocale('zh-CN')
    const host = mountLink()

    starButton(host).click()
    await nextTick()
    const guide = host.querySelector('.favorite-guide')
    expect(guide?.querySelector('kbd')).toBeNull()
    expect(guide?.textContent).toContain('打开浏览器菜单，选择「书签」或「收藏」即可收藏本站')
  })

  it('英文界面使用英文文案', async () => {
    setAppLocale('en-US')
    const host = mountLink()
    expect(starButton(host).getAttribute('aria-label')).toBe('Bookmark this site')

    starButton(host).click()
    await nextTick()
    expect(host.querySelector('.favorite-guide')?.textContent).toContain(
      'to bookmark this site in your browser',
    )
  })
})
