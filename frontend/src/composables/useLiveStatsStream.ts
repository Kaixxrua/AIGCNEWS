import { getCurrentInstance, onBeforeUnmount, ref } from 'vue'

import { fetchLiveStats, LIVE_EVENTS_URL } from '@/services/dashboard/dashboardLiveApi'
import type { Stats } from '@/features/dashboard/dashboardViewModel'

/* 首页实时计数的事件流订阅（模块级单例，全站共享一条 SSE 连接）：
   - 首选 EventSource 订阅 /dashboard/live-events：后端写路径触发重算后
     主动推送全量计数，数字变化即时驱动 RollingNumber 滚筒动画；
   - 首帧即当前常驻值，与挂载时的 REST 兜底竞速，mergeLiveStats 幂等；
   - SSE 断流由浏览器按 retry（3s）自动重连；持续断流（>15s 未 OPEN）
     降级 30s 轮询 live-stats REST，流恢复即停降级；
   - refcount 管理：首个订阅者开流，最后一个退订关流。 */
export type LiveStatsListener = (stats: Stats) => void

const FALLBACK_AFTER_MS = 15_000
const FALLBACK_INTERVAL_MS = 30_000

const listeners = new Set<LiveStatsListener>()
const streamReady = ref(false)

let eventSource: EventSource | null = null
let fallbackTimer: ReturnType<typeof setInterval> | null = null
let fallbackWatchdog: ReturnType<typeof setTimeout> | null = null

const notifyListeners = (stats: Stats) => {
  listeners.forEach((listener) => listener(stats))
}

const parseAndNotify = (raw: string) => {
  try {
    notifyListeners(JSON.parse(raw) as Stats)
  } catch {
    /* 半帧/注释帧以外的坏帧静默丢弃，等待下一帧全量值 */
  }
}

const stopFallbackPolling = () => {
  if (fallbackTimer !== null) {
    clearInterval(fallbackTimer)
    fallbackTimer = null
  }
  if (fallbackWatchdog !== null) {
    clearTimeout(fallbackWatchdog)
    fallbackWatchdog = null
  }
}

const startFallbackPolling = () => {
  if (fallbackTimer !== null) return
  /* SSE 不可用（旧代理缓冲/网络设备截断）时的近实时兜底 */
  fallbackTimer = setInterval(() => {
    void fetchLiveStats().then(notifyListeners).catch(() => {})
  }, FALLBACK_INTERVAL_MS)
}

const armFallbackWatchdog = () => {
  if (fallbackWatchdog !== null || fallbackTimer !== null) return
  fallbackWatchdog = setTimeout(() => {
    if (!streamReady.value) startFallbackPolling()
  }, FALLBACK_AFTER_MS)
}

const openStream = () => {
  if (eventSource) return
  streamReady.value = false
  if (typeof EventSource === 'undefined') {
    /* 极端环境（老旧 WebView/受限浏览器）无 EventSource：直接走降级轮询 */
    startFallbackPolling()
    return
  }
  const source = new EventSource(LIVE_EVENTS_URL)
  eventSource = source
  source.onopen = () => {
    streamReady.value = true
    stopFallbackPolling()
  }
  source.onmessage = (event) => parseAndNotify(String(event.data))
  source.onerror = () => {
    streamReady.value = false
    /* EventSource 原生自动重连；看门狗在持续断流时拉起降级轮询 */
    armFallbackWatchdog()
  }
  armFallbackWatchdog()
}

const closeStream = () => {
  eventSource?.close()
  eventSource = null
  streamReady.value = false
  stopFallbackPolling()
}

/** 订阅实时计数推送；返回退订函数（组件 onBeforeUnmount 自动调用）。 */
export const subscribeLiveStats = (listener: LiveStatsListener): (() => void) => {
  listeners.add(listener)
  if (listeners.size === 1) openStream()
  const unsubscribe = () => {
    listeners.delete(listener)
    if (listeners.size === 0) closeStream()
  }
  if (getCurrentInstance()) onBeforeUnmount(unsubscribe)
  return unsubscribe
}

/** SSE 连接状态（调试用；模板无需展示）。 */
export const useLiveStatsStreamReady = () => streamReady
