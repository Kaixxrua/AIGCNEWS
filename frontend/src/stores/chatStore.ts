import { defineStore } from 'pinia'
import { useEventSource, type SseConnection } from '../composables/useEventSource'
import {
  api,
  type ChatAttachmentRef,
  type ChatMessageDTO,
  type ConversationSummaryDTO,
  createConversation,
  deleteConversation as apiDeleteConversation,
  ensureConversation,
  fetchConversationDetail,
  fetchConversations,
  deleteConversationMessage,
} from '../services/api'

export type ChatRole = 'user' | 'assistant'
export type ConversationScope = 'global' | 'paper'
export type StreamPhase = 'idle' | 'searching' | 'reranking' | 'answering' | 'error'

let _msgIdCounter = 0
function nextLocalMsgId(): string {
  return `msg_${Date.now()}_${++_msgIdCounter}`
}

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

interface ChatState {
  activeConversationId: string | null
  activeScope: ConversationScope
  conversationMap: Record<string, ConversationSummary>
  messageMap: Record<string, ChatMessage[]>
  pendingAttachments: ChatAttachmentRef[]
  loadingHistory: boolean
  isStreaming: boolean
  streamPhase: StreamPhase
  settings: ChatSettings
}

type StreamPayload =
  | { type: 'sources'; data: unknown[] }
  | { type: 'content'; data: string }
  | { type: 'thinking'; data: string }
  | { type: 'status'; data: string }
  | { type: 'conversation'; data: { conversation_id: number | string; message_id: number | string } }
  | { type: string; data?: unknown }

const THINK_TAG_RE = /<think>([\s\S]*?)<\/think>/
let _activeConnection: SseConnection | null = null

function normalizeAttachment(input: ChatAttachmentRef | Record<string, unknown>): ChatAttachmentRef {
  const raw = input as Record<string, unknown>
  return {
    id: String(raw.id ?? ''),
    name: String(raw.name ?? raw.file_name ?? ''),
    mimeType: String(raw.mimeType ?? raw.mime_type ?? ''),
    modality: (raw.modality === 'pdf' ? 'pdf' : 'image') as 'image' | 'pdf',
    parseStatus: (raw.parseStatus ?? raw.parse_status ?? 'uploaded') as
      | 'uploaded'
      | 'processing'
      | 'ready'
      | 'failed',
    progress: typeof raw.progress === 'number' ? raw.progress : undefined,
  }
}

function normalizeConversation(dto: ConversationSummaryDTO): ConversationSummary {
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

function normalizeMessage(dto: ChatMessageDTO, conversationIdOverride?: string): ChatMessage {
  const thinking = dto.thinking || ''
  return {
    id: String(dto.id),
    conversationId: conversationIdOverride || String(dto.conversation_id),
    role: dto.role,
    content: dto.content || '',
    thinking,
    thinkingPreview: dto.thinking_preview || (thinking ? `${thinking.slice(0, 80)}${thinking.length > 80 ? '…' : ''}` : ''),
    hasThinking: dto.has_thinking ?? !!thinking,
    isThinking: dto.is_thinking ?? false,
    thinkingDurationSec: typeof (dto as unknown as Record<string, unknown>).thinking_duration_sec === 'number'
      ? (dto as unknown as Record<string, unknown>).thinking_duration_sec as number
      : 0,
    isStreaming: dto.is_streaming ?? false,
    sources: dto.sources || [],
    attachments: Array.isArray(dto.attachments) ? dto.attachments.map((item) => normalizeAttachment(item)) : [],
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
  }
}

export const useChatStore = defineStore('chat', {
  state: (): ChatState => ({
    activeConversationId: null,
    activeScope: 'global',
    conversationMap: {},
    messageMap: {},
    pendingAttachments: [],
    loadingHistory: false,
    isStreaming: false,
    streamPhase: 'idle',
    settings: {
      maxHistoryTurns: 5,
      temperature: 0.7,
      webSearch: false,
    },
  }),

  getters: {
    messages(state): ChatMessage[] {
      if (!state.activeConversationId) return []
      return state.messageMap[state.activeConversationId] || []
    },
    activeConversation(state): ConversationSummary | null {
      if (!state.activeConversationId) return null
      return state.conversationMap[state.activeConversationId] || null
    },
  },

  actions: {
    updateSettings(patch: Partial<ChatSettings>) {
      this.settings = { ...this.settings, ...patch }
    },

    clearMessages() {
      if (!this.activeConversationId) return
      this.messageMap[this.activeConversationId] = []
    },

    /**
     * 强制创建新会话并切换到该会话（解决 ensure 只返回已有会话的问题）。
     */
    async createNewConversation(scope: ConversationScope = 'global', title?: string) {
      const dto = await createConversation({ scope, title })
      const summary = normalizeConversation(dto)
      this.conversationMap = { ...this.conversationMap, [summary.id]: summary }
      this.messageMap = { ...this.messageMap, [summary.id]: [] }
      this.activeConversationId = summary.id
      this.activeScope = summary.scope
      return summary
    },

    /**
     * 删除当前活跃会话（调用后端真正删除），然后切换到最新的全局会话或创建新会话。
     */
    async deleteActiveConversation() {
      const convId = this.activeConversationId
      if (!convId) return
      try {
        await apiDeleteConversation(convId)
      } catch (e) {
        console.error('[chatStore] 删除会话失败', e)
      }
      // 从本地状态中移除
      const { [convId]: _removedConv, ...restConvMap } = this.conversationMap
      this.conversationMap = restConvMap
      const { [convId]: _removedMsgs, ...restMsgMap } = this.messageMap
      this.messageMap = restMsgMap
      this.activeConversationId = null
      // 重新加载会话列表，切换到最新的全局会话或创建新的
      await this.loadConversations('global')
      const globalConvs = Object.values(this.conversationMap)
        .filter((c) => c.scope === 'global')
        .sort((a, b) => (b.updatedAt ?? '').localeCompare(a.updatedAt ?? ''))
      const firstConv = globalConvs[0]
      if (firstConv) {
        await this.openConversation(firstConv.id)
      } else {
        await this.createNewConversation('global')
      }
    },

    addPendingAttachment(attachment: ChatAttachmentRef | string) {
      const normalized = typeof attachment === 'string'
        ? { id: attachment, name: attachment, mimeType: '', modality: 'image' as const, parseStatus: 'uploaded' as const }
        : normalizeAttachment(attachment)
      const exists = this.pendingAttachments.some((item) => item.id === normalized.id)
      if (!exists) {
        this.pendingAttachments = [...this.pendingAttachments, normalized]
      }
    },

    removePendingAttachment(attachmentId: string) {
      this.pendingAttachments = this.pendingAttachments.filter((item) => item.id !== attachmentId)
    },

    clearPendingAttachments() {
      this.pendingAttachments = []
    },

    async loadConversations(scope?: ConversationScope) {
      const response = await fetchConversations({ scope, page: 1, page_size: 50 })
      const merged = { ...this.conversationMap }
      for (const item of response.items) {
        const normalized = normalizeConversation(item)
        merged[normalized.id] = normalized
      }
      this.conversationMap = merged
      return response.items.map((item) => normalizeConversation(item))
    },

    async openConversation(conversationId: string | number) {
      const id = String(conversationId)
      this.loadingHistory = true
      try {
        const detail = await fetchConversationDetail(id)
        const conversation = normalizeConversation(detail.conversation)
        const messages = detail.messages.map((item) => normalizeMessage(item, conversation.id))
        this.conversationMap = { ...this.conversationMap, [conversation.id]: conversation }
        this.messageMap = { ...this.messageMap, [conversation.id]: messages }
        this.activeConversationId = conversation.id
        this.activeScope = conversation.scope
      } finally {
        this.loadingHistory = false
      }
    },

    async ensureScopeConversation(scope: ConversationScope, scopeKey?: string | null, title?: string) {
      const summary = normalizeConversation(await ensureConversation({ scope, scope_key: scopeKey ?? null, title }))
      this.conversationMap = { ...this.conversationMap, [summary.id]: summary }
      this.activeConversationId = summary.id
      this.activeScope = summary.scope
      if (!this.messageMap[summary.id]) {
        await this.openConversation(summary.id)
      }
      return summary
    },

    async ensurePaperConversation(paperId: string, title?: string) {
      return this.ensureScopeConversation('paper', paperId, title)
    },

    /**
     * 获取或创建论文专属会话，但**不修改** activeConversationId / activeScope。
     * 供 PaperReadView 使用，避免污染 ChatView 的全局会话状态。
     */
    async fetchPaperConversation(paperId: string, title?: string): Promise<ConversationSummary> {
      const summary = normalizeConversation(
        await ensureConversation({ scope: 'paper', scope_key: paperId, title }),
      )
      this.conversationMap = { ...this.conversationMap, [summary.id]: summary }
      if (!this.messageMap[summary.id]) {
        // 仅拉取历史消息，不切换 activeConversationId
        const detail = await fetchConversationDetail(summary.id)
        const messages = detail.messages.map((item) => normalizeMessage(item, summary.id))
        this.messageMap = { ...this.messageMap, [summary.id]: messages }
      }
      return summary
    },

    /**
     * 加载指定论文的所有历史会话列表（scope=paper, scope_key=paperId），不影响 active 状态
     */
    async loadPaperConversations(paperId: string): Promise<ConversationSummary[]> {
      const response = await fetchConversations({ scope: 'paper', page: 1, page_size: 50 })
      const paperConvs = response.items
        .map(normalizeConversation)
        .filter((c) => c.scopeKey === paperId)
      const merged = { ...this.conversationMap }
      for (const c of paperConvs) {
        merged[c.id] = c
      }
      this.conversationMap = merged
      return paperConvs
    },

    async ensureGlobalConversation(title?: string) {
      return this.ensureScopeConversation('global', null, title)
    },

    appendLocalMessage(conversationId: string, message: ChatMessage) {
      const current = this.messageMap[conversationId] || []
      this.messageMap = {
        ...this.messageMap,
        [conversationId]: [...current, message],
      }
    },

    patchMessage(conversationId: string, messageId: string, patch: Partial<ChatMessage>) {
      const current = this.messageMap[conversationId] || []
      this.messageMap = {
        ...this.messageMap,
        [conversationId]: current.map((item) => item.id === messageId ? { ...item, ...patch } : item),
      }
    },

    replaceTempAssistantMessage(conversationId: string, tempId: string, dto: ChatMessageDTO) {
      const current = this.messageMap[conversationId] || []
      const normalized = normalizeMessage(dto, conversationId)
      this.messageMap = {
        ...this.messageMap,
        [conversationId]: current.map((item) => item.id === tempId ? normalized : item),
      }
    },

    getMessageById(messageId: string): { conversationId: string; message: ChatMessage } | null {
      for (const [conversationId, messages] of Object.entries(this.messageMap)) {
        const found = messages.find((item) => item.id === messageId)
        if (found) return { conversationId, message: found }
      }
      return null
    },

    abortGeneration() {
      if (_activeConnection) {
        _activeConnection.controller.abort()
        _activeConnection = null
      }
      this.isStreaming = false
      this.streamPhase = 'idle'
      const conversationId = this.activeConversationId
      if (!conversationId) return
      const current = this.messageMap[conversationId] || []
      this.messageMap = {
        ...this.messageMap,
        [conversationId]: current.map((item) => item.isStreaming ? { ...item, isStreaming: false, isThinking: false } : item),
      }
    },

    async deleteMessage(messageId: string) {
      const result = await deleteConversationMessage(messageId)
      await this.openConversation(result.conversation_id)
    },

    async regenerateMessage(messageId: string) {
      const located = this.getMessageById(messageId)
      if (!located) return
      if (this.isStreaming) this.abortGeneration()
      await this.openConversation(located.conversationId)
      const current = this.messageMap[located.conversationId] || []
      const idx = current.findIndex((item) => item.id === messageId)
      const userMsg = idx > 0 ? current[idx - 1] : null
      if (!userMsg || userMsg.role !== 'user') return
      this.messageMap = {
        ...this.messageMap,
        [located.conversationId]: current.slice(0, idx),
      }
      const assistantTempId = nextLocalMsgId()
      this.appendLocalMessage(located.conversationId, {
        id: assistantTempId,
        conversationId: located.conversationId,
        role: 'assistant',
        content: '',
        thinking: '',
        thinkingPreview: '',
        hasThinking: true,
        isThinking: true,
        thinkingDurationSec: 0,
        isStreaming: true,
        sources: [],
        attachments: [],
      })
      await this._streamToAssistant({
        text: userMsg.content,
        conversationId: located.conversationId,
        paperId: this.conversationMap[located.conversationId]?.scope === 'paper'
          ? this.conversationMap[located.conversationId]?.scopeKey
          : undefined,
        assistantTempId,
        history: this.buildHistory(located.conversationId),
        regenerateMessageId: messageId,
      })
    },

    buildHistory(conversationId: string) {
      const historySlice = this.settings.maxHistoryTurns > 0 ? this.settings.maxHistoryTurns * 2 : 0
      const current = this.messageMap[conversationId] || []
      return historySlice > 0
        ? current
            .slice(-historySlice)
            .filter((item) => item.content.trim() !== '')
            .map((item) => ({ role: item.role, content: item.content }))
        : []
    },

    async sendMessage(text: string, paperId?: string, paperConversationId?: string) {
      const trimmed = text.trim()
      if (!trimmed && this.pendingAttachments.length === 0) return

      let conversation = this.activeConversation
      if (paperConversationId) {
        // 论文页传入已知 conversationId，直接使用，不修改 activeConversationId
        conversation = this.conversationMap[paperConversationId] ?? null
        if (!conversation) {
          // fallback: 重新 fetch（不影响 active）
          conversation = await this.fetchPaperConversation(paperId ?? '', trimmed || '论文对话')
        }
      } else if (paperId) {
        // 兼容旧调用：有 paperId 但无 paperConversationId 时，仍走 fetch 不覆盖 active
        conversation = await this.fetchPaperConversation(paperId, trimmed || '论文对话')
      } else if (!conversation || conversation.scope !== 'global') {
        conversation = await this.ensureGlobalConversation(trimmed || '新对话')
      }
      if (!conversation) return

      const conversationId = conversation.id
      const history = this.buildHistory(conversationId)
      const attachments = [...this.pendingAttachments]
      this.clearPendingAttachments()

      const userMessage: ChatMessage = {
        id: nextLocalMsgId(),
        conversationId,
        role: 'user',
        content: trimmed || '请结合附件内容进行分析。',
        thinking: '',
        thinkingPreview: '',
        hasThinking: false,
        isThinking: false,
        thinkingDurationSec: 0,
        isStreaming: false,
        sources: [],
        attachments,
      }
      this.appendLocalMessage(conversationId, userMessage)

      const assistantTempId = nextLocalMsgId()
      this.appendLocalMessage(conversationId, {
        id: assistantTempId,
        conversationId,
        role: 'assistant',
        content: '',
        thinking: '',
        thinkingPreview: '',
        hasThinking: true,
        isThinking: true,
        thinkingDurationSec: 0,
        isStreaming: true,
        sources: [],
        attachments: [],
      })

      await this._streamToAssistant({
        text: userMessage.content,
        conversationId,
        paperId,
        assistantTempId,
        history,
        attachments,
      })
    },

    async _streamToAssistant(params: {
      text: string
      conversationId: string
      assistantTempId: string
      history: Array<{ role: string; content: string }>
      attachments?: ChatAttachmentRef[]
      paperId?: string
      regenerateMessageId?: string
    }) {
      const { connect } = useEventSource()
      const { temperature } = this.settings
      let pendingSources: unknown[] = []
      let sseFinished = false
      let persistedConversationId = params.conversationId

      this.isStreaming = true
      this.streamPhase = 'searching'

      const contentQueue: string[] = []
      const thinkingQueue: string[] = []
      const CONTENT_CHARS_PER_FRAME = 3
      const THINKING_CHARS_PER_FRAME = 12
      let typingTimer: ReturnType<typeof setInterval> | null = null

      // 思维链计时：记录首次收到 thinking/content 事件的时间
      let thinkingStartMs = Date.now()
      let thinkingEndMs = 0
      let contentStarted = false

      const finishStreaming = async () => {
        // 保存流式阶段计算好的时长
        const durationSec = thinkingEndMs
          ? Math.round((thinkingEndMs - thinkingStartMs) / 1000)
          : Math.round((Date.now() - thinkingStartMs) / 1000)

        this.isStreaming = false
        this.streamPhase = 'idle'
        _activeConnection = null
        if (persistedConversationId) {
          await this.openConversation(persistedConversationId)
          // openConversation 会用后端 DTO 覆盖消息列表。
          // 后端持久化的 has_thinking 可能为 false（普通模型无 thinking），
          // 需要把 thinkingDurationSec 回写到最后一条 assistant 消息上，
          // 并确保 hasThinking=true 以保留"已完成深度思考（用时 N 秒）"提示。
          const convMessages = this.messageMap[persistedConversationId] || []
          const lastAssistant = [...convMessages].reverse().find((m) => m.role === 'assistant')
          if (lastAssistant && durationSec > 0) {
            this.patchMessage(persistedConversationId, lastAssistant.id, {
              hasThinking: true,
              thinkingDurationSec: durationSec,
            })
          }
        }
      }

      const startTyping = () => {
        if (typingTimer !== null) return
        typingTimer = setInterval(() => {
          const current = (this.messageMap[params.conversationId] || []).find((item) => item.id === params.assistantTempId)
          if (!current) return

          let updated = false
          if (thinkingQueue.length > 0) {
            const chars = thinkingQueue.splice(0, THINKING_CHARS_PER_FRAME).join('')
            const thinking = current.thinking + chars
            this.patchMessage(params.conversationId, params.assistantTempId, {
              thinking,
              thinkingPreview: `${thinking.slice(0, 80)}${thinking.length > 80 ? '…' : ''}`,
              hasThinking: true,
              isThinking: true,
              isStreaming: true,
            })
            updated = true
          } else if (contentQueue.length > 0) {
            const chars = contentQueue.splice(0, CONTENT_CHARS_PER_FRAME).join('')
            // 首次渲染 content 时，结束思维链计时
            if (!contentStarted) {
              contentStarted = true
              thinkingEndMs = thinkingEndMs || Date.now()
              const durationSec = Math.round((thinkingEndMs - thinkingStartMs) / 1000)
              this.patchMessage(params.conversationId, params.assistantTempId, {
                content: current.content + chars,
                isThinking: false,
                isStreaming: true,
                thinkingDurationSec: durationSec,
              })
            } else {
              this.patchMessage(params.conversationId, params.assistantTempId, {
                content: current.content + chars,
                isThinking: false,
                isStreaming: true,
              })
            }
            updated = true
          }

          if (!updated && sseFinished && thinkingQueue.length === 0 && contentQueue.length === 0) {
            if (typingTimer !== null) {
              clearInterval(typingTimer)
              typingTimer = null
            }
            const finalMsg = (this.messageMap[params.conversationId] || []).find((item) => item.id === params.assistantTempId)
            if (finalMsg) {
              // 如果一直没有 content（纯思维链无正文），此时也要结束 isThinking
              const durationSec = finalMsg.thinkingDurationSec || Math.round((Date.now() - thinkingStartMs) / 1000)
              this.patchMessage(params.conversationId, params.assistantTempId, {
                isThinking: false,
                isStreaming: false,
                thinkingDurationSec: durationSec,
                content: finalMsg.content || '本次请求未返回正文内容，请检查后端日志。',
                sources: pendingSources.length > 0 ? pendingSources : finalMsg.sources,
              })
            }
            void finishStreaming()
          }
        }, 16)
      }

      const body: Record<string, unknown> = {
        message: params.text,
        history: params.history,
        temperature,
        conversation_id: params.conversationId,
        // scope 取决于会话本身的 scope，而非 paperId 是否存在
        scope: this.conversationMap[params.conversationId]?.scope ?? 'global',
        web_search: this.settings.webSearch,
      }
      if (params.attachments?.length) {
        body.attachment_ids = params.attachments.map((item) => item.id)
      }
      if (params.paperId) {
        body.paper_id = params.paperId
      }

      const baseURL = (api.defaults.baseURL ?? '').replace(/\/+$/, '')
      const connection = connect({
        url: params.regenerateMessageId
          ? `${baseURL}/chat/messages/${params.regenerateMessageId}/regenerate`
          : `${baseURL}/chat/stream`,
        body: params.regenerateMessageId ? { temperature } : body,
        onMessage: (payload: unknown) => {
          const event = payload as StreamPayload
          if (event.type === 'status') {
            const statusText = String(event.data ?? '')
            if (statusText.includes('search')) this.streamPhase = 'searching'
            else if (statusText.includes('rerank')) this.streamPhase = 'reranking'
            else this.streamPhase = 'answering'
            return
          }
          if (event.type === 'sources' && Array.isArray(event.data)) {
            pendingSources = event.data
            return
          }
          if (event.type === 'conversation' && event.data) {
            const conversationData = event.data as { conversation_id?: number | string }
            persistedConversationId = String(conversationData.conversation_id ?? persistedConversationId)
            return
          }
          if (event.type === 'thinking') {
            const chunk = String(event.data ?? '')
            if (!chunk) return
            this.streamPhase = 'answering'
            for (const ch of chunk) thinkingQueue.push(ch)
            startTyping()
            return
          }
          if (event.type === 'content') {
            let chunk = String(event.data ?? '')
            if (!chunk) return
            const thinkMatch = THINK_TAG_RE.exec(chunk)
            if (thinkMatch) {
              const thinkBody = thinkMatch[1]
              const remaining = chunk.replace(THINK_TAG_RE, '').trim()
              if (thinkBody) {
                for (const ch of thinkBody) thinkingQueue.push(ch)
              }
              chunk = remaining
            }
            this.streamPhase = 'answering'
            // 记录首次收到 content 的时间，用于计算思维链时长
            if (!thinkingEndMs) {
              thinkingEndMs = Date.now()
            }
            if (chunk) {
              for (const ch of chunk) contentQueue.push(ch)
            }
            startTyping()
            return
          }
          if (event.type === 'error') {
            sseFinished = true
            if (typingTimer !== null) {
              clearInterval(typingTimer)
              typingTimer = null
            }
            this.patchMessage(params.conversationId, params.assistantTempId, {
              content: `请求失败：${String(event.data ?? '未知错误')}`,
              isThinking: false,
              isStreaming: false,
            })
            this.streamPhase = 'error'
            this.isStreaming = false
            _activeConnection = null
          }
        },
        onDone: () => {
          sseFinished = true
          if (thinkingQueue.length === 0 && contentQueue.length === 0) {
            if (typingTimer !== null) {
              clearInterval(typingTimer)
              typingTimer = null
            }
            void finishStreaming()
          }
        },
        onError: (error: unknown) => {
          sseFinished = true
          if (typingTimer !== null) {
            clearInterval(typingTimer)
            typingTimer = null
          }
          // 提取友好错误消息（支持 429 消息限额等结构化错误）
          const errMsg = error instanceof Error ? error.message : String(error)
          const isLimitError = (error as { status?: number })?.status === 429
            || (error as { errorType?: string })?.errorType === 'message_limit_exceeded'
          this.patchMessage(params.conversationId, params.assistantTempId, {
            content: isLimitError
              ? `⚠️ ${errMsg}`
              : `流式请求失败：${errMsg}`,
            isThinking: false,
            isStreaming: false,
          })
          this.streamPhase = 'error'
          this.isStreaming = false
          _activeConnection = null
        },
      })

      _activeConnection = connection
      await connection.promise
    },
  },
})
