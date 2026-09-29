import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/services/features/featuresApi', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/services/features/featuresApi')>()
  return { ...original, fetchFeatures: vi.fn() }
})

import { DEFAULT_FEATURE_FLAGS, fetchFeatures } from '@/services/features/featuresApi'
import {
  __resetFeatureFlagsForTest,
  ensureFeatureFlags,
  refreshFeatureFlags,
  useFeatureFlags,
} from './useFeatureFlags'

const flags = (overrides: Partial<typeof DEFAULT_FEATURE_FLAGS> = {}) => ({
  ...DEFAULT_FEATURE_FLAGS,
  ...overrides,
})

describe('useFeatureFlags', () => {
  beforeEach(() => {
    __resetFeatureFlagsForTest()
    vi.mocked(fetchFeatures).mockReset()
  })

  it('fetches once, maps into shared state, and caches the request', async () => {
    vi.mocked(fetchFeatures).mockResolvedValue(flags({ xSource: false }))

    const first = await ensureFeatureFlags()
    const second = await ensureFeatureFlags()

    expect(first).toEqual(flags({ xSource: false }))
    expect(second).toBe(first)
    expect(vi.mocked(fetchFeatures).mock.calls).toHaveLength(1)
    expect(useFeatureFlags().featureFlags.value.xSource).toBe(false)
  })

  it('fails open to defaults when the request fails', async () => {
    vi.mocked(fetchFeatures).mockRejectedValue(new Error('network down'))

    await expect(ensureFeatureFlags()).resolves.toEqual(DEFAULT_FEATURE_FLAGS)
    expect(useFeatureFlags().featureFlags.value).toEqual(DEFAULT_FEATURE_FLAGS)
  })

  it('reset seam restores defaults and clears the cache', async () => {
    vi.mocked(fetchFeatures).mockResolvedValue(flags({ xSource: false }))
    await ensureFeatureFlags()

    __resetFeatureFlagsForTest()
    expect(useFeatureFlags().featureFlags.value).toEqual(DEFAULT_FEATURE_FLAGS)

    vi.mocked(fetchFeatures).mockResolvedValue(flags({ xSource: true }))
    await expect(ensureFeatureFlags()).resolves.toEqual(flags({ xSource: true }))
    expect(vi.mocked(fetchFeatures).mock.calls).toHaveLength(2)
  })

  it('refreshFeatureFlags forces a refetch even after a cached load', async () => {
    vi.mocked(fetchFeatures).mockResolvedValue(flags())
    await ensureFeatureFlags()
    expect(vi.mocked(fetchFeatures).mock.calls).toHaveLength(1)

    // Monitor 保存 OAuth 配置后：同一 promise 缓存必须被强制失效
    vi.mocked(fetchFeatures).mockResolvedValue(flags({ oauthProviders: ['github'] }))
    const refreshed = await refreshFeatureFlags()

    expect(vi.mocked(fetchFeatures).mock.calls).toHaveLength(2)
    expect(refreshed.oauthProviders).toEqual(['github'])
    expect(useFeatureFlags().featureFlags.value.oauthProviders).toEqual(['github'])

    // 之后的 ensure 复用 refresh 的结果，不再重复请求
    await ensureFeatureFlags()
    expect(vi.mocked(fetchFeatures).mock.calls).toHaveLength(2)
  })
})
