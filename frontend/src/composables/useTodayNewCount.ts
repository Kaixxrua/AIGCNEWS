import { onBeforeUnmount, onMounted, ref } from 'vue'
import { fetchLiveStats } from '@/services/dashboard/dashboardLiveApi'
import { subscribeLiveStats } from '@/composables/useLiveStatsStream'

/* 顶栏报头「今日更新」计数：与首页仪表盘同一数据源、同一事件流——
   挂载即拉一次 /dashboard/live-stats 兜底竞速（取 today_new_documents），之后由
   SSE 推送即时更新；失败静默保留当前值。数字滚筒动画由 RollingNumber 承接
   （首滚 0→N + 差位滚动）。 */
export const useTodayNewCount = (
  options: { fetchStats?: typeof fetchLiveStats; subscribeStats?: typeof subscribeLiveStats } = {},
) => {
  const fetchStats = options.fetchStats ?? fetchLiveStats
  const subscribeStats = options.subscribeStats ?? subscribeLiveStats
  const todayNewCount = ref(0)

  const refresh = async () => {
    try {
      const live = await fetchStats()
      todayNewCount.value = Number(live.today_new_documents ?? 0)
    } catch {
      /* 实时计数失败静默，保留当前展示值（与仪表盘一致） */
    }
  }

  onMounted(() => { void refresh() })
  /* SSE 首帧即当前值，与 refresh 幂等；退订幂等（真实实现内部也已注册卸载退订，
     此处显式接线使注入的 subscribeStats 替身同样遵循组件生命周期）。 */
  const unsubscribe = subscribeStats((stats) => {
    todayNewCount.value = Number(stats.today_new_documents ?? 0)
  })
  onBeforeUnmount(unsubscribe)

  return { todayNewCount, refresh }
}
