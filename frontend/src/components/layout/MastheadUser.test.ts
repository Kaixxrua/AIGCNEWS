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

  it('renders nothing for anonymous visitors', () => {
    const host = mountMastheadUser()
    expect(host.querySelector('.masthead-user')).toBeNull()
  })

  it('shows the user email and free group for a free-tier account', () => {
    authBox.isLoggedIn = true
    authBox.user = { email: 'reader@example.com', membership_tier: 'free' }
    const host = mountMastheadUser()

    expect(host.querySelector('.masthead-user__name')?.textContent).toBe('reader@example.com')
    expect(host.querySelector('.masthead-user__tier')?.textContent).toBe('用户组：free')
  })

  it('labels member-tier accounts as vip', () => {
    authBox.isLoggedIn = true
    authBox.user = { email: 'vip@example.com', membership_tier: 'member' }
    const host = mountMastheadUser()

    expect(host.querySelector('.masthead-user__tier')?.textContent).toBe('用户组：vip')
  })

  it('falls back to free when the tier field is missing', () => {
    authBox.isLoggedIn = true
    authBox.user = { email: 'legacy@example.com' }
    const host = mountMastheadUser()

    expect(host.querySelector('.masthead-user__tier')?.textContent).toBe('用户组：free')
  })

  it('follows the active locale for the group label', () => {
    setAppLocale('en-US')
    authBox.isLoggedIn = true
    authBox.user = { email: 'vip@example.com', membership_tier: 'member' }
    const host = mountMastheadUser()

    expect(host.querySelector('.masthead-user__tier')?.textContent).toBe('Group: vip')
  })
})
