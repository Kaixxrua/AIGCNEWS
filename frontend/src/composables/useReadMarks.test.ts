import { mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, h, nextTick, ref, withDirectives, type Ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { READ_MARKS, useReadMarks, type ReadMarks } from './useReadMarks'

// jsdom 没有 IntersectionObserver：换成一个由用例报告露出多少的假观察器。
class FakeObserver {
  static all: FakeObserver[] = []
  observed = new Set<Element>()
  callback: IntersectionObserverCallback
  constructor(callback: IntersectionObserverCallback) {
    this.callback = callback
    FakeObserver.all.push(this)
  }
  observe(el: Element) { this.observed.add(el) }
  unobserve(el: Element) { this.observed.delete(el) }
  disconnect() { this.observed.clear() }
  takeRecords() { return [] }
}
/** 报告一个条目露出了多少：ratio 是露出自身的比例，height 是露出部分的高度（视口 800）。 */
const show = (el: Element, ratio: number, height = ratio * 100) => {
  for (const observer of FakeObserver.all) {
    if (!observer.observed.has(el)) continue
    const entry = { target: el, isIntersecting: ratio > 0, intersectionRatio: ratio, intersectionRect: { height }, rootBounds: { height: 800 } }
    observer.callback([entry as unknown as IntersectionObserverEntry], observer as unknown as IntersectionObserver)
  }
}
const stored = (list = 'test') => Object.keys(JSON.parse(localStorage.getItem(`read_marks_${list}`) ?? '{}')).sort()
let visibility: DocumentVisibilityState = 'visible'
const setVisibility = (state: DocumentVisibilityState) => {
  visibility = state
  document.dispatchEvent(new Event('visibilitychange'))
}

const mounted: VueWrapper[] = []
const mountList = (ids: Ref<string[]>, enabled: Ref<boolean> = ref(true), list = 'test') => {
  let marks!: ReadMarks
  const Probe = defineComponent({
    setup() {
      marks = useReadMarks({ list, enabled })
      return () => h('ul', ids.value.map((id, index) => withDirectives(h('li', { key: index, 'data-index': index }), [[marks.directive, id]])))
    },
  })
  const wrapper = mount(Probe, { attachTo: document.body })
  mounted.push(wrapper)
  return { marks, wrapper, item: (index: number) => wrapper.element.querySelector(`[data-index="${index}"]`)! }
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal('IntersectionObserver', FakeObserver)
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => visibility })
  visibility = 'visible'
  localStorage.clear()
})
afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  FakeObserver.all = []
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('useReadMarks', () => {
  it('records what stays half in view long enough and dims it on the next visit', () => {
    const { marks, item } = mountList(ref(['a', 'b', 'c']))

    show(item(0), 0.6)
    vi.advanceTimersByTime(READ_MARKS.dwellMs - 1)
    show(item(1), 0.6)
    vi.advanceTimersByTime(1)
    // 一闪而过的不算；比屏幕还高的条目露出半屏就算。
    vi.advanceTimersByTime(READ_MARKS.dwellMs / 2)
    show(item(1), 0.2)
    show(item(2), 0.3, 420)
    vi.advanceTimersByTime(READ_MARKS.dwellMs + READ_MARKS.flushMs)
    expect(stored()).toEqual(['a', 'c'])

    // 这一次里看过的不变淡，也不算「上次看过」。
    expect(marks.isRead('a')).toBe(false)
    expect(marks.seenBefore('a')).toBe(false)
    marks.snapshot()
    expect(marks.isRead('a')).toBe(true)
    expect(marks.seenBefore('c')).toBe(true)
    expect(marks.isRead('b')).toBe(false)
  })

  it('remembers across visits in this browser', () => {
    const first = mountList(ref(['a', 'b']))
    show(first.item(0), 1)
    vi.advanceTimersByTime(READ_MARKS.dwellMs)
    first.wrapper.unmount()
    mounted.splice(mounted.indexOf(first.wrapper), 1)

    const { marks } = mountList(ref(['a', 'b']))
    expect(marks.seenBefore('a')).toBe(true)
    expect(marks.isRead('a')).toBe(true)
    expect(marks.isRead('b')).toBe(false)
  })

  it('dims an opened item at once without moving the divider', () => {
    const { marks } = mountList(ref(['a']))
    marks.markOpened('a')
    expect(marks.isRead('a')).toBe(true)
    expect(marks.seenBefore('a')).toBe(false)
    marks.snapshot()
    expect(marks.seenBefore('a')).toBe(true)
  })

  it('keeps and shows nothing while disabled', async () => {
    localStorage.setItem('read_marks_test', JSON.stringify({ old: Math.floor(Date.now() / 60_000) }))
    const enabled = ref(false)
    const { marks, item } = mountList(ref(['a']), enabled)
    show(item(0), 1)
    vi.advanceTimersByTime(READ_MARKS.dwellMs)
    marks.markOpened('b')
    vi.advanceTimersByTime(READ_MARKS.flushMs)
    expect(stored()).toEqual(['old'])
    expect(marks.isRead('old')).toBe(false)
    expect(marks.seenBefore('old')).toBe(false)

    enabled.value = true
    await nextTick()
    expect(marks.isRead('old')).toBe(true)
    show(item(0), 1)
    vi.advanceTimersByTime(READ_MARKS.dwellMs + READ_MARKS.flushMs)
    expect(stored()).toEqual(['a', 'old'])
  })

  it('stops the clock while the tab is in the background', () => {
    const { item } = mountList(ref(['a']))
    show(item(0), 1)
    vi.advanceTimersByTime(READ_MARKS.dwellMs / 2)
    setVisibility('hidden')
    vi.advanceTimersByTime(READ_MARKS.dwellMs * 3)
    expect(stored()).toEqual([])

    setVisibility('visible')
    vi.advanceTimersByTime(READ_MARKS.dwellMs + READ_MARKS.flushMs)
    expect(stored()).toEqual(['a'])
  })

  it('follows an element that is reused for another item', async () => {
    const ids = ref(['a'])
    const { item } = mountList(ids)
    show(item(0), 1)
    vi.advanceTimersByTime(READ_MARKS.dwellMs / 2)
    ids.value = ['b']
    await nextTick()
    show(item(0), 1)
    vi.advanceTimersByTime(READ_MARKS.dwellMs + READ_MARKS.flushMs)
    expect(stored()).toEqual(['b'])
  })

  it('forgets old marks, keeps the newest up to the limit and merges other tabs', () => {
    vi.setSystemTime(new Date('2026-10-02T08:00:00Z'))
    const minute = Math.floor(Date.now() / 60_000)
    const day = 24 * 60
    localStorage.setItem('read_marks_test', JSON.stringify({ stale: minute - (READ_MARKS.keepDays + 1) * day, kept: minute - day }))
    const limit = READ_MARKS.limit
    READ_MARKS.limit = 3
    try {
      const { marks } = mountList(ref([]))
      expect(marks.seenBefore('stale')).toBe(false)
      expect(marks.seenBefore('kept')).toBe(true)

      // 另一个标签页这期间记下了 other。
      localStorage.setItem('read_marks_test', JSON.stringify({ kept: minute - day, other: minute - 5 }))
      marks.markOpened('x')
      vi.advanceTimersByTime(60_000)
      marks.markOpened('y')
      vi.advanceTimersByTime(READ_MARKS.flushMs)
      expect(stored()).toEqual(['other', 'x', 'y'])
    } finally {
      READ_MARKS.limit = limit
    }
  })

  it('works without storage', () => {
    localStorage.setItem('read_marks_test', '{not json')
    const broken = mountList(ref(['a']))
    expect(broken.marks.isRead('a')).toBe(false)

    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('denied') })
    const { marks } = mountList(ref(['a']))
    marks.markOpened('a')
    vi.advanceTimersByTime(READ_MARKS.flushMs)
    expect(marks.isRead('a')).toBe(true)
    marks.snapshot()
    expect(marks.seenBefore('a')).toBe(true)
  })
})
