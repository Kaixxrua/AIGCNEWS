import { defineStore } from 'pinia'
import {
  type ChatAttachmentRef,
  type ChatMessageDTO,
  createConversation,
  deleteConversation as apiDeleteConversation,
  ensureConversation,
  fetchConversationDetail,
  fetchConversations,
  deleteConversationMessage,
} from '../services/chat/chatApi'
import {
  connectChatStream,
  initialChatStreamEventState,
  reduceChatStreamEvent,
} from '../features/chat/chatStreamBoundary'
import {
  ChatLifecycleCoordinator,
  type ChatLifecycleState,
} from '../features/chat/chatLifecycleCoordinator'
import {
  buildChatHistory,
  normalizeChatAttachment,
  normalizeChatMessage,
  normalizeConversation,
  type ChatMessage,
  type ChatSettings,
  type ConversationScope,
  type ConversationSummary,
  type StreamPhase,
} from '../features/chat/chatModel'

export type {
  ChatMessage,
  ChatRole,
  ChatSettings,
  ConversationScope,
  ConversationSummary,
  StreamPhase,
} from '../features/chat/chatModel'

let _msgIdCounter = 0
function nextLocalMsgId(): string {
  return `msg_${Date.now()}_${++_msgIdCounter}`
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

type ChatStoreContext = ChatState & {
  $id: string
  $dispose(): void
}

const _coordinators = new WeakMap<object, ChatLifecycleCoordinator>()

function lifecycleState(store: ChatStoreContext): ChatLifecycleState {
  return {
    activeConversationId: store.activeConversationId,
    activeScope: store.activeScope,
    conversationMap: store.conversationMap,
    messageMap: store.messageMap,
  }
}

function applyLifecycleState(store: ChatStoreContext, state: ChatLifecycleState) {
  store.activeConversationId = state.activeConversationId
  store.activeScope = state.activeScope
  store.conversationMap = state.conversationMap
  store.messageMap = state.messageMap
}

function coordinatorFor(store: ChatStoreContext): ChatLifecycleCoordinator {
  const existing = _coordinators.get(store)
  if (existing) {
    existing.synchronizeState(lifecycleState(store))
    return existing
  }
  const coordinator = new ChatLifecycleCoordinator({
    async listConversations(selector) {
      const response = await fetchConversations({ scope: selector.scope, page: 1, page_size: 50 })
      return response.items
        .map(normalizeConversation)
        .filter((conversation) => selector.scopeKey === undefined || conversation.scopeKey === selector.scopeKey)
    },
    async fetchConversationDetail(conversationId) {
      const detail = await fetchConversationDetail(conversationId)
      const conversation = normalizeConversation(detail.conversation)
      return {
        conversation,
        messages: detail.messages.map((item) => normalizeChatMessage(item, conversation.id)),
      }
    },
    async createConversation(input) {
      return normalizeConversation(await createConversation({
        scope: input.scope,
        scope_key: input.scopeKey ?? null,
        title: input.title,
      }))
    },
    async ensureConversation(input) {
      return normalizeConversation(await ensureConversation({
        scope: input.scope,
        scope_key: input.scopeKey ?? null,
        title: input.title,
      }))
    },
    async deleteConversation(conversationId) {
      await apiDeleteConversation(conversationId)
    },
  }, lifecycleState(store))
  coordinator.subscribe((state) => applyLifecycleState(store, state))
  const originalDispose = store.$dispose.bind(store)
  store.$dispose = () => {
    coordinator.dispose()
    _coordinators.delete(store)
    originalDispose()
  }
  _coordinators.set(store, coordinator)
  return coordinator
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
      return coordinatorFor(this as ChatStoreContext).createAndSelect({ scope, title })
    },

    /**
     * 删除当前活跃会话（调用后端真正删除），然后切换到最新的全局会话或创建新会话。
     */
    async deleteActiveConversation() {
      const convId = this.activeConversationId
      if (!convId) return
      const coordinator = coordinatorFor(this as ChatStoreContext)
      await coordinator.deleteConversation(convId)
      const globalConversations = await coordinator.replaceConversationList({ scope: 'global' })
      const fallback = [...globalConversations].sort((a, b) => {
        const aTime = a.updatedAt ?? a.createdAt ?? ''
        const bTime = b.updatedAt ?? b.createdAt ?? ''
        return bTime.localeCompare(aTime) || a.id.localeCompare(b.id)
      })[0]
      if (fallback) {
        await coordinator.selectConversation(fallback.id)
      } else {
        await coordinator.createAndSelect({ scope: 'global' })
      }
    },

    addPendingAttachment(attachment: ChatAttachmentRef | string) {
      const normalized = typeof attachment === 'string'
        ? { id: attachment, name: attachment, mimeType: '', modality: 'image' as const, parseStatus: 'uploaded' as const }
        : normalizeChatAttachment(attachment)
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
      return coordinatorFor(this as ChatStoreContext).replaceConversationList({ scope })
    },

    async openConversation(conversationId: string | number) {
      this.loadingHistory = true
      try {
        await coordinatorFor(this as ChatStoreContext).selectConversation(String(conversationId))
      } finally {
        this.loadingHistory = false
      }
    },

    async ensureScopeConversation(scope: ConversationScope, scopeKey?: string | null, title?: string) {
      const coordinator = coordinatorFor(this as ChatStoreContext)
      const summary = await coordinator.ensureAndSelect({ scope, scopeKey: scopeKey ?? undefined, title })
      if (summary && !this.messageMap[summary.id]) {
        await coordinator.selectConversation(summary.id)
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
        const messages = detail.messages.map((item) => normalizeChatMessage(item, summary.id))
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
      const normalized = normalizeChatMessage(dto, conversationId)
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
      coordinatorFor(this as ChatStoreContext).abortActiveRun()
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
      return buildChatHistory(
        this.messageMap[conversationId] || [],
        this.settings.maxHistoryTurns,
      )
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
      const { temperature } = this.settings
      let eventState = initialChatStreamEventState(params.conversationId)
      let sseFinished = false
      const coordinator = coordinatorFor(this as ChatStoreContext)
      let runValid = true

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
        if (eventState.persistedConversationId) {
          await this.openConversation(eventState.persistedConversationId)
          // openConversation 会用后端 DTO 覆盖消息列表。
          // 后端持久化的 has_thinking 可能为 false（普通模型无 thinking），
          // 需要把 thinkingDurationSec 回写到最后一条 assistant 消息上，
          // 并确保 hasThinking=true 以保留"已完成深度思考（用时 N 秒）"提示。
          const convMessages = this.messageMap[eventState.persistedConversationId] || []
          const lastAssistant = [...convMessages].reverse().find((m) => m.role === 'assistant')
          if (lastAssistant && durationSec > 0) {
            this.patchMessage(eventState.persistedConversationId, lastAssistant.id, {
              hasThinking: true,
              thinkingDurationSec: durationSec,
            })
          }
        }
      }

      const startTyping = () => {
        if (typingTimer !== null) return
        typingTimer = setInterval(() => {
          if (!runValid) {
            if (typingTimer !== null) clearInterval(typingTimer)
            typingTimer = null
            return
          }
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
                sources: eventState.pendingSources.length > 0 ? eventState.pendingSources : finalMsg.sources,
              })
            }
            void finishStreaming()
          }
        }, 16)
      }

      const run = coordinator.startStreamRun({
        command: {
          text: params.text,
          conversationId: params.conversationId,
          history: params.history,
          temperature,
          // scope 取决于会话本身的 scope，而非 paperId 是否存在
          scope: this.conversationMap[params.conversationId]?.scope ?? 'global',
          webSearch: this.settings.webSearch,
          attachments: params.attachments,
          paperId: params.paperId,
          regenerateMessageId: params.regenerateMessageId,
        },
        conversationId: params.conversationId,
        messageId: params.assistantTempId,
        attachments: params.attachments,
        attachmentRestoration: 'never',
        connect: (command, callbacks) => {
          const connection = connectChatStream(command, {
            onMessage: callbacks.onEvent,
            onDone: callbacks.onDone,
            onError: callbacks.onError,
          })
          return {
            abort: () => connection.controller.abort(),
            promise: connection.promise,
          }
        },
        callbacks: {
          onEvent: (payload: unknown) => {
          const transition = reduceChatStreamEvent(eventState, payload)
          eventState = transition.state
          this.streamPhase = eventState.phase

          if (transition.effect.type === 'thinking') {
            for (const ch of transition.effect.chunk) thinkingQueue.push(ch)
            startTyping()
            return
          }
          if (transition.effect.type === 'content') {
            for (const ch of transition.effect.thinkingChunk) thinkingQueue.push(ch)
            // 记录首次收到 content 的时间，用于计算思维链时长
            if (!thinkingEndMs) {
              thinkingEndMs = Date.now()
            }
            for (const ch of transition.effect.chunk) contentQueue.push(ch)
            startTyping()
            return
          }
          if (transition.effect.type === 'error') {
            sseFinished = true
            if (typingTimer !== null) {
              clearInterval(typingTimer)
              typingTimer = null
            }
            this.patchMessage(params.conversationId, params.assistantTempId, {
              content: `请求失败：${transition.effect.message}`,
              isThinking: false,
              isStreaming: false,
            })
            this.isStreaming = false
            this.streamPhase = 'error'
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
              return
            }
            return false
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
        },
        onAbort: (_reason, context) => {
          runValid = false
          if (typingTimer !== null) {
            clearInterval(typingTimer)
            typingTimer = null
          }
          this.patchMessage(context.conversationId, context.messageId, {
            isThinking: false,
            isStreaming: false,
          })
          this.isStreaming = false
          this.streamPhase = 'idle'
          },
        },
      })

      this.isStreaming = true
      this.streamPhase = eventState.phase
      await run.promise
    },
  },
})
