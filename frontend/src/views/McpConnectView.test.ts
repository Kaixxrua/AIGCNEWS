import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import McpConnectView from './McpConnectView.vue'

const controllerSpy = vi.hoisted(() => vi.fn())
const clipboardCopy = vi.hoisted(() => vi.fn())
const ctlBox = vi.hoisted(() => ({ current: null as null | Record<string, any> }))
const authBox = vi.hoisted(() => ({ current: null as null | { isLoggedIn: boolean; isAdmin: boolean } }))

vi.mock('@/stores/authStore', async () => {
  const { reactive } = await import('vue')
  if (!authBox.current) authBox.current = reactive({ isLoggedIn: true, isAdmin: false })
  return { useAuthStore: () => authBox.current }
})

vi.mock('@/composables/useClipboard', () => ({
  useClipboard: () => ({ copy: clipboardCopy }),
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
        tokenManagement: '令牌管理',
        routing: 'MCP 优先路由',
        aiArtifacts: 'AI 工程产物',
        streamableHttp: 'Streamable HTTP',
        publicTools: '公开工具',
        privateFavorites: '私有收藏',
        toolSearchAi: '搜索站内精选 AI 项目',
        toolSearchPapers: '检索 arXiv 论文',
        loginToConfigure: '登录后配置',
        bearerWarning: '命令只显示一次',
        copyOneTime: '复制一次性命令',
        valid: '有效',
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
    { path: '/login', name: 'login', component: { template: '<div />' } },
  ],
})

const mountView = async () => {
  await testRouter.push('/mcp')
  await testRouter.isReady()
  const wrapper = mount(McpConnectView, { global: { plugins: [testRouter, i18n] } })
  await flushPromises()
  return wrapper
}

const controller = () => ctlBox.current as Record<string, any>
const auth = () => authBox.current as { isLoggedIn: boolean; isAdmin: boolean }

beforeEach(() => {
  controller().clientLabel.value = ''
  controller().copiedKey.value = ''
  controller().creating.value = false
  controller().deletingId.value = null
  controller().endpointWarningKey.value = ''
  controller().loadingTokens.value = false
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
    controller().copyGeneratedCommand,
    controller().copyHostInstruction,
    controller().dispose,
    controller().loadTokens,
    controller().removeToken,
    controller().startSetup,
    controller().testPublicHandshake,
    controller().tokenStatus,
  ]) {
    fn.mockClear()
  }
  auth().isLoggedIn = true
  controllerSpy.mockClear()
  clipboardCopy.mockClear()
})

describe('McpConnectView controller boundary', () => {
  it('hands clipboard, auth, navigation and translate seams to the controller', async () => {
    const pushSpy = vi.spyOn(testRouter, 'push')
    await mountView()

    expect(controllerSpy).toHaveBeenCalledOnce()
    const init = controllerSpy.mock.calls[0]![0]
    expect(init.copy).toBe(clipboardCopy)
    expect(init.isLoggedIn()).toBe(true)
    expect(typeof init.translate).toBe('function')

    await init.navigateToLogin()
    expect(pushSpy).toHaveBeenCalledWith('/login')
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
    expect(text).toContain('鉴权配置')
    expect(text).toContain('令牌管理')
    expect(text).toContain('MCP 优先路由')
    expect(text).toContain('AI 工程产物')
    expect(text).toContain('Streamable HTTP')
  })

  it('renders the normalized endpoint and triggers the public handshake', async () => {
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('https://aigcnews.cn/api/mcp')
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
})

describe('McpConnectView privacy and auth behavior', () => {
  it('never renders the transient command while offering one-time copy', async () => {
    controller().transientCommand.value = 'claude mcp add --header "Authorization: Bearer SECRET-TOKEN-VALUE"'
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('命令只显示一次')
    expect(wrapper.text()).not.toContain('SECRET-TOKEN-VALUE')
    expect(wrapper.html()).not.toContain('SECRET-TOKEN-VALUE')

    const copyButton = wrapper.findAll('button').find((button) => button.text() === '复制一次性命令')
    expect(copyButton).toBeDefined()
    await copyButton!.trigger('click')
    expect(controller().copyGeneratedCommand).toHaveBeenCalledTimes(1)
  })

  it('shows the login call-to-action when logged out and routes to login', async () => {
    auth().isLoggedIn = false
    const pushSpy = vi.spyOn(testRouter, 'push')
    const wrapper = await mountView()

    const loginButton = wrapper.findAll('button').find((button) => button.text() === '登录后配置')
    expect(loginButton).toBeDefined()
    expect(wrapper.text()).not.toContain('令牌管理')

    await loginButton!.trigger('click')
    expect(pushSpy).toHaveBeenCalledWith('/login')
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
