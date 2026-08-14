import { createApp, defineComponent, h } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useTodayNewCount } from './useTodayNewCount'

let unmount: (() => void) | undefined

const mountHarness = (
  fetchStats: () => Promise<{ today_new_documents?: number }>,
  intervalMs = 1000,
) => {
  const Harness = defineComponent({
    setup() {
      const { todayNewCount } = useTodayNewCount({ fetchStats, intervalMs })
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

describe('useTodayNewCount', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    unmount?.()
    unmount = undefined
    vi.useRealTimers()
  })

  it('fetches today_new_documents on mount and renders it', async () => {
    const fetchStats = vi.fn().mockResolvedValue({ today_new_documents: 42 })
    const { host } = mountHarness(fetchStats)

    expect(fetchStats).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(0)
    expect(host.textContent).toBe('42')
  })

  it('polls every interval and applies updated counts', async () => {
    const fetchStats = vi
      .fn()
      .mockResolvedValueOnce({ today_new_documents: 42 })
      .mockResolvedValueOnce({ today_new_documents: 57 })
    const { host } = mountHarness(fetchStats, 1000)
    await vi.advanceTimersByTimeAsync(0)
    expect(host.textContent).toBe('42')

    await vi.advanceTimersByTimeAsync(1000)
    expect(fetchStats).toHaveBeenCalledTimes(2)
    expect(host.textContent).toBe('57')
  })

  it('keeps the current value when a refresh fails', async () => {
    const fetchStats = vi
      .fn()
      .mockResolvedValueOnce({ today_new_documents: 42 })
      .mockRejectedValueOnce(new Error('network down'))
    const { host } = mountHarness(fetchStats, 1000)
    await vi.advanceTimersByTimeAsync(0)
    expect(host.textContent).toBe('42')

    await vi.advanceTimersByTimeAsync(1000)
    expect(fetchStats).toHaveBeenCalledTimes(2)
    expect(host.textContent).toBe('42')
  })

  it('stops polling after unmount', async () => {
    const fetchStats = vi.fn().mockResolvedValue({ today_new_documents: 1 })
    mountHarness(fetchStats, 1000)
    await vi.advanceTimersByTimeAsync(0)
    expect(fetchStats).toHaveBeenCalledTimes(1)

    unmount?.()
    unmount = undefined
    await vi.advanceTimersByTimeAsync(5000)
    expect(fetchStats).toHaveBeenCalledTimes(1)
  })
})
