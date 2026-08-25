import { describe, expect, it } from 'vitest'
import {
  getErrorDetail,
  getSafeInternalRedirect,
  isValidPassword,
  PASSWORD_MIN_LENGTH,
} from './authViewModel'

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

describe('password validation and API error details', () => {
  it('matches the backend minimum password length', () => {
    expect(PASSWORD_MIN_LENGTH).toBe(8)
    expect(isValidPassword('1234567')).toBe(false)
    expect(isValidPassword('12345678')).toBe(true)
  })

  it('extracts readable messages from structured validation errors', () => {
    expect(getErrorDetail({ response: { data: { detail: [
      { loc: ['body', 'new_password'], msg: 'password must be at least 8 characters' },
      { loc: ['body', 'email'], msg: 'invalid email' },
    ] } } }, 'fallback')).toBe('password must be at least 8 characters；invalid email')
  })

  it('preserves string details and falls back when absent', () => {
    expect(getErrorDetail({ response: { data: { detail: '验证码错误' } } }, 'fallback')).toBe('验证码错误')
    expect(getErrorDetail({}, 'fallback')).toBe('fallback')
  })
})
