import { mount } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useReportSubscriptions } from './useReportSubscriptions'
import { i18n } from '@/i18n'
import type { ReportKey } from '@/features/report/reportViewModel'

const makeOperations = () => ({
  loadSubscriptions: vi.fn().mockResolvedValue({ items: [] }),
  subscribeSources: vi.fn().mockResolvedValue({ sources: [] }),
  unsubscribe: vi.fn().mockResolvedValue(undefined),
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

describe('useReportSubscriptions tier-aware source selection', () => {
  it('lets members accumulate multiple daily modules', () => {
    const { controller } = withSetup({ isMember: true })

    controller.toggleSubscribeSource('github')
    controller.toggleSubscribeSource('news')

    expect(controller.selectedSubscribeSources.value).toEqual(['github', 'news'])
  })

  it('collapses the free tier to single-select so a second pick replaces the first', () => {
    const { controller } = withSetup({ isMember: false })

    controller.toggleSubscribeSource('github')
    expect(controller.selectedSubscribeSources.value).toEqual(['github'])

    controller.toggleSubscribeSource('news')
    expect(controller.selectedSubscribeSources.value).toEqual(['news'])
  })

  it('deselects a picked source on second toggle regardless of tier', () => {
    const { controller } = withSetup({ isMember: false })

    controller.toggleSubscribeSource('github')
    controller.toggleSubscribeSource('github')

    expect(controller.selectedSubscribeSources.value).toEqual([])
  })
})

describe('useReportSubscriptions quota error mapping', () => {
  it('maps a 403 from subscribeSources to the localized upgrade message', async () => {
    const { controller, operations, setError } = withSetup({ isMember: false })
    controller.toggleSubscribeSource('github')
    operations.subscribeSources.mockRejectedValue({
      response: { status: 403, data: { detail: '免费档最多订阅 1 个日报模块' } },
    })

    await controller.confirmSubscribeSources()

    expect(setError).toHaveBeenCalledWith(i18n.global.t('report.subscribeQuotaExceeded'))
  })

  it('passes through the server detail for non-quota failures', async () => {
    const { controller, operations, setError } = withSetup({ isMember: false })
    controller.toggleSubscribeSource('github')
    operations.subscribeSources.mockRejectedValue({
      response: { status: 400, data: { detail: '邮件未配置' } },
    })

    await controller.confirmSubscribeSources()

    expect(setError).toHaveBeenCalledWith('邮件未配置')
  })
})

describe('useReportSubscriptions login prompt flow', () => {
  beforeEach(() => { vi.useFakeTimers() })

  it('shows the inline prompt, then delegates to the global login dialog after 900ms', () => {
    const { controller, redirectToLogin, setError } = withSetup({ isLoggedIn: false })

    controller.promptLoginForSubscribe()
    expect(controller.showLoginPrompt.value).toBe(true)
    expect(setError).toHaveBeenCalledWith('请先登录后再订阅简报')
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

  it('anonymous manage-subscriptions attempts route through the prompt', () => {
    const { controller } = withSetup({ isLoggedIn: false })

    controller.handleManageSubscriptions()
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
