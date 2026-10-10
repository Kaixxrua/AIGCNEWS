import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import i18n from '@/i18n'
import type { McpTokenMetadata } from '@/services/mcp/mcpTokenApi'
import McpAgentSetup from './McpAgentSetup.vue'

const copyToClipboard = vi.hoisted(() => vi.fn())
const copySensitiveToClipboard = vi.hoisted(() => vi.fn())
const fetchMcpTokens = vi.hoisted(() => vi.fn())
const requestLogin = vi.hoisted(() => vi.fn())
const showToast = vi.hoisted(() => vi.fn())
const authBox = vi.hoisted(() => ({ current: null as null | { status: string; isLoggedIn: boolean; isMember: boolean } }))

vi.mock('@/stores/authStore', async () => {
  const { reactive } = await import('vue')
  authBox.current ??= reactive({ status: 'anonymous', isLoggedIn: false, isMember: false })
  return { useAuthStore: () => authBox.current }
})
vi.mock('@/composables/useClipboard', () => ({ copyToClipboard, copySensitiveToClipboard }))
vi.mock('@/services/mcp/mcpTokenApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/mcp/mcpTokenApi')>()),
  fetchMcpTokens,
}))
vi.mock('@/composables/useLoginPrompt', () => ({ useLoginPrompt: () => ({ requestLogin }) }))
vi.mock('@/composables/useToast', () => ({ showToast }))

const auth = () => authBox.current!
const signIn = (member = false) => Object.assign(auth(), { status: 'authenticated', isLoggedIn: true, isMember: member })

const token = (patch: Partial<McpTokenMetadata> = {}): McpTokenMetadata => ({
  id: 51, token_hint: 'aigc_mcp_…f00d', scopes: ['favorites:read'], client_type: 'other', client_label: 'Claude Code',
  expires_at: null, revoked_at: null, created_at: new Date().toISOString(), last_used_at: null, ...patch,
})

const mounted: VueWrapper[] = []
// 挂到 document 上：jsdom 给游离节点算的样式会缓存，v-show 切换后 isVisible 读到的还是旧值。
const mountSetup = async () => {
  const wrapper = mount(McpAgentSetup, { global: { plugins: [i18n] }, attachTo: document.body })
  mounted.push(wrapper)
  await flushPromises()
  return wrapper
}
const cta = (wrapper: VueWrapper) => wrapper.get('.agent-setup-cta')

beforeEach(() => {
  i18n.global.locale.value = 'zh-CN'
  Object.assign(auth(), { status: 'anonymous', isLoggedIn: false, isMember: false })
  copyToClipboard.mockReset().mockResolvedValue(undefined)
  copySensitiveToClipboard.mockReset().mockResolvedValue(undefined)
  fetchMcpTokens.mockReset().mockResolvedValue([])
  requestLogin.mockReset()
  showToast.mockReset()
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  sessionStorage.clear()
})

describe('McpAgentSetup', () => {
  it('lets guests copy the prompt, which carries no token, without signing in', async () => {
    const wrapper = await mountSetup()
    expect(cta(wrapper).text()).toBe('复制给 Agent 的配置提示词')

    await cta(wrapper).trigger('click')
    await flushPromises()

    expect(copyToClipboard).toHaveBeenCalledOnce()
    const prompt = copyToClipboard.mock.calls[0]![0] as string
    expect(prompt).toContain('https://aigcnews.cn/api/mcp/oauth')
    expect(prompt).not.toMatch(/aigc_mcp_|Bearer/)
    expect(copySensitiveToClipboard).not.toHaveBeenCalled()
    expect(requestLogin).not.toHaveBeenCalled()
    expect(cta(wrapper).text()).toBe('已复制，去粘给你的 Agent')
    // 游客读不了自己的令牌列表：不回显，也不去查。
    expect(fetchMcpTokens).not.toHaveBeenCalled()
    expect(wrapper.find('.token-connection').exists()).toBe(false)
  })

  it('offers guests a sign-in to see the status', async () => {
    const wrapper = await mountSetup()
    await wrapper.get('.agent-setup-hint .agent-setup-link').trigger('click')
    expect(requestLogin).toHaveBeenCalledWith('/mcp')
  })

  it('shows the full prompt behind the toggle, with no token in the page', async () => {
    const wrapper = await mountSetup()
    const toggle = wrapper.get('.agent-setup-toggle')
    const region = wrapper.get(`#${toggle.attributes('aria-controls')}`)
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(region.isVisible()).toBe(false)

    await toggle.trigger('click')
    await nextTick()

    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(toggle.text()).toBe('收起提示词')
    expect(region.isVisible()).toBe(true)
    expect(region.text()).toContain('https://aigcnews.cn/api/mcp/oauth')
    expect(wrapper.html()).not.toMatch(/aigc_mcp_[A-Za-z0-9]/)
  })

  it('waits for the new connection after a signed-in reader copies, then reports the tier', async () => {
    signIn()
    fetchMcpTokens.mockResolvedValueOnce([]).mockResolvedValue([token({ last_used_at: new Date().toISOString() })])
    const wrapper = await mountSetup()
    expect(wrapper.find('.token-connection').exists()).toBe(false)

    await cta(wrapper).trigger('click')
    await flushPromises()
    expect(fetchMcpTokens).toHaveBeenCalledOnce()
    expect(wrapper.get('.token-connection').attributes('data-connection')).toBe('waiting')

    await wrapper.get('[data-connection-action="check"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('.token-connection').attributes('data-connection')).toBe('connected')
    expect(wrapper.get('.agent-setup-tier').text()).toBe('当前档位 Free：每 24 小时 10 次、每 30 天 200 次。')
  })

  it('reports the member tier to a vip', async () => {
    signIn(true)
    fetchMcpTokens.mockResolvedValueOnce([]).mockResolvedValue([token({ last_used_at: new Date().toISOString() })])
    const wrapper = await mountSetup()
    await cta(wrapper).trigger('click')
    await flushPromises()
    await wrapper.get('[data-connection-action="check"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('.agent-setup-tier').text()).toBe('当前档位 vip：每 24 小时 200 次、每 30 天 4,000 次。')
  })

  it('stops watching when the reader signs out', async () => {
    signIn()
    const wrapper = await mountSetup()
    await cta(wrapper).trigger('click')
    await flushPromises()
    expect(wrapper.find('.token-connection').exists()).toBe(true)

    Object.assign(auth(), { status: 'anonymous', isLoggedIn: false })
    await flushPromises()

    expect(wrapper.find('.token-connection').exists()).toBe(false)
    expect(sessionStorage.length).toBe(0)
  })

  it('tells the reader when the clipboard refuses', async () => {
    copyToClipboard.mockRejectedValueOnce(new Error('denied'))
    const wrapper = await mountSetup()
    await cta(wrapper).trigger('click')
    await flushPromises()

    expect(showToast).toHaveBeenCalledWith('复制失败，请检查浏览器剪贴板权限。')
    expect(cta(wrapper).text()).toBe('复制给 Agent 的配置提示词')
  })
})
