import { mount } from '@vue/test-utils'
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

const createMcpToken = vi.hoisted(() => vi.fn())
const copy = vi.hoisted(() => vi.fn().mockResolvedValue(undefined))
vi.mock('@/services/mcp/mcpTokenApi', () => ({ createMcpToken }))
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy }) }))
vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))

const promptState = vi.hoisted(() => {
  // 模块级共享弹框状态的测试替身：用普通可变对象避免 hoisted 阶段引用 vue。
  return { open: { value: false }, redirect: { value: '/' } }
})
vi.mock('@/composables/useLoginPrompt', () => ({
  useLoginPrompt: () => ({
    isOpen: promptState.open,
    redirectTarget: promptState.redirect,
    requestLogin: (target?: unknown) => {
      promptState.redirect.value = typeof target === 'string' ? target : '/'
      promptState.open.value = true
    },
    closeLoginPrompt: () => { promptState.open.value = false },
  }),
}))

const messages = {
  mcp: {
    copied: '已复制', copyFailed: '复制失败',
    wizard: { prev: '上一步', next: '下一步', stepProgress: '{current}/{total}' },
    dshPlugin: { methods: {
      npm: { title: 'npm 最新版', description: '预构建。' },
      npmPinned: { title: 'npm 固定版', description: '固定。' },
      github: { title: 'GitHub 源码', description: '源码。' },
    } },
  },
  dsh: {
    recommended: '推荐', copy: '复制安装命令',
    wizard: {
      ariaLabel: 'dsh 安装向导',
      stepIdentity: '选择身份', stepIdentityDescription: '选择身份。',
      stepInstall: '安装方式', stepInstallDescription: '选择安装方式。',
      stepCommand: '生成命令', stepCommandDescription: '生成命令。',
      identityGuest: '游客', identityUser: '普通用户', identityVip: 'VIP',
      identityGuestDescription: '游客试用。', identityUserDescription: '普通配额。', identityVipDescription: 'VIP 配额。',
      vipRequired: '该档位需要有效会员。', vipCta: '开通 VIP', continueAsFree: '按普通用户继续',
      tokenCreating: '正在生成令牌', tokenRetry: '重试',
      commandLabel: '安装命令', patchLabel: '配置补丁', copyPatch: '复制补丁',
      oneTimeTokenWarning: '令牌仅显示一次。', anonymousHint: '游客受 IP 限额。',
    },
  },
}
const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
const router = createRouter({ history: createMemoryHistory(), routes: [
  { path: '/dsh', component: DshSetupWizard },
  { path: '/membership', component: { template: '<div />' } },
] })

const mountWizard = async () => {
  await router.push('/dsh'); await router.isReady()
  const wrapper = mount(DshSetupWizard, { global: { plugins: [router, i18n] } })
  await nextTick()
  return wrapper
}

const nextButton = (wrapper: ReturnType<typeof mount>) =>
  wrapper.findAll('button').find((button) => button.text().includes('下一步'))!

beforeEach(async () => {
  createMcpToken.mockReset()
  copy.mockClear()
  promptState.open.value = false
  promptState.redirect.value = '/'
  setActivePinia(createPinia())
})

describe('DshSetupWizard identity gate', () => {
  it('opens the global login prompt when a logged-out user picks the account tier', async () => {
    const wrapper = await mountWizard()
    await wrapper.findAll('button').find((b) => b.text().includes('普通用户'))!.trigger('click')
    await nextButton(wrapper).trigger('click')
    await nextTick()

    expect(promptState.open.value).toBe(true)
    expect(promptState.redirect.value).toBe('/dsh')
    expect(wrapper.text()).toContain('选择身份。')
  })

  it('auto-advances after login completes while still on the identity step', async () => {
    const auth = useAuthStore()
    auth.status = 'anonymous'
    const wrapper = await mountWizard()
    await wrapper.findAll('button').find((b) => b.text().includes('普通用户'))!.trigger('click')
    await nextButton(wrapper).trigger('click')
    await nextTick()
    expect(promptState.open.value).toBe(true)

    auth.status = 'authenticated'
    await nextTick()
    await nextTick()

    expect(wrapper.text()).toContain('npm 最新版')
  })

  it('blocks VIP for non-members with an upgrade hint and free-tier escape', async () => {
    const auth = useAuthStore()
    auth.status = 'authenticated'
    auth.user = freeUser
    const wrapper = await mountWizard()
    await wrapper.findAll('button').find((b) => b.text().includes('VIP'))!.trigger('click')
    await nextTick()

    expect(wrapper.text()).toContain('该档位需要有效会员。')
    expect(wrapper.get('a[href="/membership"]').text()).toContain('开通 VIP')
    await wrapper.findAll('button').find((b) => b.text().includes('按普通用户继续'))!.trigger('click')
    expect(wrapper.text()).not.toContain('该档位需要有效会员。')
  })
})

describe('DshSetupWizard command generation', () => {
  it('guest path shows the command without issuing a token', async () => {
    const wrapper = await mountWizard()
    await nextButton(wrapper).trigger('click')
    await nextTick()
    await nextButton(wrapper).trigger('click')
    await nextTick()

    expect(wrapper.text()).toContain('dsh plugin --profile web add dsh-aigc-radar')
    expect(wrapper.text()).toContain('游客受 IP 限额。')
    expect(createMcpToken).not.toHaveBeenCalled()
  })

  it('user path auto-issues one token and renders the YAML patch', async () => {
    const auth = useAuthStore()
    auth.status = 'authenticated'
    auth.user = freeUser
    createMcpToken.mockResolvedValue({ token: "aigc_mcp_x'y" })
    const wrapper = await mountWizard()
    await wrapper.findAll('button').find((b) => b.text().includes('普通用户'))!.trigger('click')
    await nextButton(wrapper).trigger('click')
    await nextTick()
    await nextButton(wrapper).trigger('click')
    await nextTick(); await nextTick()

    expect(createMcpToken).toHaveBeenCalledOnce()
    expect(createMcpToken).toHaveBeenCalledWith({ client_type: 'other', client_label: 'dsh-aigc-radar' })
    expect(wrapper.text()).toContain("mcpToken: 'aigc_mcp_x''y'")
    expect(wrapper.text()).toContain('令牌仅显示一次。')
  })

  it('shows retry state when token creation fails', async () => {
    const auth = useAuthStore()
    auth.status = 'authenticated'
    auth.user = freeUser
    createMcpToken.mockRejectedValueOnce(new Error('boom')).mockResolvedValueOnce({ token: 'aigc_mcp_ok' })
    const wrapper = await mountWizard()
    await wrapper.findAll('button').find((b) => b.text().includes('普通用户'))!.trigger('click')
    await nextButton(wrapper).trigger('click')
    await nextTick()
    await nextButton(wrapper).trigger('click')
    await nextTick(); await nextTick()

    expect(wrapper.text()).toContain('重试')
    await wrapper.findAll('button').find((b) => b.text().includes('重试'))!.trigger('click')
    await nextTick(); await nextTick()
    expect(wrapper.text()).toContain("mcpToken: 'aigc_mcp_ok'")
    expect(createMcpToken).toHaveBeenCalledTimes(2)
  })

  it('copies the install command and patch with independent feedback', async () => {
    const auth = useAuthStore()
    auth.status = 'authenticated'
    auth.user = freeUser
    createMcpToken.mockResolvedValue({ token: 'aigc_mcp_demo' })
    const wrapper = await mountWizard()
    await wrapper.findAll('button').find((b) => b.text().includes('普通用户'))!.trigger('click')
    await nextButton(wrapper).trigger('click')
    await nextTick()
    await nextButton(wrapper).trigger('click')
    await nextTick(); await nextTick()

    await wrapper.findAll('button').find((b) => b.text().includes('复制安装命令'))!.trigger('click')
    await nextTick()
    expect(copy).toHaveBeenCalledWith('dsh plugin --profile web add dsh-aigc-radar')

    await wrapper.findAll('button').find((b) => b.text().includes('复制补丁'))!.trigger('click')
    await nextTick()
    expect(copy).toHaveBeenCalledTimes(2)
    expect(String(copy.mock.calls[1]![0])).toContain("mcpToken: 'aigc_mcp_demo'")
  })
})
