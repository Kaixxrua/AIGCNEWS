import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import OAuthActionCallbackView from './OAuthActionCallbackView.vue'

const consumeOAuthBindHandoff = vi.hoisted(() => vi.fn())
const authStore = vi.hoisted(() => ({
  ensureInitialized: vi.fn(),
  fetchMe: vi.fn(),
}))
const routerReplace = vi.hoisted(() => vi.fn())

vi.mock('@/services/auth/authApi', () => ({ consumeOAuthBindHandoff }))
vi.mock('@/stores/authStore', () => ({ useAuthStore: () => authStore }))
vi.mock('vue-router', () => ({ useRouter: () => ({ replace: routerReplace }) }))

const messages = {
  auth: {
    oauthBinding: '正在完成渠道绑定…',
    oauthBindFailed: '渠道绑定失败，请重试',
    backHome: '返回首页',
  },
}
const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })

const mountView = () => mount(OAuthActionCallbackView, { global: { plugins: [i18n] } })

beforeEach(() => {
  consumeOAuthBindHandoff.mockReset().mockResolvedValue({ provider: 'github', status: 'bound', redirect_to: '/settings?tab=oauth' })
  authStore.ensureInitialized.mockReset().mockResolvedValue(undefined)
  authStore.fetchMe.mockReset().mockResolvedValue(undefined)
  routerReplace.mockReset().mockResolvedValue(undefined)
})

describe('OAuthActionCallbackView', () => {
  it('consumes the bind handoff, refreshes the authoritative projection, then redirects', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(authStore.ensureInitialized).toHaveBeenCalledTimes(1)
    expect(consumeOAuthBindHandoff).toHaveBeenCalledTimes(1)
    // 绑定成功后必须先刷新权威投影再跳转，账户设置的渠道状态才不滞后
    expect(authStore.fetchMe).toHaveBeenCalledTimes(1)
    expect(routerReplace).toHaveBeenCalledWith('/settings?tab=oauth')
    wrapper.unmount()
  })

  it('falls back to home for unsafe redirect targets', async () => {
    consumeOAuthBindHandoff.mockResolvedValue({ provider: 'github', status: 'bound', redirect_to: 'https://evil.example' })
    const wrapper = mountView()
    await flushPromises()

    expect(routerReplace).toHaveBeenCalledWith('/')
    wrapper.unmount()
  })

  it('renders the pending state while the handoff is in flight', () => {
    consumeOAuthBindHandoff.mockReturnValue(new Promise(() => {}))
    const wrapper = mountView()

    expect(wrapper.text()).toContain('正在完成渠道绑定…')
    wrapper.unmount()
  })

  it('shows the failure feedback without redirecting when consume fails', async () => {
    consumeOAuthBindHandoff.mockRejectedValue({ response: { status: 409, data: { detail: 'oauth_identity_conflict' } } })
    const wrapper = mountView()
    await flushPromises()

    expect(authStore.fetchMe).not.toHaveBeenCalled()
    expect(routerReplace).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('oauth_identity_conflict')
    expect(wrapper.text()).toContain('返回首页')

    await wrapper.find('button').trigger('click')
    expect(routerReplace).toHaveBeenCalledWith('/')
    wrapper.unmount()
  })

  it('uses the generic bind-failure message when no detail is provided', async () => {
    consumeOAuthBindHandoff.mockRejectedValue({})
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('渠道绑定失败，请重试')
    wrapper.unmount()
  })
})
