import { describe, expect, it, vi } from 'vitest'
import {
  buildChatStreamRequest,
  connectChatStream,
  initialChatStreamEventState,
  reduceChatStreamEvent,
  type ChatStreamCommand,
} from './chatStreamBoundary'

const mocks = vi.hoisted(() => ({ connect: vi.fn() }))

vi.mock('../../composables/useEventSource', () => ({
  useEventSource: () => ({ connect: mocks.connect }),
}))

vi.mock('../../services/http/apiClient', () => ({
  api: { defaults: { baseURL: '/api/' } },
}))

function command(patch: Partial<ChatStreamCommand> = {}): ChatStreamCommand {
  return {
    text: 'hello',
    conversationId: '7',
    history: [{ role: 'user', content: 'before' }],
    temperature: 0.4,
    scope: 'global',
    webSearch: true,
    ...patch,
  }
}

describe('chat stream boundary', () => {
  it('builds the exact chat stream endpoint and optional body fields', () => {
    expect(buildChatStreamRequest('/api/', command({
      attachments: [
        { id: 'a1', name: 'one', mimeType: 'image/png', modality: 'image', parseStatus: 'ready' },
        { id: 'a2', name: 'two', mimeType: 'application/pdf', modality: 'pdf', parseStatus: 'ready' },
      ],
      paperId: 'paper-1',
      scope: 'paper',
    }))).toEqual({
      url: '/api/chat/stream',
      body: {
        message: 'hello',
        history: [{ role: 'user', content: 'before' }],
        temperature: 0.4,
        conversation_id: '7',
        scope: 'paper',
        web_search: true,
        attachment_ids: ['a1', 'a2'],
        paper_id: 'paper-1',
      },
    })
  })

  it('builds regenerate requests with temperature only', () => {
    expect(buildChatStreamRequest('/api///', command({ regenerateMessageId: '42' }))).toEqual({
      url: '/api/chat/messages/42/regenerate',
      body: { temperature: 0.4 },
    })
  })

  it('reduces status, source, and persisted conversation events', () => {
    let state = initialChatStreamEventState('7')
    expect(state).toEqual({ phase: 'searching', pendingSources: [], persistedConversationId: '7' })

    state = reduceChatStreamEvent(state, { type: 'status', data: 'rerank_documents' }).state
    expect(state.phase).toBe('reranking')
    state = reduceChatStreamEvent(state, { type: 'status', data: 'compose' }).state
    expect(state.phase).toBe('answering')
    state = reduceChatStreamEvent(state, { type: 'sources', data: [{ id: 1 }] }).state
    expect(state.pendingSources).toEqual([{ id: 1 }])
    state = reduceChatStreamEvent(state, { type: 'conversation', data: { conversation_id: 9, message_id: 10 } }).state
    expect(state.persistedConversationId).toBe('9')
  })

  it('classifies thinking, embedded think content, errors, and unknown events', () => {
    const initial = initialChatStreamEventState('7')
    expect(reduceChatStreamEvent(initial, { type: 'thinking', data: 'reason' })).toMatchObject({
      state: { phase: 'answering' }, effect: { type: 'thinking', chunk: 'reason' },
    })
    expect(reduceChatStreamEvent(initial, { type: 'content', data: '<think>reason</think> answer ' })).toMatchObject({
      state: { phase: 'answering' }, effect: { type: 'content', thinkingChunk: 'reason', chunk: 'answer' },
    })
    expect(reduceChatStreamEvent(initial, { type: 'error' })).toMatchObject({
      state: { phase: 'error' }, effect: { type: 'error', message: '未知错误' },
    })
    expect(reduceChatStreamEvent(initial, { type: 'future', data: 'ignored' })).toEqual({
      state: initial, effect: { type: 'none' },
    })
  })

  it('connects through generic SSE without changing request or callback identities', () => {
    const onMessage = vi.fn()
    const onDone = vi.fn()
    const onError = vi.fn()
    const connection = { controller: new AbortController(), promise: Promise.resolve() }
    mocks.connect.mockReturnValue(connection)

    expect(connectChatStream(command(), { onMessage, onDone, onError })).toBe(connection)
    expect(mocks.connect).toHaveBeenCalledWith({
      ...buildChatStreamRequest('/api/', command()), onMessage, onDone, onError,
    })
  })
})
