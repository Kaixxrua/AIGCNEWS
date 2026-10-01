import { computed, nextTick, ref, watch, type Ref } from 'vue'
import {
  filterAndSortGlobalConversations,
  getMessageWatcherSignature,
  mapChatStoreMessage,
  type PaperReaderMessage,
} from '@/features/papers/paperReaderModel'
import type { ChatMessage, ConversationSummary } from '@/stores/chatStore'
import { i18n } from '@/i18n'

export interface PaperReaderPaper {
  id: string
  title: string
  url?: string
  summary?: string
  published_date?: string
  /** 接口给的是 JSON 字符串，旧数据可能是数组；版头用 parsePaperAuthors 读。 */
  authors?: string[] | string | null
  arxiv_id?: string | null
  source_channel?: string
  rank_in_period?: number
  raw_score?: number
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
  /** 游客只读模式：false 时不引导会话、不发送消息（默认 true）。 */
  conversationEnabled?: Ref<boolean>
}

export function usePaperReaderController<TPaper extends PaperReaderPaper>(options: PaperReaderControllerOptions<TPaper>) {
  const conversationEnabled = options.conversationEnabled ?? ref(true)
  const paper = ref<TPaper | null>(null) as Ref<TPaper | null>
  const paperLoading = ref(true)
  const paperError = ref('')
  const showConvPanel = ref(false)
  const inputText = ref('')
  const chatListRef = ref<HTMLElement | null>(null)
  const thinkingExpanded = ref<Record<string, boolean>>({})

  const currentConversationId = computed(() => options.activeConversationId.value)
  const conversationList = computed(() => filterAndSortGlobalConversations(Object.values(options.conversationMap.value)))
  const messages = computed<PaperReaderMessage[]>(() => {
    const active = currentConversationId.value
    if (!active) return []
    return (options.messageMap.value[active] || []).map(mapChatStoreMessage)
  })
  const activeConversationTitle = computed(() => {
    const id = currentConversationId.value
    if (!id) return i18n.global.t('chat.paperConversationTitle')
    return options.conversationMap.value[id]?.title || i18n.global.t('chat.paperConversationTitle')
  })
  const isSending = computed(() => options.isStreaming.value)

  const loadPaper = async (id: string) => {
    if (!id) {
      paperError.value = i18n.global.t('paper.invalidId')
      paperLoading.value = false
      return
    }
    paperLoading.value = true
    paperError.value = ''
    try {
      paper.value = await options.fetchPaper(id)
      if (!paper.value) paperError.value = i18n.global.t('paper.notFound')
    } catch (error) {
      paperError.value = String(error)
    } finally {
      paperLoading.value = false
    }
  }

  const initializePaperContext = async (id: string) => {
    await loadPaper(id)
    if (!conversationEnabled.value) return
    if (!options.activeConversationId.value) await options.ensureGlobalConversation()
    await options.loadConversations()
  }

  const handlePaperIdChange = (newId: string) => {
    void initializePaperContext(newId)
  }

  const switchConversation = async (conversationId: string) => {
    showConvPanel.value = false
    if (conversationId === options.activeConversationId.value) return
    await options.openConversation(conversationId)
  }

  const newConversation = async () => {
    showConvPanel.value = false
    await options.ensureGlobalConversation(i18n.global.t('chat.defaultConversationTitle'))
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
  const scrollBottom = async () => {
    await nextTick()
    if (chatListRef.value) chatListRef.value.scrollTop = chatListRef.value.scrollHeight
  }

  watch(() => getMessageWatcherSignature(messages.value), () => { void scrollBottom() })

  const toggleThinking = (messageId: string) => {
    thinkingExpanded.value = { ...thinkingExpanded.value, [messageId]: !thinkingExpanded.value[messageId] }
  }
  const isThinkingExpanded = (messageId: string) => !!thinkingExpanded.value[messageId]

  const sendText = async () => {
    if (!conversationEnabled.value) return
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
  return {
    paper, paperLoading, paperError, showConvPanel, currentConversationId, conversationList,
    activeConversationTitle, inputText, setChatListRef, isSending, messages,
    initializePaperContext, handlePaperIdChange,
    switchConversation, newConversation, deleteCurrentConversation, toggleThinking,
    isThinkingExpanded, sendText,
    handleKeydown,
  }
}
