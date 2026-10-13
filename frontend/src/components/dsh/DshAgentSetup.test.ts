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
const issueMcpInstallCode = vi.hoisted(() => vi.fn())
const authBox = vi.hoisted(() => ({ current: null as null | { status: string; isLoggedIn: boolean; isMember: boolean } }))

vi.mock('@/stores/authStore', async () => {
  const { reactive } = await import('vue')
  authBox.current ??= reactive({ status: 'anonymous', isLoggedIn: false, isMember: false })
  return { useAuthStore: () => authBox.current }
})
vi.mock('@/composables/useClipboard', () => ({ copyToClipboard, copySensitiveToClipboard }))
vi.mock('@/composables/useLoginPrompt', () => ({ useLoginPrompt: () => ({ requestLogin }) }))
vi.mock('@/composables/useToast', () => ({ showToast }))
vi.mock('@/services/mcp/mcpTokenApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/mcp/mcpTokenApi')>()),
  issueMcpInstallCode,
}))

const SECRET = 'aigc_mcp_DSH_secret_value'
const CODE = 'aigc_ic_DshAgentSetup_install_code_0123456789abcd'
const NEXT_CODE = 'aigc_ic_DshAgentSetup_next_code_0123456789abcdef'
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
  issueMcpInstallCode.mockReset()
    .mockResolvedValueOnce({ code: CODE, purpose: 'dsh', expires_in: 600 })
    .mockResolvedValue({ code: NEXT_CODE, purpose: 'dsh', expires_in: 600 })
  scope = effectScope()
  controller = scope.run(() => useDshSetupController({ ensureDshMcpToken, rotateDshMcpToken, fetchMcpTokens }))!
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  controller.dispose()
  scope.stop()
})

describe('DshAgentSetup', () => {
  it('asks guests to sign in first, since install codes are only issued to signed-in accounts', async () => {
    const wrapper = await mountSetup()
    expect(cta(wrapper).text()).toBe('登录后复制提示词')

    await cta(wrapper).trigger('click')
    expect(requestLogin).toHaveBeenCalledWith('/dsh')
    expect(copySensitiveToClipboard).not.toHaveBeenCalled()
    expect(issueMcpInstallCode).not.toHaveBeenCalled()
    expect(wrapper.get('.agent-setup-hint').text()).toBe(i18n.global.t('agentSetup.dsh.guestHint'))
    expect(wrapper.find('.token-connection').exists()).toBe(false)
  })

  it('previews the prompt with an install code placeholder', async () => {
    const wrapper = await mountSetup()
    await wrapper.get('.agent-setup-toggle').trigger('click')
    await nextTick()

    expect(wrapper.get('.command-preview-term').text()).toContain('dsh-aigc-radar')
    expect(wrapper.get('.command-preview-term').text()).toContain("mcpToken: '__AIGC_RADAR_TOKEN__'")
    expect(wrapper.findAll('.command-slot')).toHaveLength(1)
    expect(wrapper.get('.command-slot').text()).toBe('一次性安装码')
  })

  it('waits while the token is fetched', async () => {
    signIn()
    ensureDshMcpToken.mockReturnValue(new Promise(() => {}))
    void controller.ensure()
    const wrapper = await mountSetup()

    expect(cta(wrapper).text()).toBe('正在获取你的专属 MCP Token…')
    expect(cta(wrapper).attributes('disabled')).toBeDefined()
  })

  it('copies the prompt with a one-time install code, never the token, through the secure clipboard only', async () => {
    signIn()
    await controller.ensure()
    const wrapper = await mountSetup()
    expect(issueMcpInstallCode).toHaveBeenCalledExactlyOnceWith('dsh')
    expect(wrapper.get('.token-connection').attributes('data-connection')).toBe('waiting')

    await cta(wrapper).trigger('click')
    await flushPromises()

    expect(copySensitiveToClipboard).toHaveBeenCalledOnce()
    const prompt = copySensitiveToClipboard.mock.calls[0]![0] as string
    expect(prompt).toContain(`code:'${CODE}'`)
    expect(prompt).toContain(`${window.location.origin}/api/auth/mcp-install-codes/redeem`)
    expect(prompt).not.toContain(SECRET)
    expect(copyToClipboard).not.toHaveBeenCalled()
    expect(cta(wrapper).text()).toBe('已复制，去粘给你的 Agent')
    expect(wrapper.get('.command-slot').text()).toBe('安装码已填入')
    expect(wrapper.html()).not.toContain(SECRET)
    expect(wrapper.html()).not.toContain(CODE)

    // 下一次复制换一枚新码。
    expect(issueMcpInstallCode).toHaveBeenCalledTimes(2)
    await cta(wrapper).trigger('click')
    await flushPromises()
    expect(copySensitiveToClipboard.mock.calls[1]![0]).toContain(`code:'${NEXT_CODE}'`)
  })

  it('offers a retry when no install code can be issued', async () => {
    signIn()
    issueMcpInstallCode.mockReset().mockRejectedValueOnce(new Error('503')).mockResolvedValue({ code: CODE, purpose: 'dsh', expires_in: 600 })
    await controller.ensure()
    const wrapper = await mountSetup()

    expect(wrapper.get('.agent-setup-error').text()).toBe(i18n.global.t('agentSetup.installCode.failed'))
    await cta(wrapper).trigger('click')
    await flushPromises()
    expect(issueMcpInstallCode).toHaveBeenCalledTimes(2)
    expect(copySensitiveToClipboard).not.toHaveBeenCalled()
    expect(cta(wrapper).text()).toBe('复制给 Agent 的配置提示词')
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

  it('gives all accounts the same quota hint without VIP labels', async () => {
    signIn()
    const wrapper = await mountSetup()
    expect(wrapper.find('a[href="/membership"]').exists()).toBe(false)
    expect(wrapper.get('.dsh-quota-hint').text()).toBe(i18n.global.t('dsh.wizard.memberStatus'))

    auth().isMember = true
    await nextTick()
    expect(wrapper.find('a[href="/membership"]').exists()).toBe(false)
    expect(wrapper.get('.dsh-quota-hint').text()).toBe(i18n.global.t('dsh.wizard.memberStatus'))
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
