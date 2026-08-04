import type {
  ChatAttachmentRef,
  ChatMessageDTO,
  ConversationSummaryDTO,
} from '@/services/chat/chatApi'

export type ChatRole = 'user' | 'assistant'
export type ConversationScope = 'global' | 'paper'
export type StreamPhase = 'idle' | 'searching' | 'reranking' | 'answering' | 'error'

export interface ChatMessage {
  id: string
  conversationId: string
  role: ChatRole
  content: string
  thinking: string
  thinkingPreview: string
  hasThinking: boolean
  isThinking: boolean
  thinkingDurationSec: number
  isStreaming: boolean
  sources: unknown[]
  attachments: ChatAttachmentRef[]
  createdAt?: string
  updatedAt?: string
}

export interface ConversationSummary {
  id: string
  title: string
  scope: ConversationScope
  scopeKey?: string
  lastMessagePreview: string
  messageCount: number
  updatedAt?: string
  lastAccessedAt?: string
  createdAt?: string
}

export interface ChatSettings {
  maxHistoryTurns: number
  temperature: number
  webSearch: boolean
}

export type ChatHistoryEntry = Pick<ChatMessage, 'role' | 'content'>

export function normalizeChatAttachment(
  input: ChatAttachmentRef | Record<string, unknown>,
): ChatAttachmentRef {
  const raw = input as Record<string, unknown>
  return {
    id: String(raw.id ?? ''),
    name: String(raw.name ?? raw.file_name ?? ''),
    mimeType: String(raw.mimeType ?? raw.mime_type ?? ''),
    modality: raw.modality === 'pdf' || raw.modality === 'vision' ? raw.modality : 'image',
    parseStatus: (raw.parseStatus ?? raw.parse_status ?? 'uploaded') as ChatAttachmentRef['parseStatus'],
    progress: typeof raw.progress === 'number' ? raw.progress : undefined,
    imageRetained: typeof (raw.imageRetained ?? raw.image_retained) === 'boolean'
      ? Boolean(raw.imageRetained ?? raw.image_retained)
      : undefined,
    regenerationRequiresNewImage: typeof (raw.regenerationRequiresNewImage ?? raw.regeneration_requires_new_image) === 'boolean'
      ? Boolean(raw.regenerationRequiresNewImage ?? raw.regeneration_requires_new_image)
      : undefined,
  }
}

export function normalizeConversation(dto: ConversationSummaryDTO): ConversationSummary {
  return {
    id: String(dto.id),
    title: dto.title || '新对话',
    scope: dto.scope,
    scopeKey: dto.scope_key ?? undefined,
    lastMessagePreview: dto.last_message_preview || '',
    messageCount: dto.message_count || 0,
    updatedAt: dto.updated_at,
    lastAccessedAt: dto.last_accessed_at,
    createdAt: dto.created_at,
  }
}

export function normalizeChatMessage(
  dto: ChatMessageDTO,
  conversationIdOverride?: string,
): ChatMessage {
  const thinking = dto.thinking || ''
  const raw = dto as unknown as Record<string, unknown>
  return {
    id: String(dto.id),
    conversationId: conversationIdOverride || String(dto.conversation_id),
    role: dto.role,
    content: dto.content || '',
    thinking,
    thinkingPreview: dto.thinking_preview || (thinking ? `${thinking.slice(0, 80)}${thinking.length > 80 ? '…' : ''}` : ''),
    hasThinking: dto.has_thinking ?? !!thinking,
    isThinking: dto.is_thinking ?? false,
    thinkingDurationSec: typeof raw.thinking_duration_sec === 'number' ? raw.thinking_duration_sec : 0,
    isStreaming: dto.is_streaming ?? false,
    sources: dto.sources || [],
    attachments: Array.isArray(dto.attachments) ? dto.attachments.map(normalizeChatAttachment) : [],
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
  }
}

export function buildChatHistory(
  messages: ChatMessage[],
  maxHistoryTurns: number,
): ChatHistoryEntry[] {
  const historySize = maxHistoryTurns > 0 ? maxHistoryTurns * 2 : 0
  if (historySize === 0) return []
  return messages
    .slice(-historySize)
    .filter((message) => message.content.trim() !== '')
    .map(({ role, content }) => ({ role, content }))
}
