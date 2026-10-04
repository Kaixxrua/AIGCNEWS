import { RouterLinkStub, flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { messages } from '@/i18n'
import PaperSameDayList from '@/components/papers/PaperSameDayList.vue'
import { fetchPaperDetail } from '@/services/papers/paperApi'
import PaperReadView from './PaperReadView.vue'

// 紧凑版头的细节行和「同一天的论文」只在桌面（≥1024px）出现；jsdom 没有 matchMedia，按标志切换。
const viewport = vi.hoisted(() => ({ desktop: true }))
vi.mock('@vueuse/core', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@vueuse/core')>()
  const { ref } = await import('vue')
  return {
    ...actual,
    useMediaQuery: (query: string) => (query === '(min-width: 1024px)' ? ref(viewport.desktop) : actual.useMediaQuery(query)),
  }
})

const auth = vi.hoisted(() => ({ status: 'anonymous' }))
vi.mock('@/stores/authStore', () => ({ useAuthStore: () => auth }))

vi.mock('@/stores/chatStore', async () => {
  const { reactive } = await import('vue')
  const store = reactive({
    activeConversationId: 'conversation', conversationMap: {}, messageMap: {}, isStreaming: false,
    loadConversations: vi.fn(async () => undefined), openConversation: vi.fn(async () => undefined),
    ensureGlobalConversation: vi.fn(async () => undefined), deleteActiveConversation: vi.fn(async () => undefined),
    sendMessage: vi.fn(async () => undefined),
  })
  return { useChatStore: () => store }
})

vi.mock('vue-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue-router')>()
  return {
    ...actual,
    useRoute: () => ({ params: { id: 'second' }, fullPath: '/papers/second/read' }),
    useRouter: () => ({ back: vi.fn(), push: vi.fn() }),
  }
})

vi.mock('@/composables/useLoginPrompt', () => ({ useLoginPrompt: () => ({ requestLogin: vi.fn() }) }))
vi.mock('@/composables/useLatexRenderer', () => ({
  useLatexRenderer: () => ({ renderMarkdown: (text: string) => text, copyFormulas: vi.fn(), handleFormulaCopy: vi.fn() }),
}))

vi.mock('@/services/papers/paperApi', () => ({
  fetchPaperDetail: vi.fn(async (id: string) => ({
    id, source: 'arxiv', title: 'Second paper', summary: 'A useful abstract', url: 'https://hf-mirror.com/papers/2609.00002',
    published_date: '2026-10-01T04:26:57', authors: '["Ada", "Grace", "Alan", "Edsger", "Barbara"]', arxiv_id: '2609.00002',
    source_channel: 'huggingface_daily_html', rank_in_period: 2, raw_score: 161,
  })),
}))

const fetchTop = vi.hoisted(() => vi.fn())
vi.mock('@/services/dashboard/dashboardApi', () => ({ dashboardApi: { fetchTop } }))

const mounted: VueWrapper[] = []
const mountView = async () => {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages, missingWarn: false, fallbackWarn: false })
  const wrapper = mount(PaperReadView, {
    global: { plugins: [i18n], stubs: { RouterLink: RouterLinkStub, PaperConversationPanel: true } },
  })
  mounted.push(wrapper)
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  viewport.desktop = true
  auth.status = 'anonymous'
  fetchTop.mockReset()
  fetchTop.mockResolvedValue({
    items: [
      { id: 'first', title: 'First paper', raw_score: 201, source_channel: 'huggingface_daily_html' },
      { id: 'second', title: 'Second paper', raw_score: 161, source_channel: 'huggingface_daily_html' },
    ],
    resolvedDate: '2026-10-01', isEmbargoed: false, sourceStatus: {},
  })
})

afterEach(() => {
  while (mounted.length) mounted.pop()?.unmount()
})

describe('PaperReadView desktop density', () => {
  it('puts authors, arXiv id, upvotes and board rank under the title for desktop guests', async () => {
    const wrapper = await mountView()
    const head = wrapper.get('.paper-document-panel > header')
    expect(head.get('h1').text()).toBe('Second paper')
    expect(head.text()).toContain('Ada, Grace, Alan')
    expect(head.text()).not.toContain('Barbara')
    expect(head.text()).toContain('arXiv 2609.00002')
    expect(head.text()).toContain('HF 点赞 161')
    expect(head.text()).toContain('日榜第 2')

    const toggle = head.get('.paper-authors-toggle')
    expect(toggle.text()).toBe('等 5 人')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(head.text()).toContain('Edsger, Barbara')
  })

  it('lists the same day board in the guests\' rail under the sign-in card, marking the open paper', async () => {
    const wrapper = await mountView()
    expect(fetchTop).toHaveBeenCalledWith(expect.objectContaining({ source: 'arxiv', date: '2026-10-01', limit: 10 }))
    expect(wrapper.find('.guest-cta').exists()).toBe(true)
    expect(wrapper.find('.paper-read-shell > nav.paper-same-day').exists()).toBe(true)
    const rail = wrapper.getComponent(PaperSameDayList)
    expect(rail.get('h2').text()).toBe('同一天的论文')
    const links = rail.findAllComponents(RouterLinkStub)
    expect(links.map((link) => link.props('to'))).toEqual([
      { name: 'paper-read', params: { id: 'first' } },
      { name: 'paper-read', params: { id: 'second' } },
    ])
    expect(links[1]?.attributes('aria-current')).toBe('page')
    expect(links[0]?.attributes('aria-current')).toBeUndefined()
    expect(wrapper.find('.paper-document-panel .paper-same-day').exists()).toBe(false)
  })

  it('moves the board after the summary for signed-in readers, whose rail is the conversation', async () => {
    auth.status = 'authenticated'
    const wrapper = await mountView()
    expect(wrapper.find('.guest-cta').exists()).toBe(false)
    expect(wrapper.find('.paper-read-shell > nav.paper-same-day').exists()).toBe(false)
    expect(wrapper.find('.paper-document-panel article + nav.paper-same-day').exists()).toBe(true)
  })

  it('hides the board when the day has none', async () => {
    fetchTop.mockResolvedValue({ items: [], resolvedDate: '2026-10-01', isEmbargoed: false, sourceStatus: {} })
    const wrapper = await mountView()
    expect(wrapper.find('nav.paper-same-day').exists()).toBe(false)
  })

  it('keeps phones and tablets on the original reading layout', async () => {
    viewport.desktop = false
    const wrapper = await mountView()
    expect(fetchTop).not.toHaveBeenCalled()
    expect(wrapper.find('.paper-document-panel--detailed').exists()).toBe(false)
    expect(wrapper.find('.paper-authors').exists()).toBe(false)
    expect(wrapper.find('nav.paper-same-day').exists()).toBe(false)
    expect(wrapper.get('.guest-cta').text()).toContain('登录后即可与 AI 讨论本论文')
  })

  it.each([true, false])('only says a missing paper is not found, without the sign-in prompt (desktop: %s)', async (desktop) => {
    viewport.desktop = desktop
    vi.mocked(fetchPaperDetail).mockResolvedValueOnce(null)
    const wrapper = await mountView()
    expect(wrapper.get('[role="alert"]').text()).toBe('未找到论文')
    expect(wrapper.find('.guest-cta').exists()).toBe(false)
  })
})
