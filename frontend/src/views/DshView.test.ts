import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, getActivePinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi, beforeEach } from 'vitest'
import i18n from '@/i18n'
import DshView from './DshView.vue'
import { useAuthStore } from '@/stores/authStore'
import type { AuthUser } from '@/stores/authStore'

const freeUser: AuthUser = { user_id: 1, email: 'a@b.c', role: 'user', membership_tier: 'free' }
const memberUser: AuthUser = { ...freeUser, membership_tier: 'member', membership_expires_at: null }

const ensureDshMcpToken = vi.hoisted(() => vi.fn())
const rotateDshMcpToken = vi.hoisted(() => vi.fn())
const fetchMcpTokens = vi.hoisted(() => vi.fn())
const issueMcpInstallCode = vi.hoisted(() => vi.fn())
const copyToClipboard = vi.hoisted(() => vi.fn())
const copySensitiveToClipboard = vi.hoisted(() => vi.fn())
const requestLogin = vi.hoisted(() => vi.fn())
vi.mock('@/services/mcp/mcpTokenApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/mcp/mcpTokenApi')>()
  return { ...actual, ensureDshMcpToken, rotateDshMcpToken, fetchMcpTokens, issueMcpInstallCode }
})
vi.mock('@/composables/useClipboard', () => ({ copyToClipboard, copySensitiveToClipboard, useClipboard: () => ({ copy: copyToClipboard }) }))
vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))
vi.mock('@/composables/useLoginPrompt', () => ({ useLoginPrompt: () => ({ requestLogin }) }))
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
  return { useLiveCallCount: () => ref(682) }
})

const TOKEN = 'aigc_mcp_view'
const issued = {
  token: TOKEN, reused: false,
  token_metadata: { id: 21, token_hint: 'h', scopes: [], client_type: 'other', client_label: 'dsh-aigc-radar', expires_at: null, revoked_at: null, created_at: '2026-10-01T08:00:00Z', last_used_at: null },
}

const router = createRouter({ history: createMemoryHistory(), routes: [
  { path: '/dsh', component: DshView },
  { path: '/mcp', component: { template: '<div />' } },
  { path: '/membership', component: { template: '<div />' } },
] })

const mounted: VueWrapper[] = []
const mountView = async () => {
  // 组件必须与测试体共享同一个 active pinia，否则各自读到不同的 auth store
  await router.push('/dsh'); await router.isReady()
  const wrapper = mount(DshView, { global: { plugins: [router, i18n, getActivePinia()!] }, attachTo: document.body })
  mounted.push(wrapper)
  await flushPromises(); return wrapper
}
const signIn = (user: AuthUser = freeUser) => {
  const auth = useAuthStore()
  auth.status = 'authenticated'
  auth.user = user
}
const cta = (wrapper: VueWrapper) => wrapper.get('.agent-page-hero .agent-setup-cta')

beforeEach(() => {
  i18n.global.locale.value = 'zh-CN'
  ensureDshMcpToken.mockReset().mockResolvedValue(issued)
  rotateDshMcpToken.mockReset()
  fetchMcpTokens.mockReset().mockResolvedValue([])
  issueMcpInstallCode.mockReset().mockResolvedValue({ code: 'aigc_ic_view', purpose: 'dsh', expires_in: 600 })
  copyToClipboard.mockReset().mockResolvedValue(undefined)
  copySensitiveToClipboard.mockReset().mockResolvedValue(undefined)
  requestLogin.mockClear()
  setActivePinia(createPinia())
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
})

describe('DshView', () => {
  it('opens on the one button for guests without requesting login or a token', async () => {
    useAuthStore().status = 'anonymous'
    const wrapper = await mountView()

    expect(router.currentRoute.value.path).toBe('/dsh')
    expect(cta(wrapper).text()).toBe('登录后复制提示词')
    expect(wrapper.get('.agent-page-side .dsh-manual .agent-manual-toggle').attributes('aria-expanded')).toBe('false')
    expect(requestLogin).not.toHaveBeenCalled()
    expect(ensureDshMcpToken).not.toHaveBeenCalled()
    // 两步向导与命令台都已撤下。
    expect(wrapper.find('.dsh-wizard').exists()).toBe(false)
    expect(wrapper.find('.dsh-desk').exists()).toBe(false)
  })

  it('shows the setup to late-resolving anonymous sessions without forcing login', async () => {
    const auth = useAuthStore()
    auth.status = 'initializing'
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('正在恢复登录状态…')
    expect(wrapper.find('.agent-setup').exists()).toBe(false)
    expect(wrapper.find('.dsh-manual').exists()).toBe(false)

    auth.status = 'anonymous'
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/dsh')
    expect(requestLogin).not.toHaveBeenCalled()
    expect(wrapper.find('.agent-setup').exists()).toBe(true)
    expect(ensureDshMcpToken).not.toHaveBeenCalled()
  })

  it('asks guests to sign in only when they reach for the prompt', async () => {
    useAuthStore().status = 'anonymous'
    const wrapper = await mountView()

    await cta(wrapper).trigger('click')
    expect(requestLogin).toHaveBeenCalledWith('/dsh')
    expect(ensureDshMcpToken).not.toHaveBeenCalled()
    expect(copySensitiveToClipboard).not.toHaveBeenCalled()
  })

  it('fetches the token when a guest signs in while staying on the page', async () => {
    useAuthStore().status = 'anonymous'
    const wrapper = await mountView()
    expect(ensureDshMcpToken).not.toHaveBeenCalled()

    signIn()
    await flushPromises()

    expect(ensureDshMcpToken).toHaveBeenCalledOnce()
    expect(cta(wrapper).text()).toBe('复制给 Agent 的配置提示词')
  })

  it('fails closed while auth is degraded and never touches the token API', async () => {
    const auth = useAuthStore()
    auth.status = 'degraded'
    const initFromStorage = vi.spyOn(auth, 'initFromStorage').mockResolvedValue()
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('登录状态校验失败')
    expect(wrapper.find('.agent-setup').exists()).toBe(false)
    expect(wrapper.find('.dsh-manual').exists()).toBe(false)
    expect(router.currentRoute.value.path).toBe('/dsh')
    expect(ensureDshMcpToken).not.toHaveBeenCalled()

    await wrapper.get('.agent-page-status .agent-btn').trigger('click')
    expect(initFromStorage).toHaveBeenCalledOnce()
  })

  it('fetches the token once for a signed-in reader, points a free reader at VIP, and keeps the token off the page', async () => {
    signIn()
    const wrapper = await mountView()

    expect(ensureDshMcpToken).toHaveBeenCalledOnce()
    expect(wrapper.get('a[href="/membership"]').text()).toBe('升级 VIP')
    expect(wrapper.findAll('.command-slot--filled').length).toBeGreaterThan(0)
    expect(wrapper.html()).not.toContain(TOKEN)
    expect(wrapper.html()).not.toContain('aigc_ic_view')
  })

  it('tells a member their quota is already the highest', async () => {
    signIn(memberUser)
    const wrapper = await mountView()

    expect(wrapper.find('a[href="/membership"]').exists()).toBe(false)
    expect(wrapper.get('.dsh-quota-hint--member').text()).toBe(i18n.global.t('dsh.wizard.memberStatus'))
  })

  it('drops the token as soon as the reader signs out', async () => {
    signIn()
    const wrapper = await mountView()
    expect(wrapper.findAll('.command-slot--filled').length).toBeGreaterThan(0)

    useAuthStore().status = 'anonymous'
    await flushPromises()
    expect(cta(wrapper).text()).toBe('登录后复制提示词')
    expect(wrapper.find('.command-slot--filled').exists()).toBe(false)
  })

  it('links to MCP and the repository', async () => {
    signIn()
    const wrapper = await mountView()

    expect(wrapper.get('a[href="/mcp"]').text()).toBe('改为配置 MCP')
    const repository = wrapper.get('a[href="https://github.com/Kaixxrua/dsh-aigc-radar"]')
    expect(repository.attributes('target')).toBe('_blank')
    expect(repository.attributes('rel')).toBe('noopener')
  })
})

describe('DshView on desktop', () => {
  beforeEach(() => { viewport.desktop = true })
  afterEach(() => { viewport.desktop = false })

  it('heads the page with the stats strip', async () => {
    useAuthStore().status = 'anonymous'
    const wrapper = await mountView()
    const stats = wrapper.findAll('.dsh-stats .dsh-stat')

    expect(stats).toHaveLength(4)
    expect(stats[1]!.get('strong').text()).toBe('2')
    expect(stats[2]!.get('strong').text()).toBe('200')
    expect(stats[3]!.get('strong').text()).toBe('4,000')
    expect(ensureDshMcpToken).not.toHaveBeenCalled()
  })
})
