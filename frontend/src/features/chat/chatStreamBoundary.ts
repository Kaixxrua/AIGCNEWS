import type { SseConnectParams } from '../../composables/useEventSource'
import type { ChatAttachmentRef } from '../../services/chat/chatApi'
import type { ConversationScope, StreamPhase } from './chatModel'

export interface ChatStreamCommand {
  text: string
  conversationId: string
  history: Array<{ role: string; content: string }>
  temperature: number
  scope: ConversationScope
  webSearch: boolean
  attachments?: ChatAttachmentRef[]
  paperId?: string
  regenerateMessageId?: string
}

export interface ChatStreamRequest {
  url: string
  body: Record<string, unknown>
}

export type ChatStreamEvent =
  | { type: 'sources'; data: unknown[] }
  | { type: 'content'; data: string }
  | { type: 'thinking'; data: string }
  | { type: 'status'; data: string }
  | { type: 'conversation'; data: { conversation_id: number | string; message_id: number | string } }
  | { type: 'error'; data?: unknown }
  | { type: string; data?: unknown }

export interface ChatStreamEventState {
  phase: StreamPhase
  pendingSources: unknown[]
  persistedConversationId: string
}

export type ChatStreamEffect =
  | { type: 'none' }
  | { type: 'thinking'; chunk: string }
  | { type: 'content'; chunk: string; thinkingChunk: string }
  | { type: 'error'; message: string }

export interface ChatStreamTransition {
  state: ChatStreamEventState
  effect: ChatStreamEffect
}

const THINK_TAG_RE = /<think>([\s\S]*?)<\/think>/

export function buildChatStreamRequest(
  baseURL: string,
  command: ChatStreamCommand,
): ChatStreamRequest {
  const normalizedBaseURL = baseURL.replace(/\/+$/, '')
  if (command.regenerateMessageId) {
    return {
      url: `${normalizedBaseURL}/chat/messages/${command.regenerateMessageId}/regenerate`,
      body: { temperature: command.temperature },
    }
  }

  const body: Record<string, unknown> = {
    message: command.text,
    history: command.history,
    temperature: command.temperature,
    conversation_id: command.conversationId,
    scope: command.scope,
    web_search: command.webSearch,
  }
  if (command.attachments?.length) {
    body.attachment_ids = command.attachments.map((attachment) => attachment.id)
  }
  if (command.paperId) {
    body.paper_id = command.paperId
  }
  return { url: `${normalizedBaseURL}/chat/stream`, body }
}

export function initialChatStreamEventState(conversationId: string): ChatStreamEventState {
  return {
    phase: 'searching',
    pendingSources: [],
    persistedConversationId: conversationId,
  }
}

export function reduceChatStreamEvent(
  state: ChatStreamEventState,
  payload: unknown,
): ChatStreamTransition {
  const event = payload as ChatStreamEvent
  if (event.type === 'status') {
    const status = String(event.data ?? '')
    const phase = status.includes('search')
      ? 'searching'
      : status.includes('rerank')
        ? 'reranking'
        : 'answering'
    return { state: { ...state, phase }, effect: { type: 'none' } }
  }
  if (event.type === 'sources' && Array.isArray(event.data)) {
    return { state: { ...state, pendingSources: event.data }, effect: { type: 'none' } }
  }
  if (event.type === 'conversation' && event.data) {
    const data = event.data as { conversation_id?: number | string }
    return {
      state: {
        ...state,
        persistedConversationId: String(data.conversation_id ?? state.persistedConversationId),
      },
      effect: { type: 'none' },
    }
  }
  if (event.type === 'thinking') {
    const chunk = String(event.data ?? '')
    return {
      state: { ...state, phase: chunk ? 'answering' : state.phase },
      effect: chunk ? { type: 'thinking', chunk } : { type: 'none' },
    }
  }
  if (event.type === 'content') {
    let chunk = String(event.data ?? '')
    if (!chunk) return { state, effect: { type: 'none' } }
    const thinkMatch = THINK_TAG_RE.exec(chunk)
    const thinkingChunk = thinkMatch?.[1] ?? ''
    if (thinkMatch) chunk = chunk.replace(THINK_TAG_RE, '').trim()
    return {
      state: { ...state, phase: 'answering' },
      effect: { type: 'content', chunk, thinkingChunk },
    }
  }
  if (event.type === 'error') {
    return {
      state: { ...state, phase: 'error' },
      effect: { type: 'error', message: String(event.data ?? '未知错误') },
    }
  }
  return { state, effect: { type: 'none' } }
}

export function toSseConnectParams(
  request: ChatStreamRequest,
  callbacks: Omit<SseConnectParams, 'url' | 'body'>,
): SseConnectParams {
  return { ...request, ...callbacks }
}
