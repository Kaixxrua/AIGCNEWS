import { describe, expect, it, vi } from 'vitest'
import { createAccountVisitTracker, type AccountVisitReceipt } from './accountVisit'

const receipt: AccountVisitReceipt = {
  recorded: true, user_id: 7, server_time: '2026-10-09T15:59:59Z', next_day_at: '2026-10-10T00:00:00+08:00',
}

describe('account visit accounting', () => {
  it('ignores guests and hidden tabs, then counts a login independently of anonymous storage', async () => {
    const send = vi.fn().mockResolvedValue(receipt)
    const record = createAccountVisitTracker(send, () => 0)
    await record(null, null, true)
    await record(7, 'token', false)
    expect(send).not.toHaveBeenCalled()
    await record(7, 'token', true)
    expect(send).toHaveBeenCalledOnce()
  })

  it('deduplicates repeats and records a still-visible tab across the server midnight', async () => {
    let elapsed = 0
    const send = vi.fn().mockResolvedValue(receipt)
    const record = createAccountVisitTracker(send, () => elapsed)
    expect(await record(7, 'token', true)).toBe(1000)
    elapsed = 999
    await record(7, 'token', true)
    expect(send).toHaveBeenCalledOnce()
    elapsed = 1000
    await record(7, 'token', true)
    expect(send).toHaveBeenCalledTimes(2)
  })

  it('retries a failed request and coalesces concurrent route events', async () => {
    let resolve: (value: AccountVisitReceipt) => void = () => {}
    const send = vi.fn().mockRejectedValueOnce(new Error('offline'))
      .mockImplementationOnce(() => new Promise<AccountVisitReceipt>(done => { resolve = done }))
    const record = createAccountVisitTracker(send, () => 0)
    await record(7, 'token', true)
    const waiting = record(7, 'token', true)
    await record(7, 'token', true)
    expect(send).toHaveBeenCalledTimes(2)
    resolve(receipt)
    await waiting
    await record(7, 'token', true)
    expect(send).toHaveBeenCalledTimes(2)
  })

  it('does not let an old in-flight login acknowledge another account', async () => {
    let resolve: (value: AccountVisitReceipt) => void = () => {}
    const send = vi.fn()
      .mockImplementationOnce(() => new Promise<AccountVisitReceipt>(done => { resolve = done }))
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValue(receipt)
    const record = createAccountVisitTracker(send, () => 0)
    const first = record(7, 'token-7', true)
    await record(8, 'token-8', true)
    resolve(receipt)
    await first
    await record(8, 'token-8', true)
    expect(send.mock.calls.map(call => call[0])).toEqual(['token-7', 'token-8', 'token-8'])
  })

  it('does not cache the old profile when a new token is installed before profile refresh', async () => {
    const send = vi.fn().mockResolvedValueOnce({ ...receipt, user_id: 8 }).mockResolvedValue(receipt)
    const record = createAccountVisitTracker(send, () => 0)
    // During auth.login, token B can be installed before fetchMe replaces user A.
    await record(7, 'token-8', true)
    await record(7, 'token-7', true)
    expect(send.mock.calls.map(call => call[0])).toEqual(['token-8', 'token-7'])
  })
})
