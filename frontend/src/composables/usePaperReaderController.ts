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
  const visionMessages = ref<PaperReaderMessage[]>([])
  const thinkingExpanded = ref<Record<string, boolean>>({})
  const visionPopup = ref<VisionPopup | null>(null)
  const popupInputRef = ref<HTMLInputElement | null>(null)
  const pdfProgress = ref<PdfProgress>({ phase: 'idle', loadedPages: 0, totalPages: 0, percent: 0 })

  const currentConversationId = computed(() => options.activeConversationId.value)
  const conversationList = computed(() => filterAndSortGlobalConversations(Object.values(options.conversationMap.value)))
  const chatMessages = computed<PaperReaderMessage[]>(() => {
    const active = currentConversationId.value
    if (!active) return []
    return (options.messageMap.value[active] || []).map(mapChatStoreMessage)
  })
  const messages = computed<PaperReaderMessage[]>(() => [...chatMessages.value, ...visionMessages.value])
  const activeConversationTitle = computed(() => {
    const id = currentConversationId.value
    if (!id) return 'AI 对话'
    return options.conversationMap.value[id]?.title || 'AI 对话'
  })
  const isSending = computed(() => options.isStreaming.value)

  const loadGlobalConvList = async () => { await options.loadConversations() }

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
    await loadGlobalConvList()
  }

  const handlePaperIdChange = (newId: string) => {
    visionPopup.value = null
    void initializePaperContext(newId)
  }

  const switchConversation = async (conversationId: string) => {
    showConvPanel.value = false
    if (conversationId === options.activeConversationId.value) return
    visionMessages.value = []
    await options.openConversation(conversationId)
  }

  const newConversation = async () => {
    showConvPanel.value = false
    visionMessages.value = []
    await options.ensureGlobalConversation('新对话')
    await loadGlobalConvList()
  }

  const deleteCurrentConversation = async () => {
    if (!currentConversationId.value) return
    visionMessages.value = []
    showConvPanel.value = false
    await options.deleteActiveConversation()
    await loadGlobalConvList()
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
  const patchVisionMessage = (id: string, patch: Partial<PaperReaderMessage>) => {
    visionMessages.value = visionMessages.value.map((item) => item.id === id ? { ...item, ...patch } : item)
  }

  const sendVision = async () => {
    if (!visionPopup.value?.question.trim() || isSending.value || !currentConversationId.value) return
    const question = visionPopup.value.question.trim()
    const base64 = visionPopup.value.base64
    closePopup()

    const userId = `vision_user_${Date.now()}`
    const assistantId = `vision_assistant_${Date.now()}`
    visionMessages.value = [
      ...visionMessages.value,
      { id: userId, role: 'user', content: `[截图追问] ${question}`, imageBase64: base64 },
      { id: assistantId, role: 'assistant', content: '', isStreaming: true },
    ]

    let imageId: string
    try {
      const upload = await options.uploadScreenshot({ image_base64: base64, mime_type: 'image/jpeg' })
      imageId = upload.image_id
    } catch (error) {
      patchVisionMessage(assistantId, { isStreaming: false, content: `[上传失败] 截图上传失败：${error}` })
      return
    }

    await options.connectEventSource({
      url: options.visionRelayUrl,
      body: {
        conversation_id: currentConversationId.value,
        paper_id: options.paperId.value || null,
        question,
        image_id: imageId,
        history: chatMessages.value
          .filter((message) => message.role !== 'assistant' || message.content)
          .slice(-12)
          .map((message) => ({ role: message.role, content: message.content })),
      },
      onMessage: (payload: unknown) => {
        const event = payload as { type: string; data?: string }
        if (event.type === 'status') return
        if (event.type === 'vision_extract') {
          patchVisionMessage(assistantId, { visionExtract: event.data ?? '' })
          return
        }
        if (event.type === 'content') {
          const current = visionMessages.value.find((item) => item.id === assistantId)
          patchVisionMessage(assistantId, { content: `${current?.content || ''}${event.data ?? ''}` })
          void scrollBottom()
        }
        if (event.type === 'error') patchVisionMessage(assistantId, { isStreaming: false, content: `[错误] ${event.data ?? '未知错误'}` })
      },
      onDone: () => {
        const current = visionMessages.value.find((item) => item.id === assistantId)
        patchVisionMessage(assistantId, { isStreaming: false, content: current?.content || '（模型未返回内容）' })
      },
      onError: (error: unknown) => {
        patchVisionMessage(assistantId, { isStreaming: false, content: `[请求失败] ${error}` })
      },
    })
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
    activeConversationTitle, inputText, chatListRef, setChatListRef, isSending, messages, thinkingExpanded,
    visionPopup, popupInputRef, setPopupInputRef, pdfProgress, initializePaperContext, handlePaperIdChange,
    switchConversation, newConversation, deleteCurrentConversation, toggleThinking,
    isThinkingExpanded, onRightclickRegion, closePopup, sendVision, sendText,
    handleKeydown, handlePopupKeydown, onPdfProgress, downloadPdf,
  }
}
