import { computed, nextTick, ref, watch, type Ref } from 'vue'
import type { SseConnectParams, SseConnection } from './useEventSource'
import {
  filterAndSortGlobalConversations,
  getMessageWatcherSignature,
  mapChatStoreMessage,
  type PaperReaderMessage,
  type VisionPopup,
  type VisionRegionCapture,
} from '../features/papers/paperReaderModel'
import type { ChatMessage, ConversationSummary } from '../stores/chatStore'
import type { PdfProgress } from '../features/papers/pdfViewerModel'

export interface PaperReaderPaper {
  id: string
  title: string
  url?: string
  summary?: string
  published_date?: string
  pdf_media_url?: string | null
}

interface PaperReaderControllerOptions<TPaper extends PaperReaderPaper> {
  paperId: Ref<string>
  activeConversationId: Ref<string | null>
  conversationMap: Ref<Record<string, ConversationSummary>>
  messageMap: Ref<Record<string, ChatMessage[]>>
  isStreaming: Ref<boolean>
  fetchPaper: (id: string) => Promise<TPaper | null>
  loadConversations: () => Promise<unknown>
  openConversation: (conversationId: string) => Promise<unknown>
  ensureGlobalConversation: (title?: string) => Promise<unknown>
  deleteActiveConversation: () => Promise<unknown>
  appendLocalMessage: (conversationId: string, message: ChatMessage) => void
  patchMessage: (conversationId: string, messageId: string, patch: Partial<ChatMessage>) => void
  sendMessage: (text: string, paperId?: string, conversationId?: string) => Promise<unknown>
  uploadScreenshot: (payload: { image_base64: string; mime_type: string }) => Promise<{ image_id: string }>
  connectEventSource: (params: SseConnectParams) => SseConnection
  visionRelayUrl: string
}

export function usePaperReaderController<TPaper extends PaperReaderPaper>(options: PaperReaderControllerOptions<TPaper>) {
  const paper = ref<TPaper | null>(null) as Ref<TPaper | null>
  const paperLoading = ref(true)
  const paperError = ref('')
  const showConvPanel = ref(false)
  const inputText = ref('')
  const chatListRef = ref<HTMLElement | null>(null)
  const thinkingExpanded = ref<Record<string, boolean>>({})
  const visionPopup = ref<VisionPopup | null>(null)
  const popupInputRef = ref<HTMLInputElement | null>(null)
  const pdfProgress = ref<PdfProgress>({ phase: 'idle', loadedPages: 0, totalPages: 0, percent: 0 })

  const currentConversationId = computed(() => options.activeConversationId.value)
  const conversationList = computed(() => filterAndSortGlobalConversations(Object.values(options.conversationMap.value)))
  const messages = computed<PaperReaderMessage[]>(() => {
    const active = currentConversationId.value
    if (!active) return []
    return (options.messageMap.value[active] || []).map(mapChatStoreMessage)
  })
  const activeConversationTitle = computed(() => {
    const id = currentConversationId.value
    if (!id) return 'AI 对话'
    return options.conversationMap.value[id]?.title || 'AI 对话'
  })
  const isSending = computed(() => options.isStreaming.value)

  const loadPaper = async (id: string) => {
    if (!id) {
      paperError.value = '无效的论文 ID'
      paperLoading.value = false
      return
    }
    paperLoading.value = true
    paperError.value = ''
    try {
      paper.value = await options.fetchPaper(id)
      if (!paper.value) paperError.value = '论文不存在'
    } catch (error) {
      paperError.value = String(error)
    } finally {
      paperLoading.value = false
    }
  }

  const initializePaperContext = async (id: string) => {
    await loadPaper(id)
    if (!options.activeConversationId.value) await options.ensureGlobalConversation()
    await options.loadConversations()
  }

  const handlePaperIdChange = (newId: string) => {
    visionPopup.value = null
    void initializePaperContext(newId)
  }

  const switchConversation = async (conversationId: string) => {
    showConvPanel.value = false
    if (conversationId === options.activeConversationId.value) return
    await options.openConversation(conversationId)
  }

  const newConversation = async () => {
    showConvPanel.value = false
    await options.ensureGlobalConversation('新对话')
    await options.loadConversations()
  }

  const deleteCurrentConversation = async () => {
    if (!currentConversationId.value) return
    showConvPanel.value = false
    await options.deleteActiveConversation()
    await options.loadConversations()
  }

  const setChatListRef = (element: Element | null) => {
    chatListRef.value = element instanceof HTMLElement ? element : null
  }
  const setPopupInputRef = (element: Element | null) => {
    popupInputRef.value = element instanceof HTMLInputElement ? element : null
  }
  const scrollBottom = async () => {
    await nextTick()
    if (chatListRef.value) chatListRef.value.scrollTop = chatListRef.value.scrollHeight
  }

  watch(() => getMessageWatcherSignature(messages.value), () => { void scrollBottom() })

  const toggleThinking = (messageId: string) => {
    thinkingExpanded.value = { ...thinkingExpanded.value, [messageId]: !thinkingExpanded.value[messageId] }
  }
  const isThinkingExpanded = (messageId: string) => !!thinkingExpanded.value[messageId]

  const chatServiceDisabled = true
  const onRightclickRegion = async (payload: VisionRegionCapture) => {
    if (chatServiceDisabled) {
      visionPopup.value = null
      return
    }
    visionPopup.value = { visible: true, base64: payload.base64, question: '', pageIndex: payload.pageIndex }
    await nextTick()
    popupInputRef.value?.focus()
  }
  const closePopup = () => { visionPopup.value = null }

  const createTemporaryMessage = (
    conversationId: string,
    id: string,
    role: ChatMessage['role'],
    content: string,
    isStreaming: boolean,
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
    isStreaming,
    sources: [],
    attachments: [],
  })

  const sendVision = async () => {
    if (!visionPopup.value?.question.trim() || isSending.value || !currentConversationId.value) return
    const question = visionPopup.value.question.trim()
    const base64 = visionPopup.value.base64
    const conversationId = currentConversationId.value
    const history = (options.messageMap.value[conversationId] || [])
      .filter((message) => message.role !== 'assistant' || message.content)
      .slice(-12)
      .map((message) => ({ role: message.role, content: message.content }))
    closePopup()

    const requestId = Date.now()
    const userId = `vision_user_${requestId}`
    const assistantId = `vision_assistant_${requestId}`
    options.appendLocalMessage(
      conversationId,
      createTemporaryMessage(conversationId, userId, 'user', `[截图追问] ${question}`, false),
    )
    options.appendLocalMessage(
      conversationId,
      createTemporaryMessage(conversationId, assistantId, 'assistant', '', true),
    )

    let imageId: string
    try {
      const upload = await options.uploadScreenshot({ image_base64: base64, mime_type: 'image/jpeg' })
      imageId = upload.image_id
    } catch (error) {
      options.patchMessage(conversationId, assistantId, {
        isStreaming: false,
        content: `[上传失败] 截图上传失败：${error}`,
      })
      return
    }

    let terminalConversationReceived = false
    let terminalSync: Promise<unknown> | null = null
    const connection = options.connectEventSource({
      url: options.visionRelayUrl,
      body: {
        conversation_id: conversationId,
        paper_id: options.paperId.value || null,
        question,
        image_id: imageId,
        history,
      },
      onMessage: (payload: unknown) => {
        const event = payload as { type: string; data?: unknown }
        if (event.type === 'status') return
        if (event.type === 'conversation' && event.data && typeof event.data === 'object') {
          terminalConversationReceived = true
          const persistedId = String((event.data as { conversation_id?: string | number }).conversation_id ?? conversationId)
          terminalSync = (async () => {
            await options.loadConversations()
            await options.openConversation(persistedId)
          })()
          return
        }
        if (event.type === 'content') {
          const current = (options.messageMap.value[conversationId] || []).find((item) => item.id === assistantId)
          options.patchMessage(conversationId, assistantId, {
            content: `${current?.content || ''}${String(event.data ?? '')}`,
          })
          void scrollBottom()
        }
        if (event.type === 'error') {
          options.patchMessage(conversationId, assistantId, {
            isStreaming: false,
            content: `[错误] ${String(event.data ?? '未知错误')}`,
          })
        }
      },
      onDone: () => {
        if (terminalConversationReceived) return
        const current = (options.messageMap.value[conversationId] || []).find((item) => item.id === assistantId)
        options.patchMessage(conversationId, assistantId, {
          isStreaming: false,
          content: current?.content || '（模型未返回内容）',
        })
      },
      onError: (error: unknown) => {
        options.patchMessage(conversationId, assistantId, {
          isStreaming: false,
          content: `[请求失败] ${error}`,
        })
      },
    })
    await connection.promise
    await terminalSync
  }

  const sendText = async () => {
    const text = inputText.value.trim()
    if (!text || isSending.value) return
    inputText.value = ''
    await options.sendMessage(text, options.paperId.value, currentConversationId.value ?? undefined)
  }
  const handleKeydown = (event: KeyboardEvent) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void sendText()
    }
  }
  const handlePopupKeydown = (event: KeyboardEvent) => {
    if (event.key === 'Enter') {
      event.preventDefault()
      void sendVision()
    }
    if (event.key === 'Escape') closePopup()
  }
  const onPdfProgress = (payload: PdfProgress) => { pdfProgress.value = payload }
  const downloadPdf = () => {
    const url = paper.value?.pdf_media_url
    if (url) window.open(url, '_blank', 'noopener,noreferrer')
  }

  return {
    paper, paperLoading, paperError, showConvPanel, currentConversationId, conversationList,
    activeConversationTitle, inputText, setChatListRef, isSending, messages,
    visionPopup, setPopupInputRef, pdfProgress, initializePaperContext, handlePaperIdChange,
    switchConversation, newConversation, deleteCurrentConversation, toggleThinking,
    isThinkingExpanded, onRightclickRegion, closePopup, sendVision, sendText,
    handleKeydown, handlePopupKeydown, onPdfProgress, downloadPdf,
  }
}
