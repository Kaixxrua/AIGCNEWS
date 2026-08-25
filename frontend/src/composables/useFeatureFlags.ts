import { readonly, ref } from 'vue'
import {
  DEFAULT_FEATURE_FLAGS,
  fetchFeatures,
  type FeatureFlags,
} from '@/services/features/featuresApi'

const featureFlags = ref<FeatureFlags>({ ...DEFAULT_FEATURE_FLAGS })
let inflight: Promise<FeatureFlags> | null = null

const load = (): Promise<FeatureFlags> =>
  fetchFeatures()
    .then((fetched) => {
      featureFlags.value = fetched
      return fetched
    })
    .catch(() => featureFlags.value)

/** 拉取一次特性开关（进程内缓存共享）；请求失败保持 fail-open 默认值。 */
export const ensureFeatureFlags = (): Promise<FeatureFlags> => {
  if (!inflight) {
    inflight = load()
  }
  return inflight
}

/** 配置变更（如 Monitor 保存 OAuth/源开关）后强制重拉，登录按钮等即时刷新。 */
export const refreshFeatureFlags = (): Promise<FeatureFlags> => {
  inflight = load()
  return inflight
}

export const useFeatureFlags = () => ({
  featureFlags: readonly(featureFlags),
  ensureFeatureFlags,
  refreshFeatureFlags,
})

/** 测试缝：复位缓存与状态。 */
export const __resetFeatureFlagsForTest = (): void => {
  featureFlags.value = { ...DEFAULT_FEATURE_FLAGS }
  inflight = null
}
