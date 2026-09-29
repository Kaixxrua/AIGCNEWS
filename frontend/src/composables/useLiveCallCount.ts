import { onScopeDispose, ref, watch, type Ref } from 'vue'
import { fetchLiveStats } from '@/services/dashboard/dashboardLiveApi'
import { subscribeLiveStats } from '@/composables/useLiveStatsStream'
import type { Stats } from '@/features/dashboard/dashboardViewModel'

export type LiveCallField = 'mcp_total_calls' | 'mcp_dsh_calls'

/* /mcp 与 /dsh 页的调用计数：与首页仪表盘同一数据源（live-stats 的 mcp_total_calls / mcp_dsh_calls）与同一条
   共享 SSE 推送。只在 active 为真时拉取并订阅（桌面漫画版才展示这组统计），转为假即退订；
   失败静默保留当前值，首个有效值到达前为 null。 */
export const useLiveCallCount = (field: LiveCallField, active: Ref<boolean>) => {
  const calls = ref<number | null>(null)
  let unsubscribe: (() => void) | null = null
  const stop = () => {
    unsubscribe?.()
    unsubscribe = null
  }
  const apply = (stats: Stats) => {
    const value = stats[field]
    if (typeof value === 'number') calls.value = value
  }
  watch(active, (on) => {
    stop()
    if (!on) return
    void fetchLiveStats().then(apply).catch(() => {})
    unsubscribe = subscribeLiveStats(apply)
  }, { immediate: true })
  onScopeDispose(stop)
  return calls
}
