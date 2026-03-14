import { defineStore } from 'pinia'
import { useEventSource } from '../composables/useEventSource'
import { api } from '../services/api'

export type ChatRole = 'user' | 'assistant'

export interface ChatMessage {
  role: ChatRole
  content: string
  thinking: string
  isThinking: boolean
  sources: unknown[]
}

type StreamPayload =
  | { type: 'sources'; data: unknown[] }
  | { type: 'content'; data: string }
  | { type: 'thinking'; data: string }
  | { type: 'status'; data: string }
  | { type: string; data?: unknown }

export interface ChatSettings {
  maxHistoryTurns: number
  temperature: number
}

interface ChatState {
  messages: ChatMessage[]
  settings: ChatSettings
}

export const useChatStore = defineStore('chat', {
  state: (): ChatState => ({
    messages: [],
    settings: {
      maxHistoryTurns: 5,
      temperature: 0.7,
    },
  }),

  actions: {
    appendMessage(role: ChatRole, content: string, sources: unknown[] = [], thinking = '', isThinking = false) {
      this.messages.push({ role, content, thinking, isThinking, sources })
    },

    updateSettings(patch: Partial<ChatSettings>) {
      this.settings = { ...this.settings, ...patch }
    },

    clearMessages() {
      this.messages = []
    },

    async sendMessage(text: string) {
      const trimmed = text.trim()
      if (!trimmed) return

      const { maxHistoryTurns, temperature } = this.settings

      const historySlice = maxHistoryTurns > 0 ? maxHistoryTurns * 2 : 0
      const history =
        historySlice > 0
          ? this.messages
              .slice(-historySlice)
              .filter((m) => m.content.trim() !== '')
              .map((m) => ({ role: m.role, content: m.content }))
          : []

      this.appendMessage('user', trimmed)
      this.appendMessage('assistant', '', [], '', false)

      const assistantIndex = this.messages.length - 1
      const { connect } = useEventSource()

      let pendingSources: unknown[] = []
      let sseFinished = false

      // ── 打字机队列 ────────────────────────────────────────────
      // contentQueue / thinkingQueue 存放待逐字显示的字符
      const contentQueue: string[] = []
      const thinkingQueue: string[] = []

      // content：每帧 3 字符 @16ms ≈ 180字/秒，丝滑打字感
      // thinking：每帧 12 字符 @16ms ≈ 720字/秒，快速扫过无需精读
      const CONTENT_CHARS_PER_FRAME = 3
      const THINKING_CHARS_PER_FRAME = 12

      let typingTimer: ReturnType<typeof setInterval> | null = null

      const startTyping = () => {
        if (typingTimer !== null) return
        typingTimer = setInterval(() => {
          const msg = this.messages[assistantIndex]
          if (!msg) return

          let updated = false

          // 优先消费 thinking 队列（快速）
          if (thinkingQueue.length > 0) {
            const chars = thinkingQueue.splice(0, THINKING_CHARS_PER_FRAME).join('')
            this.messages[assistantIndex] = {
              ...msg,
              thinking: msg.thinking + chars,
              isThinking: true,
            }
            updated = true
          } else if (contentQueue.length > 0) {
            // 消费 content 队列（丝滑打字）
            const chars = contentQueue.splice(0, CONTENT_CHARS_PER_FRAME).join('')
            const currentMsg = this.messages[assistantIndex]
            if (!currentMsg) return
            this.messages[assistantIndex] = {
              ...currentMsg,
              content: currentMsg.content + chars,
              isThinking: false,
            }
            updated = true
          }

          // 两个队列都空了且 SSE 已结束 → 停止打字机，做收尾
          if (!updated && sseFinished && thinkingQueue.length === 0 && contentQueue.length === 0) {
            if (typingTimer !== null) {
              clearInterval(typingTimer)
              typingTimer = null
            }

            const finalMsg = this.messages[assistantIndex]
            if (!finalMsg) return
            this.messages[assistantIndex] = {
              ...finalMsg,
              isThinking: false,
              content: finalMsg.content || '本次请求未返回正文内容，请检查后端日志。',
              sources: pendingSources.length > 0 ? pendingSources : finalMsg.sources,
            }
          }
        }, 16) // ~60fps
      }

      // ── SSE 连接 ──────────────────────────────────────────────
      const baseURL = (api.defaults.baseURL ?? '').replace(/\/+$/, '')
      await connect({
        url: `${baseURL}/chat/stream`,
        body: { message: trimmed, history, temperature },
        onMessage: (payload: unknown) => {
          const event = payload as StreamPayload

          if (event.type === 'status') return

          if (event.type === 'sources' && Array.isArray(event.data)) {
            pendingSources = event.data
            return
          }

          if (event.type === 'thinking') {
            const chunk = String(event.data ?? '')
            if (!chunk) return
            // 将 chunk 逐字符压入 thinking 队列
            for (const ch of chunk) thinkingQueue.push(ch)
            startTyping()
            return
          }

          if (event.type === 'content') {
            const chunk = String(event.data ?? '')
            if (!chunk) return
            // 收到 content 时，thinking 阶段结束（但队列仍继续消费完）
            // 将 chunk 逐字符压入 content 队列
            for (const ch of chunk) contentQueue.push(ch)
            startTyping()
            return
          }

          if (event.type === 'error') {
            sseFinished = true
            if (typingTimer !== null) { clearInterval(typingTimer); typingTimer = null }
            const msg = this.messages[assistantIndex]
            if (!msg) return
            this.messages[assistantIndex] = {
              ...msg,
              isThinking: false,
              content: `请求失败：${String(event.data ?? '未知错误')}`,
            }
          }
        },
        onDone: () => {
          // SSE 流结束，打字机继续消费剩余队列，消完后自动停止
          sseFinished = true
          // 如果队列已空（极短回复），立即收尾
          if (thinkingQueue.length === 0 && contentQueue.length === 0) {
            if (typingTimer !== null) { clearInterval(typingTimer); typingTimer = null }
            const msg = this.messages[assistantIndex]
            if (!msg) return
            this.messages[assistantIndex] = {
              ...msg,
              isThinking: false,
              content: msg.content || '本次请求未返回正文内容，请检查后端日志。',
              sources: pendingSources.length > 0 ? pendingSources : msg.sources,
            }
          }
        },
        onError: (error: unknown) => {
          sseFinished = true
          if (typingTimer !== null) { clearInterval(typingTimer); typingTimer = null }
          const msg = this.messages[assistantIndex]
          if (!msg) return
          this.messages[assistantIndex] = {
            ...msg,
            isThinking: false,
            content: `流式请求失败：${String(error)}`,
          }
          console.error('[Chat SSE Error]', error)
        },
      })
    },
  },
})
