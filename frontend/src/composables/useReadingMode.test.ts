import { mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, nextTick, ref, type Ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { READING_MODE, useReadingMode } from './useReadingMode'

// jsdom 不排版：滚动容器的尺寸和滚动位置都由用例写死。
const scroller = (clientHeight: number, scrollHeight: number) => {
  const element = document.createElement('div')
  let top = 0
  Object.defineProperty(element, 'clientHeight', { configurable: true, get: () => clientHeight })
  Object.defineProperty(element, 'scrollHeight', { configurable: true, get: () => scrollHeight })
  Object.defineProperty(element, 'scrollTop', { configurable: true, get: () => top, set: (value: number) => { top = value } })
  return element
}
const scrollTo = (element: Element, top: number) => {
  element.scrollTop = top
  element.dispatchEvent(new Event('scroll'))
}
// 一路滚过去，每步 20px，和滚轮差不多。
const scrollAlong = (element: Element, to: number) => {
  const step = to > element.scrollTop ? 20 : -20
  while (element.scrollTop !== to) scrollTo(element, Math.abs(to - element.scrollTop) < 20 ? to : element.scrollTop + step)
}
const pointer = (type: string, clientY: number, init: MouseEventInit = {}) =>
  document.dispatchEvent(new MouseEvent(type, { clientY, bubbles: true, ...init }))

const mounted: VueWrapper[] = []
const mountReadingMode = (enabled: Ref<boolean> = ref(true)) => {
  const scope = document.createElement('main')
  document.body.append(scope)
  const page = scroller(600, 3000)
  scope.append(page)
  let state!: ReturnType<typeof useReadingMode>
  const Probe = defineComponent({
    setup() {
      state = useReadingMode({ enabled, scope: ref(scope) })
      return () => null
    },
  })
  mounted.push(mount(Probe, { attachTo: document.body }))
  return { scope, page, state, enabled }
}
const settle = () => vi.advanceTimersByTime(READING_MODE.settleMs)

beforeEach(() => {
  vi.useFakeTimers()
  Object.defineProperty(window, 'innerHeight', { configurable: true, value: 800 })
})
afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
  vi.useRealTimers()
})

describe('useReadingMode', () => {
  it('steps the chrome aside while reading down and brings it back on the way up', () => {
    const { page, state } = mountReadingMode()

    scrollAlong(page, 80)
    expect(state.hidden.value).toBe(false)
    scrollAlong(page, 400)
    expect(state.hidden.value).toBe(true)

    // 触控板上手指一抖往回 20px 不算；接着往下读再回 20px 也不算，连着往回过了 32px 才回来。
    settle()
    scrollTo(page, 380)
    expect(state.hidden.value).toBe(true)
    scrollTo(page, 420)
    scrollTo(page, 400)
    expect(state.hidden.value).toBe(true)
    scrollTo(page, 384)
    expect(state.hidden.value).toBe(false)
  })

  it('lets the frame settle before reading the direction again', () => {
    const { page, state } = mountReadingMode()
    scrollAlong(page, 2400)
    expect(state.hidden.value).toBe(true)

    // 画板变高后浏览器把滚到底的位置往回夹了 68px，这不是读者往上滚。
    scrollTo(page, 2332)
    expect(state.hidden.value).toBe(true)

    settle()
    scrollTo(page, 2340)
    scrollTo(page, 2300)
    expect(state.hidden.value).toBe(false)
  })

  it('keeps the chrome near the top, on short pages and for small scroll areas', () => {
    const { scope, page, state } = mountReadingMode()
    scrollAlong(page, READING_MODE.hideFrom)
    expect(state.hidden.value).toBe(false)

    const short = scroller(600, 600 + READING_MODE.minRoom - 1)
    const aside = scroller(200, 3000)
    scope.append(short, aside)
    scrollAlong(short, READING_MODE.minRoom - 1)
    scrollAlong(aside, 1200)
    expect(state.hidden.value).toBe(false)

    const outside = scroller(600, 3000)
    document.body.append(outside)
    scrollAlong(outside, 1200)
    expect(state.hidden.value).toBe(false)
  })

  it('comes back at the top of the page', () => {
    const { page, state } = mountReadingMode()
    scrollAlong(page, 120)
    expect(state.hidden.value).toBe(true)
    // 刚收起时页面被拉回了顶部附近（比如点了页内的「回到顶部」），再往上一点点就到顶了。
    scrollTo(page, 24)
    settle()
    scrollTo(page, 2)
    expect(state.hidden.value).toBe(false)
  })

  it('comes back when the mouse reaches the bottom edge, not when it was already resting there', () => {
    const { page, state } = mountReadingMode()
    scrollAlong(page, 400)
    pointer('pointermove', 795)
    pointer('pointermove', 796)
    expect(state.hidden.value).toBe(true)

    pointer('pointermove', 700)
    pointer('pointermove', 790)
    expect(state.hidden.value).toBe(false)

    settle()
    scrollAlong(page, 800)
    expect(state.hidden.value).toBe(true)
    pointer('pointerout', 799, { relatedTarget: null })
    expect(state.hidden.value).toBe(false)
  })

  it('comes back on Escape and when keyboard focus walks into the dock', () => {
    const { page, state } = mountReadingMode()
    scrollAlong(page, 400)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(state.hidden.value).toBe(false)

    settle()
    scrollAlong(page, 800)
    expect(state.hidden.value).toBe(true)
    const dock = document.createElement('nav')
    dock.className = 'dock'
    dock.innerHTML = '<a href="/">Home</a>'
    document.body.append(dock)
    dock.querySelector('a')!.focus()
    expect(state.hidden.value).toBe(false)
  })

  it('stays put while disabled and comes back when switched off mid-read', async () => {
    const enabled = ref(false)
    const { page, state } = mountReadingMode(enabled)
    scrollAlong(page, 800)
    expect(state.hidden.value).toBe(false)

    enabled.value = true
    await nextTick()
    scrollAlong(page, 1600)
    expect(state.hidden.value).toBe(true)

    enabled.value = false
    await nextTick()
    expect(state.hidden.value).toBe(false)
  })
})
