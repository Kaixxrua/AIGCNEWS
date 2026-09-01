import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import McpConnectView from './McpConnectView.vue'

const controllerSpy = vi.hoisted(() => vi.fn())
const clipboardCopy = vi.hoisted(() => vi.fn())
const requestLogin = vi.hoisted(() => vi.fn())
const ctlBox = vi.hoisted(() => ({ current: null as null | Record<string, any> }))
const authBox = vi.hoisted(() => ({ current: null as null | { status: 'initializing' | 'authenticated' | 'anonymous' | 'degraded'; isLoggedIn: boolean; isAdmin: boolean; isMember: boolean; initFromStorage: ReturnType<typeof vi.fn> } }))

vi.mock('@/stores/authStore', async () => {
  const { reactive } = await import('vue')
  if (!authBox.current) authBox.current = reactive({
    status: 'authenticated' as const,
    isLoggedIn: true,
    isAdmin: false,
    isMember: false,
    initFromStorage: vi.fn(),
  })
  return { useAuthStore: () => authBox.current }
})

vi.mock('@/composables/useClipboard', () => ({
  useClipboard: () => ({ copy: clipboardCopy }),
}))

vi.mock('@/composables/useLoginPrompt', () => ({
  useLoginPrompt: () => ({ requestLogin }),
}))

vi.mock('@/composables/useMcpConnectController', async () => {
  const { ref } = await import('vue')
  ctlBox.current = {
    clientDisplayLabel: vi.fn((client: { id: string }) => client.id),
    clientLabel: ref(''),
    clientOption: ref({ id: 'claude-code', setupScope: 'user', configPathKey: 'mcp.pathClaude' }),
    copiedKey: ref(''),
    copyGeneratedCommand: vi.fn(),
    copyHostInstruction: vi.fn(),
    copyQuickCommand: vi.fn(),
    clearAuthenticatedState: vi.fn(),
    creating: ref(false),
    deletingId: ref(null),
    displayedPublicTools: ref([
      { name: 'search_github_ai_projects', descriptionKey: 'mcp.toolSearchAi' },
      { name: 'search_papers', descriptionKey: 'mcp.toolSearchPapers' },
    ]),
    dispose: vi.fn(),
    endpointUrl: ref('https://aigcnews.cn/api/mcp'),
    endpointWarningKey: ref(''),
    loadTokens: vi.fn(),
    loadingTokens: ref(false),
    normalizedEndpoint: ref('https://aigcnews.cn/api/mcp'),
    quickCommand: ref(''),
    removeToken: vi.fn(),
    selectedClient: ref('claude-code'),
    selectedShell: ref('bash'),
    setupError: ref(null),
    setupNotice: ref(null),
    startSetup: vi.fn(),
    testing: ref(false),
    testMessage: ref(null),
    testPhases: ref([]),
    testPublicHandshake: vi.fn(),
    tokenStatus: vi.fn(() => 'valid'),
    tokens: ref([]),
    transientCommand: ref(''),
  }
  return { useMcpConnectController: controllerSpy.mockReturnValue(ctlBox.current) }
})

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      mcp: {
        title: '把 AIGC 雷达接入你的 Agent',
        serverEyebrow: 'AIGC RADAR MCP',
        publicEndpoint: '公开端点',
        authenticatedSetup: '鉴权配置',
        authRestoring: '正在恢复登录状态…',
        authDegraded: '登录状态校验失败。为安全起见，确认前不会签发 MCP Token。',
        authRetry: '重试',
        tokenManagement: '令牌管理',
        routing: 'MCP 优先路由',
        aiArtifacts: 'AI 工程产物',
        streamableHttp: 'Streamable HTTP',
        publicTools: '公开工具',
        privateFavorites: '私有收藏',
        toolSearchAi: '搜索站内精选 AI 项目',
        toolSearchPapers: '检索 arXiv 论文',
        loginToConfigure: '登录后配置',
        quickConnect: '免登录接入',
        wizard: {
          stepClient: '选择客户端与终端',
          stepCommand: '复制接入命令',
          stepVerify: '验证连接',
          prev: '上一步',
          next: '下一步',
          stepProgress: '第 {current} 步 · 共 {total} 步',
          resourcesToggle: '工具清单 · 示例提问 · 路由规则',
        },
        copyQuick: '复制配置命令',
        quota: {
          anonymous: 'MCP 匿名额度按 IP 计：每 24 小时 30 次；登录后 MCP/API 共用每 24 小时 60 次 + 滚动 30 天 1,200 次，开通 vip 可达 400 次 + 8,000 次。',
          free: '当前 Free 的 MCP/API 共用额度：每 24 小时 60 次 + 滚动 30 天 1,200 次；开通 vip 升至 400 次 + 8,000 次。',
          loginCta: '登录提升额度',
          vipCta: '开通 vip',
        },
        bearerWarning: '命令只显示一次',
        copyOneTime: '复制一次性命令',
        valid: '有效',
        copied: '已复制',
        dshPlugin: {
          kicker: 'DSH 插件',
          title: 'dsh 终端用户：一条命令接入',
          description: 'dsh-aigc-radar 是 dsh 终端的原生插件。',
          crossLinkTitle: '在 dsh 中原生使用 AIGC Radar',
          crossLinkDescription: 'dsh 现在有独立安装页。',
          openPage: '打开 dsh 安装页',
          recommended: '推荐',
          copy: '复制安装命令',
          repository: 'GitHub 仓库',
          sourceWarningTitle: '源码构建：',
          sourceWarning: 'pnpm 10+ 可能要求 allowBuilds；固定提交：',
          methods: {
            npm: { title: 'npm 包 · 最新版', description: '安装预构建包。' },
            github: { title: 'GitHub 源码兜底', description: '现场构建源码。' },
          },
        },
      },
    },
  },
  missingWarn: false,
  fallbackWarn: false,
})

const testRouter = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/mcp', name: 'mcp-connect', component: McpConnectView },
    { path: '/dsh', name: 'dsh', component: { template: '<div />' } },
    { path: '/membership', name: 'membership', component: { template: '<div />' } },
  ],
})

const mountView = async () => {
  await testRouter.push('/mcp')
  await testRouter.isReady()
  const wrapper = mount(McpConnectView, { global: { plugins: [testRouter, i18n] } })
  mountedWrappers.push(wrapper)
  await flushPromises()
  return wrapper
}

const controller = () => ctlBox.current as Record<string, any>
const auth = () => authBox.current as { status: 'initializing' | 'authenticated' | 'anonymous' | 'degraded'; isLoggedIn: boolean; isAdmin: boolean; isMember: boolean; initFromStorage: ReturnType<typeof vi.fn> }

const mountedWrappers: Array<{ unmount: () => void }> = []

afterEach(() => {
  for (const wrapper of mountedWrappers.splice(0)) wrapper.unmount()
})

beforeEach(() => {
  controller().clientLabel.value = ''
  controller().copiedKey.value = ''
  controller().creating.value = false
  controller().deletingId.value = null
  controller().endpointWarningKey.value = ''
  controller().loadingTokens.value = false
  controller().quickCommand.value = ''
  controller().setupError.value = null
  controller().setupNotice.value = null
  controller().testing.value = false
  controller().testMessage.value = null
  controller().testPhases.value = []
  controller().tokens.value = []
  controller().transientCommand.value = ''
  controller().selectedClient.value = 'claude-code'
  controller().selectedShell.value = 'bash'
  for (const fn of [
    controller().clientDisplayLabel,
    controller().clearAuthenticatedState,
    controller().copyGeneratedCommand,
    controller().copyHostInstruction,
    controller().copyQuickCommand,
    controller().dispose,
    controller().loadTokens,
    controller().removeToken,
    controller().startSetup,
    controller().testPublicHandshake,
    controller().tokenStatus,
  ]) {
    fn.mockClear()
  }
  auth().status = 'authenticated'
  auth().isLoggedIn = true
  auth().isMember = false
  auth().initFromStorage.mockClear()
  controllerSpy.mockClear()
  clipboardCopy.mockClear()
  requestLogin.mockClear()
})


describe('McpConnectView controller boundary', () => {
  it('hands clipboard, auth, login prompt and translate seams to the controller', async () => {
    await mountView()

    expect(controllerSpy).toHaveBeenCalledOnce()
    const init = controllerSpy.mock.calls[0]![0]
    expect(init.copy).toBe(clipboardCopy)
    expect(init.isLoggedIn()).toBe(true)
    expect(typeof init.translate).toBe('function')

    await init.navigateToLogin()
    expect(requestLogin).toHaveBeenCalledWith('/mcp')
  })

  it('loads tokens on mount and disposes the controller on unmount', async () => {
    const wrapper = await mountView()
    expect(controller().loadTokens).toHaveBeenCalledTimes(1)
    expect(controller().dispose).not.toHaveBeenCalled()

    wrapper.unmount()
    expect(controller().dispose).toHaveBeenCalledTimes(1)
  })
})

describe('McpConnectView localized rendering', () => {
  it('renders hero and section headings through i18n messages', async () => {
    const wrapper = await mountView()
    const text = wrapper.text()

    expect(text).toContain('把 AIGC 雷达接入你的 Agent')
    expect(text).toContain('AIGC RADAR MCP')
    expect(text).toContain('公开端点')
    expect(text).toContain('选择客户端与终端')
    expect(text).toContain('复制接入命令')
    expect(text).toContain('验证连接')
    expect(text).toContain('在 dsh 中原生使用 AIGC Radar')
    expect(text).toContain('令牌管理')
    expect(text).toContain('工具清单 · 示例提问 · 路由规则')
    expect(text).toContain('MCP 优先路由')
    expect(text).toContain('AI 工程产物')
    expect(text).toContain('Streamable HTTP')
  })

  it('renders the normalized endpoint and triggers the public handshake', async () => {
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('https://aigcnews.cn/api/mcp')

    await wrapper.findAll('.mcp-step-dot')[2]!.trigger('click')
    await flushPromises()

    const handshake = wrapper.findAll('button').find((button) => button.text() === 'mcp.publicHandshake')
    expect(handshake).toBeDefined()
    expect(handshake!.attributes('disabled')).toBeUndefined()

    await handshake!.trigger('click')
    expect(controller().testPublicHandshake).toHaveBeenCalledTimes(1)
  })

  it('renders the public tool catalog with localized descriptions', async () => {
    const wrapper = await mountView()
    const text = wrapper.text()

    expect(text).toContain('search_github_ai_projects')
    expect(text).toContain('搜索站内精选 AI 项目')
    expect(text).toContain('search_papers')
    expect(text).toContain('检索 arXiv 论文')
  })

  it('orders hero, wizard and tokens ahead of the collapsed resources area', async () => {
    const wrapper = await mountView()
    const sections = wrapper.findAll('section')

    expect(sections.length).toBe(6)
    expect(sections[0]!.text()).toContain('公开端点')
    expect(sections[1]!.text()).toContain('选择客户端与终端')
    expect(sections[2]!.text()).toContain('在 dsh 中原生使用 AIGC Radar')
    expect(sections[3]!.text()).toContain('令牌管理')
    expect(sections[4]!.text()).toContain('search_github_ai_projects')
    expect(sections[5]!.text()).toContain('MCP 优先路由')
  })
})

describe('McpConnectView privacy and auth behavior', () => {
  it('renders the secret-free quick command visibly and forwards quick copy', async () => {
    controller().quickCommand.value = 'claude mcp add --scope user --transport http aigc-news https://aigcnews.cn/api/mcp'
    const wrapper = await mountView()
    await wrapper.findAll('.mcp-step-dot')[1]!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('claude mcp add --scope user --transport http aigc-news')
    const copyButton = wrapper.findAll('button').find((button) => button.text() === '复制配置命令')
    expect(copyButton).toBeDefined()
    expect(copyButton!.attributes('disabled')).toBeUndefined()

    await copyButton!.trigger('click')
    expect(controller().copyQuickCommand).toHaveBeenCalledTimes(1)
  })

  it('links to the standalone dsh page without rendering install commands', async () => {
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('在 dsh 中原生使用 AIGC Radar')
    expect(wrapper.findAll('[data-install-method]')).toHaveLength(0)
    const link = wrapper.get('a[href="/dsh"]')
    expect(link.text()).toContain('打开 dsh 安装页')
    expect(wrapper.text()).not.toContain('dsh-aigc-radar@0.2.0')
  })

  it('requests the login modal for anonymous visitors without rendering configuration', async () => {
    auth().status = 'anonymous'
    auth().isLoggedIn = false
    const wrapper = await mountView()

    expect(testRouter.currentRoute.value.path).toBe('/mcp')
    expect(requestLogin).toHaveBeenCalledWith('/mcp')
    expect(wrapper.find('.mcp-wizard').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('令牌管理')
    expect(controller().loadTokens).not.toHaveBeenCalled()
    expect(controller().clearAuthenticatedState).toHaveBeenCalledOnce()
  })

  it('never renders the transient command while offering one-time copy', async () => {
    controller().transientCommand.value = 'claude mcp add --header "Authorization: Bearer SECRET-TOKEN-VALUE"'
    const wrapper = await mountView()
    await wrapper.findAll('.mcp-step-dot')[1]!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('命令只显示一次')
    expect(wrapper.text()).not.toContain('SECRET-TOKEN-VALUE')
    expect(wrapper.html()).not.toContain('SECRET-TOKEN-VALUE')

    const copyButton = wrapper.findAll('button').find((button) => button.text() === '复制一次性命令')
    expect(copyButton).toBeDefined()
    await copyButton!.trigger('click')
    expect(controller().copyGeneratedCommand).toHaveBeenCalledTimes(1)
  })

  it('keeps the page fail-closed while authentication is initializing', async () => {
    auth().status = 'initializing'
    auth().isLoggedIn = false
    const wrapper = await mountView()

    expect(testRouter.currentRoute.value.path).toBe('/mcp')
    expect(wrapper.text()).toContain('正在恢复登录状态…')
    expect(wrapper.find('.mcp-wizard').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('令牌管理')
    expect(controller().loadTokens).not.toHaveBeenCalled()
    expect(controller().clearAuthenticatedState).toHaveBeenCalledOnce()

    auth().status = 'anonymous'
    await flushPromises()
    expect(testRouter.currentRoute.value.path).toBe('/mcp')
    expect(requestLogin).toHaveBeenCalledWith('/mcp')
  })

  it('keeps degraded authentication on the page without exposing configuration', async () => {
    auth().status = 'degraded'
    auth().isLoggedIn = false
    const wrapper = await mountView()

    expect(testRouter.currentRoute.value.path).toBe('/mcp')
    expect(wrapper.text()).toContain('登录状态校验失败。为安全起见，确认前不会签发 MCP Token。')
    expect(wrapper.find('.mcp-wizard').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('令牌管理')
    expect(controller().loadTokens).not.toHaveBeenCalled()
    expect(controller().clearAuthenticatedState).toHaveBeenCalledOnce()

    const retry = wrapper.findAll('button').find((button) => button.text() === '重试')
    expect(retry).toBeDefined()
    await retry!.trigger('click')
    expect(auth().initFromStorage).toHaveBeenCalledOnce()
  })

  it('renders tokens from controller state and forwards removal', async () => {
    const token = {
      id: 3,
      client_label: '工作笔记本',
      client_type: 'claude-code',
      token_hint: 'aigc_...9f',
      created_at: '2026-07-01T08:00:00Z',
      last_used_at: null,
    }
    controller().tokens.value = [token]
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('工作笔记本')
    expect(wrapper.text()).toContain('aigc_...9f')
    expect(wrapper.text()).toContain('有效')

    const deleteButton = wrapper.findAll('button').find((button) => button.text() === 'common.delete')
    expect(deleteButton).toBeDefined()
    await deleteButton!.trigger('click')
    expect(controller().removeToken).toHaveBeenCalledWith(token)
  })
})

describe('McpConnectView quota upsell notice', () => {
  it('does not render account quota controls before authentication is confirmed', async () => {
    auth().status = 'initializing'
    auth().isLoggedIn = false
    const wrapper = await mountView()

    expect(wrapper.find('a[href="/membership"]').exists()).toBe(false)
    expect(wrapper.find('a[href="/mcp"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('MCP 匿名额度按 IP 计：每 24 小时 30 次')
    expect(controller().loadTokens).not.toHaveBeenCalled()
  })

  it('prompts free-tier users to open VIP for a higher quota', async () => {
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('当前 Free 的 MCP/API 共用额度：每 24 小时 60 次 + 滚动 30 天 1,200 次')
    const cta = wrapper.get('a[href="/membership"]')
    expect(cta.text()).toContain('开通 vip')
  })

  it('hides the notice for active VIP members', async () => {
    auth().isMember = true
    const wrapper = await mountView()

    expect(wrapper.text()).not.toContain('开通 vip')
    expect(wrapper.find('a[href="/membership"]').exists()).toBe(false)
  })
})
