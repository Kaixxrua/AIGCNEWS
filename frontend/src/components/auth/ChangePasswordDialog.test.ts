import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ChangePasswordDialog from './ChangePasswordDialog.vue'

const api = vi.hoisted(() => ({
  changePassword: vi.fn(),
  sendChangePasswordOtp: vi.fn(),
}))
const store = vi.hoisted(() => ({ replaceToken: vi.fn(), fetchMe: vi.fn() }))
vi.mock('@/services/auth/authApi', () => api)
vi.mock('@/stores/authStore', () => ({ useAuthStore: () => store }))
vi.mock('@/composables/useDockSuppression', () => ({ useDockSuppression: vi.fn() }))

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': {
  common: { close: '关闭', cancel: '取消' },
  auth: {
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
})

describe('ChangePasswordDialog', () => {
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
