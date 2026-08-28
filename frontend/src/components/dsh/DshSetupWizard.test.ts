import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import DshSetupWizard from './DshSetupWizard.vue'
import { useAuthStore } from '@/stores/authStore'
import type { AuthUser } from '@/stores/authStore'

const freeUser: AuthUser = { user_id: 1, email: 'a@b.c', role: 'user', membership_tier: 'free' }
const memberUser: AuthUser = { user_id: 1, email: 'a@b.c', role: 'user', membership_tier: 'member' }

const ensureDshMcpToken = vi.hoisted(() => vi.fn())
const rotateDshMcpToken = vi.hoisted(() => vi.fn())
const copy = vi.hoisted(() => vi.fn().mockResolvedValue(undefined))
vi.mock('@/services/mcp/mcpTokenApi', async (importOriginal) => {
  // 保留 isDshTokenRecoveryRequired 等真实辅助，只替换触网的 ensure/rotate
  const actual = await importOriginal<typeof import('@/services/mcp/mcpTokenApi')>()
  return { ...actual, ensureDshMcpToken, rotateDshMcpToken }
})
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy }) }))
vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))

const readyResult = (token: string, reused = false) => ({
  token,
  reused,
  token_metadata: {
    id: 21,
    token_hint: 'aigc_mcp_abc...wxyz',
    scopes: ['projects:favorites:read'],
    client_type: 'other',
    client_label: 'dsh-aigc-radar',
    expires_at: null,
    revoked_at: null,
  },
})

const messages = {
  mcp: {
    copied: '已复制', copyFailed: '复制失败', tokenCreateFailed: 'Token 创建失败。',
    wizard: { prev: '上一步', next: '下一步', stepProgress: '{current}/{total}' },
    dshPlugin: { methods: {
      npm: { title: 'npm 最新版', description: '预构建。' },
      github: { title: 'GitHub 源码', description: '源码。' },
    } },
  },
  dsh: {
    recommended: '推荐', copy: '复制安装命令',
    wizard: {
      ariaLabel: 'dsh 接入向导',
      stepInstall: '选择安装方式', stepInstallDescription: '选择安装方式。',
      stepCommand: '获取接入命令', stepCommandDescription: '获取命令。',
      tokenCreating: '正在获取你的专属 MCP Token…', tokenRetry: '重试',
      tokenUnavailable: 'DSH Token 服务暂不可用。',
      tokenRecovery: '旧版 Token 无法自动恢复，请重新生成。', tokenRotate: '重新生成 Token',
      commandLabel: '安装命令', tokenCommandNote: '命令会写入 dsh 补丁配置。',
      tokenReuseNote: 'Token 与账号绑定、跨刷新保持不变。',
      vipHint: 'VIP 会员享更高调用次数。', vipCta: '升级 VIP',
      memberStatus: '当前账号为 VIP 会员。',
    },
  },
}
const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
const router = createRouter({ history: createMemoryHistory(), routes: [
  { path: '/dsh', component: DshSetupWizard },
  { path: '/membership', component: { template: '<div />' } },
] })

const mountWizard = async (user: AuthUser = freeUser) => {
  const auth = useAuthStore()
  auth.status = 'authenticated'
  auth.user = user
  await router.push('/dsh'); await router.isReady()
  const wrapper = mount(DshSetupWizard, { global: { plugins: [router, i18n] } })
  await flushPromises()
  return wrapper
}

const nextButton = (wrapper: ReturnType<typeof mount>) =>
  wrapper.findAll('button').find((button) => button.text().includes('下一步'))!

beforeEach(() => {
  ensureDshMcpToken.mockReset()
  rotateDshMcpToken.mockReset()
  copy.mockClear()
  setActivePinia(createPinia())
})

describe('DshSetupWizard', () => {
  it('auto-ensures the account-bound token on mount without any identity step', async () => {
    ensureDshMcpToken.mockResolvedValue(readyResult('aigc_mcp_auto'))
    const wrapper = await mountWizard()

    // 没有身份选择步骤：直接落在安装方式步骤
    expect(wrapper.text()).toContain('npm 最新版')
    expect(wrapper.text()).not.toContain('选择身份')
    expect(wrapper.text()).not.toContain('guest')
    expect(ensureDshMcpToken).toHaveBeenCalledOnce()
  })

  it('shows free users a VIP upgrade hint linking to /membership', async () => {
    ensureDshMcpToken.mockResolvedValue(readyResult('aigc_mcp_free'))
    const wrapper = await mountWizard(freeUser)

    expect(wrapper.text()).toContain('VIP 会员享更高调用次数。')
    expect(wrapper.get('a[href="/membership"]').text()).toContain('升级 VIP')
    expect(wrapper.text()).not.toContain('当前账号为 VIP 会员。')
  })

  it('shows members their status instead of the upgrade hint', async () => {
    ensureDshMcpToken.mockResolvedValue(readyResult('aigc_mcp_vip'))
    const wrapper = await mountWizard(memberUser)

    expect(wrapper.text()).toContain('当前账号为 VIP 会员。')
    expect(wrapper.text()).not.toContain('VIP 会员享更高调用次数。')
    expect(wrapper.find('a[href="/membership"]').exists()).toBe(false)
  })

  it('walks install method → command with the ensured token folded into one line', async () => {
    ensureDshMcpToken.mockResolvedValue(readyResult("aigc_mcp_x'y"))
    const wrapper = await mountWizard()
    await wrapper.findAll('button').find((b) => b.text().includes('GitHub 源码'))!.trigger('click')
    await nextButton(wrapper).trigger('click')
    await nextTick()

    const text = wrapper.text()
    expect(text).toContain('dsh plugin --profile web add github:Kaixxrua/dsh-aigc-radar && printf')
    expect(text).toContain("mcpToken: 'aigc_mcp_x''y'")
    expect(text).toContain('~/.dsh/profiles/web/cordis.patch.yml')
    expect(text).toContain('命令会写入 dsh 补丁配置。')
    expect(text).toContain('Token 与账号绑定、跨刷新保持不变。')
  })

  it('keeps the command hidden while the token is loading', async () => {
    let resolveEnsure!: (value: ReturnType<typeof readyResult>) => void
    ensureDshMcpToken.mockReturnValue(new Promise((res) => { resolveEnsure = res }))
    const wrapper = await mountWizard()
    await nextButton(wrapper).trigger('click')
    await nextTick()

    expect(wrapper.text()).toContain('正在获取你的专属 MCP Token…')
    expect(wrapper.text()).not.toContain('printf')
    expect(wrapper.find('code').exists()).toBe(false)

    resolveEnsure(readyResult('aigc_mcp_late'))
    await flushPromises()
    expect(wrapper.text()).toContain('aigc_mcp_late')
  })

  it('shows retry state when ensure fails', async () => {
    ensureDshMcpToken.mockRejectedValueOnce(new Error('boom')).mockResolvedValueOnce(readyResult('aigc_mcp_ok'))
    const wrapper = await mountWizard()
    await nextButton(wrapper).trigger('click')
    await nextTick()

    expect(wrapper.text()).toContain('Token 创建失败。')
    await wrapper.findAll('button').find((b) => b.text().includes('重试'))!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain("mcpToken: 'aigc_mcp_ok'")
    expect(ensureDshMcpToken).toHaveBeenCalledTimes(2)
  })

  it('guides legacy-token users through explicit regeneration', async () => {
    ensureDshMcpToken.mockRejectedValue({
      isAxiosError: true,
      response: { status: 409, data: { detail: { code: 'dsh_token_recovery_required', message: 'legacy' } } },
    })
    rotateDshMcpToken.mockResolvedValue(readyResult('aigc_mcp_new'))
    const wrapper = await mountWizard()
    await nextButton(wrapper).trigger('click')
    await nextTick()

    expect(wrapper.text()).toContain('旧版 Token 无法自动恢复，请重新生成。')
    expect(wrapper.text()).not.toContain('printf')

    await wrapper.findAll('button').find((b) => b.text().includes('重新生成 Token'))!.trigger('click')
    await flushPromises()
    expect(rotateDshMcpToken).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain("mcpToken: 'aigc_mcp_new'")
  })

  it('copies the single install line with one button', async () => {
    ensureDshMcpToken.mockResolvedValue(readyResult('aigc_mcp_demo'))
    const wrapper = await mountWizard()
    await nextButton(wrapper).trigger('click')
    await nextTick()

    await wrapper.findAll('button').find((b) => b.text().includes('复制安装命令'))!.trigger('click')
    await flushPromises()
    expect(copy).toHaveBeenCalledTimes(1)
    const copied = String(copy.mock.calls[0]![0])
    expect(copied.startsWith('dsh plugin --profile web add dsh-aigc-radar && printf ')).toBe(true)
    expect(copied).toContain("mcpToken: 'aigc_mcp_demo'")
    expect(copied).toContain('> ~/.dsh/profiles/web/cordis.patch.yml')
  })

  it('regenerates the token in place from the ready state', async () => {
    ensureDshMcpToken.mockResolvedValue(readyResult('aigc_mcp_old'))
    rotateDshMcpToken.mockResolvedValue(readyResult('aigc_mcp_regen'))
    const wrapper = await mountWizard()
    await nextButton(wrapper).trigger('click')
    await nextTick()
    expect(wrapper.text()).toContain('aigc_mcp_old')

    await wrapper.findAll('button').find((b) => b.text().includes('重新生成 Token'))!.trigger('click')
    await flushPromises()
    expect(rotateDshMcpToken).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('aigc_mcp_regen')
    expect(wrapper.text()).not.toContain('aigc_mcp_old')
  })
})
