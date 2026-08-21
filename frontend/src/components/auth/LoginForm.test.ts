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
}, common: { close: '关闭' } }
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
    // dialog 模式注册入口是切换按钮而非路由链接，忘记密码仍是站内路由
    expect(wrapper.find('a[href^="/register"]').exists()).toBe(false)
    expect(wrapper.get('a[href="/forgot-password?redirect=/"]').exists()).toBe(true)
  })

  it('emits switch-to-register from the dialog register entry and keeps a route link on the page', async () => {
    const dialogForm = mountForm({ dialog: true })
    await dialogForm.get('.glass-card p button').trigger('click')
    expect(dialogForm.emitted('switch-to-register')).toHaveLength(1)

    const pageForm = mountForm()
    expect(pageForm.get('a[href^="/register"]').exists()).toBe(true)
    expect(pageForm.find('.glass-card p button').exists()).toBe(false)
  })

  it('wraps the whole login content in one opaque card in dialog mode', () => {
    const wrapper = mountForm({ dialog: true })
    const card = wrapper.get('.glass-card')
    // 外层卡片兜住标题/表单/注册链接，内层表单不再重复成卡
    expect(card.element.classList.contains('max-w-sm')).toBe(true)
    expect(card.text()).toContain('欢迎回来')
    expect(card.text()).toContain('没有账号')
    expect(wrapper.findAll('.glass-card')).toHaveLength(1)
  })

  it('keeps the standalone layout: transparent header plus a separate form card', () => {
    const wrapper = mountForm()
    const cards = wrapper.findAll('.glass-card')
    expect(cards).toHaveLength(1)
    expect(cards[0].element.classList.contains('max-w-sm')).toBe(false)
    expect(wrapper.find('button[aria-label="关闭"]').exists()).toBe(false)
  })

  it('renders a close button only in dialog mode and emits close from it', async () => {
    const wrapper = mountForm({ dialog: true })
    await wrapper.get('button[aria-label="关闭"]').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
    expect(wrapper.emitted('success')).toBeUndefined()
  })
})
