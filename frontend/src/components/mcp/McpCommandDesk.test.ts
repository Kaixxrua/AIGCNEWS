import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { ref } from 'vue'
import { createI18n } from 'vue-i18n'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { messages } from '@/i18n'
import { useMcpConnectController, type McpConnectApi, type McpConnectHandshake } from '@/composables/useMcpConnectController'
import { mcpClientOptions } from '@/features/mcp/mcpClientCatalog'
import type { McpTokenMetadata } from '@/services/mcp/mcpTokenApi'
import McpCommandDesk from './McpCommandDesk.vue'

// 桌面版接入命令台用真实控制器 + 假 API：命令模板打开就在，Token 处是占位，真实 Token 只进剪贴板。
const SECRET = 'aigc_mcp_SECRET_VALUE_42'
const ENDPOINT = 'https://aigcnews.cn/api/mcp'
const metadata: McpTokenMetadata = {
  id: 7,
  token_hint: 'aigc_mcp_abc...wxyz',
  scopes: ['projects:favorites:read'],
  client_type: 'claude',
  client_label: 'Claude Code',
  expires_at: null,
  revoked_at: null,
}

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages, missingWarn: false, fallbackWarn: false })

const mounted: VueWrapper[] = []
afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
})

const mountDesk = ({ signedIn = true, createMcpToken }: { signedIn?: boolean; createMcpToken?: McpConnectApi['createMcpToken'] } = {}) => {
  const session = ref(signedIn)
  const navigateToLogin = vi.fn()
  const copy = vi.fn(async (_value: string) => undefined)
  const handshake = vi.fn<McpConnectHandshake>(async () => [])
  const api: McpConnectApi = {
    fetchMcpTokens: vi.fn(async () => []),
    createMcpToken: createMcpToken ?? vi.fn(async () => ({ token: SECRET, token_metadata: metadata, replaced_count: 0 })),
    deleteMcpToken: vi.fn(async (id: number) => ({ deleted: true, id })),
  }
  const controller = useMcpConnectController({
    api,
    copy,
    handshake,
    navigateToLogin,
    defaultEndpoint: ENDPOINT,
    isLoggedIn: () => session.value,
    translate: (key, params) => i18n.global.t(key, params ?? {}),
    confirm: () => true,
  })
  const wrapper = mount(McpCommandDesk, { props: { controller }, global: { plugins: [i18n] } })
  mounted.push(wrapper)
  return { wrapper, api, copy, handshake, navigateToLogin }
}

const button = (wrapper: VueWrapper, label: string) => {
  const found = wrapper.findAll('button').find((candidate) => candidate.text() === label)
  if (!found) throw new Error(`no button labelled ${label}`)
  return found
}
const terminal = (wrapper: VueWrapper) => wrapper.get('.command-preview-term')
const side = (wrapper: VueWrapper) => wrapper.get('.mcp-desk-side')

describe('McpCommandDesk', () => {
  it('shows the Claude Code command template and a login-to-copy action to guests', async () => {
    const { wrapper, api, navigateToLogin } = mountDesk({ signedIn: false })

    const clients = wrapper.findAll('.mcp-desk-clients .mcp-desk-tab')
    expect(clients).toHaveLength(mcpClientOptions.length)
    expect(wrapper.get('.mcp-desk-clients [aria-pressed="true"]').text()).toBe('Claude Code')
    expect(terminal(wrapper).text()).toContain(`mcp add --scope user --transport http aigc-news '${ENDPOINT}'`)
    expect(wrapper.get('.command-slot').text()).toBe('你的 Token')
    expect(wrapper.find('[data-desk-action="generate"]').exists()).toBe(false)

    await button(wrapper, '登录后复制命令').trigger('click')
    expect(navigateToLogin).toHaveBeenCalledOnce()
    expect(api.createMcpToken).not.toHaveBeenCalled()
  })

  it('swaps the command and its target when another client tab is picked', async () => {
    const { wrapper } = mountDesk()

    await button(wrapper, 'Cursor').trigger('click')

    expect(wrapper.get('.mcp-desk-clients [aria-pressed="true"]').text()).toBe('Cursor')
    expect(wrapper.get('.mcp-desk-path').text()).toBe('.cursor/aigc-news.mcp.import.json')
    expect(terminal(wrapper).text()).toContain('aigc-news.mcp.import.json')
    expect(terminal(wrapper).text()).not.toContain('mcp add --scope user')
  })

  it('creates a token on demand and keeps the real command off the page', async () => {
    const { wrapper, api, copy } = mountDesk()
    expect(api.createMcpToken).not.toHaveBeenCalled()

    await wrapper.get('[data-desk-action="generate"]').trigger('click')
    await flushPromises()

    expect(api.createMcpToken).toHaveBeenCalledOnce()
    expect(side(wrapper).classes()).toContain('mcp-desk-side--ready')
    expect(wrapper.get('.command-slot--filled').text()).toBe('Token 已填入')
    expect(wrapper.html()).not.toContain(SECRET)

    await button(wrapper, '复制配置命令').trigger('click')
    await flushPromises()
    expect(copy).toHaveBeenCalledTimes(1)
    expect(copy.mock.calls[0]![0]).toContain(`Authorization: Bearer ${SECRET}`)

    await button(wrapper, '复制给 Agent 的配置提示词').trigger('click')
    await flushPromises()
    expect(copy).toHaveBeenCalledTimes(2)
    expect(copy.mock.calls[1]![0]).toContain(SECRET)
    expect(wrapper.html()).not.toContain(SECRET)
  })

  it('drops the generated command once the client or the terminal changes', async () => {
    const { wrapper } = mountDesk()
    await wrapper.get('[data-desk-action="generate"]').trigger('click')
    await flushPromises()
    expect(side(wrapper).classes()).toContain('mcp-desk-side--ready')

    await button(wrapper, 'Codex').trigger('click')

    expect(side(wrapper).classes()).toContain('mcp-desk-side--idle')
    expect(wrapper.find('.command-slot--filled').exists()).toBe(false)
    expect(wrapper.find('[data-desk-action="generate"]').exists()).toBe(true)
  })

  it('draws the command prompt version as one encoded-script slot', async () => {
    const { wrapper } = mountDesk()

    await button(wrapper, '命令提示符').trigger('click')

    expect(terminal(wrapper).text()).toContain('powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand')
    expect(terminal(wrapper).text()).not.toMatch(/-EncodedCommand\s+[A-Za-z0-9+/]/)
    expect(wrapper.get('.command-slot--encoded').text()).toBe('编码脚本 · 含 Token')
  })

  it('shows the failure and retries from the side card', async () => {
    const createMcpToken = vi.fn(async () => { throw new Error('boom') })
    const { wrapper } = mountDesk({ createMcpToken })

    await wrapper.get('[data-desk-action="generate"]').trigger('click')
    await flushPromises()

    expect(side(wrapper).classes()).toContain('mcp-desk-side--error')
    expect(side(wrapper).text()).toContain('boom')

    await side(wrapper).get('.btn-primary').trigger('click')
    await flushPromises()
    expect(createMcpToken).toHaveBeenCalledTimes(2)
  })

  it('runs the public handshake against the endpoint from the verify row', async () => {
    const { wrapper, handshake } = mountDesk({ signedIn: false })

    expect((wrapper.get('.mcp-desk-endpoint').element as HTMLInputElement).value).toBe(ENDPOINT)
    await button(wrapper, '公开握手').trigger('click')
    await flushPromises()

    expect(handshake).toHaveBeenCalledOnce()
    expect(handshake.mock.calls[0]![0]).toBe(ENDPOINT)
    expect(wrapper.findAll('.mcp-desk-phase')).toHaveLength(3)
  })
})
