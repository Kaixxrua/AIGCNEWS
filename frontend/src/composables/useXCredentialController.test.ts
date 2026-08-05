import { describe, expect, it, vi } from 'vitest'
import { useXCredentialController, type XCredentialApi, type XCredentialController } from './useXCredentialController'
import type { XCredential, XCredentialForm } from '@/features/monitor/monitorModel'

const firstCredential = (controller: XCredentialController) => {
  const item = controller.credentials.value[0]
  if (!item) throw new Error('expected at least one credential')
  return item
}

const credential = (overrides: Partial<XCredential> = {}): XCredential => ({
  id: 1,
  display_name: 'Primary X',
  note: '',
  enabled: true,
  sort_order: 0,
  auth_token_configured: true,
  auth_token_masked: 'masked-auth-token',
  ct0_configured: true,
  ct0_masked: 'masked-ct0',
  last_test_status: 'unknown',
  last_test_message: '',
  last_test_at: null,
  created_at: null,
  updated_at: null,
  ...overrides,
})

const createApi = (): XCredentialApi => ({
  fetchXCredentials: vi.fn(async () => [credential()]),
  saveXCredential: vi.fn(async (form: XCredentialForm) => credential({
    id: form.id ?? 9,
    display_name: form.display_name,
    note: form.note,
    enabled: form.enabled,
    sort_order: form.sort_order,
  })),
  deleteXCredential: vi.fn(async () => ({ message: 'Deleted in test', deleted: true })),
  testXCredential: vi.fn(async () => ({
    status: 'succeeded',
    message: 'Test passed in test',
    credential: credential({ last_test_status: 'succeeded' }),
  })),
})

const translate = (key: string, params?: Record<string, unknown>) => (
  params ? `${key}:${JSON.stringify(params)}` : key
)

describe('useXCredentialController', () => {
  it('loads credentials and surfaces axios detail on failure', async () => {
    const api = createApi()
    const controller = useXCredentialController({ api, translate })
    await controller.loadCredentials()
    expect(controller.credentials.value).toHaveLength(1)
    expect(controller.loading.value).toBe(false)

    api.fetchXCredentials = vi.fn(async () => {
      throw { isAxiosError: true, response: { data: { detail: 'X credential unavailable' } } }
    })
    await controller.loadCredentials()
    expect(controller.errorMsg.value).toBe('X credential unavailable')

    api.fetchXCredentials = vi.fn(async () => {
      throw new Error('network down')
    })
    await controller.loadCredentials()
    expect(controller.errorMsg.value).toBe('network down')
  })

  it('requires both write-only cookie values before creating a credential', async () => {
    const api = createApi()
    const controller = useXCredentialController({ api, translate })

    await controller.saveCredential()
    expect(api.saveXCredential).not.toHaveBeenCalled()
    expect(controller.errorMsg.value).toBe('monitor.xCredentials.authTokenRequired')

    controller.form.value.auth_token = 'test-auth-token'
    await controller.saveCredential()
    expect(api.saveXCredential).not.toHaveBeenCalled()
    expect(controller.errorMsg.value).toBe('monitor.xCredentials.ct0Required')
  })

  it('does not copy masked values into the edit form', () => {
    const controller = useXCredentialController({ translate })
    controller.editCredential(credential())

    expect(controller.form.value).toMatchObject({
      id: 1,
      display_name: 'Primary X',
      auth_token: '',
      ct0: '',
    })
  })

  it('trims fake cookie values, upserts the credential, notices, and resets the form', async () => {
    const api = createApi()
    const controller = useXCredentialController({ api, translate })
    controller.form.value = {
      id: null,
      display_name: ' Primary X ',
      note: ' production account ',
      enabled: true,
      sort_order: 2,
      auth_token: ' test-auth-token ',
      ct0: ' test-ct0 ',
    }

    await controller.saveCredential()

    expect(api.saveXCredential).toHaveBeenCalledWith(expect.objectContaining({
      display_name: 'Primary X',
      note: 'production account',
      auth_token: 'test-auth-token',
      ct0: 'test-ct0',
    }))
    expect(firstCredential(controller)).toMatchObject({ id: 9, display_name: 'Primary X', sort_order: 2 })
    expect(controller.noticeMsg.value).toBe('monitor.xCredentials.saved')
    expect(controller.form.value.id).toBeNull()
    expect(controller.form.value.auth_token).toBe('')
    expect(controller.form.value.ct0).toBe('')
  })

  it('toggles enabled without sending masked or retained secret values', async () => {
    const api = createApi()
    const controller = useXCredentialController({ api, translate })
    await controller.loadCredentials()
    await controller.toggleCredential(firstCredential(controller))

    expect(api.saveXCredential).toHaveBeenCalledWith(expect.objectContaining({
      id: 1,
      enabled: false,
      auth_token: '',
      ct0: '',
    }))
    expect(firstCredential(controller).enabled).toBe(false)
  })

  it('honors confirmation cancellation and removes the credential on confirm', async () => {
    const api = createApi()
    const confirm = vi.fn(() => false)
    const controller = useXCredentialController({ api, translate, confirm })
    await controller.loadCredentials()

    await controller.removeCredential(firstCredential(controller))
    expect(confirm).toHaveBeenCalledWith('monitor.xCredentials.deleteConfirm:{"name":"Primary X"}')
    expect(api.deleteXCredential).not.toHaveBeenCalled()
    expect(controller.credentials.value).toHaveLength(1)

    confirm.mockReturnValue(true)
    controller.editCredential(firstCredential(controller))
    await controller.removeCredential(firstCredential(controller))
    expect(api.deleteXCredential).toHaveBeenCalledWith(1)
    expect(controller.credentials.value).toHaveLength(0)
    expect(controller.form.value.id).toBeNull()
    expect(controller.noticeMsg.value).toBe('Deleted in test')
  })

  it('replaces the credential with the test result and handles failures', async () => {
    const api = createApi()
    const controller = useXCredentialController({ api, translate })
    await controller.loadCredentials()
    await controller.testCredential(firstCredential(controller))

    expect(api.testXCredential).toHaveBeenCalledWith(1)
    expect(firstCredential(controller).last_test_status).toBe('succeeded')
    expect(controller.noticeMsg.value).toBe('Test passed in test')

    api.testXCredential = vi.fn(async () => { throw new Error('test failed') })
    await controller.testCredential(firstCredential(controller))
    expect(controller.errorMsg.value).toBe('test failed')
    expect(controller.testingId.value).toBeNull()
  })

  it('ignores late completions after dispose', async () => {
    const api = createApi()
    let resolveSave: ((value: XCredential) => void) | undefined
    api.saveXCredential = vi.fn(() => new Promise<XCredential>((resolve) => { resolveSave = resolve }))
    const controller = useXCredentialController({ api, translate })
    controller.form.value = {
      ...controller.form.value,
      auth_token: 'test-auth-token',
      ct0: 'test-ct0',
    }

    const pending = controller.saveCredential()
    controller.dispose()
    resolveSave?.(credential({ id: 5 }))
    await pending

    expect(controller.noticeMsg.value).toBe('')
    expect(controller.credentials.value).toHaveLength(0)
  })
})
