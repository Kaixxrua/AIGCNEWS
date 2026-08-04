import { createApp, nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import ThemeToggle from './ThemeToggle.vue'
import i18n, { setAppLocale } from '@/i18n'
import { setAppTheme, THEME_ATTRIBUTE, THEME_STORAGE_KEY } from '@/theme'

let unmount: (() => void) | undefined

describe('ThemeToggle', () => {
  beforeEach(() => {
    localStorage.clear()
    setAppLocale('zh-CN')
    setAppTheme('light')
  })

  afterEach(() => {
    unmount?.()
    unmount = undefined
  })

  it('toggles the application theme and persists the choice', async () => {
    const host = document.createElement('div')
    document.body.appendChild(host)
    const app = createApp(ThemeToggle)
    app.use(i18n)
    app.mount(host)
    unmount = () => { app.unmount(); host.remove() }

    const button = host.querySelector('button') as HTMLButtonElement
    expect(button.getAttribute('aria-label')).toBe('主题：深色模式')
    expect(button.querySelector('svg')).not.toBeNull()

    button.click()
    await nextTick()

    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')
    expect(document.documentElement.getAttribute(THEME_ATTRIBUTE)).toBe('dark')
    expect(button.getAttribute('aria-label')).toBe('主题：浅色模式')

    button.click()
    await nextTick()

    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('light')
    expect(document.documentElement.getAttribute(THEME_ATTRIBUTE)).toBeNull()
    expect(button.getAttribute('aria-label')).toBe('主题：深色模式')
  })

  it('localizes the toggle label with the active catalog', async () => {
    const host = document.createElement('div')
    document.body.appendChild(host)
    const app = createApp(ThemeToggle)
    app.use(i18n)
    app.mount(host)
    unmount = () => { app.unmount(); host.remove() }

    const button = host.querySelector('button') as HTMLButtonElement
    setAppLocale('en-US')
    await nextTick()
    expect(button.getAttribute('aria-label')).toBe('Theme：Dark mode')
  })
})
