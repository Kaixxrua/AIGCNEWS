import { describe, expect, it } from 'vitest'
import { getLoginContextKey } from './loginContext'

describe('login destination explanations', () => {
  it.each([
    ['/projects?q=android-use', 'search'],
    ['/report?quickSearch=1', 'search'],
    ['/projects?source=favorites', 'favorites'],
    ['/projects?source=website&q=design', 'websites'],
    ['/projects?page=2', 'moreProjects'],
    ['/projects?q=%20', 'projects'],
    ['/report?date=2026-10-09', 'report'],
    ['/subscriptions', 'subscriptions'],
    ['/papers/42/read?mode=focus', 'paper'],
    ['/mcp', 'mcp'],
    ['/oauth/authorize?client_id=example', 'mcp'],
    ['/dsh', 'dsh'],
    ['/membership/checkout?plan=month', 'checkout'],
    ['/monitor', 'protected'],
  ])('explains %s without altering its destination', (target, context) => {
    expect(getLoginContextKey(target)).toBe(`loginContext.${context}`)
  })

  it.each([undefined, '/', '/unknown', 'https://example.com/projects', '//example.com/projects'])(
    'uses the ordinary sign-in description for %s', target => {
      expect(getLoginContextKey(target)).toBe('auth.loginDescription')
    },
  )
})
