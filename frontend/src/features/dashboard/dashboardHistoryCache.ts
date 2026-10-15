import type { DashboardApi, DashboardTop, DashboardTopParams } from '@/services/dashboard/dashboardContracts'

const TTL = 60_000
const MAX_ENTRIES = 36

/** A short, bounded cache shared by foreground history loads and adjacent-date prefetch. */
export const createDashboardHistoryCache = (api: DashboardApi, now: () => number) => {
  const cached = new Map<string, { top: DashboardTop; expiresAt: number }>()
  const pending = new Map<string, { promise: Promise<DashboardTop>; signal?: AbortSignal }>()

  const fetchTop = (params: DashboardTopParams): Promise<DashboardTop> => {
    if (!params.date) return api.fetchTop(params)
    const key = [params.source, params.date, params.period, params.limit].join(':')
    const hit = cached.get(key)
    if (params.cacheBuster === undefined && hit && hit.expiresAt > now()) {
      cached.delete(key)
      cached.set(key, hit)
      return Promise.resolve(hit.top)
    }
    const inflight = pending.get(key)
    if (params.cacheBuster === undefined && inflight && !inflight.signal?.aborted) return inflight.promise
    cached.delete(key)
    const requestedAt = now()
    const promise = api.fetchTop(params).then(top => {
      if (!params.signal?.aborted && pending.get(key)?.promise === promise) {
        const cstDay = new Date(requestedAt + 8 * 3_600_000).toISOString().slice(0, 10)
        const midnight = Date.parse(cstDay + 'T00:00:00+08:00') + 86_400_000
        const closeHour = top.sourceStatus[params.source]?.finalize_hour
        const closeAt = closeHour == null ? Infinity
          : Date.parse((top.resolvedDate || params.date) + 'T00:00:00+08:00') + (24 + closeHour) * 3_600_000
        cached.set(key, { top, expiresAt: Math.min(requestedAt + TTL, midnight, closeAt > requestedAt ? closeAt : Infinity) })
        if (cached.size > MAX_ENTRIES) cached.delete(cached.keys().next().value!)
      }
      return top
    }).finally(() => {
      if (pending.get(key)?.promise === promise) pending.delete(key)
    })
    pending.set(key, { promise, signal: params.signal })
    return promise
  }

  return { fetchTop }
}
