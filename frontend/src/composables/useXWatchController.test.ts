import { describe, expect, it, vi } from 'vitest'
import { useXWatchController, type XWatchApi, type XWatchController } from './useXWatchController'
import type { XWatchAccount, XWatchAccountForm } from '@/features/monitor/monitorModel'

// noUncheckedIndexedAccess 下数组下标返回 T | undefined，测试里统一断言非空
const firstAccount = (controller: XWatchController) => {
  const item = controller.accounts.value[0]
  if (!item) throw new Error('expected at least one account')
  return item
}

const account = (overrides: Partial<XWatchAccount> = {}): XWatchAccount => ({
  id: 1,
  screen_name: 'openai',
  display_name: 'OpenAI',
  note: '',
  enabled: true,
  sort_order: 0,
  last_test_status: 'unknown',
  last_test_message: '',
  last_test_at: null,
  created_at: null,
  updated_at: null,
  ...overrides,
})

const createApi = (): XWatchApi => ({
  fetchXWatchAccounts: vi.fn(async () => [account()]),
  saveXWatchAccount: vi.fn(async (form: XWatchAccountForm) => account({
    id: form.id ?? 9,
    screen_name: form.screen_name,
    display_name: form.display_name,
    note: form.note,
    enabled: form.enabled,
    sort_order: form.sort_order,
  })),
  deleteXWatchAccount: vi.fn(async () => ({ message: '已删除', deleted: true })),
  testXWatchAccount: vi.fn(async () => ({
    status: 'success',
    message: '拉取成功',
    account: account({ last_test_status: 'success' }),
  })),
})

const translate = (key: string, params?: Record<string, unknown>) => (
  params ? `${key}:${JSON.stringify(params)}` : key
)

describe('useXWatchController', () => {
  it('loads accounts and surfaces axios detail on failure', async () => {
    const api = createApi()
    const controller = useXWatchController({ api, translate })
    await controller.loadAccounts()
    expect(controller.accounts.value).toHaveLength(1)
    expect(controller.loading.value).toBe(false)

    api.fetchXWatchAccounts = vi.fn(async () => {
      // axios.isAxiosError 只检查 payload.isAxiosError === true
      throw { isAxiosError: true, response: { data: { detail: 'X 凭据未配置' } } }
    })
    await controller.loadAccounts()
    expect(controller.errorMsg.value).toBe('X 凭据未配置')

    api.fetchXWatchAccounts = vi.fn(async () => {
      throw new Error('network down')
    })
    await controller.loadAccounts()
    expect(controller.errorMsg.value).toBe('network down')
  })

  it('requires a handle before saving', async () => {
    const api = createApi()
    const controller = useXWatchController({ api, translate })
    await controller.saveAccount()
    expect(api.saveXWatchAccount).not.toHaveBeenCalled()
    expect(controller.errorMsg.value).toBe('monitor.xWatch.handleRequired')
  })

  it('strips @, upserts the saved account, notices, and resets the form', async () => {
    const api = createApi()
    const controller = useXWatchController({ api, translate })
    controller.form.value = {
      id: null, screen_name: ' @AnthropicAI ', display_name: 'Anthropic', note: '', enabled: true, sort_order: 2,
    }
    await controller.saveAccount()
    expect(api.saveXWatchAccount).toHaveBeenCalledWith(expect.objectContaining({ screen_name: 'AnthropicAI' }))
    expect(firstAccount(controller)).toMatchObject({ id: 9, screen_name: 'AnthropicAI', sort_order: 2 })
    expect(controller.noticeMsg.value).toBe('monitor.xWatch.saved')
    expect(controller.form.value.id).toBeNull()
    expect(controller.form.value.screen_name).toBe('')
  })

  it('toggles enabled and replaces the account in place', async () => {
    const api = createApi()
    const controller = useXWatchController({ api, translate })
    await controller.loadAccounts()
    await controller.toggleAccount(firstAccount(controller))
    expect(api.saveXWatchAccount).toHaveBeenCalledWith(expect.objectContaining({ id: 1, enabled: false }))
    expect(firstAccount(controller).enabled).toBe(false)
    expect(controller.accounts.value).toHaveLength(1)
  })

  it('honors confirm cancellation and removes the account on confirm', async () => {
    const api = createApi()
    const confirm = vi.fn(() => false)
    const controller = useXWatchController({ api, translate, confirm })
    await controller.loadAccounts()

    await controller.removeAccount(firstAccount(controller))
    expect(confirm).toHaveBeenCalledWith('monitor.xWatch.deleteConfirm:{"name":"openai"}')
    expect(api.deleteXWatchAccount).not.toHaveBeenCalled()
    expect(controller.accounts.value).toHaveLength(1)

    confirm.mockReturnValue(true)
    controller.editAccount(firstAccount(controller))
    await controller.removeAccount(firstAccount(controller))
    expect(api.deleteXWatchAccount).toHaveBeenCalledWith(1)
    expect(controller.accounts.value).toHaveLength(0)
    expect(controller.form.value.id).toBeNull()
    expect(controller.noticeMsg.value).toBe('已删除')
  })

  it('replaces the account with the test result and notices the backend message', async () => {
    const api = createApi()
    const controller = useXWatchController({ api, translate })
    await controller.loadAccounts()
    await controller.testAccount(firstAccount(controller))
    expect(api.testXWatchAccount).toHaveBeenCalledWith(1)
    expect(firstAccount(controller).last_test_status).toBe('success')
    expect(controller.noticeMsg.value).toBe('拉取成功')

    api.testXWatchAccount = vi.fn(async () => { throw new Error('boom') })
    await controller.testAccount(firstAccount(controller))
    expect(controller.errorMsg.value).toBe('boom')
    expect(controller.testingId.value).toBeNull()
  })

  it('ignores late completions after dispose', async () => {
    const api = createApi()
    let resolveSave: ((value: XWatchAccount) => void) | undefined
    api.saveXWatchAccount = vi.fn(() => new Promise<XWatchAccount>((resolve) => { resolveSave = resolve }))
    const controller = useXWatchController({ api, translate })
    controller.form.value = { ...controller.form.value, screen_name: 'openai' }
    const pending = controller.saveAccount()
    controller.dispose()
    resolveSave?.(account({ id: 5 }))
    await pending
    expect(controller.noticeMsg.value).toBe('')
    expect(controller.accounts.value).toHaveLength(0)
  })
})
