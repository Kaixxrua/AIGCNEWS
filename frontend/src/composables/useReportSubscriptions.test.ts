import { mount } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { useReportSubscriptions } from './useReportSubscriptions'
import { i18n } from '@/i18n'
import type { ReportKey } from '@/features/report/reportViewModel'

const makeOperations = () => ({
  loadSubscriptions: vi.fn().mockResolvedValue({ items: [] }),
  subscribeSources: vi.fn().mockResolvedValue({ sources: [] }),
  unsubscribe: vi.fn().mockResolvedValue(undefined),
  sendToEmail: vi.fn().mockResolvedValue(undefined),
})

const withSetup = ({ isMember = true }: { isMember?: boolean } = {}) => {
  const operations = makeOperations()
  const setError = vi.fn()
  let controller!: ReturnType<typeof useReportSubscriptions>
  mount(
    defineComponent({
      setup() {
        controller = useReportSubscriptions({
          isLoggedIn: ref(true),
          isMember: ref(isMember),
          selectedSource: ref<ReportKey>('all'),
          selectedDate: ref('2026-08-17'),
          locale: ref('zh-CN'),
          operations,
          redirectToLogin: vi.fn(),
          setError,
        })
        return () => null
      },
    }),
  )
  return { controller, operations, setError }
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
