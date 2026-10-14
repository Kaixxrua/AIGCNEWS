import { createApp, nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import StyleToggle from './StyleToggle.vue'
import i18n, { setAppLocale } from '@/i18n'
import { applyAppStyle, STYLE_ATTRIBUTE, STYLE_STORAGE_KEY } from '@/theme'
import { resetSimpleStylesForTest } from '@/theme/simpleStyles'

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
