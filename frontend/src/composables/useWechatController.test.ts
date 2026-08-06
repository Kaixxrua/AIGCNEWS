import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { WeChatApi } from '@/services/wechat/wechatApi'
import { useWechatController } from './useWechatController'

const createApi = (): WeChatApi => ({
  createLoginSession: vi.fn(),
  fetchQrCodeUrl: vi.fn((id: string) => `/api/ops/wechat/login-sessions/${encodeURIComponent(id)}/qrcode`),
  fetchQrCodeBlob: vi.fn(),
  fetchLoginStatus: vi.fn(),
  completeLogin: vi.fn(),
  cancelLogin: vi.fn(),
  fetchSession: vi.fn(),
  searchAccounts: vi.fn(),
  fetchAccounts: vi.fn(),
  saveAccount: vi.fn(),
  fetchArticles: vi.fn(),
  submitSync: vi.fn(),
})

describe('useWechatController', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  it('loads session and accounts on refresh', async () => {
    const api = createApi()
    vi.mocked(api.fetchSession).mockResolvedValue({
      connected: true,
      status: 'active',
      account_name: 'Admin',
      account_avatar_url: '',
      last_validated_at: null,
      last_used_at: null,
      expires_at: null,
      invalid_reason_code: null,
    })
    vi.mocked(api.fetchAccounts).mockResolvedValue([
      {
        id: 1,
        fakeid: 'fakeid-1',
        nickname: 'OpenAI',
        alias: '',
        avatar_url: '',
        signature: '',
        enabled: true,
        sort_order: 0,
        last_sync_status: 'idle',
        last_sync_message: '',
        last_sync_at: null,
        created_at: null,
        updated_at: null,
      },
    ])

    const controller = useWechatController({ api })
    await controller.refreshSession()
    await controller.loadAccounts()

    expect(controller.hasSession.value).toBe(true)
    expect(controller.accounts.value).toHaveLength(1)
    expect(controller.accounts.value[0]?.nickname).toBe('OpenAI')
  })

  it('starts login, creates object URL, polls status, and completes', async () => {
    const api = createApi()
    const revokeSpy = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    const createSpy = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob://qr')

    vi.mocked(api.createLoginSession).mockResolvedValue({
      attempt_id: 'attempt-1',
      status: 'waiting_scan',
      expires_at: '2026-08-05T12:00:00+00:00',
      error_code: null,
    })
    vi.mocked(api.fetchQrCodeBlob).mockResolvedValue(new Blob(['qr'], { type: 'image/png' }))
    vi.mocked(api.fetchLoginStatus)
      .mockResolvedValueOnce({
        attempt_id: 'attempt-1',
        status: 'scanned_waiting_confirmation',
        expires_at: '2026-08-05T12:00:00+00:00',
        error_code: null,
      })
      .mockResolvedValueOnce({
        attempt_id: 'attempt-1',
        status: 'confirmed',
        expires_at: '2026-08-05T12:00:00+00:00',
        error_code: null,
      })
    vi.mocked(api.completeLogin).mockResolvedValue({
      connected: true,
      status: 'active',
      account_name: 'Admin',
      account_avatar_url: '',
      last_validated_at: null,
      last_used_at: null,
      expires_at: null,
      invalid_reason_code: null,
    })
    vi.mocked(api.fetchAccounts).mockResolvedValue([])

    const controller = useWechatController({ api, pollIntervalMs: 500 })
    await controller.openLoginDialog()

    expect(controller.isLoginDialogOpen.value).toBe(true)
    expect(controller.qrCodeUrl.value).toBe('blob://qr')
    expect(api.createLoginSession).toHaveBeenCalledOnce()
    expect(controller.loginAttempt.value?.status).toBe('scanned_waiting_confirmation')

    await vi.advanceTimersByTimeAsync(500)
    expect(controller.loginAttempt.value?.status).toBe('confirmed')

    await controller.confirmLogin()
    expect(api.completeLogin).toHaveBeenCalledWith('attempt-1')
    expect(controller.hasSession.value).toBe(true)
    expect(controller.isLoginDialogOpen.value).toBe(false)
    expect(revokeSpy).toHaveBeenCalled()

    revokeSpy.mockRestore()
    createSpy.mockRestore()
  })

  it('stops polling and revokes object URL when dialog closes', async () => {
    const api = createApi()
    vi.mocked(api.createLoginSession).mockResolvedValue({
      attempt_id: 'attempt-2',
      status: 'waiting_scan',
      expires_at: '2026-08-05T12:00:00+00:00',
      error_code: null,
    })
    vi.mocked(api.fetchQrCodeBlob).mockResolvedValue(new Blob(['qr'], { type: 'image/png' }))
    vi.mocked(api.fetchLoginStatus).mockResolvedValue({
      attempt_id: 'attempt-2',
      status: 'waiting_scan',
      expires_at: '2026-08-05T12:00:00+00:00',
      error_code: null,
    })
    vi.mocked(api.cancelLogin).mockResolvedValue({ status: 'cancelled', attempt_id: 'attempt-2' })

    const revokeSpy = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob://qr')

    const controller = useWechatController({ api, pollIntervalMs: 500 })
    await controller.openLoginDialog()
    expect(controller.isPolling.value).toBe(true)

    controller.closeLoginDialog()
    expect(controller.isPolling.value).toBe(false)
    expect(controller.qrCodeUrl.value).toBe('')
    expect(api.cancelLogin).toHaveBeenCalledWith('attempt-2')

    revokeSpy.mockRestore()
  })

  it('searches accounts and saves selected account', async () => {
    const api = createApi()
    const account = {
      id: null,
      fakeid: 'fakeid-search',
      nickname: 'SearchResult',
      alias: '',
      avatar_url: '',
      signature: 'sig',
      enabled: true,
      sort_order: 0,
      last_sync_status: 'idle',
      last_sync_message: '',
      last_sync_at: null,
      created_at: null,
      updated_at: null,
    }
    const saved = { ...account, id: 7 }
    vi.mocked(api.searchAccounts).mockResolvedValue({ items: [account], total: 1, begin: 0, size: 5 })
    vi.mocked(api.saveAccount).mockResolvedValue(saved)

    const controller = useWechatController({ api })
    await controller.searchAccounts('AI')
    expect(api.searchAccounts).toHaveBeenCalledWith('AI', 0, 5)
    expect(controller.searchResults.value).toHaveLength(1)

    await controller.saveAccount(account)
    expect(api.saveAccount).toHaveBeenCalledWith({
      fakeid: 'fakeid-search',
      nickname: 'SearchResult',
      alias: '',
      avatar_url: '',
      signature: 'sig',
      enabled: true,
      sort_order: 0,
    })
    expect(controller.accounts.value).toHaveLength(1)
    expect(controller.selectedAccount.value?.id).toBe(7)
  })

  it('submits sync for selected account', async () => {
    const api = createApi()
    vi.mocked(api.submitSync).mockResolvedValue({ status: 'submitted', account_id: 3, message: 'ok' })

    const controller = useWechatController({ api })
    controller.selectedAccount.value = {
      id: 3,
      fakeid: 'fakeid-3',
      nickname: 'Account',
      alias: '',
      avatar_url: '',
      signature: '',
      enabled: true,
      sort_order: 0,
      last_sync_status: 'idle',
      last_sync_message: '',
      last_sync_at: null,
      created_at: null,
      updated_at: null,
    }
    await controller.submitSync()
    expect(api.submitSync).toHaveBeenCalledWith(3)
    expect(controller.notice.value).toContain('已提交')
  })

  it('surfaces FastAPI detail.message from 409 responses', async () => {
    const api = createApi()
    vi.mocked(api.searchAccounts).mockRejectedValue({
      response: {
        data: {
          detail: {
            code: 'WECHAT_ACCOUNT_CONTEXT_INVALID',
            message: '当前微信账号无法使用该功能，请使用公众号/服务号管理员账号重新扫码',
          },
        },
      },
      message: 'Request failed with status code 409',
    })

    const controller = useWechatController({ api })
    await controller.searchAccounts('AI')
    expect(controller.error.value).toBe('当前微信账号无法使用该功能，请使用公众号/服务号管理员账号重新扫码')
  })

  it('disposes resources on unmount', async () => {
    const api = createApi()
    vi.mocked(api.createLoginSession).mockResolvedValue({
      attempt_id: 'attempt-3',
      status: 'waiting_scan',
      expires_at: '2026-08-05T12:00:00+00:00',
      error_code: null,
    })
    vi.mocked(api.fetchQrCodeBlob).mockResolvedValue(new Blob(['qr'], { type: 'image/png' }))
    vi.mocked(api.fetchLoginStatus).mockResolvedValue({
      attempt_id: 'attempt-3',
      status: 'waiting_scan',
      expires_at: '2026-08-05T12:00:00+00:00',
      error_code: null,
    })
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob://qr')
    const revokeSpy = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})

    const controller = useWechatController({ api, pollIntervalMs: 500 })
    await controller.openLoginDialog()
    controller.dispose()

    expect(controller.isActive.value).toBe(false)
    expect(controller.isPolling.value).toBe(false)
    expect(controller.qrCodeUrl.value).toBe('')
    expect(revokeSpy).toHaveBeenCalled()

    revokeSpy.mockRestore()
  })
})
