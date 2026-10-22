import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, h, KeepAlive, nextTick, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PEEK_WARMUP_LIMIT, useProjectPeekWarmup } from './useProjectPeekWarmup'

class Observer {
  static all: Observer[] = []
  elements = new Set<Element>()
  callback: IntersectionObserverCallback
  constructor(callback: IntersectionObserverCallback) {
    this.callback = callback
    Observer.all.push(this)
  }
  observe(el: Element) { this.elements.add(el) }
  disconnect() { this.elements.clear() }
  report(keys: string[], isIntersecting = true) {
    const entries = [...this.elements]
      .filter((el) => keys.includes((el as HTMLElement).dataset.listKey!))
      .map((target) => ({ target, isIntersecting }) as IntersectionObserverEntry)
    this.callback(entries, this as unknown as IntersectionObserver)
  }
}

let wrapper: VueWrapper | undefined
beforeEach(() => {
  Observer.all = []
  vi.stubGlobal('IntersectionObserver', Observer)
})
afterEach(() => {
  wrapper?.unmount()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const setup = async (initial = ['a', 'b', 'site', 'c', 'd']) => {
  const keys = ref(initial)
  const enabled = ref(true)
  const active = ref(true)
  const answers = new Map<string, () => void>()
  const load = vi.fn((repoId: string) => new Promise<void>((resolve) => { answers.set(repoId, resolve) }))
  const List = defineComponent({
    setup() {
      const rows = ref<HTMLElement | null>(null)
      useProjectPeekWarmup({ enabled, rows, keys, repoOf: (key) => key === 'site' ? '' : key, load })
      return () => h('ol', { ref: rows }, keys.value.map((key) => h('li', { key, 'data-list-key': key })))
    },
  })
  wrapper = mount(defineComponent({
    setup: () => () => h(KeepAlive, {}, { default: () => active.value ? h(List) : null }),
  }), { attachTo: document.body })
  await nextTick()
  return {
    keys, enabled, active, load,
    observer: () => Observer.all[Observer.all.length - 1]!,
    finish: async (key: string) => { answers.get(key)!(); await flushPromises() },
  }
}

describe('useProjectPeekWarmup', () => {
  it('warms visible repositories before hover with at most two requests and drops rows that scrolled away', async () => {
    const list = await setup()
    expect(list.observer().elements.size).toBe(4)
    list.observer().report(['a', 'b', 'c', 'site'])
    expect(list.load.mock.calls).toEqual([['a'], ['b']])
    list.observer().report(['c'], false)
    await list.finish('a')
    expect(list.load).toHaveBeenCalledTimes(2)
    list.observer().report(['c'])
    expect(list.load.mock.calls).toEqual([['a'], ['b'], ['c']])
    await list.finish('b')
    await list.finish('c')
    list.observer().report(['a', 'b', 'c'])
    expect(list.load).toHaveBeenCalledTimes(3)
  })

  it('bounds speculative reads per page and replaces the queue when filtering or paging', async () => {
    const keys = Array.from({ length: PEEK_WARMUP_LIMIT + 2 }, (_, i) => String(i))
    const list = await setup(keys)
    list.observer().report(keys)
    for (const key of keys.slice(0, PEEK_WARMUP_LIMIT)) await list.finish(key)
    expect(list.load).toHaveBeenCalledTimes(PEEK_WARMUP_LIMIT)
    const previous = list.observer()
    list.keys.value = ['next']
    await nextTick()
    previous.report(keys)
    list.observer().report(['next'])
    expect(list.load).toHaveBeenLastCalledWith('next')
  })

  it('does not drain the previous page when its in-flight requests finish', async () => {
    const list = await setup()
    list.observer().report(['a', 'b', 'c'])
    list.keys.value = ['next']
    await nextTick()
    list.observer().report(['next'])
    await list.finish('a')
    expect(list.load.mock.calls).toEqual([['a'], ['b'], ['next']])
    await list.finish('b')
    expect(list.load).toHaveBeenCalledTimes(3)
  })

  it('pauses in hidden tabs and disabled layouts, resumes on return, and stops on unmount', async () => {
    const list = await setup()
    list.observer().report(['a', 'b', 'c', 'd'])
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
    document.dispatchEvent(new Event('visibilitychange'))
    await list.finish('a')
    await list.finish('b')
    expect(list.load).toHaveBeenCalledTimes(2)
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
    document.dispatchEvent(new Event('visibilitychange'))
    list.observer().report(['a', 'b', 'c', 'd'])
    expect(list.load.mock.calls).toEqual([['a'], ['b'], ['c'], ['d']])
    list.enabled.value = false
    await nextTick()
    expect(list.observer().elements.size).toBe(0)
    wrapper!.unmount()
    await list.finish('c')
    await list.finish('d')
    expect(list.load).toHaveBeenCalledTimes(4)
  })

  it('stops while its KeepAlive list is inactive and resumes when activated', async () => {
    const list = await setup()
    list.observer().report(['a', 'b', 'c'])
    list.active.value = false
    await nextTick()
    await list.finish('a')
    await list.finish('b')
    expect(list.load).toHaveBeenCalledTimes(2)
    list.active.value = true
    await nextTick()
    list.observer().report(['c'])
    expect(list.load).toHaveBeenLastCalledWith('c')
  })
})
