import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import McpSetupWizard from '@/components/mcp/McpSetupWizard.vue'

const buildController = () => ({
  clientDisplayLabel: vi.fn((client: { id: string }) => client.id),
  clientLabel: ref(''),
  clientOption: ref({ id: 'claude-code', setupScope: 'user', configPathKey: 'mcp.pathClaude' }),
  copiedKey: ref(''),
  copyGeneratedCommand: vi.fn(),
  copyQuickCommand: vi.fn(),
  creating: ref(false),
  endpointUrl: ref('https://aigcnews.cn/api/mcp'),
  endpointWarningKey: ref(''),
  normalizedEndpoint: ref('https://aigcnews.cn/api/mcp'),
  quickCommand: ref(''),
  selectedClient: ref('claude-code'),
  selectedShell: ref('bash'),
  setupError: ref(null),
  setupNotice: ref(null),
  startSetup: vi.fn(),
  testing: ref(false),
  testMessage: ref(null),
  testPhases: ref([]),
  testPublicHandshake: vi.fn(),
  transientCommand: ref(''),
})

const ctl = () => controllerBox as ReturnType<typeof buildController>
let controllerBox: ReturnType<typeof buildController>

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      mcp: {
        chooseClient: '客户端与终端',
        terminal: '运行命令的终端',
        quickCommandLabel: '生成的配置命令 · 无密钥',
        copyQuick: '复制配置命令',
        copied: '已复制',
        publicEndpoint: '公开端点',
        endpointAria: 'MCP 端点',
        publicHandshake: '公开握手',
        testing: '测试中…',
        favoritesAuth: '收藏授权',
        permission: '权限：读取我的项目收藏',
        bearerMemory: 'Token 仅存内存。',
        deviceLabel: '设备备注（可选）',
        multipleTokens: '不同设备可创建多个 Token。',
        creating: '创建中…',
        generateCommand: '生成用户级配置命令',
        bearerWarning: '命令只显示一次',
        bearerWarningDetail: '粘贴运行后可能进入 shell 历史。',
        hiddenConfig: '配置内容不渲染到页面。{result}',
        copyOneTime: '复制一次性命令',
        copiedClipboard: '已复制到剪贴板',
        resultClaudeCode: '写入 Claude Code 用户级 MCP 配置。',
        hintClaudeCode: '随后可运行 claude mcp list 验证。',
        loginRequiredTitle: '登录后授权个人收藏',
        loginRequiredDescription: '公开端点仍可查看与测试。',
        loginToConfigure: '登录后配置',
        scope: { user: '用户级' },
        commandPrompt: '命令提示符',
        wizard: {
          ariaLabel: 'MCP 接入向导',
          stepClient: '选择客户端与终端',
          stepCommand: '复制接入命令',
          stepVerify: '验证连接',
          stepClientDescription: '第 1 步：选择客户端。',
          stepCommandDescription: '第 2 步：复制命令。',
          stepVerifyDescription: '第 3 步：验证。',
          prev: '上一步',
          next: '下一步',
          stepProgress: '第 {current} 步 · 共 {total} 步',
          resourcesToggle: '工具清单 · 示例提问 · 路由规则',
        },
        dshPlugin: {
          kicker: 'DSH 插件',
          title: 'dsh 终端用户：一条命令接入',
          description: 'dsh-aigc-radar 是 dsh 终端的原生插件。',
          copy: '复制安装命令',
          repository: 'GitHub 仓库',
        },
      },
    },
  },
  missingWarn: false,
  fallbackWarn: false,
})

const mountWizard = async (isLoggedIn = true) => {
  const wrapper = mount(McpSetupWizard, {
    props: { controller: ctl() as any, isLoggedIn },
    global: { plugins: [i18n] },
  })
  await flushPromises()
  return wrapper
}

const buttonByText = (wrapper: VueWrapper, text: string) =>
  wrapper.findAll('button').find((button) => button.text().includes(text))

const nextButton = (wrapper: VueWrapper) => buttonByText(wrapper, '下一步')
const prevButton = (wrapper: VueWrapper) => buttonByText(wrapper, '上一步')

beforeEach(() => {
  controllerBox = buildController()
})

describe('McpSetupWizard navigation', () => {
  it('starts on the client step with the full client catalog and prev disabled', async () => {
    const wrapper = await mountWizard()

    expect(wrapper.text()).toContain('第 1 步 · 共 3 步')
    expect(wrapper.text()).toContain('客户端与终端')
    expect(wrapper.findAll('.mcp-step-dot')).toHaveLength(3)
    expect(wrapper.findAll('.mcp-choice').length).toBeGreaterThanOrEqual(9)
    expect(prevButton(wrapper)!.attributes('disabled')).toBeDefined()
    expect(nextButton(wrapper)!.attributes('disabled')).toBeUndefined()
  })

  it('walks forward with next and backward with prev, keeping controller selections', async () => {
    const wrapper = await mountWizard()

    await nextButton(wrapper)!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('第 2 步 · 共 3 步')
    expect(wrapper.text()).toContain('生成的配置命令')

    await nextButton(wrapper)!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('第 3 步 · 共 3 步')

    await prevButton(wrapper)!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('第 2 步 · 共 3 步')
    expect(ctl().selectedClient.value).toBe('claude-code')
  })

  it('jumps via the step indicator and disables next on the final step', async () => {
    const wrapper = await mountWizard()
    const dots = wrapper.findAll('.mcp-step-dot')

    await dots[2]!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('第 3 步 · 共 3 步')
    expect(wrapper.text()).toContain('公开端点')
    expect(nextButton(wrapper)!.attributes('disabled')).toBeDefined()
    expect(prevButton(wrapper)!.attributes('disabled')).toBeUndefined()

    await wrapper.findAll('.mcp-step-dot')[0]!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('第 1 步 · 共 3 步')
  })
})

describe('McpSetupWizard step content', () => {
  it('renders the quick command and forwards quick copy on the command step', async () => {
    ctl().quickCommand.value = 'claude mcp add --scope user --transport http aigc-news https://aigcnews.cn/api/mcp'
    const wrapper = await mountWizard()
    await nextButton(wrapper)!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('claude mcp add --scope user --transport http aigc-news')
    const copyButton = buttonByText(wrapper, '复制配置命令')
    expect(copyButton).toBeDefined()
    await copyButton!.trigger('click')
    expect(ctl().copyQuickCommand).toHaveBeenCalledTimes(1)
  })

  it('runs the public handshake from the verify step', async () => {
    const wrapper = await mountWizard()
    await wrapper.findAll('.mcp-step-dot')[2]!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('https://aigcnews.cn/api/mcp')
    const handshake = buttonByText(wrapper, '公开握手')
    expect(handshake).toBeDefined()
    await handshake!.trigger('click')
    expect(ctl().testPublicHandshake).toHaveBeenCalledTimes(1)
  })

  it('emits login from the command step CTA when logged out', async () => {
    const wrapper = await mountWizard(false)
    await nextButton(wrapper)!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('登录后授权个人收藏')
    await buttonByText(wrapper, '登录后配置')!.trigger('click')
    expect(wrapper.emitted('login')).toHaveLength(1)
  })

  it('never renders the transient command while offering one-time copy', async () => {
    ctl().transientCommand.value = 'claude mcp add --header "Authorization: Bearer SECRET-TOKEN-VALUE"'
    const wrapper = await mountWizard()
    await nextButton(wrapper)!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('命令只显示一次')
    expect(wrapper.html()).not.toContain('SECRET-TOKEN-VALUE')
    await buttonByText(wrapper, '复制一次性命令')!.trigger('click')
    expect(ctl().copyGeneratedCommand).toHaveBeenCalledTimes(1)
  })
})
