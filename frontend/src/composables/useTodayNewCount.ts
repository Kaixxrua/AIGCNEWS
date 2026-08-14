import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useIntervalFn } from '@vueuse/core'
import { fetchLiveStats } from '@/services/dashboard/dashboardLiveApi'

/* 顶栏报头「今日更新」计数：与首页仪表盘同一数据源、同一节奏——
   挂载即拉一次 /dashboard/live-stats（取 today_new_documents），之后每 10s 轮询；
   失败静默保留当前值。数字滚筒动画由 RollingNumber 承接（首滚 0→N + 差位滚动）。 */
export const useTodayNewCount = (
  options: { fetchStats?: typeof fetchLiveStats; intervalMs?: number } = {},
) => {
  const fetchStats = options.fetchStats ?? fetchLiveStats
  const intervalMs = options.intervalMs ?? 10_000
  const todayNewCount = ref(0)

  const refresh = async () => {
    try {
      const live = await fetchStats()
      todayNewCount.value = Number(live.today_new_documents ?? 0)
    } catch {
      /* 实时计数失败静默，保留当前展示值（与仪表盘一致） */
    }
  }

  const { pause, resume } = useIntervalFn(() => { void refresh() }, intervalMs, { immediate: false })
  onMounted(() => {
    void refresh()
    resume()
  })
  onBeforeUnmount(pause)

  return { todayNewCount, refresh }
}
