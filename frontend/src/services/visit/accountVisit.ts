export interface AccountVisitReceipt {
  recorded: boolean
  user_id?: number
  server_time?: string
  next_day_at?: string
}

export async function sendAccountVisit(token: string): Promise<AccountVisitReceipt> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 10_000)
  try {
    // Capture this session's token. A login change while a request is in flight
    // must not attribute its acknowledgement to the new account.
    const response = await fetch('/api/dashboard/account-visit', {
      method: 'POST', headers: { Authorization: `Bearer ${token}` },
      signal: controller.signal, cache: 'no-store',
    })
    if (!response.ok) throw new Error('Account visit unavailable')
    return await response.json() as AccountVisitReceipt
  } finally {
    window.clearTimeout(timeout)
  }
}

export function createAccountVisitTracker(
  send = sendAccountVisit,
  clock = () => performance.now(),
) {
  const confirmed = new Map<number, number>()
  const pending = new Set<number>()
  return async (userId: number | null, token: string | null, visible: boolean): Promise<number> => {
    if (!visible || !userId || !token || pending.has(userId)) return 30_000
    const remaining = (confirmed.get(userId) ?? 0) - clock()
    if (remaining > 0) return remaining
    pending.add(userId)
    const started = clock()
    try {
      const result = await send(token)
      if (result.recorded && result.user_id === userId && result.next_day_at && result.server_time) {
        const ttl = Date.parse(result.next_day_at) - Date.parse(result.server_time)
        if (Number.isFinite(ttl) && ttl > 0) {
          // Server day boundary, independent of client timezone/clock/storage.
          confirmed.set(userId, started + ttl)
          return Math.max(50, started + ttl - clock())
        }
      }
    } catch {
      // Retry while visible; a failed request must never mark the day counted.
    } finally {
      pending.delete(userId)
    }
    return 30_000
  }
}
