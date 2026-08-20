import { createApp } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import MastheadUser from './MastheadUser.vue'
import i18n, { setAppLocale } from '@/i18n'

/* MastheadUser 是固定标识：无论匿名、Free 还是 VIP，始终渲染「未登录 / guest」，
   不读 authStore、不随 locale 变化。组件无依赖，直接挂载即可。 */
let unmount: (() => void) | undefined

const mountMastheadUser = () => {
  const host = document.createElement('div')
  document.body.appendChild(host)
  const app = createApp(MastheadUser)
  app.use(i18n)
  app.mount(host)
  unmount = () => { app.unmount(); host.remove() }
  return host
}

describe('MastheadUser', () => {
  afterEach(() => {
    unmount?.()
    unmount = undefined
    setAppLocale('zh-CN')
  })

  it('always renders the fixed 未登录 / guest lines for anonymous visitors', () => {
    const host = mountMastheadUser()

    expect(host.querySelector('.masthead-user__status')?.textContent).toBe('未登录')
    expect(host.querySelector('.masthead-user__identity')?.textContent).toBe('guest')
  })

  it('renders the same fixed lines regardless of session state', () => {
    // 组件不读取 authStore：匿名、Free、VIP 三种真实会话下输出完全一致
    const host = mountMastheadUser()

    expect(host.querySelector('.masthead-user')?.textContent).toBe('未登录guest')
  })

  it('hides the decorative badge from assistive technology', () => {
    const host = mountMastheadUser()

    expect(host.querySelector('.masthead-user')?.getAttribute('aria-hidden')).toBe('true')
  })

  it('keeps the fixed lines under the English locale too', () => {
    setAppLocale('en-US')
    const host = mountMastheadUser()

    expect(host.querySelector('.masthead-user__status')?.textContent).toBe('未登录')
    expect(host.querySelector('.masthead-user__identity')?.textContent).toBe('guest')
  })
})
