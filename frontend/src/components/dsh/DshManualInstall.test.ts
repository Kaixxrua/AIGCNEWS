import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, nextTick, type EffectScope } from 'vue'
import i18n from '@/i18n'
import { useDshSetupController, type DshSetupController } from '@/composables/useDshSetupController'
import { DSH_MCP_TOKEN_LABEL } from '@/features/mcp/dshPlugin'
import type { DshMcpTokenResponse } from '@/services/mcp/mcpTokenApi'
import DshManualInstall from './DshManualInstall.vue'

const copyToClipboard = vi.hoisted(() => vi.fn())
const copySensitiveToClipboard = vi.hoisted(() => vi.fn())
const requestLogin = vi.hoisted(() => vi.fn())
const authBox = vi.hoisted(() => ({ current: null as null | { status: string; isLoggedIn: boolean; isMember: boolean } }))

vi.mock('@/stores/authStore', async () => {
  const { reactive } = await import('vue')
  authBox.current ??= reactive({ status: 'anonymous', isLoggedIn: false, isMember: false })
  return { useAuthStore: () => authBox.current }
})
vi.mock('@/composables/useClipboard', () => ({ copyToClipboard, copySensitiveToClipboard }))
vi.mock('@/composables/useLoginPrompt', () => ({ useLoginPrompt: () => ({ requestLogin }) }))
vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))

const SECRET = 'aigc_mcp_DSH_manual_secret'
const ready: DshMcpTokenResponse = {
  token: SECRET,
  reused: true,
  token_metadata: {
    id: 21, token_hint: 'aigc_mcp_…cret', scopes: ['favorites:read'], client_type: 'other', client_label: DSH_MCP_TOKEN_LABEL,
    expires_at: null, revoked_at: null, created_at: '2026-10-01T08:00:00Z', last_used_at: null,
  },
}
const ensureDshMcpToken = vi.fn()
const fetchMcpTokens = vi.fn()

const auth = () => authBox.current!
const signIn = () => Object.assign(auth(), { status: 'authenticated', isLoggedIn: true })

let scope: EffectScope
let controller: DshSetupController
const mounted: VueWrapper[] = []
const mountOpen = async () => {
  const wrapper = mount(DshManualInstall, { props: { controller }, global: { plugins: [i18n] }, attachTo: document.body })
  mounted.push(wrapper)
  await wrapper.get('.agent-manual-toggle').trigger('click')
  await flushPromises()
  return wrapper
}
const action = (wrapper: VueWrapper) => wrapper.get('.agent-manual-face .agent-btn')
const tabs = (wrapper: VueWrapper) => wrapper.findAll('.agent-tab')

beforeEach(() => {
  i18n.global.locale.value = 'zh-CN'
  Object.assign(auth(), { status: 'anonymous', isLoggedIn: false, isMember: false })
  copyToClipboard.mockReset().mockResolvedValue(undefined)
  copySensitiveToClipboard.mockReset().mockResolvedValue(undefined)
  requestLogin.mockReset()
  ensureDshMcpToken.mockReset().mockResolvedValue(ready)
  fetchMcpTokens.mockReset().mockResolvedValue([])
  scope = effectScope()
  controller = scope.run(() => useDshSetupController({ ensureDshMcpToken, fetchMcpTokens }))!
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  controller.dispose()
  scope.stop()
})

describe('DshManualInstall', () => {
  it('starts folded and opens on its title', async () => {
    const wrapper = mount(DshManualInstall, { props: { controller }, global: { plugins: [i18n] }, attachTo: document.body })
    mounted.push(wrapper)
    const toggle = wrapper.get('.agent-manual-toggle')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(wrapper.get(`#${toggle.attributes('aria-controls')}`).isVisible()).toBe(false)

    await toggle.trigger('click')
    await nextTick()
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(wrapper.get(`#${toggle.attributes('aria-controls')}`).isVisible()).toBe(true)
  })

  it('puts npm first and switches the command to the GitHub source', async () => {
    const wrapper = await mountOpen()
    expect(tabs(wrapper).map((tab) => tab.attributes('aria-pressed'))).toEqual(['true', 'false'])
    expect(tabs(wrapper)[0]!.find('.agent-tab-tag').text()).toBe(i18n.global.t('dsh.recommended'))
    const npmCommand = wrapper.get('.command-preview-term').text()
    expect(npmCommand).toContain('dsh plugin --profile web add dsh-aigc-radar')

    await tabs(wrapper)[1]!.trigger('click')
    await flushPromises()
    expect(controller.selectedMethod.value).toBe('github')
    expect(tabs(wrapper).map((tab) => tab.attributes('aria-pressed'))).toEqual(['false', 'true'])
    expect(wrapper.get('.command-preview-term').text()).not.toBe(npmCommand)
    expect(wrapper.get('.command-preview-term').text()).toContain('add github:Kaixxrua/dsh-aigc-radar')
  })

  it('asks guests to sign in before copying', async () => {
    const wrapper = await mountOpen()
    expect(wrapper.get('.command-slot').text()).toBe('你的 Token')
    expect(action(wrapper).text()).toBe('登录后复制命令')

    await action(wrapper).trigger('click')
    expect(requestLogin).toHaveBeenCalledWith('/dsh')
    expect(copySensitiveToClipboard).not.toHaveBeenCalled()
  })

  it('keeps the copy button off until the token is ready', async () => {
    signIn()
    const wrapper = await mountOpen()
    expect(action(wrapper).attributes('disabled')).toBeDefined()
    expect(wrapper.get('.agent-card-note').text()).toBe(i18n.global.t('mcp.desk.tokenNote'))
  })

  it('copies the command with the token through the secure clipboard only, and keeps it off the page', async () => {
    signIn()
    await controller.ensure()
    const wrapper = await mountOpen()
    expect(wrapper.get('.command-slot').text()).toBe('Token 已填入')
    expect(wrapper.get('.agent-card-note').text()).toBe(i18n.global.t('dsh.wizard.tokenCommandNote'))

    await action(wrapper).trigger('click')
    await flushPromises()
    expect(copySensitiveToClipboard).toHaveBeenCalledWith(controller.installLine.value)
    expect(copySensitiveToClipboard.mock.calls[0]![0]).toContain(SECRET)
    expect(copyToClipboard).not.toHaveBeenCalled()
    expect(action(wrapper).text()).toBe('已复制')
    expect(wrapper.html()).not.toContain(SECRET)
  })
})
