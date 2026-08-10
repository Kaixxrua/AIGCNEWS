import { readonly, ref } from 'vue'

const SHOW_DELAY_MS = 150

const isRouteLoading = ref(false)
let pendingCount = 0
let showTimer: number | undefined

const clearShowTimer = () => {
  if (showTimer !== undefined) {
    window.clearTimeout(showTimer)
    showTimer = undefined
  }
}

/** 导航开始时调用。延迟显示，避免缓存命中等快速切换时进度条闪烁。 */
export function startRouteProgress() {
  pendingCount += 1
  clearShowTimer()
  showTimer = window.setTimeout(() => {
    showTimer = undefined
    if (pendingCount > 0) isRouteLoading.value = true
  }, SHOW_DELAY_MS)
}

/** 导航结束（确认、取消或出错）时调用。与 start 成对，全部结束后才隐藏。 */
export function stopRouteProgress() {
  pendingCount = Math.max(0, pendingCount - 1)
  if (pendingCount > 0) return
  clearShowTimer()
  isRouteLoading.value = false
}

export function useRouteProgress() {
  return { isRouteLoading: readonly(isRouteLoading) }
}
