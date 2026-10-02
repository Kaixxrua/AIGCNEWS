import { onScopeDispose, shallowRef, watch } from 'vue'
import {
  fetchProjectTrends,
  type GitHubProjectTrend,
  type GitHubProjectTrendsResponse,
} from '@/services/projects/projectApi'

export interface ProjectTrendsRequest {
  repoIds: readonly string[]
  /** 今日热门再带昨日热榜名次 */
  ranks: boolean
}

// 日度指标一天才更新几轮：同一页两分钟内不重取，列表每 30 秒的静默刷新不会跟着打行情接口。
export const PROJECT_TRENDS_STALE_MS = 120_000
const CACHE_LIMIT = 8

interface Entry {
  data: GitHubProjectTrendsResponse | null
  fetchedAt: number
}

/**
 * 榜单一页的行情：一次请求取齐这一页的火花线（今日热门再带昨日名次）。翻回看过的页先用缓存；
 * 换页时上一页的数据留着，直到新的一页到了再换（对不上的行先空着），不会整片闪一下。
 * 取不到就不画：名次升降和火花线只是添在榜单上的，失败也记一笔时间，两分钟内不再重试。
 * request 返回 null（舒适版面、手机、个人收藏）时不发请求。
 */
export function useProjectTrends(
  request: () => ProjectTrendsRequest | null,
  { now = Date.now }: { now?: () => number } = {},
) {
  const trends = shallowRef<GitHubProjectTrendsResponse | null>(null)
  const cache = new Map<string, Entry>()
  let currentKey = ''
  let inflightKey = ''
  let controller: AbortController | null = null

  const remember = (key: string, entry: Entry) => {
    cache.delete(key)
    cache.set(key, entry)
    while (cache.size > CACHE_LIMIT) cache.delete(cache.keys().next().value as string)
  }

  // 撤下在途的请求时立刻清掉记号：被撤的请求要过一拍才结束，这期间再要同一页不能当成还在取。
  const abort = () => {
    controller?.abort()
    controller = null
    inflightKey = ''
  }

  const load = async (key: string, repoIds: string[], ranks: boolean) => {
    abort()
    const own = new AbortController()
    controller = own
    inflightKey = key
    try {
      const data = await fetchProjectTrends(repoIds, { ranks, signal: own.signal })
      remember(key, { data, fetchedAt: now() })
      if (currentKey === key) trends.value = data
    } catch {
      if (own.signal.aborted) return
      remember(key, { data: cache.get(key)?.data ?? null, fetchedAt: now() })
    } finally {
      if (controller === own) {
        controller = null
        inflightKey = ''
      }
    }
  }

  watch(request, (next) => {
    const repoIds = [...new Set(next?.repoIds ?? [])].filter(Boolean).sort()
    if (!next || !repoIds.length) {
      currentKey = ''
      abort()
      return
    }
    // 键按仓库排序：今日热门重排名次不算换了一页。
    const key = `${next.ranks ? 'ranks' : 'plain'}:${repoIds.join(',')}`
    currentKey = key
    const entry = cache.get(key)
    if (entry?.data) trends.value = entry.data
    if (inflightKey === key || (entry && now() - entry.fetchedAt < PROJECT_TRENDS_STALE_MS)) return
    void load(key, repoIds, next.ranks)
  }, { immediate: true })

  onScopeDispose(abort)

  const trendFor = (repoId: string): GitHubProjectTrend | undefined => (repoId ? trends.value?.items[repoId] : undefined)

  return { trends, trendFor }
}
