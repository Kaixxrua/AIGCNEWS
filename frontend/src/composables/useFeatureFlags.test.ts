import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/services/features/featuresApi', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/services/features/featuresApi')>()
  return { ...original, fetchFeatures: vi.fn() }
})

import { DEFAULT_FEATURE_FLAGS, fetchFeatures } from '@/services/features/featuresApi'
import {
  __resetFeatureFlagsForTest,
  ensureFeatureFlags,
  useFeatureFlags,
} from './useFeatureFlags'

describe('useFeatureFlags', () => {
  beforeEach(() => {
    __resetFeatureFlagsForTest()
    vi.mocked(fetchFeatures).mockReset()
  })

  it('fetches once, maps into shared state, and caches the request', async () => {
    vi.mocked(fetchFeatures).mockResolvedValue({ xSource: false, wechatSource: true })

    const first = await ensureFeatureFlags()
    const second = await ensureFeatureFlags()

    expect(first).toEqual({ xSource: false, wechatSource: true })
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
    vi.mocked(fetchFeatures).mockResolvedValue({ xSource: false, wechatSource: false })
    await ensureFeatureFlags()

    __resetFeatureFlagsForTest()
    expect(useFeatureFlags().featureFlags.value).toEqual(DEFAULT_FEATURE_FLAGS)

    vi.mocked(fetchFeatures).mockResolvedValue({ xSource: true, wechatSource: true })
    await expect(ensureFeatureFlags()).resolves.toEqual({ xSource: true, wechatSource: true })
    expect(vi.mocked(fetchFeatures).mock.calls).toHaveLength(2)
  })
})
