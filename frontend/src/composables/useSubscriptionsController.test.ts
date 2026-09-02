import { describe, expect, it, vi } from 'vitest'
import { getErrorMessage, useSubscriptionsController } from './useSubscriptionsController'
import type { SubscriptionsApi } from '@/services/subscriptions/subscriptionsApi'

vi.mock('@/composables/useClipboard', () => ({
  copyToClipboard: vi.fn().mockResolvedValue(undefined),
}))

import { copyToClipboard } from '@/composables/useClipboard'

describe('getErrorMessage mapping', () => {
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

  // 全文 RSS 已对所有注册用户免费开放：统一拼装带 token 的 member.xml 链接
  it('builds token URLs with a lazily fetched token, cached across calls', async () => {
    const api = makeFeedApi()
    const ctl = useSubscriptionsController(api)

    const allUrl = await ctl.rssLinkFor('all')
    const sourceUrl = await ctl.rssLinkFor('arxiv')

    // token 只取一次（内存缓存）；特殊字符经 encodeURIComponent 编码
    expect(api.getFeedToken).toHaveBeenCalledTimes(1)
    const token = encodeURIComponent('aigc_feed_test token')
    expect(allUrl).toBe(`${window.location.origin}/api/feeds/member.xml?token=${token}`)
    expect(sourceUrl).toBe(
      `${window.location.origin}/api/feeds/member.xml?token=${token}&source=arxiv`,
    )
  })

  it('builds per-source token URLs from the same member feed', async () => {
    const api = makeFeedApi()
    const ctl = useSubscriptionsController(api)

    const token = encodeURIComponent('aigc_feed_test token')
    expect(await ctl.rssLinkFor('x')).toBe(
      `${window.location.origin}/api/feeds/member.xml?token=${token}&source=x`,
    )
    expect(api.getFeedToken).toHaveBeenCalledTimes(1)
  })

  it('copies the resolved link and sets the rss-copied notice', async () => {
    const api = makeFeedApi()
    const ctl = useSubscriptionsController(api)

    const ok = await ctl.copyRssLink('github')

    const token = encodeURIComponent('aigc_feed_test token')
    expect(ok).toBe(true)
    expect(copyToClipboard).toHaveBeenCalledWith(
      `${window.location.origin}/api/feeds/member.xml?token=${token}&source=github`,
    )
    expect(ctl.notice.value).toBe('rss-copied')
    expect(ctl.error.value).toBe('')
  })

  it('rotate swaps the in-memory token and invalidates the old link', async () => {
    const api = makeFeedApi()
    const ctl = useSubscriptionsController(api)
    await ctl.rssLinkFor('all')
    expect(ctl.feedToken.value).toBe('aigc_feed_test token')

    const ok = await ctl.rotateFeedToken()

    expect(ok).toBe(true)
    expect(api.rotateFeedToken).toHaveBeenCalledTimes(1)
    expect(ctl.feedToken.value).toBe('aigc_feed_rotated')
    expect(ctl.notice.value).toBe('rss-rotated')
    // 后续拼链接用新 token，不再调 getFeedToken
    const url = await ctl.rssLinkFor('all')
    expect(url).toContain(encodeURIComponent('aigc_feed_rotated'))
    expect(api.getFeedToken).toHaveBeenCalledTimes(1)
  })

  it('surfaces errors instead of copying when the token endpoint fails', async () => {
    vi.mocked(copyToClipboard).mockClear()
    const api = makeFeedApi()
    api.getFeedToken.mockRejectedValue({ response: { status: 503, data: { detail: 'RSS token 服务未配置加密密钥' } } })
    const ctl = useSubscriptionsController(api)

    const ok = await ctl.copyRssLink('all')

    expect(ok).toBe(false)
    expect(ctl.error.value).toBe('RSS token 服务未配置加密密钥')
    expect(copyToClipboard).not.toHaveBeenCalled()
  })
})
