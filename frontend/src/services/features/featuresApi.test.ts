import { beforeEach, describe, expect, it, vi } from 'vitest'

const transport = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../http/apiClient', () => ({ api: transport }))

import { DEFAULT_FEATURE_FLAGS, fetchFeatures } from './featuresApi'

describe('Features API contract', () => {
  beforeEach(() => {
    transport.get.mockReset()
  })

  it('maps wire snake_case flags to camelCase', async () => {
    const signal = new AbortController().signal
    transport.get.mockResolvedValueOnce({ data: { x_source: false, wechat_source: true } })

    await expect(fetchFeatures(signal)).resolves.toEqual({ xSource: false, wechatSource: true })
    expect(transport.get).toHaveBeenLastCalledWith('/features', { signal })
  })

  it('fails open when fields are missing', async () => {
    transport.get.mockResolvedValueOnce({ data: {} })
    await expect(fetchFeatures()).resolves.toEqual(DEFAULT_FEATURE_FLAGS)

    transport.get.mockResolvedValueOnce({ data: null })
    await expect(fetchFeatures()).resolves.toEqual(DEFAULT_FEATURE_FLAGS)
  })
})
