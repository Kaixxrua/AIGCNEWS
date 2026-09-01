import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import OAuthActionCallbackView from './OAuthActionCallbackView.vue'

const authStore = vi.hoisted(() => ({
  ensureInitialized: vi.fn(),
  // store 方法内部完成 handoff 消费 + fetchMe 权威投影刷新，返回 redirect_to
  consumeOAuthBinding: vi.fn(),
}))
const routerReplace = vi.hoisted(() => vi.fn())

vi.mock('@/stores/authStore', () => ({ useAuthStore: () => authStore }))
vi.mock('vue-router', () => ({ useRouter: () => ({ replace: routerReplace }) }))

const messages = {
  auth: {
    oauthBindingInProgress: '正在完成快捷登录绑定…',
    oauthBindingFailed: '快捷登录绑定失败，请稍后重试。',
    backHome: '返回首页',
  },
}
const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })

const mountView = () => mount(OAuthActionCallbackView, { global: { plugins: [i18n] } })

beforeEach(() => {
  authStore.ensureInitialized.mockReset().mockResolvedValue(undefined)
  authStore.consumeOAuthBinding.mockReset().mockResolvedValue('/projects?source=all')
  routerReplace.mockReset().mockResolvedValue(undefined)
})

describe('OAuthActionCallbackView', () => {
  it('consumes the bind handoff via the store, then redirects to the saved location', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(authStore.ensureInitialized).toHaveBeenCalledTimes(1)
    expect(authStore.consumeOAuthBinding).toHaveBeenCalledTimes(1)
    expect(routerReplace).toHaveBeenCalledWith('/projects?source=all')
    wrapper.unmount()
  })

  it('falls back to home for unsafe redirect targets', async () => {
    authStore.consumeOAuthBinding.mockResolvedValue('https://evil.example')
    const wrapper = mountView()
    await flushPromises()

    expect(routerReplace).toHaveBeenCalledWith('/')
    wrapper.unmount()
  })

  it('renders the pending state while the handoff is in flight', () => {
    authStore.consumeOAuthBinding.mockReturnValue(new Promise(() => {}))
    const wrapper = mountView()

    expect(wrapper.text()).toContain('正在完成快捷登录绑定…')
    wrapper.unmount()
  })

  it('shows the failure feedback without redirecting when consume fails', async () => {
    authStore.consumeOAuthBinding.mockRejectedValue({ response: { status: 409, data: { detail: 'oauth_identity_conflict' } } })
    const wrapper = mountView()
    await flushPromises()

    expect(routerReplace).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('oauth_identity_conflict')
    expect(wrapper.text()).toContain('返回首页')

    await wrapper.find('button').trigger('click')
    expect(routerReplace).toHaveBeenCalledWith('/')
    wrapper.unmount()
  })

  it('uses the generic bind-failure message when no detail is provided', async () => {
    authStore.consumeOAuthBinding.mockRejectedValue({})
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('快捷登录绑定失败，请稍后重试。')
    wrapper.unmount()
  })
})
