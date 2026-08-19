import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it, vi } from 'vitest'
import DshView from './DshView.vue'

const copy = vi.hoisted(() => vi.fn().mockResolvedValue(undefined))
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy }) }))

const messages = {
  mcp: {
    copied: '已复制',
    dshPlugin: {
      methods: {
        npm: { title: 'npm 包 · 最新版', description: '安装预构建包。' },
        npmPinned: { title: 'npm 包 · 固定 0.2.0', description: '固定已验证版本。' },
        github: { title: 'GitHub 源码兜底', description: '现场构建源码。' },
      },
    },
  },
  dsh: {
    eyebrow: 'AIGC RADAR FOR DSH', title: '在 dsh 终端里搜索 AI 项目', description: '无需 Token。',
    mcpLink: '改为配置 MCP', repository: 'GitHub 仓库', installKicker: '安装', installTitle: '选择安装方式',
    installDescription: '选择一种安装方式。', recommended: '推荐', copy: '复制安装命令',
    sourceWarningTitle: '源码构建：', sourceWarning: 'pnpm 10+ 可能要求 allowBuilds；固定提交：',
    capabilitiesKicker: '插件能力', capabilitiesTitle: '原生卡片与检索路由', capabilitiesDescription: '插件能力说明。',
  },
}

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/dsh', component: DshView },
    { path: '/mcp', component: { template: '<div />' } },
  ],
})
const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })

const mountView = async () => {
  await router.push('/dsh')
  await router.isReady()
  const wrapper = mount(DshView, { global: { plugins: [router, i18n] } })
  await flushPromises()
  return wrapper
}

describe('DshView', () => {
  it('renders ordered npm and source install methods', async () => {
    const wrapper = await mountView()
    const methods = wrapper.findAll('[data-install-method]')
    expect(methods.map((item) => item.attributes('data-install-method'))).toEqual(['npm', 'npm-pinned', 'github'])
    expect(methods[0]!.text()).toContain('推荐')
    expect(methods[0]!.text()).toContain('dsh plugin --profile web add dsh-aigc-radar')
    expect(methods[1]!.text()).toContain('dsh-aigc-radar@0.2.0')
    expect(methods[2]!.text()).toContain('github:Kaixxrua/dsh-aigc-radar')
    expect(methods[2]!.text()).toContain('allowBuilds')
    expect(methods[0]!.text()).not.toContain('allowBuilds')
  })

  it('links to MCP and the repository', async () => {
    const wrapper = await mountView()
    expect(wrapper.get('a[href="/mcp"]').text()).toBe('改为配置 MCP')
    const repository = wrapper.get('a[href="https://github.com/Kaixxrua/dsh-aigc-radar"]')
    expect(repository.attributes('target')).toBe('_blank')
    expect(repository.attributes('rel')).toBe('noopener')
  })

  it('copies the selected method and shows matching feedback', async () => {
    copy.mockClear()
    const wrapper = await mountView()
    const methods = wrapper.findAll('[data-install-method]')
    await methods[1]!.get('button').trigger('click')
    await flushPromises()
    expect(copy).toHaveBeenCalledWith('dsh plugin --profile web add dsh-aigc-radar@0.2.0')
    expect(methods[1]!.get('button').text()).toBe('已复制')
    expect(methods[0]!.get('button').text()).toBe('复制安装命令')
  })
})
