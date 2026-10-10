import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ChangePasswordDialog from './ChangePasswordDialog.vue'

const api = vi.hoisted(() => ({
  changePassword: vi.fn(),
  sendChangePasswordOtp: vi.fn(),
  setupPassword: vi.fn(),
  sendPasswordSetupOtp: vi.fn(),
}))
const store = vi.hoisted(() => ({ user: { email: null as string | null }, replaceToken: vi.fn(), fetchMe: vi.fn() }))
vi.mock('@/services/auth/authApi', () => api)
vi.mock('@/stores/authStore', () => ({ useAuthStore: () => store }))
vi.mock('@/composables/useDockSuppression', () => ({ useDockSuppression: vi.fn() }))

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': {
  common: { close: '关闭', cancel: '取消' },
  auth: {
    setupPasswordAction: '设置密码', setupPasswordDescription: '验证邮箱后设置密码', setupPasswordSuccess: '密码已设置', setupPasswordOtpSent: '验证码已发送',
    email: '邮箱', emailPlaceholder: '输入邮箱', invalidEmail: '邮箱格式不正确',
    changeTitle: '修改密码', changeDescription: '说明', changeOtpLabel: '验证码', otpPlaceholder: '验证码',
    getOtp: '获取验证码', resendOtp: '重新发送 {countdown}', newPassword: '新密码', newPasswordPlaceholder: '新密码', confirmPassword: '确认密码',
    confirmPasswordPlaceholder: '确认密码', changeSubmit: '确认修改', changing: '修改中', changeOtpSent: '验证码已发送',
    changeSuccess: '修改成功', changeFailed: '修改失败', invalidOtp: '验证码错误', passwordMin: '密码太短',
    passwordMismatch: '密码不一致', rateLimited: '请求过于频繁', sendOtpFailed: '发送失败',
  },
} } })

beforeEach(() => {
  vi.clearAllMocks()
  api.sendChangePasswordOtp.mockResolvedValue({ detail: 'sent' })
  api.changePassword.mockResolvedValue({ access_token: 'replacement' })
  api.setupPassword.mockResolvedValue({ access_token: 'setup-token' })
  api.sendPasswordSetupOtp.mockResolvedValue({ detail: 'sent' })
  store.user.email = null
  document.body.innerHTML = ''
})

describe('ChangePasswordDialog', () => {
  const button = (text: string) => [...document.body.querySelectorAll('button')]
    .find(item => item.textContent?.trim() === text) as HTMLButtonElement
  const fill = async (selector: string, value: string) => {
    const input = document.body.querySelector(selector) as HTMLInputElement
    input.value = value
    input.dispatchEvent(new Event('input', { bubbles: true }))
    await flushPromises()
  }

  it('verifies an email, sets the first password and installs the token before refreshing the user', async () => {
    const wrapper = mount(ChangePasswordDialog, {
      attachTo: document.body, props: { modelValue: true, setupPassword: true }, global: { plugins: [i18n] },
    })
    expect(button('获取验证码').disabled).toBe(true)
    await fill('#password-setup-email', 'reader@example.com')
    button('获取验证码').click()
    await flushPromises()
    expect(api.sendPasswordSetupOtp).toHaveBeenCalledWith('reader@example.com')
    await fill('input[autocomplete="one-time-code"]', '123456')
    const passwords = document.body.querySelectorAll<HTMLInputElement>('input[type="password"]')
    for (const input of passwords) {
      input.value = 'new-secret123'
      input.dispatchEvent(new Event('input', { bubbles: true }))
    }
    await flushPromises()
    button('设置密码').click()
    await flushPromises()
    expect(api.setupPassword).toHaveBeenCalledWith('reader@example.com', '123456', 'new-secret123')
    expect(store.replaceToken).toHaveBeenCalledWith('setup-token')
    expect(store.replaceToken.mock.invocationCallOrder[0]).toBeLessThan(store.fetchMe.mock.invocationCallOrder[0]!)
    expect(document.body.textContent).toContain('密码已设置')
    expect(api.changePassword).not.toHaveBeenCalled()
    // The parent reflects the updated account, but the success view stays stable.
    await wrapper.setProps({ setupPassword: false })
    expect(document.body.querySelector('h3')?.textContent).toBe('设置密码')
    expect(button('设置密码').disabled).toBe(true)
    wrapper.unmount()
  })

  it('keeps an existing account email read-only and surfaces an email conflict', async () => {
    store.user.email = 'linked@example.com'
    api.setupPassword.mockRejectedValue({ response: { data: { detail: '该邮箱已有账号，请先登录原账号' } } })
    const wrapper = mount(ChangePasswordDialog, {
      attachTo: document.body, props: { modelValue: true, setupPassword: true }, global: { plugins: [i18n] },
    })
    const email = document.body.querySelector<HTMLInputElement>('#password-setup-email')!
    expect(email.value).toBe('linked@example.com')
    expect(email.readOnly).toBe(true)
    await fill('input[autocomplete="one-time-code"]', '123456')
    for (const input of document.body.querySelectorAll<HTMLInputElement>('input[type="password"]')) {
      input.value = 'new-secret123'
      input.dispatchEvent(new Event('input', { bubbles: true }))
    }
    await flushPromises()
    button('设置密码').click()
    await flushPromises()
    expect(document.body.textContent).toContain('该邮箱已有账号')
    expect(store.replaceToken).not.toHaveBeenCalled()
    expect(button('设置密码').disabled).toBe(false)
    wrapper.unmount()
  })

  it('cancels without calling password APIs', async () => {
    const wrapper = mount(ChangePasswordDialog, {
      attachTo: document.body,
      props: { modelValue: true },
      global: { plugins: [i18n] },
    })
    const cancel = [...document.body.querySelectorAll('button')].find(button => button.textContent?.includes('取消'))
    expect(cancel).toBeTruthy()
    await (cancel as HTMLButtonElement).click()
    await flushPromises()
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
    expect(api.sendChangePasswordOtp).not.toHaveBeenCalled()
    expect(api.changePassword).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
