import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useChatStore, type ChatMessage } from './chatStore'

const mocks = vi.hoisted(() => ({
  connect: vi.fn(),
  ensureConversation: vi.fn(),
  fetchConversationDetail: vi.fn(),
  fetchConversations: vi.fn(),
}))

vi.mock('../composables/useEventSource', () => ({
  useEventSource: () => ({ connect: mocks.connect }),
}))

vi.mock('../services/http/apiClient', () => ({
  api: { defaults: { baseURL: '/api/' } },
}))

vi.mock('../services/chat/chatApi', () => ({
  createConversation: vi.fn(),
  deleteConversation: vi.fn(),
  deleteConversationMessage: vi.fn(),
  ensureConversation: mocks.ensureConversation,
  fetchConversationDetail: mocks.fetchConversationDetail,
  fetchConversations: mocks.fetchConversations,
}))

function message(id: string, role: 'user' | 'assistant', content: string): ChatMessage {
  return {
    id,
    conversationId: '7',
    role,
    content,
    thinking: '',
    thinkingPreview: '',
    hasThinking: false,
    isThinking: false,
    thinkingDurationSec: 0,
    isStreaming: false,
    sources: [],
    attachments: [],
  }
}

function prepareStreamingStore() {
  const store = useChatStore()
  store.activeConversationId = '7'
  store.conversationMap = {
    '7': {
      id: '7',
      title: 'Global',
      scope: 'global',
      lastMessagePreview: '',
      messageCount: 0,
    },
  }
  store.messageMap = {
    '7': [{ ...message('temp', 'assistant', ''), hasThinking: true, isThinking: true, isStreaming: true }],
  }
  return store
}

describe('chat store domain contracts', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('normalizes history DTOs while preserving defaults, IDs, and conversation override', async () => {
    mocks.fetchConversationDetail.mockResolvedValue({
      conversation: { id: 7, title: '', scope: 'paper', scope_key: 'paper-1', message_count: 0 },
      messages: [{
        id: 9,
        conversation_id: 99,
        role: 'assistant',
        content: '',
        thinking: 'x'.repeat(81),
        attachments: [{ id: 3, file_name: 'figure.png', mime_type: 'image/png' }],
      }],
    })

    const store = useChatStore()
    await store.openConversation(7)

    expect(store.activeConversation).toMatchObject({
      id: '7', title: '新对话', scope: 'paper', scopeKey: 'paper-1', lastMessagePreview: '', messageCount: 0,
    })
    expect(store.messages[0]).toMatchObject({
      id: '9', conversationId: '7', content: '', hasThinking: true, isThinking: false,
      thinkingPreview: `${'x'.repeat(80)}…`, thinkingDurationSec: 0, isStreaming: false, sources: [],
      attachments: [{ id: '3', name: 'figure.png', mimeType: 'image/png', modality: 'image', parseStatus: 'uploaded' }],
    })
  })

  it('builds bounded non-empty history and disables it at zero turns', () => {
    const store = useChatStore()
    store.messageMap = {
      '7': [
        message('1', 'user', 'old'),
        message('2', 'assistant', 'ignored by bound'),
        message('3', 'user', '  '),
        message('4', 'assistant', 'latest'),
      ],
    }
    store.settings.maxHistoryTurns = 1

    expect(store.buildHistory('7')).toEqual([{ role: 'assistant', content: 'latest' }])
    store.settings.maxHistoryTurns = 0
    expect(store.buildHistory('7')).toEqual([])
  })

  it('loads a paper conversation without changing active global state', async () => {
    mocks.ensureConversation.mockResolvedValue({ id: 8, title: 'Paper', scope: 'paper', scope_key: 'paper-1', message_count: 1 })
    mocks.fetchConversationDetail.mockResolvedValue({
      conversation: { id: 8, title: 'Paper', scope: 'paper', scope_key: 'paper-1', message_count: 1 },
      messages: [{ id: 10, conversation_id: 8, role: 'user', content: 'paper question' }],
    })
    const store = useChatStore()
    store.activeConversationId = '7'
    store.activeScope = 'global'

    const paper = await store.fetchPaperConversation('paper-1', 'Paper')

    expect(paper.id).toBe('8')
    expect(store.messageMap['8']?.[0]?.conversationId).toBe('8')
    expect(store.activeConversationId).toBe('7')
    expect(store.activeScope).toBe('global')
  })

  it('preserves stream request, phases, event queues, rates, and persisted reload', async () => {
    vi.useFakeTimers()
    let handlers: Record<string, (...args: unknown[]) => void> = {}
    mocks.connect.mockImplementation((params: typeof handlers) => {
      handlers = params
      return { controller: new AbortController(), promise: Promise.resolve() }
    })
    mocks.fetchConversationDetail.mockResolvedValue({
      conversation: { id: 7, title: 'Global', scope: 'global', message_count: 1 },
      messages: [{ id: 11, conversation_id: 7, role: 'assistant', content: 'persisted' }],
    })
    const store = prepareStreamingStore()
    store.settings.temperature = 0.4
    store.settings.webSearch = true

    await store._streamToAssistant({
      text: 'hello', conversationId: '7', assistantTempId: 'temp', history: [{ role: 'user', content: 'before' }],
    })

    expect(mocks.connect).toHaveBeenCalledWith(expect.objectContaining({
      url: '/api/chat/stream',
      body: {
        message: 'hello', history: [{ role: 'user', content: 'before' }], temperature: 0.4,
        conversation_id: '7', scope: 'global', web_search: true,
      },
    }))
    expect(store.streamPhase).toBe('searching')
    handlers.onMessage?.({ type: 'status', data: 'rerank_documents' })
    expect(store.streamPhase).toBe('reranking')
    handlers.onMessage?.({ type: 'sources', data: [{ id: 1 }] })
    handlers.onMessage?.({ type: 'thinking', data: 'abcdefghijklmn' })
    handlers.onMessage?.({ type: 'content', data: 'abcdef' })
    await vi.advanceTimersByTimeAsync(16)
    expect(store.messageMap['7']?.[0]).toMatchObject({ thinking: 'abcdefghijkl', content: '', isThinking: true })
    await vi.advanceTimersByTimeAsync(16)
    expect(store.messageMap['7']?.[0]).toMatchObject({ thinking: 'abcdefghijklmn', content: '', isThinking: true })
    await vi.advanceTimersByTimeAsync(16)
    expect(store.messageMap['7']?.[0]).toMatchObject({ content: 'abc', isThinking: false })
    handlers.onDone?.()
    await vi.advanceTimersByTimeAsync(32)
    await vi.runAllTimersAsync()
    expect(mocks.fetchConversationDetail).toHaveBeenCalledWith('7')
    expect(store.messages[0]?.content).toBe('persisted')
    expect(store.isStreaming).toBe(false)
    expect(store.streamPhase).toBe('idle')
  })

  it('keeps one active connection, aborts it, and presents rate limits distinctly', async () => {
    const firstController = new AbortController()
    const secondController = new AbortController()
    const handlers: Array<Record<string, (...args: unknown[]) => void>> = []
    mocks.connect
      .mockImplementationOnce((params: Record<string, (...args: unknown[]) => void>) => {
        handlers.push(params)
        return { controller: firstController, promise: Promise.resolve() }
      })
      .mockImplementationOnce((params: Record<string, (...args: unknown[]) => void>) => {
        handlers.push(params)
        return { controller: secondController, promise: Promise.resolve() }
      })
    const store = prepareStreamingStore()

    await store._streamToAssistant({ text: 'one', conversationId: '7', assistantTempId: 'temp', history: [] })
    store.abortGeneration()
    expect(firstController.signal.aborted).toBe(true)
    expect(store.isStreaming).toBe(false)
    expect(store.messageMap['7']?.[0]?.isStreaming).toBe(false)

    store.messageMap['7'] = [{ ...message('temp-2', 'assistant', ''), isStreaming: true }]
    await store._streamToAssistant({ text: 'two', conversationId: '7', assistantTempId: 'temp-2', history: [], regenerateMessageId: '42' })
    expect(mocks.connect.mock.calls[1]?.[0]).toMatchObject({ url: '/api/chat/messages/42/regenerate', body: { temperature: 0.7 } })
    handlers[1]?.onError?.(Object.assign(new Error('今日额度已用完'), { status: 429 }))
    expect(store.messageMap['7']?.[0]?.content).toBe('⚠️ 今日额度已用完')
    expect(store.streamPhase).toBe('error')
  })
})
