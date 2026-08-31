import { api } from '@/services/http/apiClient'

/* 站点访问 beacon：同一匿名访客在同一 CST 自然日只计一次。
   localStorage 持久化匿名 ID，sessionStorage 仅负责同一 tab 的请求守卫。
   守卫在请求成功后落：后端不可用时本次不计，下次刷新重试。 */

const visitorIdKey = 'aigc:anonymous-visitor-id'

const beaconStorageKey = (): string => {
  const now = new Date()
  const cst = new Date(now.getTime() + (now.getTimezoneOffset() + 8 * 60) * 60_000)
  const day = `${cst.getFullYear()}-${String(cst.getMonth() + 1).padStart(2, '0')}-${String(cst.getDate()).padStart(2, '0')}`
  return `aigc:visit-beacon:${day}`
}

const createVisitorId = (): string => {
  const uuid = globalThis.crypto?.randomUUID?.()
  if (uuid) return uuid.replace(/-/g, '')
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`
}

const getVisitorId = (): string | null => {
  try {
    const existing = localStorage.getItem(visitorIdKey)?.trim()
    if (existing && /^[A-Za-z0-9_-]{16,128}$/.test(existing)) return existing
    const created = createVisitorId()
    localStorage.setItem(visitorIdKey, created)
    return created
  } catch {
    return null
  }
}

export const sendVisitBeacon = (): void => {
  let key: string
  try {
    key = beaconStorageKey()
    if (sessionStorage.getItem(key)) return
  } catch {
    /* sessionStorage 不可用（隐私模式等）：统计直接放弃，不影响浏览 */
    return
  }
  const visitorId = getVisitorId()
  if (!visitorId) return
  void api.post('/dashboard/visit', { visitor_id: visitorId }).then(() => {
    try {
      sessionStorage.setItem(key, '1')
    } catch { /* 守卫落不上则下次重试，可接受 */ }
  }).catch(() => { /* 统计失败静默，下次进入重试 */ })
}
