import { describe, expect, it } from 'vitest'
import { getSafeInternalRedirect } from './authViewModel'

describe('getSafeInternalRedirect', () => {
  it('preserves safe internal destinations after login', () => {
    expect(getSafeInternalRedirect('/papers/42/read?mode=focus')).toBe('/papers/42/read?mode=focus')
  })

  it.each([undefined, '', 'https://example.com', '//example.com/path'])(
    'falls back to home for unsafe redirect %j',
    (redirect) => {
      expect(getSafeInternalRedirect(redirect)).toBe('/')
    },
  )
})
