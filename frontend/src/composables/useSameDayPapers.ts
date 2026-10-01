import { computed, onScopeDispose, ref, watch, type Ref } from 'vue'
import { sameDayEntries } from '@/features/papers/paperHead'
import type { TopDoc } from '@/features/dashboard/dashboardViewModel'
import { dashboardApi } from '@/services/dashboard/dashboardApi'
import type { DashboardApi } from '@/services/dashboard/dashboardContracts'

interface SameDayPapersOptions {
  /** 论文发布那天（YYYY-MM-DD）；没有日期就不取。 */
  day: Ref<string | null>
  currentId: Ref<string>
  /** 只在要显示的时候取（桌面）；关掉时清空。 */
  enabled: Ref<boolean>
  limit?: number
  fetchTop?: DashboardApi['fetchTop']
}

/** 同一天的论文日榜：换论文、换日期时取消上一次请求；取不到、被禁播或后端改给别的日期时不显示。 */
export function useSameDayPapers(options: SameDayPapersOptions) {
  const fetchTop: DashboardApi['fetchTop'] = options.fetchTop ?? ((params) => dashboardApi.fetchTop(params))
  const items = ref<TopDoc[]>([])
  let controller: AbortController | null = null

  watch([options.day, options.enabled], async ([date, enabled]) => {
    controller?.abort()
    controller = null
    if (!date || !enabled) {
      items.value = []
      return
    }
    const current = new AbortController()
    controller = current
    try {
      const result = await fetchTop({ source: 'arxiv', date, limit: options.limit ?? 10, signal: current.signal })
      if (controller !== current) return
      const otherDay = result.resolvedDate !== undefined && result.resolvedDate !== date
      items.value = result.isEmbargoed || otherDay ? [] : result.items
    } catch {
      if (controller === current) items.value = []
    }
  }, { immediate: true })

  onScopeDispose(() => controller?.abort())

  const entries = computed(() => sameDayEntries(items.value, options.currentId.value))
  return { entries }
}
