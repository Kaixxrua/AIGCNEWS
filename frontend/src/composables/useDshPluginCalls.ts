import { onScopeDispose, ref, watch, type Ref } from 'vue'
import { fetchLiveStats } from '@/services/dashboard/dashboardLiveApi'
import { subscribeLiveStats } from '@/composables/useLiveStatsStream'
import type { Stats } from '@/features/dashboard/dashboardViewModel'

/* /dsh 页「dsh 插件调用」计数：与首页仪表盘同一数据源（live-stats 的 mcp_dsh_calls）与同一条共享
   SSE 推送。只在 active 为真时拉取并订阅（桌面漫画版才展示这组统计），转为假即退订；
   失败静默保留当前值，首个有效值到达前为 null。 */
export const useDshPluginCalls = (active: Ref<boolean>) => {
  const calls = ref<number | null>(null)
  let unsubscribe: (() => void) | null = null
  const stop = () => {
    unsubscribe?.()
    unsubscribe = null
  }
  const apply = (stats: Stats) => {
    if (typeof stats.mcp_dsh_calls === 'number') calls.value = stats.mcp_dsh_calls
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
