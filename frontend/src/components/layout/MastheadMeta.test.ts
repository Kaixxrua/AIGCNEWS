import { createApp, defineComponent, nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MastheadMeta from './MastheadMeta.vue'
import i18n, { setAppLocale } from '@/i18n'
import { fetchLiveStats } from '@/services/dashboard/dashboardLiveApi'

/* RollingNumber 依赖 number-flow 自定义元素（jsdom 无 ResizeObserver），
   桩化为纯文本渲染，仅校验传入的 value。 */
vi.mock('@/components/dashboard/RollingNumber.vue', () => ({
  default: defineComponent({
    name: 'RollingNumber',
    props: { value: { type: Number, required: true } },
    template: '<span class="rolling-number-stub">{{ value }}</span>',
  }),
}))

vi.mock('@/services/dashboard/dashboardLiveApi', () => ({
  fetchLiveStats: vi.fn(),
}))

/* SSE 单例在 jsdom 下无 EventSource；桩化订阅入口避免真实连接。 */
vi.mock('@/composables/useLiveStatsStream', () => ({
  subscribeLiveStats: vi.fn(() => () => {}),
}))

const fetchLiveStatsMock = vi.mocked(fetchLiveStats)

let unmount: (() => void) | undefined

const mountMasthead = () => {
  const host = document.createElement('div')
  document.body.appendChild(host)
  const app = createApp(MastheadMeta)
  app.use(i18n)
  app.mount(host)
  unmount = () => { app.unmount(); host.remove() }
  return host
}

const expectedDateLine = (locale: string) =>
  new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    weekday: 'short',
  }).format(new Date())

describe('MastheadMeta', () => {
  beforeEach(() => {
    setAppLocale('zh-CN')
    fetchLiveStatsMock.mockResolvedValue({ today_new_documents: 7 })
  })

  afterEach(() => {
    unmount?.()
    unmount = undefined
    vi.clearAllMocks()
  })

  it('renders the masthead date line and today-new label', async () => {
    const host = mountMasthead()
    await nextTick()

    const date = host.querySelector('.masthead-meta__date')
    expect(date?.textContent).toBe(expectedDateLine('zh-CN'))
    expect(host.querySelector('.masthead-meta__today')?.textContent).toContain('今日更新')
  })

  it('loads today_new_documents on mount and feeds it to the rolling number', async () => {
    const host = mountMasthead()
    await vi.waitFor(() => {
      expect(host.querySelector('.rolling-number-stub')?.textContent).toBe('7')
    })
    expect(fetchLiveStatsMock).toHaveBeenCalled()
  })

  it('follows the active locale for date and label', async () => {
    setAppLocale('en-US')
    const host = mountMasthead()
    await nextTick()

    const date = host.querySelector('.masthead-meta__date')
    expect(date?.textContent).toBe(expectedDateLine('en-US'))
    expect(host.querySelector('.masthead-meta__today')?.textContent).toContain('New today')
  })
})
