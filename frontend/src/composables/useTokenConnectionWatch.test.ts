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

  describe('startNew (after copying the agent prompt)', () => {
    const old = token({ id: 3, client_label: 'Cursor', created_at: '2026-10-01T08:00:00Z', last_used_at: '2026-10-05T11:00:00Z' })

    it('records the existing tokens at once, then sees the client authorize and connect', async () => {
      const fetchTokens = vi.fn().mockResolvedValue([old])
      const { watch } = setup(fetchTokens)
      watch.startNew()
      expect(watch.status.value).toBe('waiting')
      await vi.advanceTimersByTimeAsync(0)
      expect(fetchTokens).toHaveBeenCalledTimes(1)

      fetchTokens.mockResolvedValue([old, token({ id: 9, client_label: 'Codex' })])
      await vi.advanceTimersByTimeAsync(3_000)
      expect(watch.status.value).toBe('authorized')
      expect(watch.clientLabel.value).toBe('Codex')

      fetchTokens.mockResolvedValue([old, token({ id: 9, client_label: 'Codex', last_used_at: '2026-10-05T12:00:05Z' })])
      await vi.advanceTimersByTimeAsync(3_000)
      expect(watch.status.value).toBe('connected')
      expect(watch.fresh.value).toBe(true)
      expect(watch.clientLabel.value).toBe('Codex')
      expect(watch.lastUsedAt.value).toBe('2026-10-05T12:00:05Z')

      await vi.advanceTimersByTimeAsync(60_000)
      expect(fetchTokens).toHaveBeenCalledTimes(3)
    })

    it('does not mistake an existing token for the new client', async () => {
      const fetchTokens = vi.fn().mockResolvedValue([old, token({ id: 4, client_label: 'dsh-aigc-radar' })])
      const { watch } = setup(fetchTokens)
      watch.startNew({ ignoreLabels: ['dsh-aigc-radar'] })
      await vi.advanceTimersByTimeAsync(3_000)
      expect(watch.status.value).toBe('waiting')

      fetchTokens.mockResolvedValue([old, token({ id: 4, client_label: 'dsh-aigc-radar', last_used_at: '2026-10-05T12:00:02Z' })])
      await vi.advanceTimersByTimeAsync(3_000)
      expect(watch.status.value).toBe('waiting')

      fetchTokens.mockResolvedValue([{ ...old, last_used_at: '2026-10-05T12:00:04Z' }])
      await vi.advanceTimersByTimeAsync(3_000)
      expect(watch.status.value).toBe('connected')
      expect(watch.clientLabel.value).toBe('Cursor')
    })

    it('connects at once when the client authorized before the page started watching', async () => {
      const added = token({ id: 9, client_label: 'Claude Code', created_at: '2026-10-05T11:58:00Z', last_used_at: '2026-10-05T11:58:30Z' })
      const { watch } = setup(vi.fn().mockResolvedValue([old, added]))
      watch.startNew({ sinceMs: NOW - 5 * 60_000 })
      await vi.advanceTimersByTimeAsync(0)
      expect(watch.status.value).toBe('connected')
      expect(watch.clientLabel.value).toBe('Claude Code')
    })

    it('goes back to waiting when the authorized token disappears', async () => {
      const fetchTokens = vi.fn().mockResolvedValue([])
      const { watch } = setup(fetchTokens)
      watch.startNew()
      await vi.advanceTimersByTimeAsync(0)
      fetchTokens.mockResolvedValue([token({ id: 9, client_label: 'Codex' })])
      await vi.advanceTimersByTimeAsync(3_000)
      expect(watch.status.value).toBe('authorized')

      fetchTokens.mockResolvedValue([token({ id: 9, client_label: 'Codex', revoked_at: '2026-10-05T12:00:05Z' })])
      await vi.advanceTimersByTimeAsync(3_000)
      expect(watch.status.value).toBe('waiting')
      expect(watch.clientLabel.value).toBeNull()
    })

    it('pauses after ten minutes, but keeps an authorized client and lets the user check again', async () => {
      const fetchTokens = vi.fn().mockResolvedValue([])
      const { watch } = setup(fetchTokens)
      watch.startNew()
      await vi.advanceTimersByTimeAsync(120_000)
      expect(watch.slow.value).toBe(true)
      await vi.advanceTimersByTimeAsync(600_000)
      expect(watch.status.value).toBe('paused')

      const calls = fetchTokens.mock.calls.length
      await vi.advanceTimersByTimeAsync(60_000)
      expect(fetchTokens).toHaveBeenCalledTimes(calls)

      fetchTokens.mockResolvedValue([token({ id: 9, client_label: 'Codex' })])
      watch.checkNow()
      await vi.advanceTimersByTimeAsync(0)
      expect(watch.status.value).toBe('authorized')
      await vi.advanceTimersByTimeAsync(600_000)
      expect(watch.status.value).toBe('authorized')
    })

    it('starts over with a fresh baseline when started again after connecting', async () => {
      const first = token({ id: 9, client_label: 'Codex', last_used_at: '2026-10-05T12:00:02Z' })
      const fetchTokens = vi.fn().mockResolvedValue([])
      const { watch } = setup(fetchTokens)
      watch.startNew()
      await vi.advanceTimersByTimeAsync(0)
      fetchTokens.mockResolvedValue([first])
      await vi.advanceTimersByTimeAsync(3_000)
      expect(watch.status.value).toBe('connected')

      watch.startNew()
      expect(watch.status.value).toBe('waiting')
      expect(watch.clientLabel.value).toBeNull()
      await vi.advanceTimersByTimeAsync(3_000)
      expect(watch.status.value).toBe('waiting')
    })
  })
})
