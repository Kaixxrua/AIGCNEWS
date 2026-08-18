import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import McpPromptExampleList from './McpPromptExampleList.vue'
import { mcpExamplesByIds } from '@/features/mcp/mcpExamplePrompts'

const clipboardCopy = vi.hoisted(() => vi.fn())

vi.mock('@/composables/useClipboard', () => ({
  useClipboard: () => ({ copy: clipboardCopy }),
}))

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      mcp: { copied: '已复制' },
      mcpExamples: {
        copy: '复制',
        copyAria: '复制该提示词',
        demoAria: '在站内搜索 {query}',
        toolTagLabel: '调用 {tool}',
        ragFrameworks: { prompt: '在 AI 项目库中找 RAG 框架，按 Star 数排序。' },
        agentFrameworks: { prompt: '对比最近更新的 Agent 框架项目，推荐值得复用的。' },
        weeklyRanking: { prompt: '看看本周 AI 项目和论文榜单前十。' },
        papersRagSurvey: { prompt: '搜索关于检索增强生成评估的 arXiv 论文。' },
      },
    },
  },
  missingWarn: false,
  fallbackWarn: false,
})

beforeEach(() => {
  clipboardCopy.mockReset()
})

describe('McpPromptExampleList demo-copy mode', () => {
  // rag-frameworks 有 demoQuery（可演示），weekly-ranking 没有（仅复制）
  const examples = mcpExamplesByIds(['rag-frameworks', 'weekly-ranking'])

  it('renders a demo button only for examples with a demoQuery', () => {
    const wrapper = mount(McpPromptExampleList, {
      props: { examples, mode: 'demo-copy' },
      global: { plugins: [i18n] },
    })

    const demos = wrapper.findAll('.mcp-prompt-demo')
    expect(demos).toHaveLength(1)
    expect(demos[0]!.text()).toContain('在 AI 项目库中找 RAG 框架')
    expect(wrapper.find('.mcp-prompt-text--static').text()).toContain('看看本周 AI 项目和论文榜单前十')
  })

  it('emits the demo query when a demo chip is clicked', async () => {
    const wrapper = mount(McpPromptExampleList, {
      props: { examples, mode: 'demo-copy' },
      global: { plugins: [i18n] },
    })

    await wrapper.find('.mcp-prompt-demo').trigger('click')

    expect(wrapper.emitted('demo')).toEqual([['RAG 框架']])
  })

  it('copies the translated prompt and flips only that button to the copied state', async () => {
    const wrapper = mount(McpPromptExampleList, {
      props: { examples, mode: 'demo-copy' },
      global: { plugins: [i18n] },
    })
    const copyButtons = wrapper.findAll('.mcp-prompt-copy')
    expect(copyButtons).toHaveLength(2)

    await copyButtons[0]!.trigger('click')
    await flushPromises()

    expect(clipboardCopy).toHaveBeenCalledWith('在 AI 项目库中找 RAG 框架，按 Star 数排序。')
    expect(copyButtons[0]!.text()).toContain('已复制')
    expect(copyButtons[1]!.text()).not.toContain('已复制')
  })

  it('keeps the copy button unchanged when copying fails', async () => {
    clipboardCopy.mockRejectedValueOnce(new Error('denied'))
    const wrapper = mount(McpPromptExampleList, {
      props: { examples, mode: 'demo-copy' },
      global: { plugins: [i18n] },
    })
    const button = wrapper.find('.mcp-prompt-copy')

    await button.trigger('click')
    await flushPromises()

    expect(button.text()).not.toContain('已复制')
  })
})

describe('McpPromptExampleList copy-only mode', () => {
  const examples = mcpExamplesByIds(['rag-frameworks', 'papers-rag-survey'])

  it('renders no demo buttons and shows text copy labels', () => {
    const wrapper = mount(McpPromptExampleList, {
      props: { examples, mode: 'copy-only' },
      global: { plugins: [i18n] },
    })

    expect(wrapper.findAll('.mcp-prompt-demo')).toHaveLength(0)
    const copies = wrapper.findAll('.mcp-prompt-copy')
    expect(copies).toHaveLength(2)
    expect(copies[0]!.text()).toBe('复制')
  })

  it('shows tool tags only when showToolTag is set', () => {
    const withoutTags = mount(McpPromptExampleList, {
      props: { examples, mode: 'copy-only' },
      global: { plugins: [i18n] },
    })
    expect(withoutTags.findAll('.mcp-prompt-tool')).toHaveLength(0)

    const withTags = mount(McpPromptExampleList, {
      props: { examples, mode: 'copy-only', showToolTag: true },
      global: { plugins: [i18n] },
    })
    expect(withTags.findAll('.mcp-prompt-tool').map((tag) => tag.text())).toEqual([
      'search_github_ai_projects',
      'search_papers',
    ])
  })

  it('copies the translated prompt in copy-only mode as well', async () => {
    const wrapper = mount(McpPromptExampleList, {
      props: { examples, mode: 'copy-only', showToolTag: true },
      global: { plugins: [i18n] },
    })

    await wrapper.findAll('.mcp-prompt-copy')[1]!.trigger('click')
    await flushPromises()

    expect(clipboardCopy).toHaveBeenCalledWith('搜索关于检索增强生成评估的 arXiv 论文。')
    expect(wrapper.findAll('.mcp-prompt-copy')[1]!.text()).toBe('已复制')
  })
})
