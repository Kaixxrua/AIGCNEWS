import { ref, type Ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { i18n } from '@/i18n'
import type { ChatMessage, ConversationSummary } from '@/stores/chatStore'
import { usePaperReaderController } from './usePaperReaderController'

const conversation = (id: string): ConversationSummary => ({
  id,
  title: `Conversation ${id}`,
  scope: 'global',
  lastMessagePreview: '',
  messageCount: 0,
})

const message = (
  conversationId: string,
  id: string,
  role: ChatMessage['role'],
  content: string,
  attachments: ChatMessage['attachments'] = [],
): ChatMessage => ({
  id,
  conversationId,
  role,
  content,
  thinking: '',
  thinkingPreview: '',
  hasThinking: false,
  isThinking: false,
  thinkingDurationSec: 0,
  isStreaming: false,
  sources: [],
  attachments,
})

const createController = (overrides: { conversationEnabled?: Ref<boolean> } = {}) => {
  const activeConversationId = ref<string | null>('1')
  const conversationMap = ref<Record<string, ConversationSummary>>({ '1': conversation('1'), '2': conversation('2') })
  const messageMap = ref<Record<string, ChatMessage[]>>({
    '1': [message('1', 'existing', 'user', 'Existing message')],
    '2': [message('2', 'second', 'assistant', 'Second conversation')],
  })
  const loadConversations = vi.fn(async () => undefined)
  const ensureGlobalConversation = vi.fn(async () => undefined)
  const fetchPaper = vi.fn(async (id: string): Promise<{ id: string; title: string } | null> => ({ id, title: 'Paper' }))
  const sendMessage = vi.fn(async () => undefined)
  const openConversation = vi.fn(async (id: string) => {
    activeConversationId.value = id
  })
  const deleteActiveConversation = vi.fn(async () => {
    const deletedId = activeConversationId.value
    if (deletedId) {
      const { [deletedId]: _deletedConversation, ...remainingConversations } = conversationMap.value
      const { [deletedId]: _deletedMessages, ...remainingMessages } = messageMap.value
      conversationMap.value = remainingConversations
      messageMap.value = remainingMessages
    }
    activeConversationId.value = '2'
  })

  const controller = usePaperReaderController({
    paperId: ref('paper-1'),
    activeConversationId,
    conversationMap,
    messageMap,
    isStreaming: ref(false),
    fetchPaper,
    loadConversations,
    openConversation,
    ensureGlobalConversation,
    deleteActiveConversation,
    sendMessage,
    ...(overrides.conversationEnabled ? { conversationEnabled: overrides.conversationEnabled } : {}),
  })

  return {
    activeConversationId,
    controller,
    deleteActiveConversation,
    ensureGlobalConversation,
    fetchPaper,
    loadConversations,
    messageMap,
    openConversation,
    sendMessage,
  }
}

describe('usePaperReaderController paper conversations', () => {
  it('uses active store state when switching and deleting conversations', async () => {
    const fixture = createController()

    await fixture.controller.switchConversation('2')
    expect(fixture.activeConversationId.value).toBe('2')
    expect(fixture.controller.messages.value.map((item) => item.id)).toEqual(['second'])

    await fixture.controller.deleteCurrentConversation()
    expect(fixture.deleteActiveConversation).toHaveBeenCalledOnce()
    expect(fixture.loadConversations).toHaveBeenCalledOnce()
    expect(fixture.messageMap.value['2']).toBeUndefined()
    expect(fixture.controller.messages.value).toEqual([])
  })
})

describe('usePaperReaderController paper loading', () => {
  it('tells a missing paper apart from a failed load and never keeps showing the previous paper', async () => {
    const fixture = createController({ conversationEnabled: ref(false) })
    const { controller } = fixture
    await controller.initializePaperContext('paper-1')
    expect(controller.paper.value?.id).toBe('paper-1')
    expect(controller.paperMissing.value).toBe(false)

    // 网络或服务出错：这篇可能存在，只是没加载出来。
    fixture.fetchPaper.mockRejectedValueOnce(new Error('Network Error'))
    await controller.initializePaperContext('paper-2')
    expect(controller.paper.value).toBeNull()
    expect(controller.paperError.value).toBe(i18n.global.t('paper.loadFailed'))
    expect(controller.paperMissing.value).toBe(false)

    fixture.fetchPaper.mockResolvedValueOnce(null)
    await controller.initializePaperContext('paper-3')
    expect(controller.paperError.value).toBe(i18n.global.t('paper.notFound'))
    expect(controller.paperMissing.value).toBe(true)

    await controller.initializePaperContext('paper-1')
    expect(controller.paper.value?.id).toBe('paper-1')
    expect(controller.paperError.value).toBe('')
    expect(controller.paperMissing.value).toBe(false)

    await controller.initializePaperContext('')
    expect(controller.paper.value).toBeNull()
    expect(controller.paperMissing.value).toBe(true)
  })
})

describe('usePaperReaderController guest read-only mode', () => {
  it('loads the paper but skips conversation bootstrap when conversation is disabled', async () => {
    const fixture = createController({ conversationEnabled: ref(false) })

    await fixture.controller.initializePaperContext('paper-1')

    expect(fixture.fetchPaper).toHaveBeenCalledWith('paper-1')
    expect(fixture.controller.paper.value?.id).toBe('paper-1')
    expect(fixture.ensureGlobalConversation).not.toHaveBeenCalled()
    expect(fixture.loadConversations).not.toHaveBeenCalled()
  })

  it('does not send a message for guests', async () => {
    const fixture = createController({ conversationEnabled: ref(false) })

    fixture.controller.inputText.value = 'hello'
    await fixture.controller.sendText()
    expect(fixture.sendMessage).not.toHaveBeenCalled()
    expect(fixture.controller.inputText.value).toBe('hello')
  })
})


describe('paper context after PDF reader retirement', () => {
  it('sends text with the current paper and conversation', async () => {
    const fixture = createController()
    fixture.controller.inputText.value = ' Explain the method '
    await fixture.controller.sendText()
    expect(fixture.sendMessage).toHaveBeenCalledWith('Explain the method', 'paper-1', '1')
    expect(fixture.controller.inputText.value).toBe('')
  })
})
