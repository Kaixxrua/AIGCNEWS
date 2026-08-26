import { describe, expect, it, vi } from 'vitest'
import { getErrorMessage, useSubscriptionsController } from './useSubscriptionsController'
import type { SubscriptionsApi } from '@/services/subscriptions/subscriptionsApi'

describe('getErrorMessage quota mapping', () => {
  it('maps any 403 to the stable quota-exceeded token', () => {
    expect(
      getErrorMessage(
        { response: { status: 403, data: { detail: '免费档最多订阅 1 个日报模块' } } },
        'request-failed',
      ),
    ).toBe('quota-exceeded')
  })

  it('keeps detail passthrough for non-403 failures', () => {
    expect(
      getErrorMessage(
        { response: { status: 400, data: { detail: '渠道不可用' } } },
        'request-failed',
      ),
    ).toBe('渠道不可用')
  })

  it('falls back when the error carries no usable payload', () => {
    expect(getErrorMessage(new Error('boom'), 'request-failed')).toBe('boom')
    expect(getErrorMessage({}, 'request-failed')).toBe('request-failed')
  })
  it('maps telegram-endpoint 503 to the stable telegram-unavailable token', () => {
    expect(
      getErrorMessage(
        {
          config: { url: '/push/me/channels/telegram/link' },
          response: { status: 503, data: { detail: 'Telegram 推送未配置' } },
        },
        'request-failed',
      ),
    ).toBe('telegram-unavailable')
  })

  it('keeps detail passthrough for non-telegram 503 failures', () => {
    expect(
      getErrorMessage(
        {
          config: { url: '/push/me/feed-token' },
          response: { status: 503, data: { detail: 'RSS token 服务未配置加密密钥' } },
        },
        'request-failed',
      ),
    ).toBe('RSS token 服务未配置加密密钥')
  })
})

describe('useSubscriptionsController quota errors', () => {
  const makeApi = (reject: unknown): SubscriptionsApi =>
    ({
      createSubscription: vi.fn().mockRejectedValue(reject),
      setSubscriptionStatus: vi.fn().mockRejectedValue(reject),
    }) as unknown as SubscriptionsApi

  it('surfaces quota-exceeded when createSubscription is rejected with 403', async () => {
    const ctl = useSubscriptionsController(
      makeApi({ response: { status: 403, data: { detail: '免费档最多订阅 1 个日报模块' } } }),
    )
    ctl.newChannelId.value = 1

    const ok = await ctl.submitSubscription()

    expect(ok).toBe(false)
    expect(ctl.error.value).toBe('quota-exceeded')
  })

  it('surfaces quota-exceeded when resuming a paused subscription hits the limit', async () => {
    const ctl = useSubscriptionsController(
      makeApi({ response: { status: 403, data: { detail: '免费档最多订阅 1 个日报模块' } } }),
    )

    await ctl.toggleSubscription({
      id: 9,
      channel_id: 1,
      channel_type: 'email',
      target: 'me@example.com',
      source: 'github',
      frequency: 'daily',
      status: 'paused',
      created_at: '2026-08-01T00:00:00Z',
    })

    expect(ctl.error.value).toBe('quota-exceeded')
  })
})
