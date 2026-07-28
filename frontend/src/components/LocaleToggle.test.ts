import { createApp, nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import LocaleToggle from './LocaleToggle.vue'
import i18n, { setAppLocale } from '../i18n'
import { LOCALE_STORAGE_KEY } from '../i18n/locale'
import { NAV_ITEMS } from '../features/navigation/navigationModel'

let unmount: (() => void) | undefined

describe('LocaleToggle', () => {
  beforeEach(() => {
    localStorage.clear()
    setAppLocale('zh-CN')
  })

  afterEach(() => {
    unmount?.()
    unmount = undefined
  })

  it('changes the application locale immediately without reloading', async () => {
    const host = document.createElement('div')
    document.body.appendChild(host)
    const app = createApp(LocaleToggle)
    app.use(i18n)
    app.mount(host)
    unmount = () => { app.unmount(); host.remove() }

    const select = host.querySelector('select') as HTMLSelectElement
    expect(select.getAttribute('aria-label')).toBe('语言')

    select.value = 'en-US'
    select.dispatchEvent(new Event('change', { bubbles: true }))
    await nextTick()

    expect(i18n.global.locale.value).toBe('en-US')
    expect(localStorage.getItem(LOCALE_STORAGE_KEY)).toBe('en-US')
    expect(document.documentElement.lang).toBe('en-US')
    expect(select.getAttribute('aria-label')).toBe('Language')
  })

  it('resolves navigation label keys reactively from the active catalog', () => {
    const dashboard = NAV_ITEMS.find(item => item.to === '/')!
    expect(i18n.global.t(dashboard.labelKey)).toBe('仪表盘')
    expect(i18n.global.t('auth.loginTitle')).toBe('AIGC 资讯 · 登录')
    setAppLocale('en-US')
    expect(i18n.global.t(dashboard.labelKey)).toBe('Dashboard')
    expect(i18n.global.t('auth.loginTitle')).toBe('AIGC News · Log in')
  })
})
