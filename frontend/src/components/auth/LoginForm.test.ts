import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import LoginForm from './LoginForm.vue'

const login = vi.hoisted(() => vi.fn())
const startOAuth = vi.hoisted(() => vi.fn())
const flags = vi.hoisted(() => ({ oauthProviders: [] as string[] }))
vi.mock('@/services/auth/authApi', () => ({ startOAuth }))
vi.mock('@/composables/useFeatureFlags', () => ({ ensureFeatureFlags: async () => flags }))
vi.mock('@/stores/authStore', () => ({ useAuthStore: () => ({ login }) }))

const messages = { auth: {
  oauthOr: '快捷登录', oauth: { qq: '使用 QQ 登录', linuxdo: '使用 Linux DO 登录' },
  loginTitle: '登录', loginDescription: '欢迎回来', email: '邮箱', emailPlaceholder: '邮箱地址', password: '密码', passwordPlaceholder: '密码',
  fillEmailPassword: '请填写邮箱和密码', forgotPassword: '忘记密码', loggingIn: '登录中', login: '登录', noAccount: '没有账号', registerNow: '立即注册', loginFailed: '登录失败',
}, loginContext: { search: '登录后继续搜索', projects: '登录后可收藏项目', subscriptions: '登录后可管理订阅' }, common: { close: '关闭' } }
const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
const router = createRouter({ history: createMemoryHistory(), routes: [
  { path: '/', component: { template: '<div />' } },
  { path: '/forgot-password', component: { template: '<div />' } },
] })
const mountForm = (props = {}) => mount(LoginForm, { props, global: { plugins: [router, i18n] } })

beforeEach(async () => { flags.oauthProviders = []; startOAuth.mockReset(); login.mockReset(); login.mockResolvedValue({}); await router.push('/') })

describe('LoginForm', () => {
  it('updates the explanation when another gated action changes the return destination', async () => {
    const wrapper = mountForm({ redirect: '/projects?q=android-use' })
    expect(wrapper.text()).toContain('登录后继续搜索')
    await wrapper.setProps({ redirect: '/subscriptions' })
    expect(wrapper.text()).toContain('登录后可管理订阅')
    expect(wrapper.text()).not.toContain('登录后继续搜索')
    await wrapper.setProps({ redirect: '/' })
    expect(wrapper.text()).toContain('欢迎回来')
    wrapper.unmount()
  })

  it.each(['qq', 'linuxdo'])('starts configured %s login with the internal return path', async provider => {
    flags.oauthProviders = [provider]
    const wrapper = mountForm({ redirect: '/projects?source=all' })
    await flushPromises()
    const button = wrapper.get('.auth-oauth button')
    expect(button.text()).toBe(provider === 'qq' ? '使用 QQ 登录' : '使用 Linux DO 登录')
    await button.trigger('click')
    expect(startOAuth).toHaveBeenCalledWith(provider, '/projects?source=all')
    wrapper.unmount()
  })

  it('hides OAuth entries until credentials are configured', async () => {
    const wrapper = mountForm()
    await flushPromises()
    expect(wrapper.find('.auth-oauth').exists()).toBe(false)
    wrapper.unmount()
  })

  it('validates required credentials without calling the store', async () => {
    const wrapper = mountForm()
    await wrapper.get('.btn-primary').trigger('click')
    expect(wrapper.text()).toContain('请填写邮箱和密码')
    expect(login).not.toHaveBeenCalled()
  })

  it('trims email and emits success without navigating', async () => {
    const wrapper = mountForm({ redirect: '/forgot-password' })
    await wrapper.get('input[type="email"]').setValue(' user@example.com ')
    await wrapper.get('input[type="password"]').setValue('secret')
    await wrapper.get('.btn-primary').trigger('click'); await flushPromises()
    expect(login).toHaveBeenCalledWith('user@example.com', 'secret')
    expect(wrapper.emitted('success')).toHaveLength(1)
    expect(router.currentRoute.value.fullPath).toBe('/')
  })

  it('emits a modal event without navigating for forgot password', async () => {
    const wrapper = mountForm({ redirect: '//evil.example' })
    const forgotButton = wrapper.findAll('button').find(button => button.text() === '忘记密码')
    expect(forgotButton).toBeDefined()
    await forgotButton!.trigger('click')
    expect(wrapper.emitted('switch-to-forgot-password')).toHaveLength(1)
    expect(router.currentRoute.value.fullPath).toBe('/')
  })

  it('is modal-only and emits switch-to-register instead of linking to a page', async () => {
    const wrapper = mountForm()
    expect(wrapper.find('a[href^="/register"]').exists()).toBe(false)
    await wrapper.get('.glass-card p button').trigger('click')
    expect(wrapper.emitted('switch-to-register')).toHaveLength(1)
  })

  it('wraps all login content in one opaque card', () => {
    const wrapper = mountForm()
    const card = wrapper.get('.glass-card')
    expect(card.element.classList.contains('max-w-sm')).toBe(true)
    expect(card.text()).toContain('欢迎回来')
    expect(card.text()).toContain('没有账号')
    expect(wrapper.findAll('.glass-card')).toHaveLength(1)
  })

  it('always renders a close button and emits close from it', async () => {
    const wrapper = mountForm()
    await wrapper.get('button[aria-label="关闭"]').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
    expect(wrapper.emitted('success')).toBeUndefined()
  })
})
