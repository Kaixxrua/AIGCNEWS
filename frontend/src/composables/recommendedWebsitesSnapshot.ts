import { readonly, ref } from 'vue'
import { fetchRecommendedWebsites, type RecommendedWebsite } from '@/services/site/recommendedWebsiteApi'

/**
 * 站长推荐列表的进程内快照，null 表示还没拿到过。路由守卫据此决定游客点「网页」先看哪一页，
 * 栏目标签据此藏起还空着的「站长推荐」，推荐页据此先画出上次的列表、再静默刷新。
 */
const snapshot = ref<readonly RecommendedWebsite[] | null>(null)
let inflight: Promise<readonly RecommendedWebsite[] | null> | null = null

export const rememberRecommendedWebsites = (items: readonly RecommendedWebsite[]): void => {
  snapshot.value = items
}

/** 拉一次站长推荐（同时只发一个请求，拿到后不再重拉）；失败返回 null，下次再试。 */
export const ensureRecommendedWebsites = (): Promise<readonly RecommendedWebsite[] | null> => {
  if (snapshot.value) return Promise.resolve(snapshot.value)
  inflight ??= fetchRecommendedWebsites()
    .then((items) => {
      snapshot.value = items
      return items
    })
    .catch(() => null)
    .finally(() => {
      inflight = null
    })
  return inflight
}

export const useRecommendedWebsitesSnapshot = () => readonly(snapshot)

/** 测试缝：复位快照与在途请求。 */
export const __resetRecommendedWebsitesSnapshotForTest = (): void => {
  snapshot.value = null
  inflight = null
}
