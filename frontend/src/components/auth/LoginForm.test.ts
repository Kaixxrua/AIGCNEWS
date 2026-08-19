import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import LoginForm from './LoginForm.vue'

const login = vi.hoisted(() => vi.fn())
vi.mock('@/stores/authStore', () => ({ useAuthStore: () => ({ login }) }))

const messages = { auth: {
  loginTitle: '登录', loginDescription: '欢迎回来', email: '邮箱', emailPlaceholder: '邮箱地址', password: '密码', passwordPlaceholder: '密码',
  fillEmailPassword: '请填写邮箱和密码', forgotPassword: '忘记密码', loggingIn: '登录中', login: '登录', noAccount: '没有账号', registerNow: '立即注册', loginFailed: '登录失败',
} }
const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
const router = createRouter({ history: createMemoryHistory(), routes: [
  { path: '/', component: { template: '<div />' } }, { path: '/dsh', component: { template: '<div />' } },
  { path: '/forgot-password', component: { template: '<div />' } }, { path: '/register', component: { template: '<div />' } },
] })
const mountForm = (props = {}) => mount(LoginForm, { props, global: { plugins: [router, i18n] } })

beforeEach(async () => { login.mockReset(); login.mockResolvedValue({}); await router.push('/') })

describe('LoginForm', () => {
  it('validates required credentials without calling the store', async () => {
    const wrapper = mountForm()
    await wrapper.get('.btn-primary').trigger('click')
    expect(wrapper.text()).toContain('请填写邮箱和密码')
    expect(login).not.toHaveBeenCalled()
  })

  it('trims email, emits success, and redirects in page mode', async () => {
    const wrapper = mountForm({ redirect: '/dsh' })
    await wrapper.get('input[type="email"]').setValue(' user@example.com ')
    await wrapper.get('input[type="password"]').setValue('secret')
    await wrapper.get('.btn-primary').trigger('click'); await flushPromises()
    expect(login).toHaveBeenCalledWith('user@example.com', 'secret')
    expect(wrapper.emitted('success')).toHaveLength(1)
    expect(router.currentRoute.value.fullPath).toBe('/dsh')
  })

  it('stays on the current route in dialog mode and keeps safe auth links', async () => {
    const wrapper = mountForm({ dialog: true, redirect: '//evil.example' })
    await wrapper.get('input[type="email"]').setValue('user@example.com')
    await wrapper.get('input[type="password"]').setValue('secret')
    await wrapper.get('.btn-primary').trigger('click'); await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/')
    expect(wrapper.get('a[href="/register?redirect=/"]').exists()).toBe(true)
    expect(wrapper.get('a[href="/forgot-password?redirect=/"]').exists()).toBe(true)
  })
})
