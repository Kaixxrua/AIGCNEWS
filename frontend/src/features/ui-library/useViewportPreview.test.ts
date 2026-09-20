import { createApp, defineComponent, h, nextTick, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useViewportPreview } from './useViewportPreview'

describe('useViewportPreview', () => {
  const callbacks = new Map<Element, IntersectionObserverCallback>()
  beforeEach(() => {
    vi.useFakeTimers()
    callbacks.clear()
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => setTimeout(() => callback(performance.now()), 0))
    vi.stubGlobal('IntersectionObserver', class {
      private callback: IntersectionObserverCallback
      constructor(callback: IntersectionObserverCallback) { this.callback = callback }
      observe(target: Element) { callbacks.set(target, this.callback) }
      disconnect() {}
    })
  })
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); document.body.innerHTML = '' })

  const intersect = async (target: Element, value: boolean) => {
    callbacks.get(target)?.([{ isIntersecting: value, intersectionRatio: value ? 1 : 0 } as IntersectionObserverEntry], {} as IntersectionObserver)
    await vi.runAllTimersAsync()
  }

  it('attaches only visible media and releases it when disabled', async () => {
    const enabled = ref(true)
    let state: ReturnType<typeof useViewportPreview>
    const root = document.createElement('div')
    root.className = 'ui-library'
    document.body.append(root)
    const app = createApp(defineComponent({
      setup() {
        const element = ref<HTMLElement>()
        state = useViewportPreview(element, () => enabled.value)
        return () => h('span', { ref: element })
      },
    }))
    app.mount(root)
    const target = root.querySelector('span') as HTMLElement
    root.getBoundingClientRect = () => ({ top: 0, right: 640, bottom: 400, left: 0, width: 640, height: 400, x: 0, y: 0, toJSON() {} })
    target.getBoundingClientRect = () => ({ top: 500, right: 300, bottom: 700, left: 0, width: 300, height: 200, x: 0, y: 500, toJSON() {} })
    await intersect(target, false)
    expect(state!.attached.value).toBe(false)
    expect(state!.playing.value).toBe(false)
    target.getBoundingClientRect = () => ({ top: 20, right: 300, bottom: 220, left: 0, width: 300, height: 200, x: 0, y: 20, toJSON() {} })
    await intersect(target, true)
    expect(state!.playing.value).toBe(true)
    enabled.value = false
    await nextTick()
    await vi.runAllTimersAsync()
    expect(state!.attached.value).toBe(false)
    expect(state!.playing.value).toBe(false)
    enabled.value = true
    await nextTick()
    expect(state!.playing.value).toBe(true)
    app.unmount()
    await vi.runAllTimersAsync()
  })

  it('plays every visible card beyond three and releases offscreen media', async () => {
    const states: ReturnType<typeof useViewportPreview>[] = []
    const Card = defineComponent({
      setup() {
        const element = ref<HTMLElement>()
        states.push(useViewportPreview(element, () => true))
        return () => h('span', { ref: element })
      },
    })
    const root = document.createElement('div')
    root.className = 'ui-library'
    document.body.append(root)
    root.getBoundingClientRect = () => ({ top: 0, right: 640, bottom: 800, left: 0, width: 640, height: 800, x: 0, y: 0, toJSON() {} })
    const app = createApp(defineComponent({ render: () => h('div', Array.from({ length: 30 }, (_, i) => h(Card, { key: i }))) }))
    app.mount(root)
    const targets = [...root.querySelectorAll('span')] as HTMLElement[]
    targets.forEach((target, index) => { target.getBoundingClientRect = () => ({ top: index * 100, right: 300, bottom: index * 100 + 80, left: 0, width: 300, height: 80, x: 0, y: index * 100, toJSON() {} }) })
    for (const target of targets.slice(0, 24)) callbacks.get(target)?.([{ isIntersecting: true, intersectionRatio: 1 } as IntersectionObserverEntry], {} as IntersectionObserver)
    await vi.runAllTimersAsync()
    expect(states.filter(state => state.attached.value)).toHaveLength(24)
    expect(states.filter(state => state.playing.value)).toHaveLength(24)

    await intersect(targets[0]!, false)
    expect(states[0]!.attached.value).toBe(false)
    expect(states[3]!.attached.value).toBe(true)
    expect(states.filter(state => state.attached.value)).toHaveLength(23)
    await intersect(targets[24]!, true)
    expect(states[24]!.playing.value).toBe(true)
    await intersect(targets[0]!, true)
    expect(states[0]!.playing.value).toBe(true)
    app.unmount()
    await vi.runAllTimersAsync()
  })
})
