import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import type { McpInstallCode, McpInstallCodePurpose } from '@/services/mcp/mcpTokenApi'
import { INSTALL_CODE_MIN_REMAINING_MS, INSTALL_CODE_REFRESH_LEAD_MS, useMcpInstallCode } from './useMcpInstallCode'

const NOW = Date.parse('2026-10-10T08:00:00Z')
/** 600 秒的码：前 300 秒可写进提示词，第 270 秒起提前换新。 */
const FRESH_MS = 600_000 - INSTALL_CODE_MIN_REMAINING_MS
const REFRESH_AT = FRESH_MS - INSTALL_CODE_REFRESH_LEAD_MS

const issued = (code: string, expiresIn = 600): McpInstallCode => ({ code, purpose: 'dsh', expires_in: expiresIn })

const deferred = <T>() => {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

const pageVisibility = () => {
  let hidden = false
  const listeners = new Set<() => void>()
  return {
    listeners,
    hidden: () => hidden,
    subscribe: (listener: () => void) => {
      listeners.add(listener)
      return () => { listeners.delete(listener) }
    },
    set: (value: boolean) => {
      hidden = value
      listeners.forEach((listener) => listener())
    },
  }
}

const mountCode = (issue: (purpose: McpInstallCodePurpose) => Promise<McpInstallCode>, enabledAtStart = true) => {
  const enabled = ref(enabledAtStart)
  const visibility = pageVisibility()
  const installCode = useMcpInstallCode({ purpose: 'dsh', enabled, issue, visibility })
  return { installCode, enabled, visibility }
}

const issueMock = () => vi.fn<(purpose: McpInstallCodePurpose) => Promise<McpInstallCode>>()

beforeEach(() => {
  vi.useFakeTimers({ now: NOW })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useMcpInstallCode', () => {
  it('prefetches a code once enabled', async () => {
    const issue = issueMock().mockResolvedValue(issued('aigc_ic_first'))
    const { installCode, enabled } = mountCode(issue, false)
    expect(issue).not.toHaveBeenCalled()
    expect(installCode.status.value).toBe('idle')

    enabled.value = true
    await vi.advanceTimersByTimeAsync(0)
    expect(issue).toHaveBeenCalledExactlyOnceWith('dsh')
    expect(installCode.status.value).toBe('ready')
    expect(installCode.current()).toBe('aigc_ic_first')
  })

  it('reports loading until the first code arrives', async () => {
    const first = deferred<McpInstallCode>()
    const { installCode } = mountCode(issueMock().mockReturnValue(first.promise))
    expect(installCode.status.value).toBe('loading')
    expect(installCode.current()).toBeNull()

    first.resolve(issued('aigc_ic_first'))
    await vi.advanceTimersByTimeAsync(0)
    expect(installCode.current()).toBe('aigc_ic_first')
  })

  it('swaps the code early and keeps offering the old one while the new one is on its way', async () => {
    const second = deferred<McpInstallCode>()
    const issue = issueMock().mockResolvedValueOnce(issued('aigc_ic_first')).mockReturnValueOnce(second.promise)
    const { installCode } = mountCode(issue)
    await vi.advanceTimersByTimeAsync(REFRESH_AT - 1)
    expect(issue).toHaveBeenCalledOnce()

    await vi.advanceTimersByTimeAsync(1)
    expect(issue).toHaveBeenCalledTimes(2)
    expect(installCode.status.value).toBe('ready')
    expect(installCode.current()).toBe('aigc_ic_first')

    second.resolve(issued('aigc_ic_second'))
    await vi.advanceTimersByTimeAsync(0)
    expect(installCode.current()).toBe('aigc_ic_second')
  })

  it('never offers a code with less than five minutes left', async () => {
    const stuck = deferred<McpInstallCode>()
    const issue = issueMock().mockResolvedValueOnce(issued('aigc_ic_first')).mockReturnValue(stuck.promise)
    const { installCode } = mountCode(issue)
    await vi.advanceTimersByTimeAsync(FRESH_MS - 1)
    expect(installCode.current()).toBe('aigc_ic_first')

    await vi.advanceTimersByTimeAsync(1)
    expect(installCode.current()).toBeNull()
  })

  it('keeps the old code through a failed refresh, then reports an error once it runs out', async () => {
    const issue = issueMock().mockResolvedValueOnce(issued('aigc_ic_first')).mockRejectedValue(new Error('503'))
    const { installCode } = mountCode(issue)
    await vi.advanceTimersByTimeAsync(REFRESH_AT)
    expect(issue).toHaveBeenCalledTimes(2)
    expect(installCode.status.value).toBe('ready')
    expect(installCode.current()).toBe('aigc_ic_first')

    await vi.advanceTimersByTimeAsync(INSTALL_CODE_REFRESH_LEAD_MS)
    expect(issue).toHaveBeenCalledTimes(3)
    expect(installCode.status.value).toBe('error')
    expect(installCode.code.value).toBeNull()

    // 出错后不自己反复重试，等用户的下一次操作。
    await vi.advanceTimersByTimeAsync(30 * 60_000)
    expect(issue).toHaveBeenCalledTimes(3)
    await expect(installCode.refresh()).resolves.toBe(false)
    expect(issue).toHaveBeenCalledTimes(4)
  })

  it('does not issue codes in a background tab and catches up when the page is shown again', async () => {
    const issue = issueMock().mockResolvedValueOnce(issued('aigc_ic_first')).mockResolvedValue(issued('aigc_ic_second'))
    const { installCode, visibility } = mountCode(issue)
    await vi.advanceTimersByTimeAsync(0)
    visibility.set(true)

    await vi.advanceTimersByTimeAsync(REFRESH_AT)
    expect(issue).toHaveBeenCalledOnce()
    expect(installCode.current()).toBe('aigc_ic_first')

    await vi.advanceTimersByTimeAsync(INSTALL_CODE_REFRESH_LEAD_MS)
    expect(issue).toHaveBeenCalledOnce()
    expect(installCode.status.value).toBe('idle')
    expect(installCode.code.value).toBeNull()

    await vi.advanceTimersByTimeAsync(60 * 60_000)
    expect(issue).toHaveBeenCalledOnce()

    visibility.set(false)
    expect(installCode.status.value).toBe('loading')
    await vi.advanceTimersByTimeAsync(0)
    expect(issue).toHaveBeenCalledTimes(2)
    expect(installCode.current()).toBe('aigc_ic_second')
  })

  it('refreshes on return only when the code is due', async () => {
    const issue = issueMock().mockResolvedValue(issued('aigc_ic_first'))
    const { visibility } = mountCode(issue)
    await vi.advanceTimersByTimeAsync(0)

    visibility.set(true)
    await vi.advanceTimersByTimeAsync(60_000)
    visibility.set(false)
    await vi.advanceTimersByTimeAsync(0)
    expect(issue).toHaveBeenCalledOnce()
  })

  it('does not double-issue when the page is shown while a request is in flight', async () => {
    const first = deferred<McpInstallCode>()
    const issue = issueMock().mockReturnValue(first.promise)
    const { visibility } = mountCode(issue)

    visibility.set(true)
    visibility.set(false)
    expect(issue).toHaveBeenCalledOnce()
  })

  it('retries on return after an error', async () => {
    const issue = issueMock().mockRejectedValueOnce(new Error('offline')).mockResolvedValue(issued('aigc_ic_second'))
    const { installCode, visibility } = mountCode(issue)
    await vi.advanceTimersByTimeAsync(0)
    expect(installCode.status.value).toBe('error')

    visibility.set(true)
    visibility.set(false)
    await vi.advanceTimersByTimeAsync(0)
    expect(installCode.current()).toBe('aigc_ic_second')
  })

  it('rotates to a new code after a copy', async () => {
    const issue = issueMock().mockResolvedValueOnce(issued('aigc_ic_first')).mockResolvedValue(issued('aigc_ic_second'))
    const { installCode } = mountCode(issue)
    await vi.advanceTimersByTimeAsync(0)

    installCode.rotate()
    // 新码到手前，刚复制出去的那枚照常可用（下一次复制不会卡住）。
    expect(installCode.current()).toBe('aigc_ic_first')
    await vi.advanceTimersByTimeAsync(0)
    expect(installCode.current()).toBe('aigc_ic_second')
  })

  it('ignores a response that arrives after the code was replaced or disabled', async () => {
    const first = deferred<McpInstallCode>()
    const second = deferred<McpInstallCode>()
    const issue = issueMock().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const { installCode, enabled } = mountCode(issue)

    void installCode.refresh()
    second.resolve(issued('aigc_ic_second'))
    await vi.advanceTimersByTimeAsync(0)
    first.resolve(issued('aigc_ic_first'))
    await vi.advanceTimersByTimeAsync(0)
    expect(installCode.current()).toBe('aigc_ic_second')

    const late = deferred<McpInstallCode>()
    issue.mockReturnValueOnce(late.promise)
    installCode.rotate()
    enabled.value = false
    await vi.advanceTimersByTimeAsync(0)
    late.resolve(issued('aigc_ic_late'))
    await vi.advanceTimersByTimeAsync(0)
    expect(installCode.status.value).toBe('idle')
    expect(installCode.code.value).toBeNull()
  })

  it('treats a code that expires too soon as a failure instead of refreshing in a loop', async () => {
    const issue = issueMock().mockResolvedValue(issued('aigc_ic_short', 300))
    const { installCode } = mountCode(issue)
    await vi.advanceTimersByTimeAsync(60 * 60_000)

    expect(issue).toHaveBeenCalledOnce()
    expect(installCode.status.value).toBe('error')
    expect(installCode.current()).toBeNull()
  })

  it('stops timers and listeners on dispose', async () => {
    const issue = issueMock().mockResolvedValue(issued('aigc_ic_first'))
    const { installCode, visibility, enabled } = mountCode(issue)
    await vi.advanceTimersByTimeAsync(0)

    installCode.dispose()
    expect(visibility.listeners.size).toBe(0)
    expect(installCode.code.value).toBeNull()
    await vi.advanceTimersByTimeAsync(60 * 60_000)
    enabled.value = false
    enabled.value = true
    await vi.advanceTimersByTimeAsync(0)
    expect(issue).toHaveBeenCalledOnce()
    await expect(installCode.refresh()).resolves.toBe(false)
  })
})
