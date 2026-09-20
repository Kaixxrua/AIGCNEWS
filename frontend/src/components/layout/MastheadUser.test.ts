import { createApp, nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import MastheadUser from './MastheadUser.vue'
import i18n, { setAppLocale } from '@/i18n'

/* authStore 以 hoisted 盒子桩化：直控登录态与档位，绕过 pinia/token 存储。 */
const authBox = vi.hoisted(() => ({
  isLoggedIn: false,
  user: null as null | { email: string; username?: string | null; avatar_url?: string | null; membership_tier?: 'free' | 'member'; membership_expires_at?: string | null },
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

  it('prefers a non-empty username over the account email', () => {
    authBox.isLoggedIn = true
    authBox.user = { email: 'reader@example.com', username: '读者甲', membership_tier: 'free' }
    const host = mountMastheadUser()

    expect(host.querySelector('.masthead-user__status')?.textContent).toBe('读者甲')
  })

  it('uses the username initial when no avatar exists and when its image fails', async () => {
    authBox.isLoggedIn = true
    authBox.user = { email: 'reader@example.com', username: ' reader' }
    let host = mountMastheadUser()
    expect(host.querySelector('.user-avatar')?.textContent).toBe('R')
    unmount?.()
    authBox.user = { ...authBox.user, avatar_url: '/missing.png' }
    host = mountMastheadUser()
    const image = host.querySelector('.user-avatar img') as HTMLImageElement
    expect(image.getAttribute('src')).toBe('/missing.png')
    image.dispatchEvent(new Event('error'))
    await nextTick()
    expect(host.querySelector('.user-avatar')?.textContent).toBe('R')
    expect(host.querySelector('.masthead-user__status')?.textContent).toBe('reader')
    expect(host.querySelector('.masthead-user__identity')?.textContent).toBe('用户组：free')
  })

  it('falls back to the email when the username is null, empty, or blank', () => {
    for (const username of [null, '', '   ']) {
      authBox.isLoggedIn = true
      authBox.user = { email: 'reader@example.com', username, membership_tier: 'free' }
      const host = mountMastheadUser()

      expect(host.querySelector('.masthead-user__status')?.textContent).toBe('reader@example.com')
      unmount?.()
      unmount = undefined
    }
  })

  it('labels member-tier accounts as vip with the lifetime suffix on the same line', () => {
    authBox.isLoggedIn = true
    authBox.user = { email: 'vip@example.com', membership_tier: 'member' }
    const host = mountMastheadUser()

    expect(host.querySelector('.masthead-user__identity')?.textContent).toBe('用户组：vip  长期有效')
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

    expect(host.querySelector('.masthead-user__identity')?.textContent).toBe('Group: vip  lifetime')
  })

  /* 到期后缀期望值用 Intl 现算，与组件同一格式化器口径，免受宿主 ICU 差异影响 */
  const formatExpiry = (raw: string, locale: string) =>
    new Intl.DateTimeFormat(locale, { year: 'numeric', month: '2-digit', day: '2-digit' }).format(Date.parse(raw))

  it('appends the expiry date after the vip tier on the same line', () => {
    authBox.isLoggedIn = true
    authBox.user = { email: 'vip@example.com', membership_tier: 'member', membership_expires_at: '2027-01-01T15:59:59+00:00' }
    const host = mountMastheadUser()

    expect(host.querySelector('.masthead-user__identity')?.textContent).toBe(`用户组：vip  ${formatExpiry('2027-01-01T15:59:59+00:00', 'zh-CN')}到期`)
  })

  it('shows the lifetime suffix for member accounts without an expiry', () => {
    authBox.isLoggedIn = true
    authBox.user = { email: 'vip@example.com', membership_tier: 'member', membership_expires_at: null }
    const host = mountMastheadUser()

    expect(host.querySelector('.masthead-user__identity')?.textContent).toBe('用户组：vip  长期有效')
  })

  it('omits the expiry suffix for free-tier accounts even if an expiry leaks through', () => {
    authBox.isLoggedIn = true
    authBox.user = { email: 'reader@example.com', membership_tier: 'free', membership_expires_at: '2027-01-01T15:59:59+00:00' }
    const host = mountMastheadUser()

    expect(host.querySelector('.masthead-user__identity')?.textContent).toBe('用户组：free')
  })

  it('hides the expiry suffix when the timestamp cannot be parsed', () => {
    authBox.isLoggedIn = true
    authBox.user = { email: 'vip@example.com', membership_tier: 'member', membership_expires_at: 'not-a-date' }
    const host = mountMastheadUser()

    expect(host.querySelector('.masthead-user__identity')?.textContent).toBe('用户组：vip')
  })

  it('renders the inline expiry in English under the en-US locale', () => {
    setAppLocale('en-US')
    authBox.isLoggedIn = true
    authBox.user = { email: 'vip@example.com', membership_tier: 'member', membership_expires_at: '2027-01-01T15:59:59+00:00' }
    const host = mountMastheadUser()

    expect(host.querySelector('.masthead-user__identity')?.textContent).toBe(`Group: vip  until ${formatExpiry('2027-01-01T15:59:59+00:00', 'en-US')}`)

    unmount?.()
    authBox.user = { email: 'vip@example.com', membership_tier: 'member', membership_expires_at: null }
    const lifetimeHost = mountMastheadUser()
    expect(lifetimeHost.querySelector('.masthead-user__identity')?.textContent).toBe('Group: vip  lifetime')
  })
})
