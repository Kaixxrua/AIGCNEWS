import { createApp, nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import StyleToggle from './StyleToggle.vue'
import i18n, { setAppLocale } from '@/i18n'
import { tourActive, tourStep } from '@/features/onboarding/signals'
import { applyAppStyle, STYLE_ATTRIBUTE, STYLE_STORAGE_KEY } from '@/theme'
import { resetSimpleStylesForTest } from '@/theme/simpleStyles'
import { STYLE_HINT_DELAY_MS, STYLE_HINT_KEY } from '@/theme/styleHint'

let unmount: (() => void) | undefined

const simpleLinks = () => document.head.querySelectorAll<HTMLLinkElement>('link[data-app-style="simple"]')

const forgetStylesheet = () => {
  simpleLinks().forEach((link) => link.remove())
  resetSimpleStylesForTest()
}

// 按钮的点击处理是异步的（先等样式表），让它跑完再断言。
const settle = async () => {
  for (let i = 0; i < 5; i += 1) await Promise.resolve()
  await nextTick()
}

const mountToggle = () => {
  const host = document.createElement('div')
  document.body.appendChild(host)
  const app = createApp(StyleToggle)
  app.use(i18n)
  app.mount(host)
  unmount = () => { app.unmount(); host.remove() }
  return host.querySelector('button') as HTMLButtonElement
}

describe('StyleToggle', () => {
  beforeEach(() => {
    localStorage.clear()
    setAppLocale('zh-CN')
    applyAppStyle('comic')
    forgetStylesheet()
  })

  afterEach(() => {
    unmount?.()
    unmount = undefined
    applyAppStyle('comic')
    forgetStylesheet()
  })

  it('switches to the simple style once its stylesheet has loaded, and back to comic', async () => {
    const button = mountToggle()
    expect(button.getAttribute('aria-label')).toBe('页面风格：换成简洁版（素净低调，没有贴纸和荧光笔）')
    expect(button.querySelector('svg')).not.toBeNull()

    button.click()
    await settle()
    // 样式表还在下载：先不换版，按钮标成忙
    expect(document.documentElement.hasAttribute(STYLE_ATTRIBUTE)).toBe(false)
    expect(button.getAttribute('aria-busy')).toBe('true')
    expect(simpleLinks()).toHaveLength(1)

    simpleLinks().item(0).dispatchEvent(new Event('load'))
    await settle()
    expect(document.documentElement.getAttribute(STYLE_ATTRIBUTE)).toBe('simple')
    expect(localStorage.getItem(STYLE_STORAGE_KEY)).toBe('simple')
    expect(button.hasAttribute('aria-busy')).toBe(false)
    expect(button.getAttribute('aria-label')).toBe('页面风格：换成漫画版')

    button.click()
    await settle()
    expect(document.documentElement.hasAttribute(STYLE_ATTRIBUTE)).toBe(false)
    expect(localStorage.getItem(STYLE_STORAGE_KEY)).toBe('comic')
    expect(button.getAttribute('aria-label')).toBe('页面风格：换成简洁版（素净低调，没有贴纸和荧光笔）')
    // 切回漫画版不卸样式表，再切过去不用重下
    expect(simpleLinks()).toHaveLength(1)
  })

  it('localizes the label with the active catalog', async () => {
    const button = mountToggle()
    setAppLocale('en-US')
    await nextTick()
    expect(button.getAttribute('aria-label')).toBe('Page style：Switch to the plain style (quiet, no stickers or highlighter)')
  })
})

describe('StyleToggle hint', () => {
  const hint = () => document.body.querySelector<HTMLElement>('.style-hint')
  // jsdom 不排版：给开关一个报头右上角的位置，提示才认为它在视野里。
  const mountVisible = () => {
    const button = mountToggle()
    vi.spyOn(button, 'getBoundingClientRect').mockReturnValue({
      x: 900, y: 12, left: 900, top: 12, right: 932, bottom: 44, width: 32, height: 32, toJSON: () => ({}),
    } as DOMRect)
    return button
  }
  const waitForHint = async () => {
    vi.advanceTimersByTime(STYLE_HINT_DELAY_MS)
    await settle()
  }

  beforeEach(() => {
    vi.useFakeTimers()
    localStorage.clear()
    setAppLocale('zh-CN')
    applyAppStyle('comic')
    // applyAppStyle 会记下 app_style；提示只给本机没选过风格的人，这里抹掉它，模拟头一回来的访客。
    localStorage.removeItem(STYLE_STORAGE_KEY)
    forgetStylesheet()
    tourActive.value = false
  })

  afterEach(() => {
    unmount?.()
    unmount = undefined
    vi.useRealTimers()
    vi.restoreAllMocks()
    tourActive.value = false
    tourStep.value = null
    applyAppStyle('comic')
    forgetStylesheet()
  })

  it('points first-time visitors at the plain style once, and remembers the dismissal', async () => {
    mountVisible()
    await settle()
    expect(hint()).toBeNull()

    await waitForHint()
    expect(hint()?.getAttribute('role')).toBe('dialog')
    expect(hint()?.textContent).toContain('嫌页面太花？')

    ;(document.body.querySelector('.style-hint__dismiss') as HTMLButtonElement).click()
    await settle()
    expect(hint()).toBeNull()
    expect(localStorage.getItem(STYLE_HINT_KEY)).toBe('1')

    unmount?.()
    mountVisible()
    await waitForHint()
    expect(hint()).toBeNull()
  })

  it('stays quiet for visitors who already chose a style', async () => {
    localStorage.setItem(STYLE_STORAGE_KEY, 'comic')
    mountVisible()
    await waitForHint()
    expect(hint()).toBeNull()
  })

  it('switches to the plain style from the hint', async () => {
    mountVisible()
    await waitForHint()
    ;(document.body.querySelector('.style-hint__switch') as HTMLButtonElement).click()
    await settle()
    expect(hint()).toBeNull()
    expect(localStorage.getItem(STYLE_HINT_KEY)).toBe('1')

    simpleLinks().item(0).dispatchEvent(new Event('load'))
    await settle()
    expect(document.documentElement.getAttribute(STYLE_ATTRIBUTE)).toBe('simple')
    expect(localStorage.getItem(STYLE_STORAGE_KEY)).toBe('simple')
  })

  it('closes on Escape and on a click elsewhere', async () => {
    mountVisible()
    await waitForHint()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await settle()
    expect(hint()).toBeNull()
    expect(localStorage.getItem(STYLE_HINT_KEY)).toBe('1')

    localStorage.removeItem(STYLE_HINT_KEY)
    unmount?.()
    mountVisible()
    await waitForHint()
    expect(hint()).not.toBeNull()
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    await settle()
    expect(hint()).toBeNull()
  })

  it('waits for the site tour to finish, and counts the tour step as seen', async () => {
    tourActive.value = true
    mountVisible()
    await waitForHint()
    expect(hint()).toBeNull()

    tourActive.value = false
    await settle()
    await waitForHint()
    expect(hint()).not.toBeNull()

    tourActive.value = true
    tourStep.value = 'style'
    await settle()
    expect(hint()).toBeNull()
    expect(localStorage.getItem(STYLE_HINT_KEY)).toBe('1')
  })

  it('waits while a dialog is open', async () => {
    const dialog = document.createElement('dialog')
    dialog.setAttribute('open', '')
    document.body.appendChild(dialog)
    mountVisible()
    await waitForHint()
    expect(hint()).toBeNull()

    dialog.remove()
    await waitForHint()
    expect(hint()).not.toBeNull()
  })
})
