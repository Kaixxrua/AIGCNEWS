import { readonly, ref } from 'vue'
import {
  DEFAULT_FEATURE_FLAGS,
  fetchFeatures,
  type FeatureFlags,
} from '@/services/features/featuresApi'

const featureFlags = ref<FeatureFlags>({ ...DEFAULT_FEATURE_FLAGS })
let inflight: Promise<FeatureFlags> | null = null

/** 拉取一次特性开关（进程内缓存共享）；请求失败保持 fail-open 默认值。 */
export const ensureFeatureFlags = (): Promise<FeatureFlags> => {
  if (!inflight) {
    inflight = fetchFeatures()
      .then((fetched) => {
        featureFlags.value = fetched
        return fetched
      })
      .catch(() => featureFlags.value)
  }
  return inflight
}

export const useFeatureFlags = () => ({
  featureFlags: readonly(featureFlags),
  ensureFeatureFlags,
})

/** 测试缝：复位缓存与状态。 */
export const __resetFeatureFlagsForTest = (): void => {
  featureFlags.value = { ...DEFAULT_FEATURE_FLAGS }
  inflight = null
}
