import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, nextTick, type EffectScope } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import i18n from '@/i18n'
import { useDshSetupController, type DshSetupController } from '@/composables/useDshSetupController'
import { DSH_MCP_TOKEN_LABEL } from '@/features/mcp/dshPlugin'
import { DSH_TOKEN_RECOVERY_REQUIRED_CODE, type DshMcpTokenResponse } from '@/services/mcp/mcpTokenApi'
import DshAgentSetup from './DshAgentSetup.vue'

const copyToClipboard = vi.hoisted(() => vi.fn())
const copySensitiveToClipboard = vi.hoisted(() => vi.fn())
const requestLogin = vi.hoisted(() => vi.fn())
const showToast = vi.hoisted(() => vi.fn())
const authBox = vi.hoisted(() => ({ current: null as null | { status: string; isLoggedIn: boolean; isMember: boolean } }))

vi.mock('@/stores/authStore', async () => {
  const { reactive } = await import('vue')
  authBox.current ??= reactive({ status: 'anonymous', isLoggedIn: false, isMember: false })
  return { useAuthStore: () => authBox.current }
})
vi.mock('@/composables/useClipboard', () => ({ copyToClipboard, copySensitiveToClipboard }))
vi.mock('@/composables/useLoginPrompt', () => ({ useLoginPrompt: () => ({ requestLogin }) }))
vi.mock('@/composables/useToast', () => ({ showToast }))

const SECRET = 'aigc_mcp_DSH_secret_value'
const ready: DshMcpTokenResponse = {
  token: SECRET,
  reused: false,
  token_metadata: {
    id: 21, token_hint: 'aigc_mcp_…alue', scopes: ['favorites:read'], client_type: 'other', client_label: DSH_MCP_TOKEN_LABEL,
    expires_at: null, revoked_at: null, created_at: new Date().toISOString(), last_used_at: null,
  },
}

const ensureDshMcpToken = vi.fn()
const rotateDshMcpToken = vi.fn()
const fetchMcpTokens = vi.fn()

const router = createRouter({ history: createMemoryHistory(), routes: [
  { path: '/dsh', component: { template: '<div />' } },
  { path: '/membership', component: { template: '<div />' } },
] })

const auth = () => authBox.current!
const signIn = (member = false) => Object.assign(auth(), { status: 'authenticated', isLoggedIn: true, isMember: member })

let scope: EffectScope
let controller: DshSetupController
const mounted: VueWrapper[] = []
const mountSetup = async () => {
  const wrapper = mount(DshAgentSetup, { props: { controller }, global: { plugins: [i18n, router] }, attachTo: document.body })
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
  requestLogin.mockReset()
  showToast.mockReset()
  ensureDshMcpToken.mockReset().mockResolvedValue(ready)
  rotateDshMcpToken.mockReset().mockResolvedValue({ ...ready, token: `${SECRET}_rotated` })
  fetchMcpTokens.mockReset().mockResolvedValue([])
  scope = effectScope()
  controller = scope.run(() => useDshSetupController({ ensureDshMcpToken, rotateDshMcpToken, fetchMcpTokens }))!
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  controller.dispose()
  scope.stop()
})

describe('DshAgentSetup', () => {
  it('asks guests to sign in first, since the prompt carries their token', async () => {
    const wrapper = await mountSetup()
    expect(cta(wrapper).text()).toBe('登录后复制提示词')

    await cta(wrapper).trigger('click')
    expect(requestLogin).toHaveBeenCalledWith('/dsh')
    expect(copySensitiveToClipboard).not.toHaveBeenCalled()
    expect(wrapper.get('.agent-setup-hint').text()).toBe(i18n.global.t('agentSetup.dsh.guestHint'))
    expect(wrapper.find('.token-connection').exists()).toBe(false)
  })

  it('previews the prompt with a token placeholder', async () => {
    const wrapper = await mountSetup()
    await wrapper.get('.agent-setup-toggle').trigger('click')
    await nextTick()

    expect(wrapper.get('.command-preview-term').text()).toContain('dsh-aigc-radar')
    expect(wrapper.get('.command-slot').text()).toBe('你的 Token')
  })

  it('waits while the token is fetched', async () => {
    signIn()
    ensureDshMcpToken.mockReturnValue(new Promise(() => {}))
    void controller.ensure()
    const wrapper = await mountSetup()

    expect(cta(wrapper).text()).toBe('正在获取你的专属 MCP Token…')
    expect(cta(wrapper).attributes('disabled')).toBeDefined()
  })

  it('copies the prompt with the token through the secure clipboard only, and keeps it off the page', async () => {
    signIn()
    await controller.ensure()
    const wrapper = await mountSetup()
    expect(wrapper.get('.token-connection').attributes('data-connection')).toBe('waiting')

    await cta(wrapper).trigger('click')
    await flushPromises()

    expect(copySensitiveToClipboard).toHaveBeenCalledOnce()
    expect(copySensitiveToClipboard.mock.calls[0]![0]).toContain(SECRET)
    expect(copyToClipboard).not.toHaveBeenCalled()
    expect(cta(wrapper).text()).toBe('已复制，去粘给你的 Agent')
    expect(wrapper.get('.command-slot').text()).toBe('Token 已填入')
    expect(wrapper.html()).not.toContain(SECRET)
  })

  it('regenerates the token on request', async () => {
    signIn()
    await controller.ensure()
    const wrapper = await mountSetup()

    await wrapper.get('.agent-setup-link').trigger('click')
    await flushPromises()
    expect(rotateDshMcpToken).toHaveBeenCalledOnce()
    expect(wrapper.html()).not.toContain(SECRET)
  })

  it('walks a legacy token through regeneration', async () => {
    signIn()
    ensureDshMcpToken.mockRejectedValueOnce({ isAxiosError: true, response: { status: 409, data: { detail: { code: DSH_TOKEN_RECOVERY_REQUIRED_CODE } } } })
    await controller.ensure()
    const wrapper = await mountSetup()

    expect(wrapper.get('.agent-setup-warn').text()).toBe(i18n.global.t('dsh.wizard.tokenRecovery'))
    await cta(wrapper).trigger('click')
    await flushPromises()
    expect(rotateDshMcpToken).toHaveBeenCalledOnce()
    expect(cta(wrapper).text()).toBe('复制给 Agent 的配置提示词')
  })

  it('offers a retry when the token cannot be fetched', async () => {
    signIn()
    ensureDshMcpToken.mockRejectedValueOnce(new Error('offline'))
    await controller.ensure()
    const wrapper = await mountSetup()

    expect(wrapper.get('.agent-setup-error').text()).toBe(i18n.global.t('mcp.tokenCreateFailed'))
    await cta(wrapper).trigger('click')
    await flushPromises()
    expect(ensureDshMcpToken).toHaveBeenCalledTimes(2)
  })

  it('points a free reader at VIP and tells a member their quota is the highest', async () => {
    signIn()
    const wrapper = await mountSetup()
    expect(wrapper.get('.dsh-quota-hint a[href="/membership"]').text()).toBe('升级 VIP')

    auth().isMember = true
    await nextTick()
    expect(wrapper.find('a[href="/membership"]').exists()).toBe(false)
    expect(wrapper.get('.dsh-quota-hint--member').text()).toBe(i18n.global.t('dsh.wizard.memberStatus'))
  })

  it('tells the reader when the clipboard refuses', async () => {
    signIn()
    await controller.ensure()
    copySensitiveToClipboard.mockRejectedValueOnce(new Error('denied'))
    const wrapper = await mountSetup()
    await cta(wrapper).trigger('click')
    await flushPromises()

    expect(showToast).toHaveBeenCalledWith(i18n.global.t('mcp.copyFailed'))
    expect(cta(wrapper).text()).toBe('复制给 Agent 的配置提示词')
  })
})
