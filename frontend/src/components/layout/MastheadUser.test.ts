import { createApp } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import MastheadUser from './MastheadUser.vue'
import i18n, { setAppLocale } from '@/i18n'

/* authStore 以 hoisted 盒子桩化：直控登录态与档位，绕过 pinia/token 存储。 */
const authBox = vi.hoisted(() => ({
  isLoggedIn: false,
  user: null as null | { email: string; membership_tier?: 'free' | 'member' },
}))

vi.mock('@/stores/authStore', () => ({ useAuthStore: () => authBox }))

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
    authBox.isLoggedIn = false
    authBox.user = null
    setAppLocale('zh-CN')
  })

  it('shows the fixed 未登录 / guest lines for anonymous visitors', () => {
    const host = mountMastheadUser()

    expect(host.querySelector('.masthead-user__status')?.textContent).toBe('未登录')
    expect(host.querySelector('.masthead-user__identity')?.textContent).toBe('guest')
  })

  it('keeps the anonymous lines fixed under the English locale too', () => {
    setAppLocale('en-US')
    const host = mountMastheadUser()

    expect(host.querySelector('.masthead-user__status')?.textContent).toBe('未登录')
    expect(host.querySelector('.masthead-user__identity')?.textContent).toBe('guest')
  })

  it('shows the account email and free group once a free-tier user logs in', () => {
    authBox.isLoggedIn = true
    authBox.user = { email: 'reader@example.com', membership_tier: 'free' }
    const host = mountMastheadUser()

    expect(host.querySelector('.masthead-user__status')?.textContent).toBe('reader@example.com')
    expect(host.querySelector('.masthead-user__identity')?.textContent).toBe('用户组：free')
  })

  it('labels member-tier accounts as vip', () => {
    authBox.isLoggedIn = true
    authBox.user = { email: 'vip@example.com', membership_tier: 'member' }
    const host = mountMastheadUser()

    expect(host.querySelector('.masthead-user__identity')?.textContent).toBe('用户组：vip')
  })

  it('falls back to free when the tier field is missing', () => {
    authBox.isLoggedIn = true
    authBox.user = { email: 'legacy@example.com' }
    const host = mountMastheadUser()

    expect(host.querySelector('.masthead-user__identity')?.textContent).toBe('用户组：free')
  })

  it('follows the active locale for the logged-in group label', () => {
    setAppLocale('en-US')
    authBox.isLoggedIn = true
    authBox.user = { email: 'vip@example.com', membership_tier: 'member' }
    const host = mountMastheadUser()

    expect(host.querySelector('.masthead-user__identity')?.textContent).toBe('Group: vip')
  })
})
