import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/composables/useClipboard', () => ({
  copyToClipboard: vi.fn().mockResolvedValue(undefined),
  copySensitiveToClipboard: vi.fn().mockResolvedValue(undefined),
}))

import { useReportSubscriptions } from './useReportSubscriptions'
import { i18n } from '@/i18n'
import { copySensitiveToClipboard, copyToClipboard } from '@/composables/useClipboard'
import type { FeedTokenInfo } from '@/services/auth/feedTokenApi'
import type { ReportKey, SubscriptionPlan } from '@/features/report/reportViewModel'

beforeEach(() => {
  vi.mocked(copyToClipboard).mockReset()
  vi.mocked(copyToClipboard).mockResolvedValue(undefined)
  vi.mocked(copySensitiveToClipboard).mockReset()
  vi.mocked(copySensitiveToClipboard).mockResolvedValue(undefined)
  localStorage.clear()
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})

const makePlan = (overrides: Partial<SubscriptionPlan> = {}): SubscriptionPlan => ({
  can_select_multiple_sources: true,
  max_sources: 8,
  active_sources: [],
  capabilities: [
    { kind: 'rss', key: 'rss-briefing', feed: 'briefing', selectable: true, active: false, disabled_reason: null },
    { kind: 'account_email', key: 'account-email', selectable: true, active: false, disabled_reason: null },
    { kind: 'push_channel', key: 'push-webhook-7', channel_id: 7, channel_type: 'webhook', target: 'https://example.com/hook', verified: true, status: 'active', selectable: true, active: false, disabled_reason: null },
    { kind: 'push_channel', key: 'push-wechat-coming-soon', channel_type: 'wechat', verified: false, status: 'coming_soon', selectable: false, active: false, disabled_reason: '暂未开放' },
  ],
  ...overrides,
})

const makeFeedToken = (token: string): FeedTokenInfo => ({
  token,
  token_hint: `${token.slice(0, 8)}...`,
  created: false,
  created_at: null,
})

const makeOperations = () => ({
  loadPlan: vi.fn().mockResolvedValue(makePlan()),
  loadSubscriptions: vi.fn().mockResolvedValue({ items: [] }),
  applyPlan: vi.fn().mockResolvedValue({ sources: ['github'], deliveries: [{ kind: 'account_email', status: 'applied' }] }),
  getFeedToken: vi.fn().mockResolvedValue(makeFeedToken('aigc_feed_test token')),
  rotateFeedToken: vi.fn().mockResolvedValue(makeFeedToken('aigc_feed_rotated')),
  sendToEmail: vi.fn().mockResolvedValue(undefined),
})

const withSetup = ({ isLoggedIn = true, member = false }: { isLoggedIn?: boolean; member?: boolean } = {}) => {
  const operations = makeOperations()
  const setError = vi.fn()
  const redirectToLogin = vi.fn()
  const loggedIn = ref(isLoggedIn)
  const membership = ref(member)
  const userId = ref<number | null>(isLoggedIn ? 42 : null)
  let controller!: ReturnType<typeof useReportSubscriptions>
  const wrapper = mount(
    defineComponent({
      setup() {
        controller = useReportSubscriptions({
          isLoggedIn: loggedIn,
          isMember: membership,
          userId,
          selectedSource: ref<ReportKey>('all'),
          selectedDate: ref('2026-08-17'),
          locale: ref('zh-CN'),
          operations,
          redirectToLogin,
          setError,
        })
        return () => null
      },
    }),
  )
  return { controller, operations, setError, redirectToLogin, loggedIn, membership, userId, wrapper }
}

describe('useReportSubscriptions wizard flow', () => {
  it('opens the panel and loads the plan', async () => {
    const { controller, operations } = withSetup()

    controller.openSubscribePanel()
    await flushPromises()

    expect(controller.showSubscribePanel.value).toBe(true)
    expect(operations.loadPlan).toHaveBeenCalledOnce()
    expect(controller.plan.value).toEqual(makePlan())
  })

  it('preselects active sources from the plan', async () => {
    const { controller, operations } = withSetup()
    operations.loadPlan.mockResolvedValue(makePlan({ active_sources: ['github', 'news'] }))

    controller.openSubscribePanel()
    await flushPromises()

    expect(controller.selectedSources.value).toEqual(['github', 'news'])
  })

  it('preselects the current source when no active sources exist', async () => {
    const { controller } = withSetup()

    controller.openSubscribePanel()
    await flushPromises()

    expect(controller.selectedSources.value).toEqual(['all'])
  })

  it('lets members accumulate multiple daily modules', () => {
    const { controller } = withSetup()
    controller.plan.value = makePlan()
    controller.selectedSources.value = []

    controller.toggleSubscribeSource('github')
    controller.toggleSubscribeSource('news')

    expect(controller.selectedSources.value).toEqual(['github', 'news'])
  })

  it('collapses the free tier to single-select so a second pick replaces the first', async () => {
    const { controller, operations } = withSetup()
    operations.loadPlan.mockResolvedValue(makePlan({ can_select_multiple_sources: false, max_sources: 1 }))

    controller.openSubscribePanel()
    await flushPromises()

    controller.toggleSubscribeSource('github')
    expect(controller.selectedSources.value).toEqual(['github'])

    controller.toggleSubscribeSource('news')
    expect(controller.selectedSources.value).toEqual(['news'])
  })

  it('deselects a picked source on second toggle regardless of tier', () => {
    const { controller } = withSetup()
    controller.selectedSources.value = []

    controller.toggleSubscribeSource('github')
    controller.toggleSubscribeSource('github')

    expect(controller.selectedSources.value).toEqual([])
  })

  it('keeps a new user on step one when no source is selected', () => {
    const { controller } = withSetup()
    controller.selectedSources.value = []

    controller.goToDeliveryStep()

    expect(controller.step.value).toBe(1)
  })

  it('lets an existing push-only plan clear sources and continue to delivery step', async () => {
    const { controller, operations } = withSetup()
    operations.loadPlan.mockResolvedValue(makePlan({
      active_sources: ['github'],
      capabilities: makePlan().capabilities.map(cap =>
        cap.key === 'push-webhook-7' ? { ...cap, active: true } : cap,
      ),
    }))

    controller.openSubscribePanel()
    await flushPromises()
    controller.selectedSources.value = []

    controller.goToDeliveryStep()

    expect(controller.step.value).toBe(2)
  })

  it('toggles selectable deliveries and ignores coming_soon items', () => {
    const { controller } = withSetup()
    controller.plan.value = makePlan()

    controller.toggleDelivery('rss-briefing')
    expect(controller.selectedDeliveryKeys.value).toContain('rss-briefing')

    controller.toggleDelivery('push-wechat-coming-soon')
    expect(controller.selectedDeliveryKeys.value).not.toContain('push-wechat-coming-soon')
  })

  it('submits the selected sources and deliveries', async () => {
    const { controller, operations } = withSetup()
    controller.plan.value = makePlan()
    controller.selectedSources.value = ['github']
    controller.selectedDeliveryKeys.value = ['rss-briefing', 'account-email']
    controller.step.value = 2

    await controller.confirmSubscriptionPlan()

    expect(operations.applyPlan).toHaveBeenCalledOnce()
    const payload = operations.applyPlan.mock.calls[0]![0]
    expect(payload.sources).toEqual(['github'])
    expect(payload.deliveries).toEqual([
      { kind: 'rss', feed: 'briefing' },
      { kind: 'account_email' },
    ])
    expect(controller.showSubscribePanel.value).toBe(false)
    expect(payload.sync).toBe(true)
    expect(controller.rssSubscribed.value).toBe(true)
    expect(controller.emailSubscribed.value).toBe(true)
    expect(copyToClipboard).toHaveBeenCalledWith(`${window.location.origin}/api/feeds/briefing.xml`)
    expect(controller.emailSentMsg.value).toBe(i18n.global.t('report.wizard.subscriptionAndRssCopied'))
  })

  it('preselects active deliveries but leaves RSS virtual delivery unselected', async () => {
    const { controller, operations } = withSetup()
    operations.loadPlan.mockResolvedValue(makePlan({
      active_sources: ['github'],
      capabilities: makePlan().capabilities.map(cap =>
        cap.key === 'account-email' || cap.key === 'push-webhook-7'
          ? { ...cap, active: true }
          : cap,
      ),
    }))

    controller.openSubscribePanel()
    await flushPromises()

    expect(controller.selectedDeliveryKeys.value).toEqual(['account-email', 'push-webhook-7'])
  })

  it('rejects a partial plan without sending a request', async () => {
    const { controller, operations, setError } = withSetup()
    controller.selectedSources.value = ['github']
    controller.selectedDeliveryKeys.value = []
    controller.step.value = 2

    await controller.confirmSubscriptionPlan()

    expect(setError).toHaveBeenCalledWith(i18n.global.t('report.wizard.errorPlanMustBeTogether'))
    expect(operations.applyPlan).not.toHaveBeenCalled()
  })

  it('confirms before clearing an existing plan and sends an empty sync payload', async () => {
    const { controller, operations } = withSetup()
    operations.loadPlan.mockResolvedValue(makePlan({
      active_sources: ['github'],
      capabilities: makePlan().capabilities.map(cap =>
        cap.key === 'account-email' ? { ...cap, active: true } : cap,
      ),
    }))
    controller.openSubscribePanel()
    await flushPromises()
    controller.selectedSources.value = []
    controller.selectedDeliveryKeys.value = []
    controller.step.value = 2
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)

    await controller.confirmSubscriptionPlan()

    expect(confirmSpy).toHaveBeenCalledWith(i18n.global.t('report.wizard.unsubscribeConfirm'))
    expect(operations.applyPlan).toHaveBeenCalledWith(expect.objectContaining({
      sources: [], deliveries: [], sync: true,
    }))
  })

  it('does not submit when the user cancels the full unsubscribe confirmation', async () => {
    const { controller, operations } = withSetup()
    controller.plan.value = makePlan({ active_sources: ['github'] })
    controller.selectedSources.value = []
    controller.selectedDeliveryKeys.value = []
    controller.step.value = 2
    vi.spyOn(window, 'confirm').mockReturnValue(false)

    await controller.confirmSubscriptionPlan()

    expect(operations.applyPlan).not.toHaveBeenCalled()
  })

  it('confirms partial reductions before submitting', async () => {
    const { controller, operations } = withSetup()
    controller.plan.value = makePlan({
      active_sources: ['github', 'news'],
      capabilities: makePlan().capabilities.map(cap =>
        cap.key === 'account-email' ? { ...cap, active: true } : cap,
      ),
    })
    controller.selectedSources.value = ['github']
    controller.selectedDeliveryKeys.value = ['account-email']
    controller.step.value = 2
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)

    await controller.confirmSubscriptionPlan()

    expect(confirmSpy).toHaveBeenCalledWith(i18n.global.t('report.wizard.reductionConfirm'))
    expect(operations.applyPlan).toHaveBeenCalledOnce()
  })

  it('does not fetch the member token for public RSS and caches it for member RSS', async () => {
    const { controller, operations } = withSetup()
    controller.plan.value = makePlan()

    await controller.copyRssLink(false)
    expect(operations.getFeedToken).not.toHaveBeenCalled()
    expect(copyToClipboard).toHaveBeenCalledWith(`${window.location.origin}/api/feeds/briefing.xml`)

    await controller.copyRssLink(true)
    await controller.copyRssLink(true)
    expect(operations.getFeedToken).toHaveBeenCalledOnce()
    expect(copySensitiveToClipboard).toHaveBeenLastCalledWith(
      `${window.location.origin}/api/feeds/briefing-digest.xml?token=${encodeURIComponent('aigc_feed_test token')}`,
    )
  })

  it('automatically copies the private digest for members after RSS subscription', async () => {
    const { controller, operations, membership } = withSetup({ member: true })
    controller.plan.value = makePlan()
    controller.selectedSources.value = ['github']
    controller.selectedDeliveryKeys.value = ['rss-briefing']
    controller.step.value = 2

    await controller.confirmSubscriptionPlan()

    expect(membership.value).toBe(true)
    expect(operations.getFeedToken).toHaveBeenCalledOnce()
    expect(copySensitiveToClipboard).toHaveBeenCalledWith(
      `${window.location.origin}/api/feeds/briefing-digest.xml?token=${encodeURIComponent('aigc_feed_test token')}`,
    )
    expect(controller.rssSubscribed.value).toBe(true)
  })

  it('keeps the applied RSS status when clipboard copy fails', async () => {
    const { controller, operations, setError } = withSetup()
    controller.plan.value = makePlan()
    controller.selectedSources.value = ['github']
    controller.selectedDeliveryKeys.value = ['rss-briefing']
    controller.step.value = 2
    vi.mocked(copyToClipboard).mockRejectedValueOnce(new Error('clipboard denied'))

    await controller.confirmSubscriptionPlan()

    expect(operations.applyPlan).toHaveBeenCalledOnce()
    expect(controller.rssSubscribed.value).toBe(true)
    expect(controller.emailSentMsg.value).not.toBe(i18n.global.t('report.wizard.subscriptionAndRssCopied'))
    expect(setError).toHaveBeenCalledWith(i18n.global.t('report.wizard.errorRss'))
  })

  it('clears session delivery statuses when the plan omits them', async () => {
    const { controller } = withSetup()
    controller.rssSubscribed.value = true
    controller.emailSubscribed.value = true
    controller.plan.value = makePlan()
    controller.selectedSources.value = ['github']
    controller.selectedDeliveryKeys.value = ['push-webhook-7']
    controller.step.value = 2

    await controller.confirmSubscriptionPlan()

    expect(controller.rssSubscribed.value).toBe(false)
    expect(controller.emailSubscribed.value).toBe(false)
  })

  it('clears session delivery statuses on account invalidation', async () => {
    const { controller, loggedIn, userId } = withSetup()
    controller.rssSubscribed.value = true
    controller.emailSubscribed.value = true

    loggedIn.value = false
    userId.value = null
    await flushPromises()

    expect(controller.rssSubscribed.value).toBe(false)
    expect(controller.emailSubscribed.value).toBe(false)
  })

  it('copies the active subscribed RSS link through the header action', async () => {
    const { controller } = withSetup({ member: true })
    controller.rssSubscribed.value = true

    await controller.copySubscribedRss()

    expect(copySensitiveToClipboard).toHaveBeenCalledWith(
      `${window.location.origin}/api/feeds/briefing-digest.xml?token=${encodeURIComponent('aigc_feed_test token')}`,
    )
  })

  it('requires confirmation before rotating the member RSS token', async () => {
    const { controller, operations } = withSetup()
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)

    expect(await controller.rotateRssToken()).toBe(false)
    expect(confirmSpy).toHaveBeenCalledWith(i18n.global.t('report.wizard.rssResetConfirm'))
    expect(operations.rotateFeedToken).not.toHaveBeenCalled()

    confirmSpy.mockReturnValue(true)
    expect(await controller.rotateRssToken()).toBe(true)
    expect(operations.rotateFeedToken).toHaveBeenCalledOnce()
    expect(controller.rssNotice.value).toBe('rss-rotated')
  })

  it('surfaces clipboard failures without exposing the token in the DOM or storage', async () => {
    const { controller, operations } = withSetup()
    controller.plan.value = makePlan()
    vi.mocked(copySensitiveToClipboard).mockRejectedValueOnce(new Error('clipboard denied'))

    expect(await controller.copyRssLink(true)).toBe(false)
    expect(document.body.textContent).not.toContain('aigc_feed_test token')
    expect(localStorage.getItem('aigc_feed_test token')).toBeNull()
    expect(operations.getFeedToken).toHaveBeenCalledOnce()
  })

  it('invalidates the in-memory RSS token when the account changes', async () => {
    const { controller, operations, userId } = withSetup()

    expect(await controller.copyRssLink(true)).toBe(true)
    userId.value = 43
    await flushPromises()
    expect(await controller.copyRssLink(true)).toBe(true)

    expect(operations.getFeedToken).toHaveBeenCalledTimes(2)
  })

  it('does not publish a stale plan after logout during loading', async () => {
    const { controller, operations, loggedIn, userId } = withSetup()
    let resolvePlan!: (plan: SubscriptionPlan) => void
    operations.loadPlan.mockReturnValueOnce(new Promise(resolve => { resolvePlan = resolve }))

    controller.openSubscribePanel()
    loggedIn.value = false
    userId.value = null
    resolvePlan(makePlan({ active_sources: ['github'] }))
    await flushPromises()

    expect(controller.plan.value).toBeNull()
    expect(controller.selectedSources.value).toEqual([])
  })
})

describe('useReportSubscriptions quota error mapping', () => {
  it('maps a 403 quota error to the localized upgrade message', async () => {
    const { controller, operations, setError } = withSetup()
    controller.selectedSources.value = ['github']
    controller.selectedDeliveryKeys.value = ['account-email']
    controller.plan.value = makePlan()
    controller.step.value = 2
    operations.applyPlan.mockRejectedValue({
      response: { status: 403, data: { detail: { code: 'quota-exceeded', message: '免费档最多订阅 1 个日报模块' } } },
    })

    await controller.confirmSubscriptionPlan()

    expect(setError).toHaveBeenCalledWith(i18n.global.t('report.wizard.errorQuotaExceeded'))
  })

  it('maps a 403 vip error to the localized vip message', async () => {
    const { controller, operations, setError } = withSetup()
    controller.selectedSources.value = ['github']
    controller.selectedDeliveryKeys.value = ['account-email']
    controller.plan.value = makePlan()
    controller.step.value = 2
    operations.applyPlan.mockRejectedValue({
      response: { status: 403, data: { detail: { code: 'vip-required', message: '当前功能仅对有效会员开放' } } },
    })

    await controller.confirmSubscriptionPlan()

    expect(setError).toHaveBeenCalledWith(i18n.global.t('report.wizard.errorVipRequired'))
  })

  it('passes through the server detail for non-quota failures', async () => {
    const { controller, operations, setError } = withSetup()
    controller.selectedSources.value = ['github']
    controller.selectedDeliveryKeys.value = ['account-email']
    controller.plan.value = makePlan()
    controller.step.value = 2
    operations.applyPlan.mockRejectedValue({
      response: { status: 400, data: { detail: '邮件未配置' } },
    })

    await controller.confirmSubscriptionPlan()

    expect(setError).toHaveBeenCalledWith('邮件未配置')
  })
})

describe('useReportSubscriptions login prompt flow', () => {
  beforeEach(() => { vi.useFakeTimers() })

  it('shows the inline prompt, then delegates to the global login dialog after 900ms', () => {
    const { controller, redirectToLogin, setError } = withSetup({ isLoggedIn: false })

    controller.promptLoginForSubscribe()
    expect(controller.showLoginPrompt.value).toBe(true)
    expect(setError).toHaveBeenCalledWith(i18n.global.t('report.loginError'))
    expect(redirectToLogin).not.toHaveBeenCalled()

    vi.advanceTimersByTime(900)
    expect(redirectToLogin).toHaveBeenCalledOnce()
    vi.useRealTimers()
  })

  it('cancels the deferred login request when the inline prompt is closed first', () => {
    const { controller, redirectToLogin } = withSetup({ isLoggedIn: false })

    controller.promptLoginForSubscribe()
    controller.closeLoginPrompt()
    vi.advanceTimersByTime(900)

    expect(redirectToLogin).not.toHaveBeenCalled()
    vi.useRealTimers()
  })

  it('cancels the deferred login request when the user becomes authenticated first', () => {
    const { controller, redirectToLogin, loggedIn } = withSetup({ isLoggedIn: false })

    controller.promptLoginForSubscribe()
    loggedIn.value = true
    vi.advanceTimersByTime(900)

    expect(redirectToLogin).not.toHaveBeenCalled()
    vi.useRealTimers()
  })

  it('login-and-redirect closes the inline prompt and fires immediately', () => {
    const { controller, redirectToLogin } = withSetup({ isLoggedIn: false })

    controller.promptLoginForSubscribe()
    controller.handleLoginAndRedirect()

    expect(controller.showLoginPrompt.value).toBe(false)
    expect(redirectToLogin).toHaveBeenCalledOnce()
    vi.useRealTimers()
  })

  it('anonymous subscribe attempts route through the prompt', () => {
    const { controller } = withSetup({ isLoggedIn: false })

    controller.toggleSubscribe()
    expect(controller.showLoginPrompt.value).toBe(true)
    expect(controller.showSubscribePanel.value).toBe(false)
    vi.useRealTimers()
  })

  it('unmount clears the pending login timer', () => {
    const { controller, redirectToLogin, wrapper } = withSetup({ isLoggedIn: false })

    controller.promptLoginForSubscribe()
    wrapper.unmount()
    vi.advanceTimersByTime(900)

    expect(redirectToLogin).not.toHaveBeenCalled()
    vi.useRealTimers()
  })
})
