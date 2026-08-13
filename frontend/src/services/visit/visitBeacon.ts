import { api } from '@/services/http/apiClient'

/* 站点访问 beacon：进来一次网站计一次（纯次数口径，不去重）。
   sessionStorage 守卫——同一 tab 会话内刷新/SPA 导航不重复计，
   关掉 tab 再进算新一次；key 带 CST 日期，跨天后同 tab 会重新计。
   守卫在请求成功后落：后端不可用时本次不计，下次刷新重试。 */

const beaconStorageKey = (): string => {
  const now = new Date()
  const cst = new Date(now.getTime() + (now.getTimezoneOffset() + 8 * 60) * 60_000)
  const day = `${cst.getFullYear()}-${String(cst.getMonth() + 1).padStart(2, '0')}-${String(cst.getDate()).padStart(2, '0')}`
  return `aigc:visit-beacon:${day}`
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
  void api.post('/dashboard/visit').then(() => {
    try {
      sessionStorage.setItem(key, '1')
    } catch { /* 守卫落不上则下次重试，可接受 */ }
  }).catch(() => { /* 统计失败静默，下次进入重试 */ })
}
