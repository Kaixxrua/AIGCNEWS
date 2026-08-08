import { describe, expect, it } from 'vitest'
import {
  SUBSCRIPTION_FREQUENCIES,
  SUBSCRIPTION_SOURCES,
  detectWebhookPlatform,
  isChannelBindable,
  isHttpsUrlShape,
  isValidEmailShape,
  isValidOtpCode,
  normalizeEmail,
} from './subscriptionsModel'
import type { PushChannel } from './subscriptionsModel'

const channel = (overrides: Partial<PushChannel>): PushChannel => ({
  id: 1,
  channel_type: 'email',
  target: 'a@b.com',
  verified: true,
  status: 'active',
  created_at: '2026-08-01T00:00:00Z',
  ...overrides,
})

describe('detectWebhookPlatform', () => {
  it('recognizes provider hosts case-insensitively', () => {
    expect(detectWebhookPlatform('https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x')).toBe('wecom')
    expect(detectWebhookPlatform('https://QYAPI.WEIXIN.QQ.COM/cgi-bin/webhook/send?key=x')).toBe('wecom')
    expect(detectWebhookPlatform('https://oapi.dingtalk.com/robot/send?access_token=x')).toBe('dingtalk')
    expect(detectWebhookPlatform('https://open.feishu.cn/open-apis/bot/v2/hook/x')).toBe('lark')
    expect(detectWebhookPlatform('https://open.larksuite.com/open-apis/bot/v2/hook/x')).toBe('lark')
  })

  it('falls back to generic for unknown hosts and invalid URLs', () => {
    expect(detectWebhookPlatform('https://hooks.example.com/x')).toBe('generic')
    expect(detectWebhookPlatform('not a url')).toBe('generic')
    expect(detectWebhookPlatform('')).toBe('generic')
  })
})

describe('isChannelBindable', () => {
  it('requires verified and active', () => {
    expect(isChannelBindable(channel({}))).toBe(true)
    expect(isChannelBindable(channel({ verified: false }))).toBe(false)
    expect(isChannelBindable(channel({ status: 'disabled' }))).toBe(false)
  })
})

describe('email and otp shape helpers', () => {
  it('normalizes email by trimming and lowercasing', () => {
    expect(normalizeEmail('  Foo@Example.COM ')).toBe('foo@example.com')
  })

  it('validates email shape on the normalized value', () => {
    expect(isValidEmailShape('a@b.com')).toBe(true)
    expect(isValidEmailShape('  A@B.co ')).toBe(true)
    expect(isValidEmailShape('a@b')).toBe(false)
    expect(isValidEmailShape('a b@c.com')).toBe(false)
    expect(isValidEmailShape('')).toBe(false)
  })

  it('validates 6-digit otp codes', () => {
    expect(isValidOtpCode('123456')).toBe(true)
    expect(isValidOtpCode(' 123456 ')).toBe(true)
    expect(isValidOtpCode('12345')).toBe(false)
    expect(isValidOtpCode('12345a')).toBe(false)
  })
})

describe('isHttpsUrlShape', () => {
  it('accepts https URLs within the length budget', () => {
    expect(isHttpsUrlShape('https://hooks.example.com/x')).toBe(true)
    expect(isHttpsUrlShape('  https://hooks.example.com/x  ')).toBe(true)
  })

  it('rejects non-https, malformed, empty and overlong values', () => {
    expect(isHttpsUrlShape('http://hooks.example.com/x')).toBe(false)
    expect(isHttpsUrlShape('ftp://hooks.example.com/x')).toBe(false)
    expect(isHttpsUrlShape('not a url')).toBe(false)
    expect(isHttpsUrlShape('')).toBe(false)
    expect(isHttpsUrlShape(`https://example.com/${'a'.repeat(2048)}`)).toBe(false)
  })
})

describe('subscription vocabulary', () => {
  it('mirrors the backend source and frequency vocabulary', () => {
    expect(SUBSCRIPTION_SOURCES).toEqual([
      'all',
      'arxiv',
      'github',
      'news',
      'producthunt',
      'hackernews',
      'x',
      'dailyhot',
    ])
    expect(SUBSCRIPTION_FREQUENCIES).toEqual(['daily'])
  })
})
