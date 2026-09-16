import type { ChatMessage, ConversationSummary } from '@/stores/chatStore'

export interface PaperReaderMessage {
  id: string
  role: ChatMessage['role']
  content: string
  thinking?: string
  thinkingPreview?: string
  hasThinking?: boolean
  isThinking?: boolean
  thinkingDurationSec?: number
  isStreaming?: boolean
  isVisual?: boolean
  screenshotRetained?: boolean
  regenerationRequiresNewImage?: boolean
  showRaw?: boolean
}

export function filterAndSortGlobalConversations(
  conversations: ConversationSummary[],
): ConversationSummary[] {
  return conversations
    .filter((conversation) => conversation.scope === 'global')
    .sort((a, b) => {
      const ta = a.updatedAt ?? a.createdAt ?? ''
      const tb = b.updatedAt ?? b.createdAt ?? ''
      return tb.localeCompare(ta)
    })
}

export function mapChatStoreMessage(message: ChatMessage): PaperReaderMessage {
  const visualAttachment = message.attachments.find((attachment) => attachment.modality === 'vision')
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    thinking: message.thinking,
    thinkingPreview: message.thinkingPreview,
    hasThinking: message.hasThinking || !!message.thinking,
    isThinking: message.isThinking,
    thinkingDurationSec: message.thinkingDurationSec,
    isStreaming: message.isStreaming,
    isVisual: !!visualAttachment,
    screenshotRetained: visualAttachment?.imageRetained,
    regenerationRequiresNewImage: visualAttachment?.regenerationRequiresNewImage,
    showRaw: false,
  }
}

export function getMessageWatcherSignature(messages: PaperReaderMessage[]): string {
  return messages
    .map((message) => `${message.id}:${message.content.length}:${message.thinking?.length || 0}:${message.hasThinking ? 1 : 0}:${message.isThinking ? 1 : 0}:${message.thinkingDurationSec || 0}`)
    .join('|')
}
