import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, getActivePinia, setActivePinia } from 'pinia'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import DshView from './DshView.vue'
import { useAuthStore } from '@/stores/authStore'
import type { AuthUser } from '@/stores/authStore'

const freeUser: AuthUser = { user_id: 1, email: 'a@b.c', role: 'user', membership_tier: 'free' }

const ensureDshMcpToken = vi.hoisted(() => vi.fn())
const rotateDshMcpToken = vi.hoisted(() => vi.fn())
const copy = vi.hoisted(() => vi.fn().mockResolvedValue(undefined))
const requestLogin = vi.hoisted(() => vi.fn())
vi.mock('@/services/mcp/mcpTokenApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/mcp/mcpTokenApi')>()
  return { ...actual, ensureDshMcpToken, rotateDshMcpToken }
})
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy }) }))
vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))
vi.mock('@/composables/useLoginPrompt', () => ({ useLoginPrompt: () => ({ requestLogin }) }))

const messages = {
  mcp: { copied: '已复制', copyFailed: '复制失败', tokenCreateFailed: 'Token 创建失败。', wizard: { prev: '上一步', next: '下一步', stepProgress: '{current}/{total}' }, dshPlugin: { methods: {
    npm: { title: 'npm 最新版', description: '预构建。' }, github: { title: 'GitHub 源码', description: '源码。' },
  } } },
  dsh: {
    eyebrow: 'AIGC RADAR FOR DSH', title: '在 dsh 终端里搜索 AI 项目', description: '登录后自动分配专属 Token。',
    mcpLink: '改为配置 MCP', repository: 'GitHub 仓库', recommended: '推荐', copy: '复制安装命令',
    capabilitiesKicker: '插件能力', capabilitiesTitle: '原生卡片与检索路由', capabilitiesDescription: '插件能力说明。',
    authRestoring: '正在恢复登录状态…', authDegraded: '登录状态校验失败。', authRetry: '重试',
    wizard: {
      ariaLabel: 'dsh 接入向导',
      stepInstall: '选择安装方式', stepInstallDescription: '选择安装方式。',
      stepCommand: '获取接入命令', stepCommandDescription: '获取命令。',
      tokenCreating: '正在获取你的专属 MCP Token…', tokenRetry: '重试',
      tokenUnavailable: 'DSH Token 服务暂不可用。',
      tokenRecovery: '旧版 Token 无法自动恢复。', tokenRotate: '重新生成 Token',
      commandLabel: '安装命令', tokenCommandNote: '命令会写入 dsh 补丁配置。',
      tokenReuseNote: 'Token 与账号绑定、跨刷新保持不变。',
      vipHint: 'VIP 会员享更高调用次数。', vipCta: '升级 VIP',
      memberStatus: '当前账号为 VIP 会员。',
    },
  },
}

const router = createRouter({ history: createMemoryHistory(), routes: [
  { path: '/dsh', component: DshView },
  { path: '/mcp', component: { template: '<div />' } },
  { path: '/membership', component: { template: '<div />' } },
] })
const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })

const mountView = async () => {
  // 组件必须与测试体共享同一个 active pinia，否则各自读到不同的 auth store
  await router.push('/dsh'); await router.isReady()
  const wrapper = mount(DshView, { global: { plugins: [router, i18n, getActivePinia()!] } })
  await flushPromises(); return wrapper
}

beforeEach(() => {
  ensureDshMcpToken.mockReset()
  rotateDshMcpToken.mockReset()
  copy.mockClear()
  requestLogin.mockClear()
  setActivePinia(createPinia())
})

describe('DshView', () => {
  it('renders the wizard for anonymous visitors without requesting login on mount', async () => {
    const auth = useAuthStore()
    auth.status = 'anonymous'
    const wrapper = await mountView()

    expect(router.currentRoute.value.path).toBe('/dsh')
    expect(requestLogin).not.toHaveBeenCalled()
    expect(wrapper.find('.dsh-wizard').exists()).toBe(true)
    expect(wrapper.text()).toContain('npm 最新版')
    expect(ensureDshMcpToken).not.toHaveBeenCalled()
  })

  it('shows the wizard to late-resolving anonymous sessions without forcing login', async () => {
    const auth = useAuthStore()
    auth.status = 'initializing'
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('正在恢复登录状态…')
    expect(router.currentRoute.value.path).toBe('/dsh')

    auth.status = 'anonymous'
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/dsh')
    expect(requestLogin).not.toHaveBeenCalled()
    expect(wrapper.find('.dsh-wizard').exists()).toBe(true)
    expect(ensureDshMcpToken).not.toHaveBeenCalled()
  })

  it('defers the login prompt to the wizard next step for guests', async () => {
    const auth = useAuthStore()
    auth.status = 'anonymous'
    const wrapper = await mountView()

    await wrapper.findAll('button').find((b) => b.text().includes('下一步'))!.trigger('click')
    await flushPromises()

    expect(requestLogin).toHaveBeenCalledWith('/dsh')
    expect(wrapper.text()).toContain('1/2')
    expect(ensureDshMcpToken).not.toHaveBeenCalled()
  })

  it('auto-ensures the token when a guest signs in while staying on the page', async () => {
    ensureDshMcpToken.mockResolvedValue({
      token: 'aigc_mcp_view', reused: false,
      token_metadata: { id: 21, token_hint: 'h', scopes: [], client_type: 'other', client_label: 'dsh-aigc-radar', expires_at: null, revoked_at: null },
    })
    const auth = useAuthStore()
    auth.status = 'anonymous'
    const wrapper = await mountView()
    expect(ensureDshMcpToken).not.toHaveBeenCalled()

    auth.status = 'authenticated'
    auth.user = freeUser
    await flushPromises()

    expect(ensureDshMcpToken).toHaveBeenCalledOnce()
    expect(wrapper.find('.dsh-wizard').exists()).toBe(true)
  })

  it('fails closed while auth is degraded and never touches the token API', async () => {
    const auth = useAuthStore()
    auth.status = 'degraded'
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('登录状态校验失败。')
    expect(wrapper.find('.dsh-wizard').exists()).toBe(false)
    expect(router.currentRoute.value.path).toBe('/dsh')
    expect(ensureDshMcpToken).not.toHaveBeenCalled()
  })

  it('mounts the wizard and auto-ensures the token once authenticated', async () => {
    ensureDshMcpToken.mockResolvedValue({
      token: 'aigc_mcp_view', reused: false,
      token_metadata: { id: 21, token_hint: 'h', scopes: [], client_type: 'other', client_label: 'dsh-aigc-radar', expires_at: null, revoked_at: null },
    })
    const auth = useAuthStore()
    auth.status = 'authenticated'
    auth.user = freeUser
    const wrapper = await mountView()

    expect(wrapper.find('.dsh-wizard').exists()).toBe(true)
    expect(ensureDshMcpToken).toHaveBeenCalledOnce()
    // Free 用户看到 VIP 提示，但流程不被阻断
    expect(wrapper.get('a[href="/membership"]').text()).toContain('升级 VIP')
  })

  it('links to MCP and the repository', async () => {
    ensureDshMcpToken.mockResolvedValue({
      token: 'aigc_mcp_view', reused: true,
      token_metadata: { id: 21, token_hint: 'h', scopes: [], client_type: 'other', client_label: 'dsh-aigc-radar', expires_at: null, revoked_at: null },
    })
    const auth = useAuthStore()
    auth.status = 'authenticated'
    auth.user = freeUser
    const wrapper = await mountView()

    expect(wrapper.get('a[href="/mcp"]').text()).toBe('改为配置 MCP')
    const repository = wrapper.get('a[href="https://github.com/Kaixxrua/dsh-aigc-radar"]')
    expect(repository.attributes('target')).toBe('_blank')
    expect(repository.attributes('rel')).toBe('noopener')
  })
})
