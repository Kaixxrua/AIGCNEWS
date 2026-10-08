import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import DashboardNewWords from './DashboardNewWords.vue'
import { fetchNewWords, type NewWord, type NewWordsSnapshot } from '@/services/dashboard/newWordsApi'
import zh from '@/i18n/locales/zh-CN'

vi.mock('@/services/dashboard/newWordsApi', () => ({ fetchNewWords: vi.fn() }))
const showModal = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'showModal')
const close = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'close')
beforeAll(() => {
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value() { this.setAttribute('open', '') } })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value() { this.removeAttribute('open'); this.dispatchEvent(new Event('close')) } })
})
afterAll(() => {
  for (const [name, descriptor] of [['showModal', showModal], ['close', close]] as const) {
    if (descriptor) Object.defineProperty(HTMLDialogElement.prototype, name, descriptor)
    else Reflect.deleteProperty(HTMLDialogElement.prototype, name)
  }
})
const word: NewWord = {
  id: 'prism', term: 'Prism Routing', definition_zh: '测试用训练机制解释。', definition_en: 'Fixture definition.',
  reason_zh: '测试用的新意说明。', reason_en: 'Fixture novelty.',
  first_seen: '2026-10-07',
  evidence: [{ id: 'paper', title: 'Original paper', url: 'https://arxiv.org/abs/example', source: 'arxiv', published_at: '2026-10-07' }],
}
function snapshot(date = '2026-10-08', items = [word]): NewWordsSnapshot {
  return { date, generated_at: null, status: items.length ? 'ready' : 'empty', items }
}
let wrapper: VueWrapper | undefined
function render() {
  wrapper = mount(DashboardNewWords, {
    attachTo: document.body,
    props: { date: '2026-10-08', historical: false },
    global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zh } })] },
  })
  return wrapper
}
afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  vi.resetAllMocks()
  vi.useRealTimers()
  document.body.innerHTML = ''
})

describe('homepage new concepts', () => {
  it('shows at most two concepts and opens source-backed details without an unsafe link', async () => {
    const unsafe = { ...word, evidence: [...word.evidence, { ...word.evidence[0]!, id: 'unsafe', url: 'javascript:alert(1)' }] }
    vi.mocked(fetchNewWords).mockResolvedValue(snapshot('2026-10-08', [unsafe, { ...word, id: 'second', term: 'Test Two' }, { ...word, id: 'third' }]))
    const view = render()
    await flushPromises()
    expect(view.findAll('.new-word')).toHaveLength(2)
    await view.get('.new-word').trigger('click')
    await flushPromises()
    const dialog = document.querySelector('dialog')!
    expect(dialog.open).toBe(true)
    expect(dialog.textContent).toContain(word.definition_zh)
    expect(dialog.textContent).toContain(word.reason_zh)
    expect(dialog.querySelectorAll('a')).toHaveLength(1)
    expect(dialog.querySelector('a')?.rel).toBe('noopener noreferrer')
    expect(dialog.querySelector('a')?.href).toBe(word.evidence[0]!.url)
    ;(dialog.querySelector('button') as HTMLButtonElement).click()
    await flushPromises()
    expect(dialog.open).toBe(false)
  })

  it('never shows yesterday’s words while a new calendar request is pending', async () => {
    let resolveOld!: (value: NewWordsSnapshot) => void
    vi.mocked(fetchNewWords).mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve }))
    vi.mocked(fetchNewWords).mockResolvedValueOnce(snapshot('2026-10-07', [{ ...word, term: 'History fixture' }]))
    const view = render()
    const signal = vi.mocked(fetchNewWords).mock.calls[0]![1]
    await view.setProps({ date: '2026-10-07', historical: true })
    await flushPromises()
    expect(signal.aborted).toBe(true)
    expect(view.text()).toContain('当日热词')
    expect(view.text()).toContain('History fixture')
    resolveOld(snapshot())
    await flushPromises()
    expect(view.text()).not.toContain('Prism Routing')
  })

  it('closes details on date change and uses an honest empty state', async () => {
    vi.mocked(fetchNewWords).mockResolvedValueOnce(snapshot()).mockResolvedValueOnce(snapshot('2026-10-06', []))
    const view = render()
    await flushPromises()
    await view.get('.new-word').trigger('click')
    await view.setProps({ date: '2026-10-06', historical: true })
    await flushPromises()
    expect(document.querySelector('dialog')!.open).toBe(false)
    expect(view.find('.new-word').exists()).toBe(false)
    expect(view.text()).toContain('暂无符合条件的新概念')
  })

  it('retries failures and preserves same-day words during a failed refresh', async () => {
    vi.useFakeTimers()
    vi.mocked(fetchNewWords).mockRejectedValueOnce(new Error('Offline')).mockResolvedValueOnce(snapshot()).mockRejectedValueOnce(new Error('Offline'))
    const view = render()
    await flushPromises()
    expect(view.text()).toContain('热词暂时读取失败')
    expect(view.find('.new-word').exists()).toBe(false)
    await view.get('.new-words-retry').trigger('click')
    await flushPromises()
    expect(view.text()).toContain(word.term)
    await vi.advanceTimersByTimeAsync(60_000)
    await flushPromises()
    expect(view.text()).toContain(word.term)
    expect(view.get('.new-words-retry').text()).toBe('重试')
  })
})
