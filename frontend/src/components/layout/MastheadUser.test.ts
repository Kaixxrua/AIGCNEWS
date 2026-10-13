import { createApp, nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import MastheadUser from './MastheadUser.vue'
import i18n, { setAppLocale } from '@/i18n'

/* authStore 以 hoisted 盒子桩化：直控登录态与档位，绕过 pinia/token 存储。 */
const authBox = vi.hoisted(() => ({
  isLoggedIn: false,
  user: null as null | { user_id?: number; email: string; username?: string | null; avatar_url?: string | null; membership_tier?: 'free' | 'member'; membership_expires_at?: string | null },
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
    expect(host.querySelector('.user-avatar img.user-avatar__default')?.getAttribute('src')).toBeTruthy()
    expect(host.querySelector('.user-avatar')?.textContent).not.toContain('?')
  })

  it('keeps the anonymous lines fixed under the English locale too', () => {
    setAppLocale('en-US')
    const host = mountMastheadUser()

    expect(host.querySelector('.masthead-user__status')?.textContent).toBe('未登录')
    expect(host.querySelector('.masthead-user__identity')?.textContent).toBe('guest')
  })

  it('shows only the account email once a free-tier user logs in', () => {
    authBox.isLoggedIn = true
    authBox.user = { email: 'reader@example.com', membership_tier: 'free' }
    const host = mountMastheadUser()

    expect(host.querySelector('.masthead-user__status')?.textContent).toBe('reader@example.com')
    expect(host.querySelector('.masthead-user__identity')).toBeNull()
  })

  it('prefers a non-empty username over the account email', () => {
    authBox.isLoggedIn = true
    authBox.user = { email: 'reader@example.com', username: '读者甲', membership_tier: 'free' }
    const host = mountMastheadUser()

    expect(host.querySelector('.masthead-user__status')?.textContent).toBe('读者甲')
  })

  it('uses a stable default avatar when no avatar exists and when its image fails', async () => {
    authBox.isLoggedIn = true
    authBox.user = { user_id: 42, email: 'reader@example.com', username: ' reader' }
    let host = mountMastheadUser()
    const fallback = host.querySelector('.user-avatar img.user-avatar__default')?.getAttribute('src')
    expect(fallback).toBeTruthy()
    unmount?.()
    authBox.user = { ...authBox.user, avatar_url: '/missing.png' }
    host = mountMastheadUser()
    const image = host.querySelector('.user-avatar img') as HTMLImageElement
    expect(image.getAttribute('src')).toBe('/missing.png')
    image.dispatchEvent(new Event('error'))
    await nextTick()
    expect(host.querySelector('.user-avatar img.user-avatar__default')?.getAttribute('src')).toBe(fallback)
    expect(host.querySelector('.masthead-user__status')?.textContent).toBe('reader')
    expect(host.querySelector('.masthead-user__identity')).toBeNull()
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

  it.each(['zh-CN', 'en-US'] as const)('hides billing tier and expiry for all signed-in accounts in %s', (locale) => {
    setAppLocale(locale)
    for (const billing of [
      {},
      { membership_tier: 'free' as const },
      { membership_tier: 'member' as const, membership_expires_at: null },
      { membership_tier: 'member' as const, membership_expires_at: '2020-01-01T00:00:00Z' },
      { membership_tier: 'member' as const, membership_expires_at: '2030-01-01T00:00:00Z' },
    ]) {
      authBox.isLoggedIn = true
      authBox.user = { email: 'reader@example.com', username: '读者', ...billing }
      const host = mountMastheadUser()
      expect(host.querySelector('.masthead-user__status')?.textContent).toBe('读者')
      expect(host.querySelector('.masthead-user__identity')).toBeNull()
      expect(host.textContent).not.toMatch(/VIP|vip|Group:|用户组|到期|expiry|lifetime/)
      unmount?.()
      unmount = undefined
    }
  })
})
