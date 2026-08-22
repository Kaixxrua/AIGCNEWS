import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import DshView from './DshView.vue'

const copy = vi.hoisted(() => vi.fn().mockResolvedValue(undefined))
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy }) }))
vi.mock('@/services/mcp/mcpTokenApi', () => ({ createMcpToken: vi.fn().mockResolvedValue({ token: 'aigc_mcp_test' }) }))

const messages = {
  mcp: { copied: '已复制', copyFailed: '复制失败', wizard: { prev: '上一步', next: '下一步', stepProgress: '{current}/{total}' }, dshPlugin: { methods: {
    npm: { title: 'npm 最新版', description: '预构建。' }, github: { title: 'GitHub 源码', description: '源码。' },
  } } },
  dsh: {
    eyebrow: 'AIGC RADAR FOR DSH', title: '在 dsh 终端里搜索 AI 项目', description: '选择身份后开始安装。',
    mcpLink: '改为配置 MCP', repository: 'GitHub 仓库', recommended: '推荐', copy: '复制安装命令',
    capabilitiesKicker: '插件能力', capabilitiesTitle: '原生卡片与检索路由', capabilitiesDescription: '插件能力说明。',
    wizard: {
      ariaLabel: 'dsh 安装向导', stepIdentity: '选择身份', stepIdentityDescription: '选择身份。', stepInstall: '安装方式', stepInstallDescription: '选择安装方式。', stepCommand: '生成命令', stepCommandDescription: '生成命令。',
      identityGuest: 'guest', identityUser: 'Free', identityVip: 'VIP', identityGuestDescription: 'guest 试用。', identityUserDescription: 'Free 配额。', identityVipDescription: 'VIP 配额。',
      vipRequired: '需要会员', vipCta: '开通 VIP', continueAsFree: '按 Free 继续', tokenCreating: '正在生成令牌', tokenRetry: '重试', commandLabel: '安装命令', tokenCommandNote: '命令会写入 dsh 补丁配置。', oneTimeTokenWarning: '令牌仅显示一次。', anonymousHint: 'guest 受 IP 限额。',
    },
    methods: { npm: { title: 'npm 最新版', description: '预构建。' }, github: { title: 'GitHub 源码', description: '源码。' } },
  },
}

const router = createRouter({ history: createMemoryHistory(), routes: [
  { path: '/dsh', component: DshView }, { path: '/mcp', component: { template: '<div />' } },
] })
const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })

const mountView = async () => {
  await router.push('/dsh'); await router.isReady()
  const wrapper = mount(DshView, { global: { plugins: [router, i18n, setActivePinia(createPinia())] } })
  await flushPromises(); return wrapper
}

beforeEach(() => { copy.mockClear(); setActivePinia(createPinia()) })

describe('DshView', () => {
  it('walks guests through identity, install method, and command steps', async () => {
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('选择身份')
    expect(wrapper.findAll('.dsh-wizard button').length).toBeGreaterThan(3)
    const next = wrapper.findAll('button').find(button => button.text().includes('下一步'))!
    await next.trigger('click')
    expect(wrapper.text()).toContain('npm 最新版')
    await wrapper.findAll('button').find(button => button.text().includes('GitHub 源码'))!.trigger('click')
    await wrapper.findAll('button').find(button => button.text().includes('下一步'))!.trigger('click')
    expect(wrapper.text()).toContain('dsh plugin --profile web add github:Kaixxrua/dsh-aigc-radar')
    expect(wrapper.text()).toContain('guest 受 IP 限额。')
  })

  it('links to MCP and the repository', async () => {
    const wrapper = await mountView()
    expect(wrapper.get('a[href="/mcp"]').text()).toBe('改为配置 MCP')
    const repository = wrapper.get('a[href="https://github.com/Kaixxrua/dsh-aigc-radar"]')
    expect(repository.attributes('target')).toBe('_blank')
    expect(repository.attributes('rel')).toBe('noopener')
  })

  it('copies the generated install command', async () => {
    const wrapper = await mountView()
    await wrapper.findAll('button').find(button => button.text().includes('下一步'))!.trigger('click')
    await wrapper.findAll('button').find(button => button.text().includes('下一步'))!.trigger('click')
    const copyButton = wrapper.findAll('button').find(button => button.text().includes('复制安装命令'))!
    await copyButton.trigger('click'); await flushPromises()
    expect(copy).toHaveBeenCalledWith('dsh plugin --profile web add dsh-aigc-radar')
  })
})
