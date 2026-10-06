import { mount, RouterLinkStub, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { createI18n } from 'vue-i18n'
import TrackingDigestHistory from './TrackingDigestHistory.vue'
import { trackingZh } from '@/i18n/locales/tracking'
import type { TrackingDigest } from '@/features/tracking/trackingModel'

let wrapper: VueWrapper
let observations: ((entries: { isIntersecting: boolean; intersectionRatio: number }[]) => void)[]
const issue = (id: number): TrackingDigest => ({
  id, issue_date: '2026-09-11', delivery_status: 'none', truncated: false, created_at: '2026-09-11T00:00:00Z',
  items: [{ key: 'item-' + id, title: 'RAG update', summary: 'Example result', source: 'news',
    url: 'https://example.com', observed_at: '2026-09-11T00:00:00Z', matched_rules: ['RAG'] }],
})
beforeEach(() => {
  vi.useFakeTimers()
  observations = []
  vi.stubGlobal('IntersectionObserver', class {
    constructor(callback: typeof observations[number]) { observations.push(callback) }
    observe() {}
    disconnect() {}
  })
  Object.defineProperty(document, 'hidden', { value: false, configurable: true })
})
afterEach(() => {
  wrapper?.unmount()
  vi.unstubAllGlobals()
  vi.useRealTimers()
  Reflect.deleteProperty(document, 'hidden')
})
async function render(digests = [issue(10)], props: Record<string, unknown> = {}) {
  wrapper = mount(TrackingDigestHistory, { attachTo: document.body, props: { digests, ...props }, global: {
    plugins: [createI18n({ legacy: false, locale: 'zh', messages: { zh: {
      tracking: trackingZh, subscriptions: { sources: { news: '新闻' } },
    } } })],
    stubs: { RouterLink: RouterLinkStub },
  } })
  await nextTick()
}
const intersect = (value: boolean, callback = observations[observations.length - 1]!) =>
  callback([{ isIntersecting: value, intersectionRatio: value ? 1 : 0 }])

describe('viewing tracking results', () => {
  it('does not acknowledge merely loading a page; waits for the result to enter the viewport', async () => {
    await render()
    expect(wrapper.emitted('viewed')).toBeUndefined()
    intersect(false)
    expect(wrapper.emitted('viewed')).toBeUndefined()
    intersect(true)
    expect(wrapper.emitted('viewed')).toEqual([[10]])
  })
  it('waits for tab visibility and retries only while visible', async () => {
    await render()
    Object.defineProperty(document, 'hidden', { value: true, configurable: true })
    intersect(true)
    await vi.advanceTimersByTimeAsync(30_000)
    expect(wrapper.emitted('viewed')).toBeUndefined()
    Object.defineProperty(document, 'hidden', { value: false, configurable: true })
    document.dispatchEvent(new Event('visibilitychange'))
    expect(wrapper.emitted('viewed')).toEqual([[10]])
    intersect(false)
    await vi.advanceTimersByTimeAsync(30_000)
    expect(wrapper.emitted('viewed')).toHaveLength(1)
  })
  it('never marks a new issue using visibility from the old one', async () => {
    await render()
    const old = observations[0]!
    intersect(true)
    await wrapper.setProps({ digests: [issue(11)] })
    intersect(true, old)
    expect(wrapper.emitted('viewed')).toEqual([[10]])
    intersect(true)
    expect(wrapper.emitted('viewed')).toEqual([[10], [11]])
  })
  it('flags surging keywords above the results, with the daily average to one decimal', async () => {
    await render([{ ...issue(10), surges: [
      { query: 'Agent', count: 23, baseline: 4 },
      { query: 'RAG', count: 5, baseline: 0.7 },
    ] }])
    const surges = wrapper.get('.tracking-surges')
    expect(surges.get('.tracking-surges-title').text()).toBe('热度飙升')
    expect(surges.findAll('li').map((line) => line.text())).toEqual([
      '「Agent」近 24 小时 23 条，前 7 天日均 4 条',
      '「RAG」近 24 小时 5 条，前 7 天日均 0.7 条',
    ])
    const results = wrapper.get('.tracking-results').element
    expect(surges.element.compareDocumentPosition(results) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    // 免费账号与存量简报是空列表，旧后端没有这个字段：都不显示
    await wrapper.setProps({ digests: [{ ...issue(11), surges: [] }] })
    expect(wrapper.find('.tracking-surges').exists()).toBe(false)
    await wrapper.setProps({ digests: [issue(12)] })
    expect(wrapper.find('.tracking-surges').exists()).toBe(false)
  })
  it('has no receipt for missing or empty results', async () => {
    await render([])
    expect(observations).toHaveLength(0)
    await wrapper.setProps({ digests: [{ ...issue(10), items: [] }] })
    expect(observations).toHaveLength(0)
    expect(wrapper.emitted('viewed')).toBeUndefined()
  })
})

describe('exporting digest history', () => {
  it('offers vip members CSV and JSON next to the issue picker', async () => {
    await render([issue(10)], { member: true })
    const group = wrapper.get('.tracking-digest-tools [role="group"]')
    expect(group.attributes('aria-label')).toBe('导出最近 90 天简报')
    const buttons = group.findAll('button')
    expect(buttons.map((button) => button.text())).toEqual(['CSV', 'JSON'])
    expect(buttons[0]!.attributes('title')).toBe('CSV：一行一条结果，可用 Excel 打开')
    await buttons[1]!.trigger('click')
    expect(wrapper.emitted('export')).toEqual([['json']])
    expect(wrapper.find('.tracking-digest-tools select').exists()).toBe(true)
    expect(wrapper.findComponent(RouterLinkStub).exists()).toBe(false)
  })
  it('locks both formats while one downloads and shows why an export failed', async () => {
    await render([issue(10)], { member: true, exporting: 'csv' })
    const buttons = wrapper.findAll('.tracking-export button')
    expect(buttons.map((button) => button.attributes('disabled'))).toEqual(['', ''])
    expect(buttons.map((button) => button.attributes('aria-busy'))).toEqual(['true', 'false'])
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    await wrapper.setProps({ exporting: '', exportError: 'membership_required' })
    expect(wrapper.get('[role="alert"]').text()).toBe('导出是 VIP 权益，开通后即可使用。')
  })
  it('points free accounts to vip instead, and shows nothing without digests', async () => {
    await render()
    expect(wrapper.find('.tracking-export').exists()).toBe(false)
    const link = wrapper.getComponent(RouterLinkStub)
    expect(link.props('to')).toBe('/membership')
    expect(link.text()).toBe('VIP 可导出')
    expect(link.attributes('title')).toBe('开通 VIP 后可导出最近 90 天简报（CSV / JSON）')
    await wrapper.setProps({ digests: [], member: true })
    expect(wrapper.find('.tracking-digest-tools').exists()).toBe(false)
  })
})
