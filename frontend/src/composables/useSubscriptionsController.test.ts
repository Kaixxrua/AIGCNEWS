import { describe, expect, it, vi } from 'vitest'
import { getErrorMessage, useSubscriptionsController } from './useSubscriptionsController'
import type { SubscriptionsApi } from '@/services/subscriptions/subscriptionsApi'

vi.mock('@/composables/useClipboard', () => ({
  copyToClipboard: vi.fn().mockResolvedValue(undefined),
}))

import { copyToClipboard } from '@/composables/useClipboard'

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

describe('useSubscriptionsController RSS links', () => {
  const makeFeedApi = (): SubscriptionsApi & { getFeedToken: ReturnType<typeof vi.fn> } =>
    ({
      getFeedToken: vi.fn().mockResolvedValue({
        token: 'aigc_feed_test token',
        token_hint: 'aigc_feed_tes...oken',
        created: true,
        created_at: '2026-08-25T08:00:00Z',
      }),
      rotateFeedToken: vi.fn().mockResolvedValue({
        token: 'aigc_feed_rotated',
        token_hint: 'aigc_feed_rot...ated',
        created: true,
        created_at: '2026-08-26T08:00:00Z',
      }),
    }) as unknown as SubscriptionsApi & { getFeedToken: ReturnType<typeof vi.fn> }

  it('builds member URLs with a lazily fetched token, cached across calls', async () => {
    const api = makeFeedApi()
    const ctl = useSubscriptionsController(api)

    const allUrl = await ctl.rssLinkFor('all', true)
    const sourceUrl = await ctl.rssLinkFor('arxiv', true)

    // token 只取一次（内存缓存）；特殊字符经 encodeURIComponent 编码
    expect(api.getFeedToken).toHaveBeenCalledTimes(1)
    const token = encodeURIComponent('aigc_feed_test token')
    expect(allUrl).toBe(`${window.location.origin}/api/feeds/member.xml?token=${token}`)
    expect(sourceUrl).toBe(
      `${window.location.origin}/api/feeds/member.xml?token=${token}&source=arxiv`,
    )
  })

  it('builds public URLs for free users without touching the token endpoint', async () => {
    const api = makeFeedApi()
    const ctl = useSubscriptionsController(api)

    expect(await ctl.rssLinkFor('all', false)).toBe(`${window.location.origin}/api/feed.xml`)
    expect(await ctl.rssLinkFor('x', false)).toBe(`${window.location.origin}/api/feeds/x.xml`)
    expect(api.getFeedToken).not.toHaveBeenCalled()
  })

  it('copies the resolved link and sets the rss-copied notice', async () => {
    const api = makeFeedApi()
    const ctl = useSubscriptionsController(api)

    const ok = await ctl.copyRssLink('github', false)

    expect(ok).toBe(true)
    expect(copyToClipboard).toHaveBeenCalledWith(`${window.location.origin}/api/feeds/github.xml`)
    expect(ctl.notice.value).toBe('rss-copied')
    expect(ctl.error.value).toBe('')
  })

  it('rotate swaps the in-memory token and invalidates the old link', async () => {
    const api = makeFeedApi()
    const ctl = useSubscriptionsController(api)
    await ctl.rssLinkFor('all', true)
    expect(ctl.feedToken.value).toBe('aigc_feed_test token')

    const ok = await ctl.rotateFeedToken()

    expect(ok).toBe(true)
    expect(api.rotateFeedToken).toHaveBeenCalledTimes(1)
    expect(ctl.feedToken.value).toBe('aigc_feed_rotated')
    expect(ctl.notice.value).toBe('rss-rotated')
    // 后续拼链接用新 token，不再调 getFeedToken
    const url = await ctl.rssLinkFor('all', true)
    expect(url).toContain(encodeURIComponent('aigc_feed_rotated'))
    expect(api.getFeedToken).toHaveBeenCalledTimes(1)
  })

  it('surfaces errors instead of copying when the token endpoint fails', async () => {
    vi.mocked(copyToClipboard).mockClear()
    const api = makeFeedApi()
    api.getFeedToken.mockRejectedValue({ response: { status: 503, data: { detail: 'RSS token 服务未配置加密密钥' } } })
    const ctl = useSubscriptionsController(api)

    const ok = await ctl.copyRssLink('all', true)

    expect(ok).toBe(false)
    expect(ctl.error.value).toBe('RSS token 服务未配置加密密钥')
    expect(copyToClipboard).not.toHaveBeenCalled()
  })
})
