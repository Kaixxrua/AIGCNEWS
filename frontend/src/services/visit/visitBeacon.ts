import { api } from '@/services/http/apiClient'

/* 站点访问 beacon：同一匿名访客在同一 CST 自然日只计一次。
   localStorage 持久化匿名 ID，sessionStorage 仅负责同一 tab 的请求守卫。
   守卫在请求成功后落：后端不可用时本次不计，下次刷新重试。 */

const visitorIdKey = 'aigc:anonymous-visitor-id'

/* 429 提示链接的来源标记，与后端 landing_sources.LANDING_SOURCES 是同一组值。
   有的客户端会把紧跟的句号、汉字也算进链接：标记后面接的不是字母、数字、_ 或 - 就照样认。 */
const landingRefPattern = /^(?:mcp|api)-429-(?:anon|daily|monthly)(?![\w-])/

export interface LandingLocation {
  pathname: string
  search: string
}

export interface LandingSource {
  ref: string
  path: string
}

/** 从落地地址读出 429 提示链接的来源标记；没带或不认识时返回 null。 */
export const readLandingSource = (location: LandingLocation): LandingSource | null => {
  let ref: string | null
  try {
    ref = new URLSearchParams(location.search).get('ref')
  } catch {
    return null
  }
  const match = ref ? landingRefPattern.exec(ref.trim()) : null
  if (!match) return null
  return { ref: match[0], path: location.pathname.slice(0, 256) }
}

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

/* landing 是路由接管前记下的落地地址（见 main.ts）。带 429 来源标记时绕过当天的守卫照样上报：
   访问由后端按访客去重不会重复计数，落地来源要单独记一次。 */
export const sendVisitBeacon = (landing: LandingLocation | null = null): void => {
  const source = landing ? readLandingSource(landing) : null
  let key: string
  try {
    key = beaconStorageKey()
    if (sessionStorage.getItem(key) && !source) return
  } catch {
    /* sessionStorage 不可用（隐私模式等）：统计直接放弃，不影响浏览 */
    return
  }
  const visitorId = getVisitorId()
  if (!visitorId) return
  const body = source
    ? { visitor_id: visitorId, landing_ref: source.ref, landing_path: source.path }
    : { visitor_id: visitorId }
  void api.post('/dashboard/visit', body).then(() => {
    try {
      sessionStorage.setItem(key, '1')
    } catch { /* 守卫落不上则下次重试，可接受 */ }
  }).catch(() => { /* 统计失败静默，下次进入重试 */ })
}
