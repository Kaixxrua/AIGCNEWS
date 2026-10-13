import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '@/i18n'
import McpConnectView from './McpConnectView.vue'

const copyToClipboard = vi.hoisted(() => vi.fn())
const copySensitiveToClipboard = vi.hoisted(() => vi.fn())
const fetchMcpTokens = vi.hoisted(() => vi.fn())
const createMcpToken = vi.hoisted(() => vi.fn())
const issueMcpInstallCode = vi.hoisted(() => vi.fn())
const requestLogin = vi.hoisted(() => vi.fn())
type AuthStatus = 'initializing' | 'authenticated' | 'anonymous' | 'degraded'
const authBox = vi.hoisted(() => ({ current: null as null | { status: AuthStatus; isLoggedIn: boolean; isMember: boolean; initFromStorage: ReturnType<typeof vi.fn> } }))
// 桌面（≥1024px）报头多一行统计；jsdom 没有 matchMedia，按标志切换。
const viewport = vi.hoisted(() => ({ desktop: false }))
vi.mock('@vueuse/core', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@vueuse/core')>()
  const { ref } = await import('vue')
  return {
    ...actual,
    useMediaQuery: (query: string) => (query === '(min-width: 1024px)' ? ref(viewport.desktop) : actual.useMediaQuery(query)),
  }
})
vi.mock('@/composables/useLiveCallCount', async () => {
  const { ref } = await import('vue')
  return { useLiveCallCount: () => ref(4668) }
})
vi.mock('@/stores/authStore', async () => {
  const { reactive } = await import('vue')
  authBox.current ??= reactive({ status: 'anonymous' as AuthStatus, isLoggedIn: false, isMember: false, initFromStorage: vi.fn() })
  return { useAuthStore: () => authBox.current }
})
vi.mock('@/composables/useClipboard', () => ({ copyToClipboard, copySensitiveToClipboard, useClipboard: () => ({ copy: copyToClipboard }) }))
vi.mock('@/services/mcp/mcpTokenApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/mcp/mcpTokenApi')>()),
  createMcpToken,
  fetchMcpTokens,
  issueMcpInstallCode,
}))
vi.mock('@/composables/useLoginPrompt', () => ({ useLoginPrompt: () => ({ requestLogin }) }))
vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))

const router = createRouter({ history: createMemoryHistory(), routes: [
  { path: '/mcp', component: McpConnectView },
  { path: '/membership', component: { template: '<div />' } },
] })

const auth = () => authBox.current!
const setAuth = (status: AuthStatus, member = false) => Object.assign(auth(), { status, isLoggedIn: status === 'authenticated', isMember: status === 'authenticated' && member })

const mounted: VueWrapper[] = []
const mountView = async () => {
  await router.push('/mcp')
  await router.isReady()
  const wrapper = mount(McpConnectView, { global: { plugins: [router, i18n] }, attachTo: document.body })
  mounted.push(wrapper)
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  i18n.global.locale.value = 'zh-CN'
  setAuth('anonymous')
  auth().initFromStorage.mockReset()
  copyToClipboard.mockReset().mockResolvedValue(undefined)
  copySensitiveToClipboard.mockReset().mockResolvedValue(undefined)
  fetchMcpTokens.mockReset().mockResolvedValue([])
  createMcpToken.mockReset()
  issueMcpInstallCode.mockReset().mockResolvedValue({ code: 'aigc_ic_view', purpose: 'mcp', expires_in: 600 })
  requestLogin.mockReset()
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  sessionStorage.clear()
})

describe('McpConnectView', () => {
  it('opens on the one button, with the address and the folded manual setup beside it', async () => {
    const wrapper = await mountView()

    expect(wrapper.get('h1').text()).toBe(i18n.global.t('mcp.title'))
    expect(wrapper.get('.agent-page-hero .agent-setup-cta').text()).toBe('复制给 Agent 的配置提示词')
    expect(wrapper.get('.agent-page-side .agent-endpoint').text()).toBe('https://aigcnews.cn/api/mcp/oauth')
    expect(wrapper.get('.agent-page-side .agent-manual-toggle').attributes('aria-expanded')).toBe('false')
    expect(wrapper.findAll('.agent-examples .mcp-prompt-list li').length).toBeGreaterThan(0)
    // 九个客户端 × 三种终端的选择器、命令台与分步向导都已撤下。
    expect(wrapper.find('.mcp-wizard').exists()).toBe(false)
    expect(wrapper.find('.mcp-desk').exists()).toBe(false)
  })

  it('lets guests use the page without asking them to sign in or pitching a quota', async () => {
    const wrapper = await mountView()

    expect(router.currentRoute.value.path).toBe('/mcp')
    expect(requestLogin).not.toHaveBeenCalled()
    expect(fetchMcpTokens).not.toHaveBeenCalled()
    expect(createMcpToken).not.toHaveBeenCalled()
    expect(wrapper.find('a[href="/membership"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('开通 vip')
    expect(wrapper.text()).not.toContain('当前 Free 的')
  })

  it('keeps the page fail-closed while sign-in is being restored', async () => {
    setAuth('initializing')
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('正在恢复登录状态…')
    expect(wrapper.find('.agent-setup').exists()).toBe(false)
    expect(wrapper.find('.agent-manual').exists()).toBe(false)
    expect(wrapper.find('a[href="/membership"]').exists()).toBe(false)
    expect(wrapper.find('a[href="/mcp"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('开通 vip')
    expect(wrapper.text()).not.toContain('当前 Free 的')

    setAuth('anonymous')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/mcp')
    expect(requestLogin).not.toHaveBeenCalled()
    expect(wrapper.find('.agent-setup').exists()).toBe(true)
  })

  it('offers a retry when the sign-in state cannot be verified', async () => {
    setAuth('degraded')
    const wrapper = await mountView()

    expect(wrapper.get('.agent-page-status .agent-card-error').text()).toBe(i18n.global.t('mcp.authDegraded'))
    expect(wrapper.find('.agent-setup').exists()).toBe(false)
    expect(fetchMcpTokens).not.toHaveBeenCalled()

    await wrapper.get('.agent-page-status .agent-btn').trigger('click')
    expect(auth().initFromStorage).toHaveBeenCalledOnce()
  })

  it('keeps the free reader setup free of purchase prompts', async () => {
    setAuth('authenticated')
    const wrapper = await mountView()

    expect(wrapper.find('.agent-quota').exists()).toBe(false)
    expect(wrapper.find('a[href="/membership"]').exists()).toBe(false)
    expect(wrapper.text()).not.toMatch(/VIP|vip/)
  })

  it('hides the quota prompt from members', async () => {
    setAuth('authenticated', true)
    const wrapper = await mountView()

    expect(wrapper.find('.agent-quota').exists()).toBe(false)
    expect(wrapper.find('a[href="/membership"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('开通 vip')
  })

  it('leaves the stats strip to desktop', async () => {
    const wrapper = await mountView()
    expect(wrapper.find('.mcp-stats').exists()).toBe(false)
  })
})

describe('McpConnectView on desktop', () => {
  beforeEach(() => { viewport.desktop = true })
  afterEach(() => { viewport.desktop = false })

  it('heads the page with the live call count and the free account quota', async () => {
    const wrapper = await mountView()
    const stats = wrapper.findAll('.mcp-stats .mcp-stat')

    expect(stats).toHaveLength(3)
    expect(stats[1]!.get('strong').text()).toBe('200')
    expect(stats[2]!.get('strong').text()).toBe('4,000')
    expect(wrapper.get('.agent-page-hero .agent-setup-cta').text()).toBe('复制给 Agent 的配置提示词')
  })
})
