import { createApp, defineComponent, h } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useTodayNewCount } from './useTodayNewCount'
import type { LiveStatsListener } from './useLiveStatsStream'

let unmount: (() => void) | undefined

const mountHarness = (
  fetchStats: () => Promise<{ today_new_documents?: number }>,
  subscribeStats?: (listener: LiveStatsListener) => () => void,
) => {
  const Harness = defineComponent({
    setup() {
      const { todayNewCount } = useTodayNewCount({ fetchStats, subscribeStats })
      return () => h('div', String(todayNewCount.value))
    },
  })
  const host = document.createElement('div')
  document.body.appendChild(host)
  const app = createApp(Harness)
  app.mount(host)
  unmount = () => { app.unmount(); host.remove() }
  return { host }
}

const flushMicrotasks = () => new Promise<void>((resolve) => { setTimeout(resolve, 0) })

describe('useTodayNewCount', () => {
  afterEach(() => {
    unmount?.()
    unmount = undefined
  })

  it('fetches today_new_documents on mount and renders it', async () => {
    const fetchStats = vi.fn().mockResolvedValue({ today_new_documents: 42 })
    const { host } = mountHarness(fetchStats)

    expect(fetchStats).toHaveBeenCalledTimes(1)
    await flushMicrotasks()
    expect(host.textContent).toBe('42')
  })

  it('applies pushed counts from the live stats stream', async () => {
    const fetchStats = vi.fn().mockResolvedValue({ today_new_documents: 42 })
    let listener: LiveStatsListener | undefined
    const subscribeStats = vi.fn((cb: LiveStatsListener) => {
      listener = cb
      return () => {}
    })
    const { host } = mountHarness(fetchStats, subscribeStats)
    await flushMicrotasks()
    expect(host.textContent).toBe('42')
    expect(subscribeStats).toHaveBeenCalledTimes(1)

    listener?.({ today_new_documents: 57 })
    await flushMicrotasks()
    expect(host.textContent).toBe('57')
  })

  it('keeps the current value when a refresh fails', async () => {
    const fetchStats = vi.fn().mockRejectedValue(new Error('network down'))
    const { host } = mountHarness(fetchStats)
    await flushMicrotasks()
    expect(host.textContent).toBe('0')
  })

  it('unsubscribes from the stream on unmount', async () => {
    const fetchStats = vi.fn().mockResolvedValue({ today_new_documents: 1 })
    const unsubscribe = vi.fn()
    const subscribeStats = vi.fn((_cb: LiveStatsListener) => unsubscribe)
    mountHarness(fetchStats, subscribeStats)
    await flushMicrotasks()

    unmount?.()
    unmount = undefined
    expect(unsubscribe).toHaveBeenCalledTimes(1)
  })
})
