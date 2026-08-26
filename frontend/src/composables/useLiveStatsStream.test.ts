import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Stats } from '@/features/dashboard/dashboardViewModel'

vi.mock('@/services/dashboard/dashboardLiveApi', () => ({
  fetchLiveStats: vi.fn(),
  LIVE_EVENTS_URL: '/api/dashboard/live-events',
}))

/* jsdom 无 EventSource：最小假实现，记录实例供测试驱动 open/message/error。 */
class FakeEventSource {
  static instances: FakeEventSource[] = []

  readonly url: string
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  closed = false

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  close() {
    this.closed = true
  }

  emitOpen() {
    this.onopen?.()
  }

  emitMessage(payload: Stats) {
    this.onmessage?.({ data: JSON.stringify(payload) })
  }

  emitError() {
    this.onerror?.()
  }
}

/* 被测模块是模块级单例：每个用例 resetModules 后动态导入拿全新状态；
   fetchLiveStats 的 mock 实例在 mock 注册表内共享，必须取新引用再断言。 */
const loadModule = async () => {
  vi.resetModules()
  const stream = await import('./useLiveStatsStream')
  const api = await import('@/services/dashboard/dashboardLiveApi')
  const fetchMock = vi.mocked(api.fetchLiveStats)
  fetchMock.mockClear()
  fetchMock.mockResolvedValue({ total_documents: 1 })
  return { stream, fetchMock }
}

/* 前序用例的模块实例若留下活动定时器（未退订），会在 fake clock 推进时
   继续触发共享的 fetchLiveStats mock 造成串扰：统一记录退订句柄收尾。 */
const subscriptions: Array<() => void> = []
const subscribe = (stream: Pick<StreamModule, 'subscribeLiveStats'>, listener: (stats: Stats) => void) => {
  const unsubscribe = stream.subscribeLiveStats(listener)
  subscriptions.push(unsubscribe)
  return unsubscribe
}

type StreamModule = typeof import('./useLiveStatsStream')

describe('useLiveStatsStream', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    FakeEventSource.instances = []
    vi.stubGlobal('EventSource', FakeEventSource)
  })

  afterEach(() => {
    while (subscriptions.length > 0) subscriptions.pop()?.()
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('shares one connection across subscribers and closes after the last unsubscribe', async () => {
    const { stream } = await loadModule()
    const first = vi.fn()
    const second = vi.fn()

    const unsub1 = subscribe(stream, first)
    const unsub2 = subscribe(stream, second)
    expect(FakeEventSource.instances).toHaveLength(1)
    expect(FakeEventSource.instances[0]?.url).toBe('/api/dashboard/live-events')

    FakeEventSource.instances[0]?.emitMessage({ total_documents: 7 })
    expect(first).toHaveBeenCalledWith({ total_documents: 7 })
    expect(second).toHaveBeenCalledWith({ total_documents: 7 })

    unsub1()
    expect(FakeEventSource.instances[0]?.closed).toBe(false)
    unsub2()
    expect(FakeEventSource.instances[0]?.closed).toBe(true)
  })

  it('drops malformed frames without breaking later messages', async () => {
    const { stream } = await loadModule()
    const listener = vi.fn()
    subscribe(stream, listener)
    const source = FakeEventSource.instances[0]

    source?.onmessage?.({ data: '{not-json' })
    expect(listener).not.toHaveBeenCalled()
    source?.emitMessage({ total_documents: 9 })
    expect(listener).toHaveBeenCalledWith({ total_documents: 9 })
  })

  it('falls back to REST polling when the stream stays down, and stops on recovery', async () => {
    const { stream, fetchMock } = await loadModule()
    const listener = vi.fn()
    subscribe(stream, listener)
    const source = FakeEventSource.instances[0]

    source?.emitError()
    await vi.advanceTimersByTimeAsync(15_000)
    expect(fetchMock).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(30_000)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(30_000)
    expect(fetchMock).toHaveBeenCalledTimes(2)

    /* SSE 恢复（浏览器自动重连成功）→ 降级轮询立即停止 */
    source?.emitOpen()
    await vi.advanceTimersByTimeAsync(90_000)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('keeps polling when the stream errors again before opening', async () => {
    const { stream, fetchMock } = await loadModule()
    subscribe(stream, vi.fn())
    const source = FakeEventSource.instances[0]

    source?.emitError()
    await vi.advanceTimersByTimeAsync(15_000 + 30_000)
    expect(fetchMock).toHaveBeenCalledTimes(1)

    source?.emitError()
    await vi.advanceTimersByTimeAsync(30_000)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('starts fallback polling immediately when EventSource is unavailable', async () => {
    vi.stubGlobal('EventSource', undefined)
    const { stream, fetchMock } = await loadModule()
    subscribe(stream, vi.fn())
    expect(FakeEventSource.instances).toHaveLength(0)

    await vi.advanceTimersByTimeAsync(30_000)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('does not start fallback polling while the stream is healthy', async () => {
    const { stream, fetchMock } = await loadModule()
    subscribe(stream, vi.fn())
    const source = FakeEventSource.instances[0]
    source?.emitOpen()

    await vi.advanceTimersByTimeAsync(120_000)
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
