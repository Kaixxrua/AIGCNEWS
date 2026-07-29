import { computed, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import type { SseConnectParams } from './useEventSource'
import type { ChatMessage, ConversationSummary } from '../stores/chatStore'
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

const deferred = () => {
  let resolve!: () => void
  const promise = new Promise<void>((done) => { resolve = done })
  return { promise, resolve }
}

const createController = () => {
  const activeConversationId = ref<string | null>('1')
  const conversationMap = ref<Record<string, ConversationSummary>>({ '1': conversation('1'), '2': conversation('2') })
  const messageMap = ref<Record<string, ChatMessage[]>>({
    '1': [message('1', 'existing', 'user', 'Existing message')],
    '2': [message('2', 'second', 'assistant', 'Second conversation')],
  })
  const stream = deferred()
  let streamParams: SseConnectParams | null = null

  const loadConversations = vi.fn(async () => undefined)
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
    fetchPaper: vi.fn(async (id: string) => ({ id, title: 'Paper' })),
    loadConversations,
    openConversation,
    ensureGlobalConversation: vi.fn(async () => undefined),
    deleteActiveConversation,
    appendLocalMessage: (conversationId, localMessage) => {
      messageMap.value = {
        ...messageMap.value,
        [conversationId]: [...(messageMap.value[conversationId] || []), localMessage],
      }
    },
    patchMessage: (conversationId, messageId, patch) => {
      messageMap.value = {
        ...messageMap.value,
        [conversationId]: (messageMap.value[conversationId] || []).map((item) => (
          item.id === messageId ? { ...item, ...patch } : item
        )),
      }
    },
    sendMessage: vi.fn(async () => undefined),
    uploadScreenshot: vi.fn(async () => ({ image_id: 'uploaded-image' })),
    connectEventSource: (params) => {
      streamParams = params
      return { controller: new AbortController(), promise: stream.promise }
    },
    visionRelayUrl: '/chat/vision-relay',
  })

  return {
    activeConversationId,
    controller,
    deleteActiveConversation,
    loadConversations,
    messageMap,
    openConversation,
    stream,
    streamParams: computed(() => streamParams),
  }
}

describe('usePaperReaderController persisted visual messages', () => {
  it('replaces optimistic visual messages from the server on the terminal conversation event', async () => {
    const fixture = createController()
    fixture.controller.visionPopup.value = {
      visible: true,
      base64: 'data:image/jpeg;base64,raw-image-must-not-be-restored',
      question: 'Explain this figure',
      pageIndex: 0,
    }

    const pending = fixture.controller.sendVision()
    await Promise.resolve()
    await Promise.resolve()

    expect(fixture.messageMap.value['1']).toHaveLength(3)
    expect(JSON.stringify(fixture.messageMap.value['1'])).not.toContain('raw-image-must-not-be-restored')

    fixture.streamParams.value?.onMessage({ type: 'content', data: 'temporary answer' })
    fixture.openConversation.mockImplementationOnce(async (id: string) => {
      fixture.activeConversationId.value = id
      fixture.messageMap.value = {
        ...fixture.messageMap.value,
        [id]: [
          message(id, 'server-user', 'user', 'Explain this figure', [{
            id: '',
            name: '',
            mimeType: '',
            modality: 'vision',
            parseStatus: 'uploaded',
            imageRetained: false,
            regenerationRequiresNewImage: true,
          }]),
          message(id, 'server-assistant', 'assistant', 'Persisted answer'),
        ],
      }
    })
    fixture.streamParams.value?.onMessage({
      type: 'conversation',
      data: { conversation_id: 1, message_id: 22 },
    })
    fixture.streamParams.value?.onDone?.()
    fixture.stream.resolve()
    await pending

    expect(fixture.loadConversations).toHaveBeenCalledOnce()
    expect(fixture.openConversation).toHaveBeenCalledWith('1')
    expect(fixture.messageMap.value['1']?.map((item) => item.id)).toEqual(['server-user', 'server-assistant'])
    expect(fixture.controller.messages.value[0]).toMatchObject({
      isVisual: true,
      screenshotRetained: false,
      regenerationRequiresNewImage: true,
    })
    expect(JSON.stringify(fixture.controller.messages.value)).not.toContain('base64')
    expect(JSON.stringify(fixture.controller.messages.value)).not.toContain('raw-image-must-not-be-restored')
  })

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
