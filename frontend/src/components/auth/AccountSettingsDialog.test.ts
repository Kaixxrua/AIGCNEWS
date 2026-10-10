import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AccountSettingsDialog from './AccountSettingsDialog.vue'

const updateProfile = vi.hoisted(() => vi.fn())
const sendEmailChangeCurrentOtp = vi.hoisted(() => vi.fn())
const sendEmailChangeNewOtp = vi.hoisted(() => vi.fn())
const confirmEmailChange = vi.hoisted(() => vi.fn())
const startOAuthBind = vi.hoisted(() => vi.fn())
const flags = vi.hoisted(() => ({ oauthProviders: ['github', 'google', 'wechat'] }))
vi.mock('@/composables/useFeatureFlags', () => ({
  useFeatureFlags: () => ({ featureFlags: { value: flags } }),
  ensureFeatureFlags: vi.fn(async () => flags),
}))
const authStore = vi.hoisted(() => ({
  user: null as unknown as {
    user_id: number
    email: string | null
    username: string
    username_change_available_at?: string | null
    role: string
    email_verified: boolean
    membership_tier: string
    membership_expires_at: string | null
    created_at: string
    password_login_enabled: boolean
    oauth_identities: { provider: string; display_email?: string | null; email_verified?: boolean }[]
  },
  replaceToken: vi.fn(),
  fetchMe: vi.fn(),
}))

vi.mock('@/services/auth/authApi', () => ({
  updateProfile,
  sendEmailChangeCurrentOtp,
  sendEmailChangeNewOtp,
  confirmEmailChange,
  startOAuthBind,
}))
vi.mock('@/stores/authStore', () => ({ useAuthStore: () => authStore }))
vi.mock('vue-router', () => ({ useRoute: () => ({ fullPath: '/projects?source=all' }) }))
vi.mock('@/composables/useDockSuppression', () => ({ useDockSuppression: vi.fn() }))
vi.mock('@/components/auth/ChangePasswordDialog.vue', () => ({
  default: { props: ['modelValue', 'setupPassword'], emits: ['update:modelValue'], template: '<div v-if="modelValue" data-testid="password-dialog" :data-setup="setupPassword" />' },
}))

const messages = {
  common: { close: '关闭', cancel: '取消' },
  auth: {
    setupPasswordAction: '设置密码',
    changeUsernameAction: '改名', usernameChangeHint: '用户名每 3 天可修改一次。', usernameNextChange: '下次可修改时间：{time}。',
    accountSettings: '账户设置', accountOverview: '账户信息', accountOverviewDescription: '查看当前账户资料，并管理登录方式。',
    username: '用户名', email: '邮箱', emailVerified: '邮箱验证', registeredAt: '注册时间', role: '角色', membership: '会员状态', memberMembership: 'VIP 会员', freeMembership: '普通用户',
    verified: '已验证', unverified: '未验证', notAvailable: '暂无', notSet: '未设置', editUsername: '修改用户名', saveUsername: '保存用户名', savingUsername: '保存中…',
    usernameRequired: '请输入用户名。', usernameTooLong: '用户名不能超过 64 个字符。', usernameSaved: '用户名已更新。', usernameSaveFailed: '用户名更新失败，请稍后重试。',
    connectedLoginMethods: '已连接的快捷登录', connected: '已连接', notConnected: '未连接',
    oauthBindFailed: '渠道绑定失败，请重试',
    passwordLogin: '密码登录', passwordEnabled: '已启用', passwordDisabled: '未启用', changePasswordAction: '修改密码', closeAccountSettings: '关闭账户设置',
    changeEmailAction: '换绑', emailChangeTitle: '换绑邮箱', emailChangeHint: '验证码 5 分钟内有效，需同时验证当前邮箱与新邮箱。',
    newEmailLabel: '新邮箱', newEmailPlaceholder: '输入新邮箱', currentEmailOtpLabel: '当前邮箱验证码', newEmailOtpLabel: '新邮箱验证码',
    emailChangeCurrentOtpSent: '验证码已发送至当前邮箱', emailChangeNewOtpSent: '验证码已发送至新邮箱',
    emailChangeSubmit: '确认换绑', emailChanging: '换绑中…', emailChangeSuccess: '邮箱已换绑', emailChangeFailed: '邮箱换绑失败，请稍后重试',
    getOtp: '获取验证码', resendOtp: '重新获取({countdown}s)', otpPlaceholder: '6 位数字验证码',
    invalidEmail: '请输入正确格式的邮箱地址', invalidOtp: '验证码应为 6 位数字', rateLimited: '请 60 秒后再试', sendOtpFailed: '发送验证码失败，请稍后再试',
  },
}
const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })

const mountDialog = (modelValue = true) => mount(AccountSettingsDialog, {
  attachTo: document.body,
  props: { modelValue },
  global: { plugins: [i18n] },
})

const baseUser = () => ({
  user_id: 7,
  email: 'reader@example.com',
  username: 'Reader',
  role: 'user' as const,
  email_verified: true,
  membership_tier: 'member' as const,
  membership_expires_at: null,
  created_at: '2026-01-02T03:04:05Z',
  password_login_enabled: true,
  oauth_identities: [{ provider: 'github', display_email: 'reader@example.com', email_verified: true }],
})

const findButton = (text: string) =>
  [...document.body.querySelectorAll('button')].find(button => button.textContent?.includes(text)) as HTMLButtonElement | undefined

const openEmailChange = async () => {
  findButton('换绑')?.click()
  await nextTick()
}

beforeEach(() => {
  updateProfile.mockReset().mockResolvedValue({ ...baseUser(), username: 'New name' })
  sendEmailChangeCurrentOtp.mockReset().mockResolvedValue({ detail: 'sent' })
  sendEmailChangeNewOtp.mockReset().mockResolvedValue({ detail: 'sent' })
  confirmEmailChange.mockReset().mockResolvedValue({ ...baseUser(), email: 'newbox@example.com' })
  startOAuthBind.mockReset().mockResolvedValue(undefined)
  authStore.user = baseUser()
  flags.oauthProviders = ['github', 'google', 'wechat']
  document.body.innerHTML = ''
})

describe('AccountSettingsDialog', () => {
  it('renders the current account projection including registration date and login states', () => {
    const wrapper = mountDialog()
    const dialog = document.body.querySelector('[role="dialog"]') as HTMLElement
    expect(dialog.getAttribute('aria-modal')).toBe('true')
    expect(dialog.getAttribute('aria-labelledby')).toBe('account-settings-dialog-title')
    expect(dialog.textContent).toContain('reader@example.com')
    expect(dialog.textContent).toContain(new Intl.DateTimeFormat('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit',
    }).format(new Date(baseUser().created_at)))
    expect(dialog.textContent).toContain('邮箱验证')
    expect(dialog.textContent).toContain('已验证')
    expect(dialog.textContent).toContain('密码登录')
    wrapper.unmount()
  })

  it('renders each provider as a real one-row button with icon, name and status together', () => {
    const wrapper = mountDialog()
    const providerGrid = document.body.querySelector('.grid.grid-cols-3') as HTMLElement
    expect(providerGrid).toBeTruthy()
    const buttons = providerGrid.querySelectorAll<HTMLButtonElement>(':scope > button')
    expect(buttons).toHaveLength(3)
    expect(providerGrid.querySelectorAll('svg')).toHaveLength(3)

    const github = buttons[0] as HTMLButtonElement
    // 图标、渠道名、状态在同一行（单个 flex 行容器内）
    const row = github.querySelector(':scope > span.flex') as HTMLElement
    expect(row).toBeTruthy()
    expect(row.textContent).toContain('GitHub')
    expect(row.textContent).toContain('已连接')
    expect(github.disabled).toBe(true)

    const google = buttons[1] as HTMLButtonElement
    expect(google.textContent).toContain('Google')
    expect(google.textContent).toContain('未连接')
    expect(google.disabled).toBe(false)

    const wechat = buttons[2] as HTMLButtonElement
    expect(wechat.textContent).toContain('微信')
    expect(wechat.textContent).toContain('未连接')
    expect(wechat.disabled).toBe(false)
    wrapper.unmount()
  })

  it('starts an authenticated bind flow for unconnected providers and never for connected ones', async () => {
    const wrapper = mountDialog()
    const providerGrid = document.body.querySelector('.grid.grid-cols-3') as HTMLElement
    const buttons = providerGrid.querySelectorAll<HTMLButtonElement>(':scope > button')

    ;(buttons[0] as HTMLButtonElement).click()
    ;(buttons[1] as HTMLButtonElement).click()
    await nextTick()

    expect(startOAuthBind).toHaveBeenCalledTimes(1)
    expect(startOAuthBind).toHaveBeenCalledWith('google', '/projects?source=all')
    wrapper.unmount()
  })

  it('only offers configured providers and retains already linked identities', async () => {
    flags.oauthProviders = ['qq', 'linuxdo']
    const wrapper = mountDialog()
    const buttons = [...document.body.querySelectorAll<HTMLButtonElement>('.oauth-provider-btn')]
    expect(buttons.map(button => button.textContent)).toEqual([
      expect.stringContaining('GitHub'), expect.stringContaining('QQ'), expect.stringContaining('Linux DO'),
    ])
    buttons[1]!.click()
    await flushPromises()
    expect(startOAuthBind).toHaveBeenCalledWith('qq', '/projects?source=all')
    buttons[2]!.click()
    await nextTick()
    expect(startOAuthBind).toHaveBeenCalledWith('linuxdo', '/projects?source=all')
    wrapper.unmount()
  })

  it('prevents duplicate binding requests and lets the user retry after a failure', async () => {
    flags.oauthProviders = ['qq', 'linuxdo']
    let rejectStart!: (reason: unknown) => void
    startOAuthBind.mockImplementationOnce(() => new Promise((_, reject) => { rejectStart = reject }))
    const wrapper = mountDialog()
    const linuxdo = findButton('Linux DO')!

    linuxdo.click()
    linuxdo.click()
    await nextTick()
    expect(startOAuthBind).toHaveBeenCalledTimes(1)
    expect(linuxdo.disabled).toBe(true)
    expect(findButton('QQ')!.disabled).toBe(true)

    rejectStart({})
    await flushPromises()
    expect(document.body.textContent).toContain('渠道绑定失败，请重试')
    expect(linuxdo.disabled).toBe(false)

    linuxdo.click()
    await flushPromises()
    expect(startOAuthBind).toHaveBeenCalledTimes(2)
    expect(document.body.textContent).not.toContain('渠道绑定失败，请重试')
    wrapper.unmount()
  })

  it('hides unconfigured QQ and Linux DO binding entries', () => {
    flags.oauthProviders = []
    const wrapper = mountDialog()
    const buttons = document.body.querySelectorAll<HTMLButtonElement>('.oauth-provider-btn')
    expect(buttons).toHaveLength(1)
    expect(buttons[0]!.textContent).toContain('GitHub')
    expect(buttons[0]!.disabled).toBe(true)
    wrapper.unmount()
  })

  it('shows the email rebind entry only for accounts with an email and toggles the form', async () => {
    const wrapper = mountDialog()
    expect(findButton('换绑')).toBeTruthy()

    await openEmailChange()
    expect(document.body.querySelector('#account-settings-new-email')).toBeTruthy()
    expect(document.body.textContent).toContain('换绑邮箱')

    findButton('取消')?.click()
    await nextTick()
    expect(document.body.querySelector('#account-settings-new-email')).toBeFalsy()
    wrapper.unmount()
  })

  it('hides the email rebind entry for OAuth-only accounts without an email', () => {
    authStore.user = { ...baseUser(), email: null }
    const wrapper = mountDialog()
    expect(findButton('换绑')).toBeUndefined()
    wrapper.unmount()
  })

  it('sends the new-email code after validating the address, then enforces the countdown', async () => {
    const wrapper = mountDialog()
    await openEmailChange()
    const newEmailInput = document.body.querySelector('#account-settings-new-email') as HTMLInputElement
    const sendNewButton = newEmailInput.parentElement?.querySelector('button') as HTMLButtonElement

    newEmailInput.value = 'not-an-email'
    newEmailInput.dispatchEvent(new Event('input', { bubbles: true }))
    await nextTick()
    // 邮箱格式无效时发码按钮保持禁用，不会发起请求
    expect(sendNewButton.disabled).toBe(true)
    sendNewButton.click()
    await flushPromises()
    expect(sendEmailChangeNewOtp).not.toHaveBeenCalled()

    newEmailInput.value = 'NewBox@Example.com'
    newEmailInput.dispatchEvent(new Event('input', { bubbles: true }))
    await nextTick()
    sendNewButton.click()
    await flushPromises()

    expect(sendEmailChangeNewOtp).toHaveBeenCalledWith('NewBox@Example.com')
    expect(document.body.textContent).toContain('验证码已发送至新邮箱')
    expect(sendNewButton.disabled).toBe(true)
    expect(sendNewButton.textContent).toContain('重新获取')
    wrapper.unmount()
  })

  it('sends the current-email code without any address input', async () => {
    const wrapper = mountDialog()
    await openEmailChange()
    const currentCodeInput = document.body.querySelector('#account-settings-current-code') as HTMLInputElement
    const sendCurrentButton = currentCodeInput.parentElement?.querySelector('button') as HTMLButtonElement
    sendCurrentButton.click()
    await flushPromises()

    expect(sendEmailChangeCurrentOtp).toHaveBeenCalledTimes(1)
    expect(document.body.textContent).toContain('验证码已发送至当前邮箱')
    expect(sendCurrentButton.disabled).toBe(true)
    wrapper.unmount()
  })

  it('confirms the rebind with both codes and installs the authoritative projection', async () => {
    const wrapper = mountDialog()
    await openEmailChange()
    const setInput = (selector: string, value: string) => {
      const input = document.body.querySelector(selector) as HTMLInputElement
      input.value = value
      input.dispatchEvent(new Event('input', { bubbles: true }))
    }
    setInput('#account-settings-new-email', 'newbox@example.com')
    setInput('#account-settings-current-code', '111111')
    setInput('#account-settings-new-code', '222222')
    await nextTick()
    findButton('确认换绑')?.click()
    await flushPromises()

    expect(confirmEmailChange).toHaveBeenCalledWith('newbox@example.com', '111111', '222222')
    expect(authStore.user.email).toBe('newbox@example.com')
    expect(document.body.textContent).toContain('邮箱已换绑')
    wrapper.unmount()
  })

  it('rejects malformed codes without calling confirm', async () => {
    const wrapper = mountDialog()
    await openEmailChange()
    const setInput = (selector: string, value: string) => {
      const input = document.body.querySelector(selector) as HTMLInputElement
      input.value = value
      input.dispatchEvent(new Event('input', { bubbles: true }))
    }
    setInput('#account-settings-new-email', 'newbox@example.com')
    setInput('#account-settings-current-code', '11111')
    setInput('#account-settings-new-code', '222222')
    await nextTick()
    findButton('确认换绑')?.click()
    await flushPromises()

    expect(confirmEmailChange).not.toHaveBeenCalled()
    expect(document.body.textContent).toContain('验证码应为 6 位数字')
    wrapper.unmount()
  })

  it('surfaces the neutral conflict detail from the backend', async () => {
    confirmEmailChange.mockRejectedValue({ response: { status: 409, data: { detail: '换绑失败，请更换邮箱后重试' } } })
    const wrapper = mountDialog()
    await openEmailChange()
    const setInput = (selector: string, value: string) => {
      const input = document.body.querySelector(selector) as HTMLInputElement
      input.value = value
      input.dispatchEvent(new Event('input', { bubbles: true }))
    }
    setInput('#account-settings-new-email', 'newbox@example.com')
    setInput('#account-settings-current-code', '111111')
    setInput('#account-settings-new-code', '222222')
    await nextTick()
    findButton('确认换绑')?.click()
    await flushPromises()

    expect(document.body.textContent).toContain('换绑失败，请更换邮箱后重试')
    expect(document.body.textContent).not.toContain('邮箱已换绑')
    wrapper.unmount()
  })

  it('offers first-password setup for OAuth accounts, including accounts without email', async () => {
    const wrapper = mountDialog()
    expect(findButton('修改密码')).toBeTruthy()
    wrapper.unmount()

    authStore.user = { ...baseUser(), email: null, password_login_enabled: false }
    const second = mountDialog()
    expect(findButton('修改密码')).toBeUndefined()
    expect(document.body.textContent).toContain('未启用')
    expect(document.body.textContent).not.toContain('暂不可用')
    findButton('设置密码')!.click()
    await nextTick()
    expect(document.body.querySelector('[data-testid="password-dialog"]')?.getAttribute('data-setup')).toBe('true')
    second.unmount()
  })

  it('trims and saves the username, then updates the authoritative store projection', async () => {
    const wrapper = mountDialog()
    await nextTick()
    const input = document.body.querySelector('#account-settings-username') as HTMLInputElement
    findButton('改名')!.click()
    expect(document.activeElement).toBe(input)
    expect(input.selectionStart).toBe(0)
    expect(input.selectionEnd).toBe('Reader'.length)
    input.value = '  New name  '
    input.dispatchEvent(new Event('input', { bubbles: true }))
    await nextTick()
    ;(document.body.querySelector('button.btn-primary') as HTMLButtonElement).click()
    await flushPromises()

    expect(updateProfile).toHaveBeenCalledWith('New name')
    expect(authStore.user.username).toBe('New name')
    expect(document.body.textContent).toContain('用户名已更新。')
    wrapper.unmount()
  })

  it('rejects blank usernames without issuing a mutation', async () => {
    const wrapper = mountDialog()
    const input = document.body.querySelector('#account-settings-username') as HTMLInputElement
    input.value = '   '
    input.dispatchEvent(new Event('input', { bubbles: true }))
    await nextTick()
    ;(document.body.querySelector('button.btn-primary') as HTMLButtonElement).click()
    await nextTick()

    expect(updateProfile).not.toHaveBeenCalled()
    expect(document.body.textContent).toContain('请输入用户名。')
    wrapper.unmount()
  })

  it('shows the persisted cooldown and enables renaming when 72 hours have elapsed', async () => {
    vi.useFakeTimers()
    const start = new Date('2026-10-08T12:00:00Z')
    const available = new Date(start.getTime() + 72 * 60 * 60 * 1000)
    vi.setSystemTime(start)
    authStore.user.username_change_available_at = available.toISOString()
    const wrapper = mountDialog()
    try {
      const input = document.body.querySelector('#account-settings-username') as HTMLInputElement
      const save = findButton('保存用户名')!
      expect(input.readOnly).toBe(true)
      expect(save.disabled).toBe(true)
      expect(document.body.textContent).toContain('下次可修改时间：')
      save.click()
      expect(updateProfile).not.toHaveBeenCalled()
      vi.setSystemTime(available)
      await vi.advanceTimersByTimeAsync(1000)
      expect(input.readOnly).toBe(false)
      expect(save.disabled).toBe(false)
      expect(document.body.textContent).toContain('用户名每 3 天可修改一次。')
    } finally {
      wrapper.unmount()
      vi.useRealTimers()
    }
  })

  it('refreshes account details when another session has already renamed', async () => {
    updateProfile.mockRejectedValueOnce({ isAxiosError: true, response: { status: 429, data: { detail: '用户名每 3 天只能修改一次' } } })
    authStore.fetchMe.mockResolvedValueOnce(undefined)
    const wrapper = mountDialog()
    findButton('保存用户名')!.click()
    await flushPromises()
    expect(document.body.textContent).toContain('用户名每 3 天只能修改一次')
    expect(authStore.fetchMe).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('opens the password subflow without closing the account overview', async () => {
    const wrapper = mountDialog()
    findButton('修改密码')?.click()
    await nextTick()

    expect(document.body.querySelector('[data-testid="password-dialog"]')).toBeTruthy()
    expect(document.body.querySelector('[aria-labelledby="account-settings-dialog-title"]')).toBeTruthy()
    wrapper.unmount()
  })

  it('closes the email form on Escape first, then the dialog', async () => {
    const wrapper = mountDialog()
    await openEmailChange()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await nextTick()

    expect(document.body.querySelector('#account-settings-new-email')).toBeFalsy()
    expect(document.body.querySelector('[aria-labelledby="account-settings-dialog-title"]')).toBeTruthy()
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await nextTick()
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
    wrapper.unmount()
  })

  it('closes on Escape and restores focus to the opener', async () => {
    const opener = document.createElement('button')
    document.body.appendChild(opener)
    opener.focus()
    const wrapper = mountDialog()
    await nextTick()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await nextTick()

    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
    await wrapper.setProps({ modelValue: false })
    await nextTick()
    expect(document.activeElement).toBe(opener)
    wrapper.unmount()
  })
})
