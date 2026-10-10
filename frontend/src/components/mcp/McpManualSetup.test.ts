import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { AxiosError, AxiosHeaders } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import i18n from '@/i18n'
import { MANUAL_MCP_TOKEN_LABEL } from '@/features/mcp/manualMcpConfig'
import type { CreateMcpTokenResponse } from '@/services/mcp/mcpTokenApi'
import McpManualSetup from './McpManualSetup.vue'

const copyToClipboard = vi.hoisted(() => vi.fn())
const copySensitiveToClipboard = vi.hoisted(() => vi.fn())
const createMcpToken = vi.hoisted(() => vi.fn())
const fetchMcpTokens = vi.hoisted(() => vi.fn())
const requestLogin = vi.hoisted(() => vi.fn())
const authBox = vi.hoisted(() => ({ current: null as null | { status: string; isLoggedIn: boolean; isMember: boolean } }))

vi.mock('@/stores/authStore', async () => {
  const { reactive } = await import('vue')
  authBox.current ??= reactive({ status: 'anonymous', isLoggedIn: false, isMember: false })
  return { useAuthStore: () => authBox.current }
})
vi.mock('@/composables/useClipboard', () => ({ copyToClipboard, copySensitiveToClipboard }))
vi.mock('@/services/mcp/mcpTokenApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/mcp/mcpTokenApi')>()),
  createMcpToken,
  fetchMcpTokens,
}))
vi.mock('@/composables/useLoginPrompt', () => ({ useLoginPrompt: () => ({ requestLogin }) }))
vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))

const SECRET = 'aigc_mcp_MANUAL_secret_value'
const created: CreateMcpTokenResponse = {
  token: SECRET,
  token_metadata: {
    id: 77, token_hint: 'aigc_mcp_…alue', scopes: ['favorites:read'], client_type: 'other', client_label: MANUAL_MCP_TOKEN_LABEL,
    expires_at: null, revoked_at: null, created_at: new Date().toISOString(), last_used_at: null,
  },
  replaced_count: 0,
}

const auth = () => authBox.current!
const signIn = () => Object.assign(auth(), { status: 'authenticated', isLoggedIn: true })

const mounted: VueWrapper[] = []
const mountOpen = async () => {
  const wrapper = mount(McpManualSetup, { global: { plugins: [i18n] }, attachTo: document.body })
  mounted.push(wrapper)
  await wrapper.get('.agent-manual-toggle').trigger('click')
  await flushPromises()
  return wrapper
}
const action = (wrapper: VueWrapper) => wrapper.get('.agent-manual-face .agent-btn')

beforeEach(() => {
  i18n.global.locale.value = 'zh-CN'
  Object.assign(auth(), { status: 'anonymous', isLoggedIn: false, isMember: false })
  copyToClipboard.mockReset().mockResolvedValue(undefined)
  copySensitiveToClipboard.mockReset().mockResolvedValue(undefined)
  createMcpToken.mockReset().mockResolvedValue(created)
  fetchMcpTokens.mockReset().mockResolvedValue([])
  requestLogin.mockReset()
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
})

describe('McpManualSetup', () => {
  it('starts folded and opens on its title', async () => {
    const wrapper = mount(McpManualSetup, { global: { plugins: [i18n] }, attachTo: document.body })
    mounted.push(wrapper)
    const toggle = wrapper.get('.agent-manual-toggle')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(wrapper.get(`#${toggle.attributes('aria-controls')}`).isVisible()).toBe(false)

    await toggle.trigger('click')
    await nextTick()
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(wrapper.classes()).toContain('agent-manual--open')
    expect(wrapper.get(`#${toggle.attributes('aria-controls')}`).isVisible()).toBe(true)
  })

  it('shows guests the template and asks them to sign in before a token is issued', async () => {
    const wrapper = await mountOpen()
    expect(wrapper.get('.command-preview-term').text()).toContain('"Authorization": "Bearer')
    expect(wrapper.get('.command-slot').text()).toBe('你的 Token')

    await action(wrapper).trigger('click')
    expect(action(wrapper).text()).toBe('登录后生成')
    expect(requestLogin).toHaveBeenCalledWith('/mcp')
    expect(createMcpToken).not.toHaveBeenCalled()
  })

  it('issues a token on request and copies it only through the secure clipboard', async () => {
    signIn()
    const wrapper = await mountOpen()
    expect(createMcpToken).not.toHaveBeenCalled()
    expect(action(wrapper).text()).toBe('生成配置')

    await action(wrapper).trigger('click')
    await flushPromises()
    expect(createMcpToken).toHaveBeenCalledWith({ client_type: 'other', client_label: MANUAL_MCP_TOKEN_LABEL })
    expect(wrapper.get('.command-slot').text()).toBe('Token 已填入')
    expect(wrapper.get('.token-connection').attributes('data-connection')).toBe('waiting')

    await action(wrapper).trigger('click')
    await flushPromises()
    expect(copySensitiveToClipboard).toHaveBeenCalledOnce()
    expect(copySensitiveToClipboard.mock.calls[0]![0]).toContain(`Bearer ${SECRET}`)
    expect(copyToClipboard).not.toHaveBeenCalled()
    expect(wrapper.html()).not.toContain(SECRET)
  })

  it('drops the token as soon as the reader signs out', async () => {
    signIn()
    const wrapper = await mountOpen()
    await action(wrapper).trigger('click')
    await flushPromises()
    expect(wrapper.get('.command-slot').text()).toBe('Token 已填入')

    Object.assign(auth(), { status: 'anonymous', isLoggedIn: false })
    await flushPromises()
    expect(action(wrapper).text()).toBe('登录后生成')

    signIn()
    await flushPromises()
    expect(action(wrapper).text()).toBe('生成配置')
    expect(wrapper.get('.command-slot').text()).toBe('你的 Token')
    expect(wrapper.find('.token-connection').exists()).toBe(false)
  })

  it('asks to sign in again when the session has expired', async () => {
    signIn()
    createMcpToken.mockRejectedValueOnce(new AxiosError('expired', '401', undefined, undefined, {
      status: 401, statusText: 'Unauthorized', headers: {}, config: { headers: new AxiosHeaders() }, data: {},
    }))
    const wrapper = await mountOpen()
    await action(wrapper).trigger('click')
    await flushPromises()

    expect(wrapper.get('.agent-card-error').text()).toBe(i18n.global.t('mcp.loginExpired'))
    expect(action(wrapper).text()).toBe('重试')
  })
})
