import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import zh from '@/i18n/locales/zh-CN'
import WeChatLoginView from './WeChatLoginView.vue'

const { prepareWeChatLogin, requestLogin } = vi.hoisted(() => ({ prepareWeChatLogin: vi.fn(), requestLogin: vi.fn() }))
vi.mock('@/services/auth/authApi', () => ({ prepareWeChatLogin }))
vi.mock('@/composables/useLoginPrompt', () => ({ useLoginPrompt: () => ({ requestLogin }) }))

const authorization = (state = 'first') => `https://open.weixin.qq.com/connect/qrconnect?appid=wx-site&scope=snsapi_login&state=${state}&redirect_uri=https%3A%2F%2Faigcnews.cn%2Fapi%2Fauth%2Foauth%2Fwechat%2Fcallback#wechat_redirect`
let wrapper: VueWrapper | undefined
const mountPage = async (redirect = '/membership?plan=yearly') => {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/', component: { template: '<div />' } },
    { path: '/oauth/wechat', component: { template: '<div />' } },
  ] })
  await router.push({ path: '/oauth/wechat', query: { redirect } })
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zh } })
  wrapper = mount(WeChatLoginView, { global: { plugins: [router, i18n], stubs: { LocaleToggle: true } } })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  prepareWeChatLogin.mockReset().mockResolvedValue({ authorization_url: authorization(), expires_in: 300 })
  requestLogin.mockReset()
})
afterEach(() => { wrapper?.unmount(); vi.useRealTimers() })

describe('WeChat quick sign-in page', () => {
  it('loads the official frame while retaining the original destination', async () => {
    const page = await mountPage()
    expect(prepareWeChatLogin).toHaveBeenCalledWith('/membership?plan=yearly', expect.any(AbortSignal))
    expect(page.text()).toContain('正在加载微信登录二维码')
    const frame = page.get('iframe')
    const url = new URL(frame.attributes('src')!)
    expect(url.origin).toBe('https://open.weixin.qq.com')
    expect(url.searchParams.get('self_redirect')).toBe('false')
    expect(url.searchParams.get('state')).toBe('first')
    expect(frame.attributes('title')).toBe('微信官方登录二维码')
    await frame.trigger('load')
    expect(page.text()).not.toContain('正在加载微信登录二维码')
    expect(page.text()).toContain('刷新二维码')
    const other = page.findAll('button').find(button => button.text() === '使用其他方式登录')!
    await other.trigger('click')
    expect(requestLogin).toHaveBeenCalledWith('/membership?plan=yearly')
  })

  it('expires the frame and starts a fresh browser-bound attempt on retry', async () => {
    const page = await mountPage()
    const firstSignal = prepareWeChatLogin.mock.calls[0]![1] as AbortSignal
    await page.get('iframe').trigger('load')
    await vi.advanceTimersByTimeAsync(300_000)
    expect(page.find('iframe').exists()).toBe(false)
    expect(page.find('a[href^="https://open.weixin.qq.com"]').exists()).toBe(false)
    expect(page.text()).toContain('二维码已过期')
    prepareWeChatLogin.mockResolvedValueOnce({ authorization_url: authorization('second'), expires_in: 300 })
    await page.get('[role="status"] button').trigger('click')
    await flushPromises()
    expect(firstSignal.aborted).toBe(true)
    expect(page.get('iframe').attributes('src')).toContain('state=second')
    expect(prepareWeChatLogin).toHaveBeenCalledTimes(2)
  })

  it('offers the official page if the embedded frame times out', async () => {
    const page = await mountPage()
    await vi.advanceTimersByTimeAsync(15_000)
    expect(page.text()).toContain('微信登录加载失败')
    expect(page.find('iframe').exists()).toBe(false)
    expect(page.get('a[href^="https://open.weixin.qq.com"]').attributes('href')).toBe(authorization())
  })

  it('shows an honest unavailable state without exposing server configuration', async () => {
    prepareWeChatLogin.mockRejectedValueOnce({ response: { data: { detail: 'oauth_provider_unavailable' } } })
    const page = await mountPage()
    expect(page.text()).toContain('微信登录暂未开放')
    expect(page.text()).not.toContain('oauth_provider_unavailable')
    expect(page.find('iframe').exists()).toBe(false)
    expect(page.text()).toContain('使用其他方式登录')
  })

  it.each(['https://evil.test/connect/qrconnect', 'https://open.weixin.qq.com/other', 'javascript:alert(1)'])('never embeds unexpected authorization URLs: %s', async authorization_url => {
    prepareWeChatLogin.mockResolvedValueOnce({ authorization_url, expires_in: 300 })
    const page = await mountPage()
    expect(page.find('iframe').exists()).toBe(false)
    expect(page.text()).toContain('微信登录加载失败')
  })

  it('falls back to home for an external return destination', async () => {
    await mountPage('//evil.test')
    expect(prepareWeChatLogin).toHaveBeenCalledWith('/', expect.any(AbortSignal))
  })

  it('aborts a pending request on navigation and ignores its late result', async () => {
    let resolve!: (value: { authorization_url: string; expires_in: number }) => void
    prepareWeChatLogin.mockReturnValueOnce(new Promise(done => { resolve = done }))
    const page = await mountPage()
    const signal = prepareWeChatLogin.mock.calls[0]![1] as AbortSignal
    page.unmount()
    wrapper = undefined
    expect(signal.aborted).toBe(true)
    resolve({ authorization_url: authorization(), expires_in: 300 })
    await flushPromises()
    expect(vi.getTimerCount()).toBe(0)
  })
})
