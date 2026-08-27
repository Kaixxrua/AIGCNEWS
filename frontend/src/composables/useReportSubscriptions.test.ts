import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useReportSubscriptions } from './useReportSubscriptions'
import { i18n } from '@/i18n'
import type { ReportKey, SubscriptionPlan } from '@/features/report/reportViewModel'

const makePlan = (overrides: Partial<SubscriptionPlan> = {}): SubscriptionPlan => ({
  can_select_multiple_sources: true,
  max_sources: 8,
  active_sources: [],
  capabilities: [
    { kind: 'rss', key: 'rss-briefing', feed: 'briefing', selectable: true, disabled_reason: null },
    { kind: 'account_email', key: 'account-email', selectable: true, disabled_reason: null },
    { kind: 'push_channel', key: 'push-webhook-7', channel_id: 7, channel_type: 'webhook', target: 'https://example.com/hook', verified: true, status: 'active', selectable: true, disabled_reason: null },
    { kind: 'push_channel', key: 'push-wechat-coming-soon', channel_type: 'wechat', verified: false, status: 'coming_soon', selectable: false, disabled_reason: '暂未开放' },
  ],
  ...overrides,
})

const makeOperations = () => ({
  loadPlan: vi.fn().mockResolvedValue(makePlan()),
  loadSubscriptions: vi.fn().mockResolvedValue({ items: [] }),
  applyPlan: vi.fn().mockResolvedValue({ sources: ['github'], deliveries: [{ kind: 'account_email', status: 'applied' }] }),
  sendToEmail: vi.fn().mockResolvedValue(undefined),
})

const withSetup = ({ isMember = true, isLoggedIn = true }: { isMember?: boolean; isLoggedIn?: boolean } = {}) => {
  const operations = makeOperations()
  const setError = vi.fn()
  const redirectToLogin = vi.fn()
  const loggedIn = ref(isLoggedIn)
  let controller!: ReturnType<typeof useReportSubscriptions>
  const wrapper = mount(
    defineComponent({
      setup() {
        controller = useReportSubscriptions({
          isLoggedIn: loggedIn,
          isMember: ref(isMember),
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
  return { controller, operations, setError, redirectToLogin, loggedIn, wrapper }
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
    const { controller } = withSetup({ isMember: true })
    controller.plan.value = makePlan()
    controller.selectedSources.value = []

    controller.toggleSubscribeSource('github')
    controller.toggleSubscribeSource('news')

    expect(controller.selectedSources.value).toEqual(['github', 'news'])
  })

  it('collapses the free tier to single-select so a second pick replaces the first', async () => {
    const { controller, operations } = withSetup({ isMember: false })
    operations.loadPlan.mockResolvedValue(makePlan({ can_select_multiple_sources: false, max_sources: 1 }))

    controller.openSubscribePanel()
    await flushPromises()

    controller.toggleSubscribeSource('github')
    expect(controller.selectedSources.value).toEqual(['github'])

    controller.toggleSubscribeSource('news')
    expect(controller.selectedSources.value).toEqual(['news'])
  })

  it('deselects a picked source on second toggle regardless of tier', () => {
    const { controller } = withSetup({ isMember: false })
    controller.selectedSources.value = []

    controller.toggleSubscribeSource('github')
    controller.toggleSubscribeSource('github')

    expect(controller.selectedSources.value).toEqual([])
  })

  it('advances to delivery step only when at least one source is selected', () => {
    const { controller } = withSetup()
    controller.selectedSources.value = []

    controller.goToDeliveryStep()

    expect(controller.step.value).toBe(1)
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
    const payload = operations.applyPlan.mock.calls[0][0]
    expect(payload.sources).toEqual(['github'])
    expect(payload.deliveries).toEqual([
      { kind: 'rss', feed: 'briefing' },
      { kind: 'account_email' },
    ])
    expect(controller.showSubscribePanel.value).toBe(false)
  })

  it('requires at least one delivery before submitting', async () => {
    const { controller, setError } = withSetup()
    controller.selectedSources.value = ['github']
    controller.selectedDeliveryKeys.value = []
    controller.step.value = 2

    await controller.confirmSubscriptionPlan()

    expect(setError).toHaveBeenCalledWith(i18n.global.t('report.wizard.errorNoDelivery'))
  })
})

describe('useReportSubscriptions quota error mapping', () => {
  it('maps a 403 quota error to the localized upgrade message', async () => {
    const { controller, operations, setError } = withSetup({ isMember: false })
    controller.selectedSources.value = ['github']
    controller.selectedDeliveryKeys.value = ['account-email']
    controller.deliveryCapabilities.value = makePlan().capabilities
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
    controller.deliveryCapabilities.value = makePlan().capabilities
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
    controller.deliveryCapabilities.value = makePlan().capabilities
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
