import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { McpTokenMetadata } from '@/services/mcp/mcpTokenApi'
import { useTokenConnectionWatch } from './useTokenConnectionWatch'

const NOW = Date.parse('2026-10-05T12:00:00Z')

const token = (patch: Partial<McpTokenMetadata> = {}): McpTokenMetadata => ({
  id: 7,
  token_hint: 'aigc_mcp_abc...wxyz',
  scopes: ['projects:favorites:read'],
  client_type: 'claude',
  client_label: 'Claude Code',
  expires_at: null,
  revoked_at: null,
  last_used_at: null,
  ...patch,
})

const fakeVisibility = () => {
  let hidden = false
  const listeners = new Set<() => void>()
  return {
    hidden: () => hidden,
    subscribe: (listener: () => void) => {
      listeners.add(listener)
      return () => { listeners.delete(listener) }
    },
    set(next: boolean) {
      hidden = next
      for (const listener of [...listeners]) listener()
    },
    listeners: () => listeners.size,
  }
}

const deferred = <T>() => {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => { resolve = res })
  return { promise, resolve }
}

const setup = (fetchTokens = vi.fn().mockResolvedValue([token()])) => {
  const visibility = fakeVisibility()
  const watch = useTokenConnectionWatch({ fetchTokens, now: () => Date.now(), visibility })
  return { watch, fetchTokens, visibility }
}

beforeEach(() => {
  vi.useFakeTimers({ now: NOW })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useTokenConnectionWatch', () => {
  it('waits for a fresh token and turns connected on its first use, then stops', async () => {
    const { watch, fetchTokens } = setup()
    watch.start(token())

    expect(watch.status.value).toBe('waiting')
    expect(fetchTokens).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(3_000)
    expect(fetchTokens).toHaveBeenCalledTimes(1)
    expect(watch.status.value).toBe('waiting')

    fetchTokens.mockResolvedValue([token({ last_used_at: '2026-10-05T12:00:05Z' })])
    await vi.advanceTimersByTimeAsync(3_000)
    expect(watch.status.value).toBe('connected')
    expect(watch.fresh.value).toBe(true)
    expect(watch.lastUsedAt.value).toBe('2026-10-05T12:00:05Z')

    await vi.advanceTimersByTimeAsync(120_000)
    expect(fetchTokens).toHaveBeenCalledTimes(2)
  })

  it('polls every 3s for a minute, then every 10s, opens the tips at two minutes and pauses at ten', async () => {
    const { watch, fetchTokens } = setup()
    watch.start(token())

    await vi.advanceTimersByTimeAsync(60_000)
    expect(fetchTokens).toHaveBeenCalledTimes(20)
    await vi.advanceTimersByTimeAsync(10_000)
    expect(fetchTokens).toHaveBeenCalledTimes(21)

    await vi.advanceTimersByTimeAsync(40_000)
    expect(watch.slow.value).toBe(false)
    await vi.advanceTimersByTimeAsync(10_000)
    expect(watch.slow.value).toBe(true)

    await vi.advanceTimersByTimeAsync(480_000)
    expect(watch.status.value).toBe('paused')
    expect(fetchTokens).toHaveBeenCalledTimes(74)
    await vi.advanceTimersByTimeAsync(60_000)
    expect(fetchTokens).toHaveBeenCalledTimes(74)

    watch.checkNow()
    expect(watch.status.value).toBe('waiting')
    expect(watch.checking.value).toBe(true)
    expect(fetchTokens).toHaveBeenCalledTimes(75)
    await vi.advanceTimersByTimeAsync(0)
    expect(watch.checking.value).toBe(false)
    expect(watch.slow.value).toBe(true)
    await vi.advanceTimersByTimeAsync(3_000)
    expect(fetchTokens).toHaveBeenCalledTimes(76)
  })

  it('goes back to the quick cadence when the user copies the command again', async () => {
    const { watch, fetchTokens } = setup()
    watch.start(token())
    await vi.advanceTimersByTimeAsync(90_000)
    const before = fetchTokens.mock.calls.length

    watch.nudge()
    await vi.advanceTimersByTimeAsync(3_000)
    expect(fetchTokens).toHaveBeenCalledTimes(before + 1)
    await vi.advanceTimersByTimeAsync(3_000)
    expect(fetchTokens).toHaveBeenCalledTimes(before + 2)
  })

  it('stops for good once the token is gone', async () => {
    const { watch, fetchTokens } = setup(vi.fn().mockResolvedValue([token({ id: 3 })]))
    watch.start(token())
    await vi.advanceTimersByTimeAsync(3_000)

    expect(watch.status.value).toBe('gone')
    watch.nudge()
    watch.checkNow()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(fetchTokens).toHaveBeenCalledTimes(1)
    expect(watch.checking.value).toBe(false)
  })

  it('shows a reused token as connected before and only polls after the user acts', async () => {
    const lastUse = '2026-10-02T08:00:00Z'
    const { watch, fetchTokens } = setup(vi.fn().mockResolvedValue([token({ last_used_at: lastUse })]))
    watch.start(token({ last_used_at: lastUse }))

    expect(watch.status.value).toBe('connected')
    expect(watch.fresh.value).toBe(false)
    expect(watch.lastUsedAt.value).toBe(lastUse)
    await vi.advanceTimersByTimeAsync(60_000)
    expect(fetchTokens).not.toHaveBeenCalled()

    watch.nudge()
    await vi.advanceTimersByTimeAsync(3_000)
    expect(fetchTokens).toHaveBeenCalledTimes(1)
    expect(watch.fresh.value).toBe(false)

    fetchTokens.mockResolvedValue([token({ last_used_at: '2026-10-05T12:00:20Z' })])
    await vi.advanceTimersByTimeAsync(3_000)
    expect(watch.status.value).toBe('connected')
    expect(watch.fresh.value).toBe(true)
    expect(watch.lastUsedAt.value).toBe('2026-10-05T12:00:20Z')
  })

  it('pauses while the page is hidden and checks at once when the user comes back', async () => {
    const { watch, fetchTokens, visibility } = setup()
    watch.start(token())

    visibility.set(true)
    await vi.advanceTimersByTimeAsync(30_000)
    expect(fetchTokens).not.toHaveBeenCalled()

    visibility.set(false)
    expect(fetchTokens).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(3_000)
    expect(fetchTokens).toHaveBeenCalledTimes(2)
  })

  it('resumes a paused watch when the user comes back to the page', async () => {
    const { watch, fetchTokens, visibility } = setup()
    watch.start(token())
    await vi.advanceTimersByTimeAsync(600_000)
    expect(watch.status.value).toBe('paused')
    const before = fetchTokens.mock.calls.length

    visibility.set(true)
    visibility.set(false)
    expect(watch.status.value).toBe('waiting')
    expect(fetchTokens).toHaveBeenCalledTimes(before + 1)
  })

  it('stops polling when the session has expired but keeps going through other failures', async () => {
    const fetchTokens = vi.fn()
      .mockRejectedValueOnce(new Error('network'))
      .mockRejectedValueOnce({ isAxiosError: true, response: { status: 401 } })
    const { watch } = setup(fetchTokens)
    watch.start(token())

    await vi.advanceTimersByTimeAsync(3_000)
    expect(watch.status.value).toBe('waiting')
    await vi.advanceTimersByTimeAsync(3_000)
    expect(watch.status.value).toBe('paused')
    await vi.advanceTimersByTimeAsync(60_000)
    expect(fetchTokens).toHaveBeenCalledTimes(2)
  })

  it('ignores a late answer about a token it no longer watches', async () => {
    const pending = deferred<McpTokenMetadata[]>()
    const fetchTokens = vi.fn().mockReturnValueOnce(pending.promise).mockResolvedValue([token({ id: 8 })])
    const { watch } = setup(fetchTokens)
    watch.start(token())
    await vi.advanceTimersByTimeAsync(3_000)

    watch.start(token({ id: 8 }))
    pending.resolve([token({ last_used_at: '2026-10-05T12:00:01Z' })])
    await vi.advanceTimersByTimeAsync(0)
    expect(watch.status.value).toBe('waiting')
    expect(watch.lastUsedAt.value).toBeNull()

    await vi.advanceTimersByTimeAsync(3_000)
    expect(fetchTokens).toHaveBeenCalledTimes(2)
    expect(watch.status.value).toBe('waiting')
  })

  it('lets go of the page on stop and dispose', async () => {
    const { watch, fetchTokens, visibility } = setup()
    watch.start(token())
    expect(visibility.listeners()).toBe(1)

    watch.stop()
    expect(watch.status.value).toBe('idle')
    expect(visibility.listeners()).toBe(0)
    await vi.advanceTimersByTimeAsync(10_000)
    expect(fetchTokens).not.toHaveBeenCalled()

    watch.start(token())
    watch.dispose()
    watch.start(token())
    expect(watch.status.value).toBe('idle')
    expect(visibility.listeners()).toBe(0)
    await vi.advanceTimersByTimeAsync(10_000)
    expect(fetchTokens).not.toHaveBeenCalled()
  })
})
