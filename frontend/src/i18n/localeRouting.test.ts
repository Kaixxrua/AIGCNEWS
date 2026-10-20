import { nextTick } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import i18n, { installI18n, setAppLocale } from '@/i18n'
import { installLocaleRouting } from './localeRouting'

let stop: (() => void) | undefined
afterEach(() => {
  stop?.()
  localStorage.clear()
  window.history.replaceState(null, '', '/')
  setAppLocale('zh-CN')
})

describe('language-specific URLs', () => {
  it('loads the requested language before the first render', () => {
    setAppLocale('zh-CN')
    window.history.replaceState(null, '', '/?tab=news&lang=en-US')
    expect(installI18n()).toBe('en-US')
    expect(document.documentElement.lang).toBe('en-US')
    window.history.replaceState(null, '', '/?lang=en-US&lang=zh-CN')
    expect(installI18n()).toBe('zh-CN')
  })

  it('keeps locale, URL and history consistent when following links or toggling languages', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/', name: 'dashboard', component: { template: '<div />' } }],
    })
    stop = installLocaleRouting(router)
    await router.push('/?tab=news&lang=en-US#ranking-content')
    await nextTick()
    expect(i18n.global.locale.value).toBe('en-US')
    setAppLocale('zh-CN')
    await nextTick()
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(router.currentRoute.value.fullPath).toBe('/?tab=news&lang=zh-CN#ranking-content')

    await router.push('/?lang=en-US')
    await nextTick()
    expect(i18n.global.locale.value).toBe('en-US')
    router.back()
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(router.currentRoute.value.query.tab).toBe('news')
    expect(i18n.global.locale.value).toBe('zh-CN')

    await router.push('/?lang=invalid')
    expect(i18n.global.locale.value).toBe('zh-CN')
  })
})
