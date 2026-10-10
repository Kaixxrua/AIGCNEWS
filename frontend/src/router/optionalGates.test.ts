import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import router from './index'
import { useAuthStore } from '@/stores/authStore'
import { DEFAULT_FEATURE_FLAGS } from '@/services/features/featuresApi'
import { DEFAULT_CONTACT_PAGE } from '@/services/site/contactPageApi'

const gates = vi.hoisted(() => ({
  ensureFeatureFlags: vi.fn(),
  ensureContactPageConfig: vi.fn(),
}))

vi.mock('@/composables/useFeatureFlags', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/composables/useFeatureFlags')>()),
  ensureFeatureFlags: gates.ensureFeatureFlags,
}))
vi.mock('@/composables/useContactPageConfig', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/composables/useContactPageConfig')>()),
  ensureContactPageConfig: gates.ensureContactPageConfig,
}))

describe('optional route gates', () => {
  beforeEach(async () => {
    setActivePinia(createPinia())
    useAuthStore().status = 'anonymous'
    gates.ensureFeatureFlags.mockReset().mockResolvedValue({ ...DEFAULT_FEATURE_FLAGS })
    gates.ensureContactPageConfig.mockReset().mockResolvedValue({ ...DEFAULT_CONTACT_PAGE, enabled: true })
    await router.replace('/')
  })

  it('opens the public projects page without awaiting unrelated config', async () => {
    await router.push('/projects')

    expect(router.currentRoute.value.name).toBe('github-projects')
    expect(gates.ensureFeatureFlags).not.toHaveBeenCalled()
    expect(gates.ensureContactPageConfig).not.toHaveBeenCalled()
  })

  it('still redirects when the X source is disabled', async () => {
    gates.ensureFeatureFlags.mockResolvedValue({ ...DEFAULT_FEATURE_FLAGS, xSource: false })

    await router.push('/x')

    expect(router.currentRoute.value.path).toBe('/')
    expect(gates.ensureFeatureFlags).toHaveBeenCalledOnce()
    expect(gates.ensureContactPageConfig).not.toHaveBeenCalled()
  })

  it('still redirects when the contact page is disabled', async () => {
    gates.ensureContactPageConfig.mockResolvedValue({ ...DEFAULT_CONTACT_PAGE })

    await router.push('/contact')

    expect(router.currentRoute.value.path).toBe('/')
    expect(gates.ensureFeatureFlags).not.toHaveBeenCalled()
    expect(gates.ensureContactPageConfig).toHaveBeenCalledOnce()
  })

  it('allows enabled gated routes after checking their own config', async () => {
    await router.push('/x')
    expect(router.currentRoute.value.path).toBe('/x')
    expect(gates.ensureFeatureFlags).toHaveBeenCalledOnce()
    expect(gates.ensureContactPageConfig).not.toHaveBeenCalled()

    await router.push('/contact')
    expect(router.currentRoute.value.path).toBe('/contact')
    expect(gates.ensureContactPageConfig).toHaveBeenCalledOnce()
  })
})
