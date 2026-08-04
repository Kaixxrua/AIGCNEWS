import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ensureConversation,
  fetchConversationDetail,
} from '@/services/chat/chatApi'
import { connectChatStream } from '@/features/chat/chatStreamBoundary'
import { useChatStore } from '@/stores/chatStore'
import type { ConversationSummary } from '@/features/chat/chatModel'

const connectMock = vi.hoisted(() => vi.fn())
const coordMock = vi.hoisted(() => ({
  subscribe: vi.fn(),
  synchronizeState: vi.fn(),
  dispose: vi.fn(),
  createAndSelect: vi.fn(),
  replaceConversationList: vi.fn(),
  selectConversation: vi.fn(),
  ensureAndSelect: vi.fn(),
  deleteConversation: vi.fn(),
  abortActiveRun: vi.fn(),
  startStreamRun: vi.fn(),
}))

vi.mock('@/composables/useEventSource', () => ({
  useEventSource: () => ({ connect: connectMock }),
}))

vi.mock('@/services/chat/chatApi', () => ({
  ensureConversation: vi.fn(),
  fetchConversationDetail: vi.fn(),
  fetchConversations: vi.fn(),
  createConversation: vi.fn(),
  deleteConversation: vi.fn(),
  deleteConversationMessage: vi.fn(),
}))

vi.mock('@/features/chat/chatLifecycleCoordinator', () => ({
  ChatLifecycleCoordinator: class {
    constructor() {
      Object.assign(this, coordMock)
    }
  },
}))

const summary = (id: string, patch: Partial<ConversationSummary> = {}): ConversationSummary => ({
  id,
  title: id,
  scope: 'global',
  lastMessagePreview: '',
  messageCount: 0,
  ...patch,
})

const assistantMessage = (id: string, conversationId: string) => ({
  id,
  conversationId,
  role: 'assistant' as const,
  content: '',
  thinking: '',
  thinkingPreview: '',
  hasThinking: true,
  isThinking: true,
  thinkingDurationSec: 0,
  isStreaming: true,
  sources: [],
  attachments: [],
})

const orderOf = (fn: ReturnType<typeof vi.fn>) => fn.mock.invocationCallOrder[0]!

describe('chat concurrency behavior', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    Object.values(coordMock).forEach((fn) => fn.mockReset())
    connectMock.mockReset()
    vi.mocked(ensureConversation).mockReset()
    vi.mocked(fetchConversationDetail).mockReset()
  })

  it('deletes the active conversation, reloads globals, then selects the deterministic fallback', async () => {
    const store = useChatStore()
    store.activeConversationId = 'c-dead'
    store.activeScope = 'global'
    coordMock.replaceConversationList.mockResolvedValue([
      summary('b', { updatedAt: '2024-01-01T00:00:00Z' }),
      summary('c', { updatedAt: '2024-01-02T00:00:00Z' }),
      summary('a', { updatedAt: '2024-01-02T00:00:00Z' }),
    ])

    await store.deleteActiveConversation()

    expect(coordMock.deleteConversation).toHaveBeenCalledWith('c-dead')
    expect(coordMock.replaceConversationList).toHaveBeenCalledWith({ scope: 'global' })
    // 时间倒序优先，时间相同取 id 字典序最小者（a < c）
    expect(coordMock.selectConversation).toHaveBeenCalledWith('a')
    expect(orderOf(coordMock.deleteConversation)).toBeLessThan(orderOf(coordMock.replaceConversationList))
    expect(orderOf(coordMock.replaceConversationList)).toBeLessThan(orderOf(coordMock.selectConversation))
    expect(coordMock.createAndSelect).not.toHaveBeenCalled()
  })

  it('creates a fresh global conversation when no fallback remains', async () => {
    const store = useChatStore()
    store.activeConversationId = 'c-dead'
    coordMock.replaceConversationList.mockResolvedValue([])

    await store.deleteActiveConversation()

    expect(coordMock.createAndSelect).toHaveBeenCalledWith({ scope: 'global' })
    expect(coordMock.selectConversation).not.toHaveBeenCalled()
  })

  it('routes abortGeneration to the coordinator run seam', () => {
    const store = useChatStore()

    store.abortGeneration()

    expect(coordMock.abortActiveRun).toHaveBeenCalledOnce()
  })

  it('consumes pending attachments before streaming and hands them to the run', async () => {
    const store = useChatStore()
    store.conversationMap = { g1: summary('g1') }
    store.activeConversationId = 'g1'
    store.activeScope = 'global'
    store.addPendingAttachment({ id: 'att-1', name: 'a.png', mimeType: 'image/png', modality: 'image', parseStatus: 'uploaded' })
    let pendingAtStream: unknown
    const streamSpy = vi
      .spyOn(store, '_streamToAssistant')
      .mockImplementation(() => {
        pendingAtStream = store.pendingAttachments
        return Promise.resolve()
      })

    await store.sendMessage('hello')

    expect(streamSpy).toHaveBeenCalledOnce()
    const args = streamSpy.mock.calls[0]![0]
    expect(args.conversationId).toBe('g1')
    expect(args.attachments?.map((item) => item.id)).toEqual(['att-1'])
    expect(pendingAtStream).toEqual([])
    expect(store.pendingAttachments).toEqual([])
    expect(store.messageMap.g1![0]).toMatchObject({ role: 'user', content: 'hello' })
    expect(store.messageMap.g1![0]!.attachments.map((item) => item.id)).toEqual(['att-1'])
  })

  it('keeps paper conversation fetches from touching active global state', async () => {
    const store = useChatStore()
    store.activeConversationId = 'g1'
    store.activeScope = 'global'
    vi.mocked(ensureConversation).mockResolvedValue({
      id: 88,
      scope: 'paper',
      scope_key: '42',
      title: '论文对话',
      last_message_preview: '',
      message_count: 0,
      updated_at: '2024-01-03T00:00:00Z',
      last_accessed_at: null,
      created_at: '2024-01-03T00:00:00Z',
    } as never)
    vi.mocked(fetchConversationDetail).mockResolvedValue({
      conversation: { id: 88 },
      messages: [],
    } as never)

    const paperSummary = await store.fetchPaperConversation('42', '论文对话')

    expect(paperSummary.id).toBe('88')
    expect(store.activeConversationId).toBe('g1')
    expect(store.activeScope).toBe('global')

    const streamSpy = vi.spyOn(store, '_streamToAssistant').mockResolvedValue(undefined)
    await store.sendMessage('paper question', '42', '88')

    expect(streamSpy).toHaveBeenCalledOnce()
    expect(streamSpy.mock.calls[0]![0].conversationId).toBe('88')
    expect(store.activeConversationId).toBe('g1')
    expect(store.activeScope).toBe('global')
  })

  it('delegates global conversation ensuring without direct active-state assignment', async () => {
    const store = useChatStore()
    coordMock.ensureAndSelect.mockResolvedValue(summary('g-new'))
    vi.spyOn(store, '_streamToAssistant').mockResolvedValue(undefined)

    await store.sendMessage('hello')

    expect(coordMock.ensureAndSelect).toHaveBeenCalledWith({ scope: 'global', scopeKey: undefined, title: 'hello' })
    // active 状态的切换由协调器订阅回调负责，action 本身不直接赋值
    expect(store.activeConversationId).toBeNull()
    expect(store.activeScope).toBe('global')
  })

  it('binds stream callbacks to the captured conversation and assistant ids', async () => {
    const store = useChatStore()
    store.conversationMap = { p1: summary('p1', { scope: 'paper', scopeKey: '42' }) }
    store.messageMap = { p1: [assistantMessage('a1', 'p1')] }
    coordMock.startStreamRun.mockReturnValue({ promise: Promise.resolve(), abort: vi.fn() })

    await store._streamToAssistant({ text: 't', conversationId: 'p1', assistantTempId: 'a1', history: [] })

    expect(coordMock.startStreamRun).toHaveBeenCalledOnce()
    const runArgs = coordMock.startStreamRun.mock.calls[0]![0]
    expect(runArgs.conversationId).toBe('p1')
    expect(runArgs.messageId).toBe('a1')
    // scope 取决于会话本身的 scope，而非 paperId 是否存在
    expect(runArgs.command.scope).toBe('paper')

    runArgs.callbacks.onError(new Error('boom'))
    expect(store.messageMap.p1![0]).toMatchObject({
      content: '流式请求失败：boom',
      isThinking: false,
      isStreaming: false,
    })
    expect(store.isStreaming).toBe(false)
    expect(store.streamPhase).toBe('error')

    runArgs.callbacks.onAbort('user', { conversationId: 'p1', messageId: 'a1' })
    expect(store.messageMap.p1![0]).toMatchObject({ isThinking: false, isStreaming: false })
    expect(store.streamPhase).toBe('idle')
  })

  it('resolves stream scope to global when the conversation is unknown', async () => {
    const store = useChatStore()
    store.messageMap = { ghost: [assistantMessage('a1', 'ghost')] }
    coordMock.startStreamRun.mockReturnValue({ promise: Promise.resolve(), abort: vi.fn() })

    await store._streamToAssistant({ text: 't', conversationId: 'ghost', assistantTempId: 'a1', history: [] })

    expect(coordMock.startStreamRun.mock.calls[0]![0].command.scope).toBe('global')
  })

  it('forwards stream callbacks unchanged through the connection boundary', () => {
    connectMock.mockReturnValue({ controller: new AbortController(), promise: Promise.resolve() })
    const onMessage = () => {}
    const onDone = () => true
    const onError = () => {}

    connectChatStream(
      { text: 'hello', conversationId: 'g1', history: [], scope: 'global' } as never,
      { onMessage, onDone, onError },
    )

    expect(connectMock).toHaveBeenCalledOnce()
    const params = connectMock.mock.calls[0]![0]
    expect(params.onMessage).toBe(onMessage)
    expect(params.onDone).toBe(onDone)
    expect(params.onError).toBe(onError)
  })
})
