import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import ReportArchiveLinks from './ReportArchiveLinks.vue'
import { i18n } from '@/i18n'
import { api } from '@/services/http/apiClient'

vi.mock('@/services/http/apiClient', () => ({ api: { get: vi.fn() } }))
const get = vi.mocked(api.get)
const wrappers: ReturnType<typeof mount>[] = []
const show = () => {
  const wrapper = mount(ReportArchiveLinks, {
    props: { source: 'news', date: '2026-10-20' }, global: { plugins: [i18n] },
  })
  wrappers.push(wrapper)
  return wrapper
}
const links = [{ date: '2026-10-18', url: '/report?date=2026-10-18&type=news&lang=zh-CN' }]

beforeEach(() => { get.mockReset(); i18n.global.locale.value = 'zh-CN' })
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); i18n.global.locale.value = 'zh-CN' })

it('renders ordinary crawlable links to published issues with explicit dates and locale', async () => {
  get.mockResolvedValue({ data: { items: links } })
  const wrapper = show()
  await flushPromises()
  expect(wrapper.get('nav').attributes('aria-label')).toBe('往期简报')
  expect(wrapper.get('a').attributes('href')).toBe(links[0]!.url)
  expect(wrapper.get('time').attributes('datetime')).toBe('2026-10-18')
  expect(get).toHaveBeenCalledWith('/report/archive', expect.objectContaining({
    params: { source: 'news', date: '2026-10-20', locale: 'zh-CN' },
  }))
})

it('replaces links when language changes and ignores an older in-flight response', async () => {
  let resolveFirst: (value: unknown) => void = () => {}
  get.mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve }))
  const wrapper = show()
  const firstSignal = get.mock.calls[0]![1]!.signal as AbortSignal
  get.mockResolvedValue({ data: { items: [{ ...links[0], url: links[0]!.url.replace('zh-CN', 'en-US') }] } })
  i18n.global.locale.value = 'en-US'
  await flushPromises()
  expect(firstSignal.aborted).toBe(true)
  expect(wrapper.get('nav').attributes('aria-label')).toBe('Earlier briefings')
  expect(wrapper.get('a').attributes('href')).toContain('lang=en-US')
  resolveFirst({ data: { items: links } })
  await flushPromises()
  expect(wrapper.get('a').attributes('href')).toContain('lang=en-US')
})

it('clears stale links for failed requests or sources without public archives', async () => {
  get.mockResolvedValueOnce({ data: { items: links } }).mockRejectedValueOnce(new Error('offline'))
  const wrapper = show()
  await flushPromises()
  await wrapper.setProps({ date: '2026-10-17' })
  await flushPromises()
  expect(wrapper.find('nav').exists()).toBe(false)
  await wrapper.setProps({ source: 'x' })
  expect(get).toHaveBeenCalledTimes(2)
  wrapper.unmount()
  expect((get.mock.calls[1]![1]!.signal as AbortSignal).aborted).toBe(true)
})
