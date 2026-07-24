<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useEventSource } from '../composables/useEventSource'
import { useLatexRenderer } from '../composables/useLatexRenderer'
import { api, fetchPaperDetail, type PaperItem } from '../services/api'
import { useChatStore } from '../stores/chatStore'
import PdfCanvasViewer from '../components/PdfCanvasViewer.vue'
import type { PdfProgress } from '../features/papers/pdfViewerModel'
import {
  filterAndSortGlobalConversations,
  getMessageWatcherSignature,
  mapChatStoreMessage,
  type PaperReaderMessage,
  type VisionPopup,
  type VisionRegionCapture,
} from '../features/papers/paperReaderModel'
import { Eye, Clipboard, Camera } from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()
const chatStore = useChatStore()
const { renderMarkdown, copyFormulas, handleFormulaCopy } = useLatexRenderer()

const paper = ref<PaperItem | null>(null)
const paperLoading = ref(true)
const paperError = ref('')
const paperId = computed(() => String(route.params.id ?? ''))

// 论文页共用全局会话（activeConversationId），不使用 paper scope 独立会话
const currentConversationId = computed(() => chatStore.activeConversationId)

// 历史会话面板（与 ChatView 共用全局会话列表）
const showConvPanel = ref(false)

const conversationList = computed(() => {
  return filterAndSortGlobalConversations(Object.values(chatStore.conversationMap))
})

const loadGlobalConvList = async () => {
  await chatStore.loadConversations('global')
}

const switchConversation = async (convId: string) => {
  showConvPanel.value = false
  if (convId === chatStore.activeConversationId) return
  visionMessages.value = []
  // openConversation 会同步 activeConversationId，论文页消息区随之更新
  await chatStore.openConversation(convId)
}

const newConversation = async () => {
  showConvPanel.value = false
  visionMessages.value = []
  await chatStore.ensureGlobalConversation('新对话')
  await loadGlobalConvList()
}

const loadPaper = async (id: string) => {
  if (!id) {
    paperError.value = '无效的论文 ID'
    paperLoading.value = false
    return
  }
  paperLoading.value = true
  paperError.value = ''
  try {
    paper.value = await fetchPaperDetail(id)
    if (!paper.value) paperError.value = '论文不存在'
  } catch (e) {
    paperError.value = String(e)
  } finally {
    paperLoading.value = false
  }
}

const initializePaperContext = async (id: string) => {
  await loadPaper(id)
  // 进入论文页时保留已有全局会话；若无会话则确保创建一个
  if (!chatStore.activeConversationId) {
    await chatStore.ensureGlobalConversation()
  }
  await loadGlobalConvList()
}

onMounted(() => {
  void initializePaperContext(paperId.value)
})

watch(paperId, (newId) => {
  visionPopup.value = null
  void initializePaperContext(newId)
})

const pdfProgress = ref<PdfProgress>({
  phase: 'idle',
  loadedPages: 0,
  totalPages: 0,
  percent: 0,
})

const onPdfProgress = (payload: PdfProgress) => {
  pdfProgress.value = payload
}

const chatMessages = computed<PaperReaderMessage[]>(() => {
  const active = currentConversationId.value
  if (!active) return []
  const mapped = chatStore.messageMap[active] || []
  return mapped.map(mapChatStoreMessage)
})

// 当前活跃会话摘要（用于显示标题）
const activeConversationTitle = computed(() => {
  const id = currentConversationId.value
  if (!id) return 'AI 对话'
  return chatStore.conversationMap[id]?.title || 'AI 对话'
})

const inputText = ref('')
const chatListRef = ref<HTMLElement | null>(null)
const isSending = computed(() => chatStore.isStreaming)
const visionMessages = ref<PaperReaderMessage[]>([])

const messages = computed<PaperReaderMessage[]>(() => [...chatMessages.value, ...visionMessages.value])
const thinkingExpanded = ref<Record<string, boolean>>({})

const toggleThinking = (msgId: string) => {
  thinkingExpanded.value = { ...thinkingExpanded.value, [msgId]: !thinkingExpanded.value[msgId] }
}
const isThinkingExpanded = (msgId: string) => !!thinkingExpanded.value[msgId]

const deleteCurrentConversation = async () => {
  if (!currentConversationId.value) return
  visionMessages.value = []
  showConvPanel.value = false
  await chatStore.deleteActiveConversation()
  await loadGlobalConvList()
}

const scrollBottom = async () => {
  await nextTick()
  if (chatListRef.value) chatListRef.value.scrollTop = chatListRef.value.scrollHeight
}

watch(() => getMessageWatcherSignature(messages.value), () => {
  void scrollBottom()
})

const visionPopup = ref<VisionPopup | null>(null)
const popupInputRef = ref<HTMLInputElement | null>(null)

const chatServiceDisabled = true

const onRightclickRegion = async (payload: VisionRegionCapture) => {
  if (chatServiceDisabled) {
    visionPopup.value = null
    return
  }
  visionPopup.value = {
    visible: true,
    base64: payload.base64,
    question: '',
    pageIndex: payload.pageIndex,
  }
  await nextTick()
  popupInputRef.value?.focus()
}

const closePopup = () => {
  visionPopup.value = null
}

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

  const baseURL = (api.defaults.baseURL ?? '').replace(/\/+$/, '')
  const { connect } = useEventSource()

  let imageId: string
  try {
    const uploadRes = await api.post<{ image_id: string }>('/chat/upload-screenshot', {
      image_base64: base64,
      mime_type: 'image/jpeg',
    })
    imageId = uploadRes.data.image_id
  } catch (e) {
    patchVisionMessage(assistantId, { isStreaming: false, content: `[上传失败] 截图上传失败：${e}` })
    return
  }

  await connect({
    url: `${baseURL}/chat/vision-relay`,
    body: {
      conversation_id: currentConversationId.value,
      paper_id: paperId.value || null,
      question,
      image_id: imageId,
      history: chatMessages.value
        .filter((m) => m.role !== 'assistant' || m.content)
        .slice(-12)
        .map((m) => ({ role: m.role, content: m.content })),
    },
    onMessage: (payload: unknown) => {
      const ev = payload as { type: string; data?: string }
      if (ev.type === 'status') return
      if (ev.type === 'vision_extract') {
        patchVisionMessage(assistantId, { visionExtract: ev.data ?? '' })
        return
      }
      if (ev.type === 'content') {
        const current = visionMessages.value.find((item) => item.id === assistantId)
        patchVisionMessage(assistantId, { content: `${current?.content || ''}${ev.data ?? ''}` })
        void scrollBottom()
      }
      if (ev.type === 'error') {
        patchVisionMessage(assistantId, { isStreaming: false, content: `[错误] ${ev.data ?? '未知错误'}` })
      }
    },
    onDone: () => {
      const current = visionMessages.value.find((item) => item.id === assistantId)
      patchVisionMessage(assistantId, { isStreaming: false, content: current?.content || '（模型未返回内容）' })
    },
    onError: (e: unknown) => {
      patchVisionMessage(assistantId, { isStreaming: false, content: `[请求失败] ${e}` })
    },
  })
}

const sendText = async () => {
  const text = inputText.value.trim()
  if (!text || isSending.value) return
  inputText.value = ''
  // 论文页使用全局会话，传 paperId 作为 RAG 上下文，activeConversationId 已是 global 不会被覆盖
  await chatStore.sendMessage(text, paperId.value, currentConversationId.value ?? undefined)
}

const handleKeydown = (e: KeyboardEvent) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    void sendText()
  }
}

const handlePopupKeydown = (e: KeyboardEvent) => {
  if (e.key === 'Enter') {
    e.preventDefault()
    void sendVision()
  }
  if (e.key === 'Escape') closePopup()
}

onMounted(() => document.addEventListener('click', handleFormulaCopy))
onUnmounted(() => document.removeEventListener('click', handleFormulaCopy))

const downloadPdf = () => {
  const url = paper.value?.pdf_media_url
  if (url) window.open(url, '_blank', 'noopener,noreferrer')
}
</script>

<template>
  <div class="paper-read-shell w-full flex-1 min-h-0 flex flex-col md:flex-row overflow-hidden">
    <div class="relative w-full h-1/2 md:h-full md:w-[35%] flex-shrink-0 flex flex-col bg-white border-r border-gray-100/80 hover:border-gray-200 transition-colors">
      <header class="flex shrink-0 items-center justify-between px-4 py-3 relative" style="border-bottom: 1px solid rgba(168,162,158,0.12)">
        <button class="flex items-center gap-1.5 text-xs text-stone-400 hover:text-stone-600 transition" @click="router.push('/chat')">
          <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/>
          </svg>
          返回
        </button>

        <!-- 历史会话切换按钮 -->
        <div class="relative">
          <button
            class="flex items-center gap-1 text-xs font-semibold text-stone-600 font-serif hover:text-stone-800 transition select-none max-w-[140px]"
            @click="showConvPanel = !showConvPanel"
          >
            <span class="truncate">{{ activeConversationTitle }}</span>
            <svg class="h-3 w-3 opacity-60 shrink-0" :class="showConvPanel ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24" style="transition: transform 0.15s">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
            </svg>
          </button>

          <!-- 下拉面板 -->
          <Transition name="dropdown">
            <div
              v-if="showConvPanel"
              class="absolute top-full left-1/2 -translate-x-1/2 mt-2 w-56 rounded-xl bg-white shadow-lg z-50 overflow-hidden"
              style="border: 1px solid rgba(168,162,158,0.2)"
            >
              <!-- 新建会话 -->
              <button
                class="w-full flex items-center gap-2 px-3 py-2.5 text-xs text-cyan-600 font-medium hover:bg-cyan-50 transition border-b border-stone-100"
                @click="newConversation"
              >
                <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
                </svg>
                新建会话
              </button>

              <!-- 历史会话列表（与 ChatView 共用全局会话） -->
              <div class="max-h-48 overflow-y-auto">
                <button
                  v-for="conv in conversationList"
                  :key="conv.id"
                  class="w-full flex items-center gap-2 px-3 py-2 text-xs text-stone-600 hover:bg-stone-50 transition"
                  :class="conv.id === currentConversationId ? 'bg-stone-100 font-semibold text-stone-800' : ''"
                  @click="switchConversation(conv.id)"
                >
                  <svg class="h-3.5 w-3.5 shrink-0 opacity-40" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>
                  </svg>
                  <span class="truncate">{{ conv.title || '对话' }}</span>
                </button>
                <div v-if="!conversationList.length" class="px-3 py-3 text-xs text-stone-400 text-center">暂无历史会话</div>
              </div>
            </div>
          </Transition>
        </div>

        <button class="text-xs text-stone-400 hover:text-red-500 transition" @click="deleteCurrentConversation">删除</button>
      </header>

      <!-- 点击外部关闭面板 -->
      <div v-if="showConvPanel" class="fixed inset-0 z-40" @click="showConvPanel = false"/>

      <div ref="chatListRef" class="flex-1 overflow-y-auto space-y-4 px-4 py-4">
        <div v-if="!messages.length" class="flex h-full flex-col items-center justify-center gap-2 text-stone-400">
          <svg class="h-12 w-12 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>
          </svg>
          <p class="text-sm font-medium">开始对话</p>
          <p class="text-xs text-center max-w-[220px]">结合当前论文内容向 AI 提问</p>
        </div>

        <div
          v-for="msg in messages"
          :key="msg.id"
          class="flex"
          :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
        >
          <div v-if="msg.role === 'assistant'" class="mr-2 mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-stone-700 text-white text-2xs font-bold">AI</div>

          <div class="max-w-[85%]" :class="msg.role === 'user' ? '' : 'flex-1'">
            <div v-if="msg.role === 'user'" class="rounded-[18px] rounded-br-sm bg-stone-700 px-3.5 py-2.5 text-xs leading-6 text-white">
              <div v-if="msg.imageBase64" class="mb-2 rounded-lg overflow-hidden border border-white/20">
                <img :src="msg.imageBase64" alt="截图" class="w-full max-h-[200px] object-contain bg-white/10" />
              </div>
              {{ msg.content }}
            </div>

            <div v-else class="space-y-1.5">
              <details v-if="msg.visionExtract" class="rounded-xl overflow-hidden" style="border: 1px solid rgba(168,162,158,0.18)">
                <summary class="cursor-pointer px-3 py-2 text-2xs font-medium text-stone-400 select-none hover:bg-stone-50">
                  <Eye class="h-3 w-3 inline-block mr-1" />视觉提取内容（点击展开）
                </summary>
                <pre class="px-3 pb-3 pt-1 text-2xs leading-5 text-stone-500 whitespace-pre-wrap break-all">{{ msg.visionExtract }}</pre>
              </details>

              <div
                v-if="msg.hasThinking || msg.isThinking || msg.thinking"
                class="thinking-block overflow-hidden"
                :class="msg.isThinking ? 'thinking-block--active' : ''"
              >
                <button
                  class="thinking-header flex w-full items-center gap-2 px-3.5 py-2.5 text-left"
                  :class="msg.isThinking ? 'cursor-default' : 'cursor-pointer'"
                  @click="!msg.isThinking && toggleThinking(msg.id)"
                >
                  <span v-if="msg.isThinking" class="thinking-spinner" />
                  <svg v-else class="h-3.5 w-3.5 shrink-0" style="color: #7c6f5c" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.347.346A3 3 0 0115 18H9a3 3 0 01-2.12-.879l-.347-.346a5 5 0 010-7.072z"/>
                  </svg>
                  <span class="flex-1 text-xs font-medium thinking-label">
                    <template v-if="msg.isThinking">
                      <span class="thinking-dots-text">正在深度思考</span>
                    </template>
                    <template v-else>
                      已完成深度思考
                      <span v-if="(msg.thinkingDurationSec || 0) > 0" class="thinking-duration">（用时 {{ msg.thinkingDurationSec }} 秒）</span>
                    </template>
                  </span>
                  <svg
                    v-if="!msg.isThinking"
                    class="h-3.5 w-3.5 shrink-0 text-stone-400 transition-transform duration-300"
                    :class="isThinkingExpanded(msg.id) ? 'rotate-180' : ''"
                    fill="none" stroke="currentColor" viewBox="0 0 24 24"
                  >
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                  </svg>
                </button>

                <Transition name="thinking-expand">
                  <div
                    v-if="msg.thinking || msg.isThinking"
                    v-show="msg.isThinking || isThinkingExpanded(msg.id)"
                    class="thinking-body px-3.5 pb-2.5"
                  >
                    <div class="thinking-content-inner">
                      <p v-if="msg.thinking" class="font-mono text-[11px] leading-[1.7] text-stone-500 whitespace-pre-wrap break-words">{{ msg.thinking }}</p>
                      <p v-else-if="msg.isThinking" class="text-[11px] text-stone-400 italic">正在检索与生成中…</p>
                      <span v-if="msg.isThinking" class="thinking-cursor" />
                    </div>
                  </div>
                </Transition>
              </div>

              <div v-if="!msg.content && msg.isStreaming && !msg.hasThinking && !msg.isThinking && !msg.thinking" class="flex items-center gap-1.5 rounded-[18px] px-3.5 py-2.5 bg-stone-50">
                <span v-for="i in 3" :key="i" class="h-1.5 w-1.5 animate-bounce rounded-full bg-stone-300" :style="`animation-delay:${(i-1)*150}ms`"/>
              </div>

              <div v-if="msg.content" class="rounded-[18px] rounded-bl-sm px-3.5 py-2.5" style="background: rgba(255,255,255,0.9); border: 1px solid rgba(168,162,158,0.18)">
                <div class="flex justify-end gap-1 mb-1">
                  <button
                    class="text-2xs px-2 py-0.5 rounded-md bg-stone-100 text-stone-400 hover:text-stone-600 transition"
                    @click="copyFormulas(msg.content)"
                    title="复制公式 LaTeX 源码"
                  >
                    <Clipboard class="h-3 w-3" /> 复制公式
                  </button>
                </div>
                <div class="prose-content text-xs leading-6 text-stone-700" v-html="renderMarkdown(msg.content)"/>
                <span v-if="msg.isStreaming" class="inline-block h-3 w-0.5 animate-pulse bg-stone-500 ml-0.5 align-middle"/>
              </div>
            </div>
          </div>

          <div v-if="msg.role === 'user'" class="ml-2 mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-stone-200 text-stone-600 text-2xs font-bold">U</div>
        </div>
      </div>

      <footer class="shrink-0 px-3 py-3" style="border-top: 1px solid rgba(168,162,158,0.12)">
        <div class="flex items-end gap-2">
          <textarea
            v-model="inputText"
            rows="1"
            class="flex-1 resize-none rounded-2xl border border-stone-200 bg-white px-3 py-2 text-xs text-stone-700 placeholder:text-stone-400 focus:outline-none focus:ring-1 focus:ring-cyan-400/40 max-h-28 min-h-[38px]"
            placeholder="输入问题…（Enter 发送）"
            :disabled="isSending"
            @keydown="handleKeydown"
          />
          <button
            class="flex h-[38px] w-[38px] shrink-0 items-center justify-center rounded-full bg-stone-700 text-white transition hover:bg-stone-800 disabled:opacity-40"
            :disabled="!inputText.trim() || isSending"
            @click="sendText"
          >
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
          </button>
        </div>
      </footer>
      <div class="absolute inset-0 z-[60] flex items-center justify-center bg-white/75 px-4 backdrop-blur-sm">
        <div class="max-w-xs rounded-3xl border border-stone-200 bg-white/95 px-6 py-8 text-center shadow-2xl">
          <div class="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-3xl bg-stone-100">
            <svg class="h-7 w-7 text-stone-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.6">
              <path stroke-linecap="round" stroke-linejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>
            </svg>
          </div>
          <p class="text-base font-semibold text-stone-800 font-serif">服务暂未开放敬请期待</p>
          <p class="mt-2 text-xs leading-5 text-stone-500">论文旁 AI 对话功能正在维护升级中，当前暂不可使用。</p>
        </div>
      </div>
    </div>

    <div class="flex-1 min-w-0 min-h-0 h-1/2 md:h-auto flex flex-col overflow-hidden bg-gray-50/50">
      <header class="flex shrink-0 items-start justify-between gap-3 px-5 py-3" style="border-bottom: 1px solid rgba(168,162,158,0.12)">
        <div class="min-w-0 flex-1">
          <div v-if="paperLoading" class="h-4 w-48 animate-pulse rounded bg-stone-200"/>
          <h1 v-else-if="paper" class="text-sm font-semibold text-stone-800 leading-snug line-clamp-2 font-serif">{{ paper.title }}</h1>
          <p v-else class="text-sm text-red-400">{{ paperError || '论文加载失败' }}</p>

          <div v-if="paper" class="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-stone-400">
            <span v-if="paper.published_date">{{ paper.published_date?.slice(0, 10) }}</span>
            <a v-if="paper.url" :href="paper.url" target="_blank" rel="noopener noreferrer" class="hover:text-stone-600 underline transition">原始链接 ↗</a>
            <span v-if="pdfProgress.phase === 'rendering' && pdfProgress.totalPages > 0" class="text-cyan-600 font-medium">
              渲染 {{ pdfProgress.loadedPages }}/{{ pdfProgress.totalPages }} 页
            </span>
          </div>
        </div>

        <button
          v-if="paper?.pdf_media_url"
          class="shrink-0 flex items-center gap-1.5 rounded-xl border border-stone-200 bg-white px-3 py-1.5 text-xs text-stone-600 transition hover:bg-stone-50 hover:border-stone-300"
          @click="downloadPdf"
        >
          <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/>
          </svg>
          下载 PDF
        </button>
      </header>

      <div class="flex-1 min-h-0 flex flex-col relative overflow-hidden">
        <PdfCanvasViewer
          :pdf-url="paper?.pdf_media_url ?? null"
          @rightclick-region="onRightclickRegion"
          @progress="onPdfProgress"
        />

        <Transition name="popup-fade">
          <div
            v-if="visionPopup?.visible"
            class="absolute bottom-4 md:bottom-24 left-1/2 -translate-x-1/2 w-[340px] max-w-[calc(100%_-_24px)] max-h-[calc(100%_-_24px)] overflow-y-auto rounded-2xl p-4 shadow-2xl"
            style="background: rgba(255,255,255,0.97); border: 1px solid rgba(168,162,158,0.25); backdrop-filter: blur(16px); z-index: 50"
          >
            <p class="mb-2 text-xs font-semibold text-stone-600 flex items-center gap-1"><Camera class="h-3.5 w-3.5" /> 已截取区域，向 AI 提问</p>
            <div class="mb-2 max-h-[160px] overflow-hidden rounded-lg border border-stone-200 bg-stone-100">
              <img :src="visionPopup.base64" alt="截图预览" class="w-full h-auto object-contain max-h-[160px]" />
            </div>
            <input
              ref="popupInputRef"
              v-model="visionPopup.question"
              type="text"
              placeholder="例如：请解释这个图表的含义…"
              class="w-full rounded-xl border border-stone-200 bg-stone-50 px-3 py-2 text-xs text-stone-700 placeholder:text-stone-400 focus:outline-none focus:ring-1 focus:ring-cyan-400/40"
              @keydown="handlePopupKeydown"
            />
            <div class="mt-2.5 flex gap-2">
              <button
                class="flex-1 rounded-xl bg-stone-700 px-3 py-1.5 text-xs text-white transition hover:bg-stone-800 disabled:opacity-40"
                :disabled="!visionPopup.question.trim() || isSending"
                @click="sendVision"
              >
                发送
              </button>
              <button class="rounded-xl border border-stone-200 px-3 py-1.5 text-xs text-stone-500 transition hover:bg-stone-50" @click="closePopup">
                取消
              </button>
            </div>
          </div>
        </Transition>

        <div
          v-if="!paperLoading && paper && !paper.pdf_media_url"
          class="absolute inset-0 flex items-center justify-center px-8"
        >
          <div class="max-w-xl rounded-2xl p-6 text-center" style="background: rgba(255,255,255,0.85); border: 1px solid rgba(168,162,158,0.18)">
            <p class="mb-3 text-sm font-semibold text-stone-700 font-serif">PDF 暂未就绪</p>
            <p class="text-xs text-stone-500 leading-6">{{ paper.summary?.slice(0, 400) }}…</p>
            <a v-if="paper.url" :href="paper.url" target="_blank" rel="noopener noreferrer" class="mt-4 inline-block text-xs text-stone-500 underline hover:text-stone-700">在 arXiv/HuggingFace 上查看 ↗</a>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.paper-read-shell {
  --paper: #f4f0e6;
  --paper-raised: #fffdf6;
  --ink: #191a16;
  --rule: rgba(25, 26, 22, 0.72);
  --lime: #c7ff2e;
  background: var(--paper);
  color: var(--ink);
}

.paper-read-shell > div {
  border-color: var(--rule) !important;
  background: var(--paper) !important;
}

.paper-read-shell header,
.paper-read-shell footer {
  border-color: var(--rule) !important;
  background: var(--paper-raised);
}

.paper-read-shell button,
.paper-read-shell textarea,
.paper-read-shell input { border-radius: 4px; }

.paper-read-shell button:focus-visible,
.paper-read-shell textarea:focus-visible,
.paper-read-shell input:focus-visible {
  outline: 2px solid var(--ink);
  outline-offset: 2px;
  box-shadow: 0 0 0 4px var(--lime);
}

.paper-read-shell button[class*="bg-stone-700"] {
  border: 1px solid var(--ink);
  background: var(--ink) !important;
  color: var(--paper-raised) !important;
}

.paper-read-shell button[class*="bg-stone-700"]:hover:not(:disabled) {
  background: var(--lime) !important;
  color: var(--ink) !important;
}

.paper-read-shell [class*="text-cyan"] { color: #4b6100 !important; }
.paper-read-shell [class*="bg-cyan"] { background-color: var(--lime) !important; }

.paper-read-shell textarea,
.paper-read-shell input {
  border-color: rgba(25, 26, 22, 0.52);
  background: #fffef9;
}

.paper-read-shell .absolute.inset-0.z-\[60\] {
  background: rgba(244, 240, 230, 0.9);
  backdrop-filter: none;
}

.paper-read-shell .absolute.inset-0.z-\[60\] > div {
  border-color: var(--ink);
  border-radius: 6px;
  background: var(--paper-raised);
  box-shadow: 6px 6px 0 rgba(25, 26, 22, 0.16);
}

.paper-read-shell .absolute.top-full {
  border-color: var(--ink) !important;
  border-radius: 4px;
  background: var(--paper-raised) !important;
  box-shadow: 4px 4px 0 rgba(25, 26, 22, 0.14);
}

.popup-fade-enter-active,
.popup-fade-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.popup-fade-enter-from,
.popup-fade-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(8px) scale(0.97);
}
.popup-fade-enter-to,
.popup-fade-leave-from {
  transform: translateX(-50%) translateY(0) scale(1);
}

:deep(.katex-display) {
  overflow-x: auto;
  overflow-y: hidden;
  max-width: 100%;
  padding: 4px 0;
}
:deep(.katex-display > .katex) {
  white-space: nowrap;
}
:deep(.prose-content) {
  overflow: hidden;
  max-width: 100%;
}
:deep(.formula-wrap) {
  position: relative;
  overflow-x: auto;
  overflow-y: hidden;
  padding: 6px 0;
}
:deep(.formula-copy-btn) {
  position: absolute;
  top: 2px;
  right: 2px;
  z-index: 5;
  cursor: pointer;
  background: rgba(245,245,244,0.85);
  border: 1px solid rgba(168,162,158,0.2);
  border-radius: 6px;
  padding: 1px 5px;
  font-size: 11px;
  line-height: 1.4;
  opacity: 0;
  transition: opacity 0.15s;
}
:deep(.formula-wrap:hover .formula-copy-btn) {
  opacity: 1;
}
:deep(.katex-block-wrapper) {
  position: relative;
  overflow-x: auto;
  overflow-y: hidden;
  padding: 6px 0;
}

/* Cherry Studio 风格思维链块（论文阅读页 scoped 样式） */
.thinking-block {
  border-radius: 16px;
  border: 1px solid rgba(120, 100, 70, 0.18);
  background: linear-gradient(135deg, rgba(255,252,245,0.95) 0%, rgba(250,247,240,0.92) 100%);
  overflow: hidden;
  transition: border-color 0.2s ease;
}
.thinking-block--active {
  border-color: rgba(120, 100, 70, 0.32);
  background: linear-gradient(135deg, rgba(255,253,248,0.98) 0%, rgba(252,249,242,0.96) 100%);
}
.thinking-header {
  width: 100%;
  background: transparent;
  border: none;
  outline: none;
  transition: background 0.15s ease;
}
.thinking-header:hover {
  background: rgba(120, 100, 70, 0.05);
}
.thinking-label {
  color: #7c6f5c;
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0.01em;
}
.thinking-dots-text {
  background: linear-gradient(90deg, #a08060 0%, #c8a870 40%, #a08060 80%);
  background-size: 200% auto;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  animation: shimmer 1.8s linear infinite;
}
.thinking-duration {
  color: #b0a090;
  font-weight: 400;
}
.thinking-spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 2px solid rgba(160, 128, 96, 0.25);
  border-top-color: #a08060;
  animation: thinking-spin 0.8s linear infinite;
  flex-shrink: 0;
}
.thinking-body {
  border-top: 1px solid rgba(120, 100, 70, 0.12);
}
.thinking-content-inner {
  max-height: 260px;
  overflow-y: auto;
  padding: 2px 0;
  scrollbar-width: thin;
  scrollbar-color: rgba(120,100,70,0.2) transparent;
}
.thinking-content-inner::-webkit-scrollbar {
  width: 4px;
}
.thinking-content-inner::-webkit-scrollbar-thumb {
  background: rgba(120,100,70,0.2);
  border-radius: 2px;
}
.thinking-cursor {
  display: inline-block;
  width: 1px;
  height: 12px;
  background: #a08060;
  margin-left: 2px;
  vertical-align: middle;
  animation: blink 0.9s step-end infinite;
}
.thinking-expand-enter-active,
.thinking-expand-leave-active {
  transition: max-height 0.28s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.2s ease;
  overflow: hidden;
  max-height: 300px;
}
.thinking-expand-enter-from,
.thinking-expand-leave-to {
  max-height: 0;
  opacity: 0;
}
.thinking-expand-enter-to,
.thinking-expand-leave-from {
  opacity: 1;
}

.dropdown-enter-active,
.dropdown-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.dropdown-enter-from,
.dropdown-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(-6px) scale(0.97);
}
.dropdown-enter-to,
.dropdown-leave-from {
  opacity: 1;
  transform: translateX(-50%) translateY(0) scale(1);
}

@keyframes thinking-spin {
  to { transform: rotate(360deg); }
}
@keyframes shimmer {
  to { background-position: -200% center; }
}
@keyframes blink {
  50% { opacity: 0; }
}
</style>
