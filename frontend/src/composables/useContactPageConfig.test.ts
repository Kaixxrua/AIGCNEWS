import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/services/site/contactPageApi', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/services/site/contactPageApi')>()
  return { ...original, fetchContactPage: vi.fn() }
})

import { DEFAULT_CONTACT_PAGE, fetchContactPage } from '@/services/site/contactPageApi'
import {
  __resetContactPageConfigForTest,
  ensureContactPageConfig,
  refreshContactPageConfig,
  useContactPageConfig,
} from './useContactPageConfig'

const ENABLED_PAGE = {
  enabled: true,
  navLabel: '合作',
  title: '联系合作',
  subtitle: '外包 · 商务合作',
  serviceCards: [],
  contactEntries: [],
  bodyMarkdown: '',
  updatedAt: null,
}

describe('useContactPageConfig', () => {
  beforeEach(() => {
    __resetContactPageConfigForTest()
    vi.mocked(fetchContactPage).mockReset()
  })

  it('fetches once, maps into shared state, and caches the request', async () => {
    vi.mocked(fetchContactPage).mockResolvedValue(ENABLED_PAGE)

    const first = await ensureContactPageConfig()
    const second = await ensureContactPageConfig()

    expect(first).toEqual(ENABLED_PAGE)
    expect(second).toBe(first)
    expect(vi.mocked(fetchContactPage).mock.calls).toHaveLength(1)
    expect(useContactPageConfig().contactPageConfig.value.enabled).toBe(true)
  })

  it('fails closed to defaults when the request fails', async () => {
    // 与特性开关相反：失败保持隐藏，不给未配置站点闪空页面
    vi.mocked(fetchContactPage).mockRejectedValue(new Error('network down'))

    await expect(ensureContactPageConfig()).resolves.toEqual(DEFAULT_CONTACT_PAGE)
    expect(useContactPageConfig().contactPageConfig.value).toEqual(DEFAULT_CONTACT_PAGE)
  })

  it('refresh clears the cache and re-fetches (monitor save → live dock update)', async () => {
    vi.mocked(fetchContactPage).mockResolvedValue(DEFAULT_CONTACT_PAGE)
    await ensureContactPageConfig()

    vi.mocked(fetchContactPage).mockResolvedValue(ENABLED_PAGE)
    await expect(refreshContactPageConfig()).resolves.toEqual(ENABLED_PAGE)

    expect(vi.mocked(fetchContactPage).mock.calls).toHaveLength(2)
    expect(useContactPageConfig().contactPageConfig.value.navLabel).toBe('合作')
  })

  it('reset seam restores defaults and clears the cache', async () => {
    vi.mocked(fetchContactPage).mockResolvedValue(ENABLED_PAGE)
    await ensureContactPageConfig()

    __resetContactPageConfigForTest()
    expect(useContactPageConfig().contactPageConfig.value).toEqual(DEFAULT_CONTACT_PAGE)

    vi.mocked(fetchContactPage).mockResolvedValue(ENABLED_PAGE)
    await expect(ensureContactPageConfig()).resolves.toEqual(ENABLED_PAGE)
    expect(vi.mocked(fetchContactPage).mock.calls).toHaveLength(2)
  })
})
