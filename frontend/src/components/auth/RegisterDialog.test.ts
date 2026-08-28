import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RegisterDialog from './RegisterDialog.vue'

const apiPost = vi.hoisted(() => vi.fn())
const login = vi.hoisted(() => vi.fn())
vi.mock('@/services/http/apiClient', () => ({ api: { post: apiPost } }))
vi.mock('@/stores/authStore', () => ({ useAuthStore: () => ({ login }) }))

const messages = {
  common: { close: '关闭' },
  auth: {
    registerTitle: '注册', registerDescription: '创建账号', otp: '验证码', otpPlaceholder: '6 位验证码',
    username: '用户名', usernamePlaceholder: '设置一个用户名',
    password: '密码', confirmPassword: '确认密码', confirmPasswordPlaceholder: '再输一次',
    agreeAria: '同意协议', agreeTerms: '我已阅读', terms: '条款', and: '和', termsSuffix: '。',
    registering: '注册中', register: '注册', hasAccount: '已有账号', goLogin: '去登录',
    invalidEmailGeneric: '邮箱无效', invalidOtp: '验证码无效', invalidUsername: '用户名无效', passwordMin: '密码太短', passwordMismatch: '两次密码不一致', mustAgree: '请同意协议',
    registerSuccess: '注册成功', registerFailed: '注册失败', otpSent: '验证码已发送', sendOtpFailed: '发送失败', rateLimited: '太频繁',
    email: '邮箱', emailPlaceholder: '邮箱地址', sendOtp: '发送验证码', resendOtp: '重发',
  },
  footer: { privacy: '隐私' },
}
const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
const router = createRouter({ history: createMemoryHistory(), routes: [
  { path: '/', component: { template: '<div />' } },
  { path: '/disclaimer', component: { template: '<div />' } },
  { path: '/privacy', component: { template: '<div />' } },
] })

const mountDialog = (modelValue = true) => mount(RegisterDialog, {
  attachTo: document.body,
  props: { modelValue, redirect: '/dsh' },
  global: { plugins: [i18n, router] },
})

beforeEach(() => {
  apiPost.mockReset().mockResolvedValue({})
  login.mockReset().mockResolvedValue({})
  document.body.innerHTML = ''
})

describe('RegisterDialog', () => {
  it('renders as a modal card containing the whole register form and closes from ✕', async () => {
    const wrapper = mountDialog()
    const dialog = document.body.querySelector('[role="dialog"]') as HTMLElement
    expect(dialog.getAttribute('aria-modal')).toBe('true')
    const card = dialog.querySelector('.glass-card') as HTMLElement
    expect(card).toBeTruthy()
    // 整卡兜住：标题、邮箱/验证码/用户名/密码输入、协议勾选、注册按钮、去登录入口都在卡内
    expect(card.querySelector('h1')?.textContent).toBe('注册')
    expect(card.querySelectorAll('input').length).toBeGreaterThanOrEqual(5)
    expect(card.textContent).toContain('去登录')
    ;(card.querySelector('button[aria-label="关闭"]') as HTMLButtonElement).click()
    await nextTick()
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
    wrapper.unmount()
  })

  it('emits switch-to-login from the go-login entry', async () => {
    const wrapper = mountDialog()
    const btn = [...document.body.querySelectorAll('button')].find(b => b.textContent === '去登录') as HTMLButtonElement
    btn.click()
    await nextTick()
    expect(wrapper.emitted('switch-to-login')).toHaveLength(1)
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    wrapper.unmount()
  })

  it('registers, auto-logs in, and emits success+close without navigating', async () => {
    const wrapper = mountDialog()
    const dialog = document.body.querySelector('[role="dialog"]') as HTMLElement
    const inputs = [...dialog.querySelectorAll('input')] as HTMLInputElement[]
    // OtpEmailField 的邮箱框 + 验证码框 + 用户名框 + 两个密码框；原生赋值 + input 事件触发 v-model
    const setNative = (el: HTMLInputElement, value: string) => {
      el.value = value
      el.dispatchEvent(new Event('input', { bubbles: true }))
    }
    setNative(inputs[0]!, 'new@example.com')
    setNative(inputs[1]!, '123456')
    setNative(inputs[2]!, '读者甲')
    setNative(inputs[3]!, 'secret1234')
    setNative(inputs[4]!, 'secret1234')
    await nextTick()
    // 勾选协议
    ;([...dialog.querySelectorAll('button')].find(b => b.getAttribute('aria-label') === '同意协议') as HTMLButtonElement).click()
    await nextTick()
    ;([...dialog.querySelectorAll('button')].find(b => b.textContent?.includes('注册') && b.classList.contains('btn-primary')) as HTMLButtonElement).click()
    await flushPromises()
    // onSuccess 有 REGISTER_REDIRECT_DELAY_MS（800ms）延迟，等待计时器触发
    await new Promise(r => setTimeout(r, 900))
    await nextTick()

    expect(apiPost).toHaveBeenCalledWith('/auth/register', { email: 'new@example.com', email_code: '123456', password: 'secret1234', username: '读者甲' })
    expect(login).toHaveBeenCalledWith('new@example.com', 'secret1234')
    expect(wrapper.emitted('success')).toHaveLength(1)
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
    // 弹窗模式不跳页
    expect(router.currentRoute.value.fullPath).toBe('/')
    wrapper.unmount()
  })
})
