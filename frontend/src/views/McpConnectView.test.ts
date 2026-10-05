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
// 桌面（≥1024px）打开就是接入命令台，手机与平板仍是三步向导；jsdom 没有 matchMedia，按标志切换。
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
    clientOption: ref({ id: 'claude-code', label: 'Claude Code', format: 'claude-cli', setupScope: 'user', configPathKey: 'mcp.pathClaude', descriptionKey: 'mcp.clients.claude-code.description' }),
    copiedKey: ref(''),
    copyAgentSetupPrompt: vi.fn(),
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
    isLoggedIn: ref(true),
    loadTokens: vi.fn(),
    loadingTokens: ref(false),
    normalizedEndpoint: ref('https://aigcnews.cn/api/mcp'),
    quickCommand: ref(''),
    removeToken: vi.fn(),
    requestLogin: vi.fn(),
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
        loginRequiredTitle: '登录后管理 Token 与收藏授权',
        loginRequiredDescription: '游客可查看本页并选择客户端；创建或删除 Token、生成含账号凭证的命令与个人收藏授权需要登录。',
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
          free: '当前 Free 的 MCP/API 共用额度：每 24 小时 60 次 + 每 30 天 1,200 次；开通 vip 升至 400 次 + 8,000 次。',
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
      mcpAutoCommand: {
        label: '账号配置命令 · 自动包含 Token', description: '自动生成带 Token 的命令。',
        creating: '正在创建专属 MCP Token 并生成配置命令…', ready: '配置命令已自动包含你的 MCP Token', copy: '复制配置命令',
        copyAgentPrompt: '复制给 Agent 的配置提示词', agentPromptHint: '粘贴给 Agent 自动配置。',
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
  controller().isLoggedIn.value = true
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
    controller().requestLogin,
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
    expect(text).not.toContain('公开端点')
    expect(text).toContain('选择客户端与终端')
    expect(text).toContain('复制接入命令')
    expect(text).toContain('验证连接')
    expect(text).not.toContain('在 dsh 中原生使用 AIGC Radar')
    expect(text).not.toContain('令牌管理')
    expect(text).not.toContain('工具清单 · 示例提问 · 路由规则')
    expect(text).not.toContain('MCP 优先路由')
    expect(text).toContain('Streamable HTTP')
  })

  it('shows the endpoint only in the verification step and triggers the handshake', async () => {
    const wrapper = await mountView()

    expect(wrapper.text()).not.toContain('https://aigcnews.cn/api/mcp')

    await wrapper.findAll('.mcp-step-dot')[2]!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('https://aigcnews.cn/api/mcp')

    const handshake = wrapper.findAll('button').find((button) => button.text() === 'mcp.publicHandshake')
    expect(handshake).toBeDefined()
    expect(handshake!.attributes('disabled')).toBeUndefined()

    await handshake!.trigger('click')
    expect(controller().testPublicHandshake).toHaveBeenCalledTimes(1)
  })

  it('keeps the hero, wizard and authenticated token controls in order', async () => {
    const wrapper = await mountView()
    const sections = wrapper.findAll('section')

    expect(sections.length).toBe(2)
    expect(sections[0]!.text()).toContain('AIGC RADAR MCP')
    expect(sections[1]!.text()).toContain('选择客户端与终端')
    expect(wrapper.text()).not.toContain('令牌管理')
  })
})

describe('McpConnectView privacy and auth behavior', () => {
  it('automatically starts authenticated command creation on the command step', async () => {
    const wrapper = await mountView()
    await wrapper.findAll('.mcp-step-dot')[1]!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('账号配置命令 · 自动包含 Token')
    expect(controller().startSetup).toHaveBeenCalledOnce()
    expect(wrapper.text()).not.toContain('收藏授权')
  })

  it('renders the guest shell for anonymous visitors without requesting login on mount', async () => {
    auth().status = 'anonymous'
    auth().isLoggedIn = false
    controller().isLoggedIn.value = false
    const wrapper = await mountView()

    expect(testRouter.currentRoute.value.path).toBe('/mcp')
    expect(requestLogin).not.toHaveBeenCalled()
    // 游客可查看向导并选择客户端；Token API 不被触发
    expect(wrapper.find('.mcp-wizard').exists()).toBe(true)
    expect(wrapper.text()).toContain('选择客户端与终端')
    expect(controller().loadTokens).not.toHaveBeenCalled()
    expect(controller().clearAuthenticatedState).toHaveBeenCalledOnce()

    // 游客页面只保留介绍和接入向导，登录在向导下一步按需触发。
    expect(wrapper.findAll('section')).toHaveLength(2)
    expect(wrapper.text()).not.toContain('登录后管理 Token 与收藏授权')
    expect(wrapper.find('.mcp-token-list').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('登录提升额度')
  })

  it('gates wizard forward navigation behind the login prompt for guests', async () => {
    auth().status = 'anonymous'
    auth().isLoggedIn = false
    controller().isLoggedIn.value = false
    const wrapper = await mountView()

    // 游客点「下一步」/前方步骤点：弹登录、停留在第 1 步
    await wrapper.findAll('.mcp-step-dot')[1]!.trigger('click')
    await flushPromises()
    expect(controller().requestLogin).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('第 1 步 · 共 3 步')

    // 登录完成后即可前进
    controller().isLoggedIn.value = true
    await wrapper.findAll('.mcp-step-dot')[1]!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('第 2 步 · 共 3 步')
  })

  it('never renders the transient command while offering one-time copy', async () => {
    controller().transientCommand.value = 'claude mcp add --header "Authorization: Bearer SECRET-TOKEN-VALUE"'
    const wrapper = await mountView()
    await wrapper.findAll('.mcp-step-dot')[1]!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('配置命令已自动包含你的 MCP Token')
    expect(wrapper.text()).not.toContain('SECRET-TOKEN-VALUE')
    expect(wrapper.html()).not.toContain('SECRET-TOKEN-VALUE')

    const copyButton = wrapper.findAll('button').find((button) => button.text() === '复制配置命令')
    expect(copyButton).toBeDefined()
    await copyButton!.trigger('click')
    expect(controller().copyGeneratedCommand).toHaveBeenCalledTimes(1)

    const agentPromptButton = wrapper.findAll('button').find((button) => button.text() === '复制给 Agent 的配置提示词')
    expect(agentPromptButton).toBeDefined()
    await agentPromptButton!.trigger('click')
    expect(controller().copyAgentSetupPrompt).toHaveBeenCalledTimes(1)
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
    controller().isLoggedIn.value = false
    await flushPromises()
    // 异步恢复为游客：页面留在 /mcp 并渲染游客壳，不再强制弹登录
    expect(testRouter.currentRoute.value.path).toBe('/mcp')
    expect(requestLogin).not.toHaveBeenCalled()
    expect(wrapper.find('.mcp-wizard').exists()).toBe(true)
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

  it('omits the token management list while preserving token creation and auth cleanup', async () => {
    controller().tokens.value = [{ id: 3, client_label: '工作笔记本', token_hint: 'aigc_...9f' }]
    const wrapper = await mountView()
    expect(wrapper.find('.mcp-token-list').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('工作笔记本')
    expect(controller().removeToken).not.toHaveBeenCalled()
    expect(controller().loadTokens).toHaveBeenCalledOnce()

    await wrapper.findAll('.mcp-step-dot')[1]!.trigger('click')
    await flushPromises()
    expect(controller().startSetup).toHaveBeenCalledOnce()

    auth().status = 'anonymous'
    auth().isLoggedIn = false
    await flushPromises()
    expect(controller().clearAuthenticatedState).toHaveBeenCalledOnce()
  })
})

describe('McpConnectView quota upsell notice', () => {
  it('does not render account quota controls before authentication is confirmed', async () => {
    auth().status = 'initializing'
    auth().isLoggedIn = false
    const wrapper = await mountView()

    expect(wrapper.find('a[href="/membership"]').exists()).toBe(false)
    expect(wrapper.find('a[href="/mcp"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('开通 vip')
    expect(wrapper.text()).not.toContain('当前 Free 的')
    expect(controller().loadTokens).not.toHaveBeenCalled()
  })

  it('prompts free-tier users to open VIP for a higher quota', async () => {
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('当前 Free 的 MCP/API 共用额度：每 24 小时 60 次 + 每 30 天 1,200 次')
    const cta = wrapper.get('a[href="/membership"]')
    expect(cta.text()).toContain('开通 vip')
  })

  it('hides quota notices and the token login card for guests', async () => {
    auth().status = 'anonymous'
    auth().isLoggedIn = false
    controller().isLoggedIn.value = false
    const wrapper = await mountView()

    // 网站不向游客推介匿名额度：按 IP 匿名桶只是 GitHub/NPM 发布渠道
    // （插件开箱即用）的默认体验，不在站内展示
    expect(wrapper.text()).not.toContain('开通 vip')
    expect(wrapper.text()).not.toContain('当前 Free 的')
    expect(wrapper.find('a[href="/membership"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('登录后管理 Token 与收藏授权')
    expect(wrapper.text()).not.toContain('登录提升额度')
  })

  it('hides the notice for active VIP members', async () => {
    auth().isMember = true
    const wrapper = await mountView()

    expect(wrapper.text()).not.toContain('开通 vip')
    expect(wrapper.find('a[href="/membership"]').exists()).toBe(false)
  })
})

describe('McpConnectView on desktop', () => {
  beforeEach(() => { viewport.desktop = true })
  afterEach(() => { viewport.desktop = false })

  it('opens on the command desk with the stats strip instead of the step wizard', async () => {
    const wrapper = await mountView()

    expect(wrapper.find('.mcp-desk').exists()).toBe(true)
    expect(wrapper.find('.mcp-wizard').exists()).toBe(false)
    expect(wrapper.findAll('.mcp-stats .mcp-stat')).toHaveLength(4)
    expect(wrapper.get('.command-preview-term').text()).toContain('mcp add --scope user --transport http aigc-news')
    expect(controller().startSetup).not.toHaveBeenCalled()
  })

  it('keeps the one-time command off the page on the desk too', async () => {
    controller().transientCommand.value = 'claude mcp add --header "Authorization: Bearer SECRET-TOKEN-VALUE"'
    const wrapper = await mountView()

    expect(wrapper.find('.command-slot--filled').exists()).toBe(true)
    expect(wrapper.html()).not.toContain('SECRET-TOKEN-VALUE')
  })
})
