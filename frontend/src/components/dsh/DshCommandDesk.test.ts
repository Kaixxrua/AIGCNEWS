import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { messages } from '@/i18n'
import { useAuthStore, type AuthUser } from '@/stores/authStore'
import DshCommandDesk from './DshCommandDesk.vue'

// 桌面版 dsh 接入命令台：命令模板打开就在，Token 处是占位；登录后自动取回账号的 dsh Token，只进剪贴板。
const freeUser: AuthUser = { user_id: 1, email: 'a@b.c', role: 'user', membership_tier: 'free' }
const memberUser: AuthUser = { user_id: 1, email: 'a@b.c', role: 'user', membership_tier: 'member' }

const ensureDshMcpToken = vi.hoisted(() => vi.fn())
const rotateDshMcpToken = vi.hoisted(() => vi.fn())
const fetchMcpTokens = vi.hoisted(() => vi.fn())
const copy = vi.hoisted(() => vi.fn())
const requestLogin = vi.hoisted(() => vi.fn())
vi.mock('@/services/mcp/mcpTokenApi', async (importOriginal) => {
  // 保留 isDshTokenRecoveryRequired 等真实辅助，只替换触网的 ensure/rotate 与连接检测用的令牌列表
  const actual = await importOriginal<typeof import('@/services/mcp/mcpTokenApi')>()
  return { ...actual, ensureDshMcpToken, rotateDshMcpToken, fetchMcpTokens }
})
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy }) }))
vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))
vi.mock('@/composables/useLoginPrompt', () => ({ useLoginPrompt: () => ({ requestLogin }) }))

const tokenRow = (lastUsedAt: string | null = null) => ({
  id: 21,
  token_hint: 'aigc_mcp_abc...wxyz',
  scopes: ['projects:favorites:read'],
  client_type: 'other',
  client_label: 'dsh-aigc-radar',
  expires_at: null,
  revoked_at: null,
  last_used_at: lastUsedAt,
})

const readyResult = (token: string, reused = false, lastUsedAt: string | null = null) => ({
  token,
  reused,
  token_metadata: tokenRow(lastUsedAt),
})

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages, missingWarn: false, fallbackWarn: false })
const router = createRouter({ history: createMemoryHistory(), routes: [
  { path: '/dsh', component: { template: '<div />' } },
  { path: '/membership', component: { template: '<div />' } },
] })

const mounted: VueWrapper[] = []
const mountDesk = async (user: AuthUser | null = freeUser) => {
  const auth = useAuthStore()
  auth.status = user ? 'authenticated' : 'anonymous'
  auth.user = user
  await router.push('/dsh'); await router.isReady()
  const wrapper = mount(DshCommandDesk, { global: { plugins: [router, i18n] } })
  mounted.push(wrapper)
  await flushPromises()
  return wrapper
}

const button = (wrapper: VueWrapper, label: string) => {
  const found = wrapper.findAll('button').find((candidate) => candidate.text().includes(label))
  if (!found) throw new Error(`no button labelled ${label}`)
  return found
}
const terminal = (wrapper: VueWrapper) => wrapper.get('.command-preview-term')
const side = (wrapper: VueWrapper) => wrapper.get('.dsh-desk-side')

beforeEach(() => {
  ensureDshMcpToken.mockReset()
  rotateDshMcpToken.mockReset()
  fetchMcpTokens.mockReset().mockResolvedValue([tokenRow()])
  copy.mockReset().mockResolvedValue(undefined)
  requestLogin.mockClear()
  setActivePinia(createPinia())
})
afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
})

describe('DshCommandDesk', () => {
  it('shows guests the npm command template and asks them to sign in before copying', async () => {
    const wrapper = await mountDesk(null)

    expect(wrapper.get('[aria-pressed="true"]').text()).toContain('npm 包 · 最新版')
    expect(terminal(wrapper).text()).toContain('dsh plugin --profile web add dsh-aigc-radar && printf')
    expect(terminal(wrapper).text()).toContain('~/.dsh/profiles/web/cordis.patch.yml')
    expect(wrapper.get('.command-slot').text()).toBe('你的 Token')
    expect(side(wrapper).classes()).toContain('dsh-desk-side--guest')
    expect(ensureDshMcpToken).not.toHaveBeenCalled()

    await button(wrapper, '登录后复制命令').trigger('click')
    expect(requestLogin).toHaveBeenCalledWith('/dsh')
  })

  it('fetches the account token on mount and copies the real line without showing it', async () => {
    ensureDshMcpToken.mockResolvedValue(readyResult('aigc_mcp_demo'))
    const wrapper = await mountDesk()

    expect(ensureDshMcpToken).toHaveBeenCalledOnce()
    expect(side(wrapper).classes()).toContain('dsh-desk-side--ready')
    expect(wrapper.get('.command-slot--filled').text()).toBe('Token 已填入')
    expect(wrapper.html()).not.toContain('aigc_mcp_demo')

    await button(wrapper, '复制安装命令').trigger('click')
    await flushPromises()
    expect(copy).toHaveBeenCalledTimes(1)
    const line = String(copy.mock.calls[0]![0])
    expect(line.startsWith('dsh plugin --profile web add dsh-aigc-radar && printf ')).toBe(true)
    expect(line).toContain("mcpToken: 'aigc_mcp_demo'")

    await button(wrapper, '复制给 Agent 的配置提示词').trigger('click')
    await flushPromises()
    const prompt = String(copy.mock.calls[1]![0])
    expect(prompt).toContain('npm 包 · 最新版')
    expect(prompt).toContain("mcpToken: 'aigc_mcp_demo'")
    expect(wrapper.html()).not.toContain('aigc_mcp_demo')
  })

  it('swaps to the GitHub source command with its description', async () => {
    ensureDshMcpToken.mockResolvedValue(readyResult('aigc_mcp_gh'))
    const wrapper = await mountDesk()

    await button(wrapper, 'GitHub 源码兜底').trigger('click')

    expect(wrapper.get('[aria-pressed="true"]').text()).toContain('GitHub 源码兜底')
    expect(terminal(wrapper).text()).toContain('dsh plugin --profile web add github:Kaixxrua/dsh-aigc-radar && printf')
    expect(wrapper.get('.dsh-desk-method').text()).toBe(i18n.global.t('mcp.dshPlugin.methods.github.description'))

    await button(wrapper, '复制安装命令').trigger('click')
    await flushPromises()
    expect(String(copy.mock.calls[0]![0])).toContain('github:Kaixxrua/dsh-aigc-radar')
  })

  it('retries after a failed fetch', async () => {
    ensureDshMcpToken.mockRejectedValue(new Error('boom'))
    const wrapper = await mountDesk()
    expect(side(wrapper).classes()).toContain('dsh-desk-side--error')

    ensureDshMcpToken.mockResolvedValue(readyResult('aigc_mcp_ok'))
    await button(wrapper, '重试').trigger('click')
    await flushPromises()

    expect(ensureDshMcpToken).toHaveBeenCalledTimes(2)
    expect(side(wrapper).classes()).toContain('dsh-desk-side--ready')
  })

  it('asks legacy-token users to regenerate explicitly', async () => {
    ensureDshMcpToken.mockRejectedValue({
      isAxiosError: true,
      response: { status: 409, data: { detail: { code: 'dsh_token_recovery_required', message: 'legacy' } } },
    })
    rotateDshMcpToken.mockResolvedValue(readyResult('aigc_mcp_new'))
    const wrapper = await mountDesk()
    expect(side(wrapper).classes()).toContain('dsh-desk-side--recovery')

    await button(wrapper, '重新生成 Token').trigger('click')
    await flushPromises()

    expect(rotateDshMcpToken).toHaveBeenCalledOnce()
    expect(side(wrapper).classes()).toContain('dsh-desk-side--ready')
    expect(side(wrapper).find('[data-connection="waiting"]').exists()).toBe(true)
    expect(wrapper.html()).not.toContain('aigc_mcp_new')
  })

  it('drops the token and the copy buttons when the session ends', async () => {
    ensureDshMcpToken.mockResolvedValue(readyResult('aigc_mcp_temp'))
    const wrapper = await mountDesk()
    expect(side(wrapper).classes()).toContain('dsh-desk-side--ready')

    const auth = useAuthStore()
    auth.status = 'anonymous'
    auth.user = null
    await flushPromises()

    expect(side(wrapper).classes()).toContain('dsh-desk-side--guest')
    expect(wrapper.find('.command-slot--filled').exists()).toBe(false)
    expect(wrapper.findAll('button').some((candidate) => candidate.text().includes('复制安装命令'))).toBe(false)
  })

  it('shows members their status instead of the upgrade hint', async () => {
    ensureDshMcpToken.mockResolvedValue(readyResult('aigc_mcp_vip'))
    const wrapper = await mountDesk(memberUser)

    expect(wrapper.get('.dsh-quota-hint--member').text()).toBe(i18n.global.t('dsh.wizard.memberStatus'))
    expect(wrapper.find('a[href="/membership"]').exists()).toBe(false)
  })
})

describe('DshCommandDesk connection status', () => {
  afterEach(() => { vi.useRealTimers() })

  it('waits for dsh to use a fresh token and then shows it connected', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    ensureDshMcpToken.mockResolvedValue(readyResult('aigc_mcp_live'))
    const wrapper = await mountDesk()

    const waiting = side(wrapper).get('[data-connection="waiting"]')
    expect(waiting.text()).toContain('等待 dsh 连接')
    expect(fetchMcpTokens).not.toHaveBeenCalled()

    fetchMcpTokens.mockResolvedValue([tokenRow('2026-10-05T12:00:05Z')])
    await vi.advanceTimersByTimeAsync(3_000)
    await flushPromises()

    expect(fetchMcpTokens).toHaveBeenCalledOnce()
    expect(side(wrapper).get('[data-connection="connected"]').text()).toContain('已连接')
    expect(wrapper.html()).not.toContain('aigc_mcp_live')
  })

  it('tells returning users their reused token connected before, without polling', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    ensureDshMcpToken.mockResolvedValue(readyResult('aigc_mcp_old', true, '2026-10-02T08:00:00Z'))
    const wrapper = await mountDesk()

    expect(side(wrapper).get('[data-connection="seen"]').text()).toContain('以前连上过')
    await vi.advanceTimersByTimeAsync(60_000)
    expect(fetchMcpTokens).not.toHaveBeenCalled()
  })

  it('watches a reused token again once the command is copied', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    ensureDshMcpToken.mockResolvedValue(readyResult('aigc_mcp_old', true, '2026-10-02T08:00:00Z'))
    fetchMcpTokens.mockResolvedValue([tokenRow('2026-10-02T08:00:00Z')])
    const wrapper = await mountDesk()

    await button(wrapper, '复制安装命令').trigger('click')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(3_000)
    expect(fetchMcpTokens).toHaveBeenCalledOnce()
    expect(side(wrapper).find('[data-connection="seen"]').exists()).toBe(true)

    fetchMcpTokens.mockResolvedValue([tokenRow('2026-10-05T12:00:30Z')])
    await vi.advanceTimersByTimeAsync(3_000)
    await flushPromises()
    expect(side(wrapper).find('[data-connection="connected"]').exists()).toBe(true)
  })
})
