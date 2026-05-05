<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useChatStore } from '../stores/chatStore'
import { useAuthStore } from '../stores/authStore'
import { useLatexRenderer } from '../composables/useLatexRenderer'
import {
  getAttachmentStatus,
  uploadImageAttachment,
  uploadPdfAttachment,
  type AttachmentMeta,
} from '../services/api'
import { Clipboard, SquareCode, FileText, Image, Globe } from 'lucide-vue-next'

const store = useChatStore()
const authStore = useAuthStore()
const router = useRouter()
const inputText = ref('')
const listRef = ref<HTMLElement | null>(null)
const showSettings = ref(false)
const isSending = ref(false)
const isUploading = ref(false)
const isLoadingInit = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)
const attachmentMetas = ref<AttachmentMeta[]>([])
const showSidebar = ref(true)

const localSettings = ref({ ...store.settings })
const webSearchEnabled = computed({
  get: () => store.settings.webSearch,
  set: (val: boolean) => store.updateSettings({ webSearch: val }),
})

/** 会话列表（按 updatedAt 降序） */
const conversationList = computed(() => {
  return Object.values(store.conversationMap)
    .filter((c) => c.scope === 'global')
    .sort((a, b) => {
      const ta = a.updatedAt ?? a.createdAt ?? ''
      const tb = b.updatedAt ?? b.createdAt ?? ''
      return tb.localeCompare(ta)
    })
})

const { renderMarkdown, copyFormulas, handleFormulaCopy } = useLatexRenderer()

const messages = computed(() => store.messages)
const rawModeSet = ref(new Set<number>())
const toggleRaw = (idx: number) => {
  if (rawModeSet.value.has(idx)) rawModeSet.value.delete(idx)
  else rawModeSet.value.add(idx)
  rawModeSet.value = new Set(rawModeSet.value)
}

interface SourceFlat {
  id?: string
  score?: number
  source?: string
  title?: string
  url?: string
  published_date?: string
  metadata?: {
    title?: string
    url?: string
    source?: string
    source_type?: string
    node?: { id?: string }
  }
}

const getSourceTitle = (src: unknown): string => {
  const s = src as SourceFlat
  return s?.title || s?.metadata?.title || s?.metadata?.node?.id || s?.id || 'Unknown Source'
}

const getSourceType = (src: unknown): string => {
  const s = src as SourceFlat
  const channel = s?.source || s?.metadata?.source_type || s?.metadata?.source || ''
  if (channel === 'arxiv') return 'Arxiv'
  if (channel === 'github') return 'GitHub'
  if (channel === 'news') return 'News'
  if (channel === 'web') return 'Web'
  if (channel.toLowerCase().includes('neo4j') || channel.toLowerCase().includes('graph')) return 'Neo4j'
  if (channel.toLowerCase().includes('milvus') || channel.toLowerCase().includes('vector')) return 'Milvus'
  return channel || 'Unknown'
}

const getSourceUrl = (src: unknown): string | null => {
  const s = src as SourceFlat
  return s?.url || s?.metadata?.url || null
}

/** 来源徽章按类型分色 CSS 类 */
const sourceTypeBadgeClass = (type: string): string => {
  const t = type.toLowerCase()
  if (t === 'arxiv') return 'badge-arxiv'
  if (t === 'github') return 'badge-github'
  if (t === 'news') return 'badge-news'
  if (t === 'neo4j') return 'badge-neo4j'
  if (t === 'milvus') return 'badge-milvus'
  if (t === 'web') return 'badge-web'
  return 'badge-default'
}

const thinkingExpanded = ref<Record<string, boolean>>({})

const toggleThinking = (msgId: string) => {
  thinkingExpanded.value = { ...thinkingExpanded.value, [msgId]: !thinkingExpanded.value[msgId] }
}
const isThinkingExpanded = (msgId: string) => !!thinkingExpanded.value[msgId]

const autoScroll = ref(true)

const onWheelHandler = (e: WheelEvent) => { if (e.deltaY < 0) autoScroll.value = false }

let lastTouchY = 0
const onTouchStart = (e: TouchEvent) => { lastTouchY = e.touches[0]?.clientY ?? 0 }
const onTouchMoveHandler = (e: TouchEvent) => {
  const currentY = e.touches[0]?.clientY ?? 0
  if (currentY > lastTouchY) autoScroll.value = false
  lastTouchY = currentY
}

/** 流式阶段文案映射 */
const streamPhaseLabel = computed(() => {
  switch (store.streamPhase) {
    case 'searching': return '正在检索资料…'
    case 'reranking': return '正在精排匹配…'
    case 'answering': return '正在生成回答…'
    case 'error': return '请求出错'
    default: return ''
  }
})

onMounted(async () => {
  const el = listRef.value
  if (el) {
    el.addEventListener('wheel', onWheelHandler, { passive: true })
    el.addEventListener('touchstart', onTouchStart, { passive: true })
    el.addEventListener('touchmove', onTouchMoveHandler, { passive: true })
  }
  document.addEventListener('click', handleFormulaCopy)
  const pending = authStore.consumePendingMessage()
  if (pending) {
    inputText.value = pending
  }

  // 已登录时：加载历史会话列表 + 确保全局会话存在（解决首次无会话、消息被吞问题）
  if (authStore.isLoggedIn) {
    isLoadingInit.value = true
    try {
      await store.loadConversations('global')
      await store.ensureGlobalConversation()
    } catch (e) {
      console.error('[ChatView] 初始化会话失败', e)
    } finally {
      isLoadingInit.value = false
    }
  }
})

onUnmounted(() => {
  const el = listRef.value
  if (el) {
    el.removeEventListener('wheel', onWheelHandler)
    el.removeEventListener('touchstart', onTouchStart)
    el.removeEventListener('touchmove', onTouchMoveHandler)
  }
  document.removeEventListener('click', handleFormulaCopy)
})

const scrollToBottom = async () => {
  if (!autoScroll.value) return
  await nextTick()
  const el = listRef.value
  if (!el) return
  el.scrollTop = el.scrollHeight
}

let scrollRafId: number | null = null
const scheduleScroll = () => {
  if (!autoScroll.value) return
  if (scrollRafId !== null) return
  scrollRafId = requestAnimationFrame(async () => {
    scrollRafId = null
    await scrollToBottom()
  })
}

watch(
  () => store.messages.map((m) => `${m.role}:${m.content.length}:${m.thinking.length}`).join('|'),
  scheduleScroll,
)

const openFilePicker = () => {
  fileInputRef.value?.click()
}

const removeAttachment = (attachmentId: string) => {
  store.removePendingAttachment(attachmentId)
  attachmentMetas.value = attachmentMetas.value.filter((item) => item.id !== attachmentId)
}

const refreshAttachmentStatus = async (attachmentId: string) => {
  try {
    const latest = await getAttachmentStatus(attachmentId)
    attachmentMetas.value = attachmentMetas.value.map((item) => item.id === attachmentId ? latest : item)
  } catch (error) {
    console.error('[Attachment status error]', error)
  }
}

const handleFileChange = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return

  if (!authStore.isLoggedIn) {
    authStore.savePendingMessage(inputText.value.trim())
    router.push({ path: '/login', query: { redirect: '/chat' } })
    input.value = ''
    return
  }

  isUploading.value = true
  try {
    let meta: AttachmentMeta
    if (file.type.startsWith('image/')) {
      const fileReader = new FileReader()
      const dataUrl = await new Promise<string>((resolve, reject) => {
        fileReader.onload = () => resolve(String(fileReader.result ?? ''))
        fileReader.onerror = reject
        fileReader.readAsDataURL(file)
      })
      meta = await uploadImageAttachment(dataUrl, file.type, file.name)
    } else if (file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')) {
      meta = await uploadPdfAttachment(file)
    } else {
      alert('仅支持图片或 PDF 文件')
      input.value = ''
      return
    }

    store.addPendingAttachment(meta.id)
    attachmentMetas.value = [...attachmentMetas.value, meta]

    if (meta.status === 'processing') {
      window.setTimeout(() => {
        void refreshAttachmentStatus(meta.id)
      }, 1500)
    }
  } catch (error) {
    console.error('[Attachment upload error]', error)
    alert('附件上传失败，请稍后重试')
  } finally {
    isUploading.value = false
    input.value = ''
  }
}

const handleAbort = () => {
  store.abortGeneration()
  isSending.value = false
}

const handleRegenerate = async (messageId: string) => {
  if (store.isStreaming) {
    store.abortGeneration()
  }
  isSending.value = true
  try {
    await store.regenerateMessage(messageId)
  } finally {
    isSending.value = false
  }
}

const handleDeleteMessage = (messageId: string) => {
  store.deleteMessage(messageId)
}

const handleSend = async () => {
  const text = inputText.value.trim()
  if ((!text && attachmentMetas.value.length === 0) || isSending.value) return

  if (!authStore.isLoggedIn) {
    authStore.savePendingMessage(text)
    router.push({ path: '/login', query: { redirect: '/chat' } })
    return
  }

  inputText.value = ''
  autoScroll.value = true
  isSending.value = true
  try {
    await store.sendMessage(text || '请结合附件内容进行分析。')
    attachmentMetas.value = []
  }
  finally { isSending.value = false }
  await scrollToBottom()
}

const handleKeydown = async (e: KeyboardEvent) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); await handleSend() }
}

const openSettings = () => { localSettings.value = { ...store.settings }; showSettings.value = true }
const saveSettings = () => { store.updateSettings({ ...localSettings.value }); showSettings.value = false }
const cancelSettings = () => { showSettings.value = false }
</script>

<template>
  <!-- 双栏布局：左侧会话列表 + 右侧对话区 -->
  <div class="flex h-full overflow-hidden">

    <!-- 左侧历史会话列表 -->
    <aside
      v-if="showSidebar"
      class="flex flex-col shrink-0 border-r overflow-hidden"
      style="width: 220px; border-color: rgba(168,162,158,0.18); background: rgba(255,255,255,0.6)"
    >
      <!-- 侧边栏标题 + 新建按钮 -->
      <div class="flex items-center justify-between px-3 py-3 shrink-0" style="border-bottom: 1px solid rgba(168,162,158,0.15)">
        <span class="text-xs font-semibold text-stone-500 tracking-wide">历史会话</span>
        <button
          class="rounded-lg p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-700 transition text-xs"
          title="新建对话"
          @click="() => authStore.isLoggedIn && store.createNewConversation('global')"
        >
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
        </button>
      </div>

      <!-- 加载中 -->
      <div v-if="isLoadingInit" class="flex items-center justify-center py-6">
        <svg class="h-4 w-4 animate-spin text-stone-400" viewBox="0 0 24 24" fill="none">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"/>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"/>
        </svg>
      </div>

      <!-- 会话列表 -->
      <div v-else class="flex-1 overflow-y-auto py-1">
        <div
          v-for="conv in conversationList"
          :key="conv.id"
          class="mx-2 my-0.5 cursor-pointer rounded-xl px-3 py-2.5 transition-all"
          :class="conv.id === store.activeConversationId
            ? 'bg-stone-700 text-white'
            : 'hover:bg-stone-100 text-stone-600'"
          @click="() => store.openConversation(conv.id)"
        >
          <p class="truncate text-xs font-medium leading-5">{{ conv.title || '新对话' }}</p>
          <p
            class="truncate text-2xs leading-4 mt-0.5"
            :class="conv.id === store.activeConversationId ? 'text-stone-300' : 'text-stone-400'"
          >
            {{ conv.lastMessagePreview || '暂无消息' }}
          </p>
        </div>
        <div v-if="!conversationList.length" class="px-4 py-6 text-center text-xs text-stone-400">
          暂无历史会话
        </div>
      </div>
    </aside>

    <section class="relative flex flex-col overflow-hidden flex-1">

      <!-- 标题栏 -->
      <header class="stagger-enter flex items-center justify-between px-5 py-3.5 shrink-0"
        style="border-bottom: 1px solid rgba(168,162,158,0.15)"
      >
        <div class="flex items-center gap-3">
          <!-- 侧边栏折叠按钮 -->
          <button
            class="rounded-lg p-1.5 text-stone-400 hover:bg-stone-100 hover:text-stone-700 transition"
            :title="showSidebar ? '收起会话列表' : '展开会话列表'"
            @click="showSidebar = !showSidebar"
          >
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="3" x2="9" y2="21"/>
            </svg>
          </button>
          <div class="flex h-9 w-9 items-center justify-center rounded-2xl bg-stone-100">
            <svg class="h-5 w-5 text-stone-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M12 2a10 10 0 100 20 10 10 0 000-20z"/>
              <path d="M9.5 9.5a2.5 2.5 0 015 0c0 2-2 3-2.5 4"/>
              <circle cx="12" cy="17" r=".5" fill="currentColor"/>
            </svg>
          </div>
          <div>
            <h2 class="text-sm font-semibold text-stone-800 font-serif">
              {{ store.activeConversation?.title || 'RAG 智能助手' }}
            </h2>
            <p class="text-2xs text-stone-400">
              记忆 {{ store.settings.maxHistoryTurns }} 轮 · T={{ store.settings.temperature.toFixed(1) }}
            </p>
          </div>
        </div>

        <div class="flex items-center gap-1.5">
          <!-- 流式状态指示器 -->
          <Transition name="settings-panel">
            <div v-if="store.isStreaming" class="stream-indicator mr-2">
              <span class="stream-dot" />
              <span>{{ streamPhaseLabel }}</span>
            </div>
          </Transition>

          <button class="btn-ghost text-xs" @click="store.deleteActiveConversation()">
            <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/><path d="M10 11v6M14 11v6"/>
            </svg>
            清空
          </button>
          <button class="rounded-full p-2 text-stone-400 transition hover:bg-stone-100 hover:text-stone-600" @click="openSettings">
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <circle cx="12" cy="12" r="3"/><path d="M19.07 4.93l-1.41 1.41M16.24 7.76A6 6 0 1 0 7.76 16.24M4.93 19.07l1.41-1.41"/>
            </svg>
          </button>
        </div>
      </header>

      <!-- 设置浮层 -->
      <Transition name="settings-panel">
        <div
          v-if="showSettings"
          class="absolute left-1/2 top-[60px] z-30 w-80 -translate-x-1/2 glass-card p-5"
          style="box-shadow: 0 4px 20px rgba(0,0,0,0.06)"
        >
          <h3 class="mb-4 text-sm font-semibold text-stone-800 font-serif">对话设置</h3>
          <div class="mb-4 space-y-1.5">
            <label class="flex items-center justify-between text-sm text-stone-500">
              <span>历史记忆轮次</span>
              <span class="font-bold text-stone-800">{{ localSettings.maxHistoryTurns }}</span>
            </label>
            <input v-model.number="localSettings.maxHistoryTurns" type="range" min="0" max="20" step="1" class="w-full accent-stone-600 h-1.5 rounded-full" />
            <div class="flex justify-between text-2xs text-stone-400"><span>0 无记忆</span><span>20</span></div>
          </div>
          <div class="mb-4 space-y-1.5">
            <label class="flex items-center justify-between text-sm text-stone-500">
              <span>Temperature</span>
              <span class="font-bold text-stone-800">{{ localSettings.temperature.toFixed(1) }}</span>
            </label>
            <input v-model.number="localSettings.temperature" type="range" min="0" max="2" step="0.1" class="w-full accent-stone-600 h-1.5 rounded-full" />
            <div class="flex justify-between text-2xs text-stone-400"><span>0.0 精确</span><span>2.0 创意</span></div>
          </div>
          <div class="flex gap-2">
            <button class="btn-secondary flex-1 justify-center" @click="cancelSettings">取消</button>
            <button class="btn-primary flex-1 justify-center" @click="saveSettings">保存</button>
          </div>
        </div>
      </Transition>

      <div v-if="showSettings" class="fixed inset-0 z-20" @click="cancelSettings" />

      <!-- 消息列表 -->
      <div ref="listRef" class="stagger-enter flex-1 space-y-5 overflow-y-auto px-5 py-5" style="animation-delay: 0.1s">
        <div v-if="!messages.length" class="flex h-full flex-col items-center justify-center gap-3 text-stone-400">
          <div class="flex h-16 w-16 items-center justify-center rounded-3xl bg-stone-100">
            <svg class="h-8 w-8 opacity-40 text-stone-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>
            </svg>
          </div>
          <p class="text-sm font-medium text-stone-500 font-serif">开始一段对话</p>
          <p class="text-xs text-center max-w-xs text-stone-400">输入问题，RAG 助手将基于知识库给出准确答案并提供参考来源</p>
        </div>

        <div
          v-for="(msg, idx) in messages"
          :key="msg.id"
          class="flex animate-slide-up"
          :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
        >
          <div
            v-if="msg.role !== 'user'"
            class="mr-2.5 mt-1 h-7 w-7 shrink-0 flex items-center justify-center rounded-full bg-stone-700 text-white text-xs font-bold shadow-sm"
          >AI</div>

          <div class="max-w-[80%]" :class="msg.role === 'user' ? 'max-w-[70%]' : 'flex-1'">
            <!-- 用户气泡 -->
            <div
              v-if="msg.role === 'user'"
              class="inline-block rounded-[20px] rounded-br-md bg-stone-700 px-4 py-3 text-sm leading-6 text-white shadow-sm"
            >{{ msg.content }}</div>

            <!-- AI 消息 -->
            <div v-else class="space-y-2">
              <!-- 思维链 — Cherry Studio 风格 -->
              <div
                v-if="msg.hasThinking || msg.isThinking"
                class="thinking-block overflow-hidden"
                :class="msg.isThinking ? 'thinking-block--active' : ''"
              >
                <!-- 折叠头部 -->
                <button
                  class="thinking-header flex w-full items-center gap-2 px-4 py-3 text-left"
                  :class="msg.isThinking ? 'cursor-default' : 'cursor-pointer'"
                  @click="!msg.isThinking && toggleThinking(msg.id)"
                >
                  <!-- 思考中旋转光圈 -->
                  <span v-if="msg.isThinking" class="thinking-spinner" />
                  <!-- 完成后大脑图标 -->
                  <svg v-else class="h-3.5 w-3.5 shrink-0" style="color: #7c6f5c" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.347.346A3 3 0 0115 18H9a3 3 0 01-2.12-.879l-.347-.346a5 5 0 010-7.072z"/>
                  </svg>
                  <span class="flex-1 text-xs font-medium thinking-label">
                    <template v-if="msg.isThinking">
                      <span class="thinking-dots-text">正在深度思考</span>
                    </template>
                    <template v-else>
                      已完成深度思考
                      <span v-if="msg.thinkingDurationSec > 0" class="thinking-duration">（用时 {{ msg.thinkingDurationSec }} 秒）</span>
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

                <!-- 思维链内容（可展开/折叠）：thinking 为空且非思考中时不渲染空白区域 -->
                <Transition name="thinking-expand">
                  <div
                    v-if="msg.thinking || msg.isThinking"
                    v-show="msg.isThinking || isThinkingExpanded(msg.id)"
                    class="thinking-body px-4 pb-3"
                  >
                    <div class="thinking-content-inner">
                      <p v-if="msg.thinking" class="font-mono text-[11px] leading-[1.7] text-stone-500 whitespace-pre-wrap break-words">{{ msg.thinking }}</p>
                      <p v-else-if="msg.isThinking" class="text-[11px] text-stone-400 italic">正在检索与生成中…</p>
                      <span v-if="msg.isThinking" class="thinking-cursor" />
                    </div>
                  </div>
                </Transition>
              </div>

              <!-- 等待点动画 -->
              <div v-if="!msg.content && !msg.hasThinking && !msg.isThinking" class="flex items-center gap-1.5 rounded-[20px] px-4 py-3 bg-stone-50">
                <span class="h-2 w-2 animate-bounce rounded-full bg-stone-300" style="animation-delay: 0ms"/>
                <span class="h-2 w-2 animate-bounce rounded-full bg-stone-300" style="animation-delay: 150ms"/>
                <span class="h-2 w-2 animate-bounce rounded-full bg-stone-300" style="animation-delay: 300ms"/>
              </div>

              <!-- 正文 -->
              <div v-if="msg.content" class="rounded-[20px] rounded-bl-md px-4 py-3" style="background: rgba(255,255,255,0.85); border: 1px solid rgba(168,162,158,0.20)">
                <!-- 渲染/源码/复制按钮 -->
                <div class="flex justify-end gap-1 mb-1">
                  <button
                    class="inline-flex items-center gap-1 text-2xs px-2 py-0.5 rounded-md bg-stone-100 text-stone-400 hover:text-stone-600 transition"
                    @click="copyFormulas(msg.content)"
                    title="复制公式 LaTeX 源码"
                  >
                    <Clipboard class="h-3 w-3" /> 复制公式
                  </button>
                  <button
                    class="inline-flex items-center gap-1 text-2xs px-2 py-0.5 rounded-md transition"
                    :class="rawModeSet.has(idx) ? 'bg-stone-200 text-stone-600' : 'bg-stone-100 text-stone-400 hover:text-stone-600'"
                    @click="toggleRaw(idx)"
                  >
                    <SquareCode class="h-3 w-3" />
                    {{ rawModeSet.has(idx) ? '渲染公式' : '源码' }}
                  </button>
                </div>
                <!-- 渲染后内容 -->
                <div v-if="!rawModeSet.has(idx)" class="prose-content text-sm leading-7 text-stone-700" v-html="renderMarkdown(msg.content)" />
                <!-- LaTeX 源码 -->
                <pre v-else class="text-sm leading-6 text-stone-600 whitespace-pre-wrap break-all font-mono bg-stone-50 rounded-lg p-3">{{ msg.content }}</pre>
              </div>

              <div class="flex items-center gap-2 px-1 pt-1 text-2xs text-stone-400">
                <button
                  class="transition hover:text-stone-600"
                  @click="handleRegenerate(msg.id)"
                >重新生成</button>
                <button
                  class="transition hover:text-red-500"
                  @click="handleDeleteMessage(msg.id)"
                >删除</button>
              </div>

              <!-- 来源卡片 -->
              <div v-if="msg.sources?.length" class="space-y-1.5 pt-1">
                <p class="text-2xs font-semibold uppercase tracking-widest text-stone-400 px-1">参考来源 · {{ msg.sources.length }} 条</p>
                <div class="flex flex-col gap-1.5">
                  <div
                    v-for="(source, sidx) in msg.sources"
                    :key="sidx"
                    class="flex items-center gap-2 rounded-2xl px-3 py-2 text-xs card-hover"
                    style="background: rgba(255,255,255,0.85); border: 1px solid rgba(168,162,158,0.20)"
                  >
                    <span class="shrink-0 text-2xs font-bold text-stone-400 w-4 text-center">{{ sidx + 1 }}</span>
                    <span class="shrink-0" :class="sourceTypeBadgeClass(getSourceType(source))">{{ getSourceType(source) }}</span>
                    <span class="min-w-0 flex-1 truncate font-medium text-stone-600" :title="getSourceTitle(source)">{{ getSourceTitle(source) }}</span>
                    <a v-if="getSourceUrl(source)" :href="getSourceUrl(source)!" target="_blank" rel="noopener noreferrer" class="shrink-0 text-stone-400 hover:text-stone-600 transition-colors">
                      <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>
                    </a>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div v-if="msg.role === 'user'" class="ml-2.5 mt-1 h-7 w-7 shrink-0 flex items-center justify-center rounded-full bg-stone-200 text-stone-600 text-xs font-bold">U</div>
        </div>
      </div>

      <!-- 回到底部 -->
      <div v-if="!autoScroll" class="pointer-events-none absolute bottom-20 right-5 z-10">
        <button class="pointer-events-auto btn-primary text-xs" @click="() => { autoScroll = true; scrollToBottom() }">
          <svg class="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
          回到底部
        </button>
      </div>

      <!-- 输入区 -->
      <footer class="stagger-enter shrink-0 p-4" style="border-top: 1px solid rgba(168,162,158,0.15); animation-delay: 0.2s">
        <div v-if="attachmentMetas.length" class="mb-3 flex flex-wrap gap-2">
          <div
            v-for="attachment in attachmentMetas"
            :key="attachment.id"
            class="flex items-center gap-2 rounded-full border border-stone-200 bg-stone-50 px-3 py-1.5 text-xs text-stone-600"
          >
            <component :is="attachment.type === 'pdf' ? FileText : Image" class="h-3.5 w-3.5 shrink-0" />
            <span class="max-w-[180px] truncate">{{ attachment.filename || attachment.id }}</span>
            <span v-if="attachment.status !== 'ready'" class="text-cyan-600">{{ attachment.status }}</span>
            <button class="text-stone-400 hover:text-red-500" @click="removeAttachment(attachment.id)">×</button>
          </div>
        </div>
        <!-- 工具栏（联网搜索等开关）— 暂时隐藏，待配置 KIMI_API_KEY 后启用 -->
        <!-- <div class="flex items-center gap-2 mb-2">
          <button
            class="web-search-toggle"
            :class="webSearchEnabled ? 'web-search-toggle--active' : ''"
            :title="webSearchEnabled ? '关闭联网搜索' : '开启联网搜索'"
            @click="webSearchEnabled = !webSearchEnabled"
          >
            <Globe class="h-3.5 w-3.5" />
            <span>联网搜索</span>
            <span v-if="webSearchEnabled" class="web-search-dot" />
          </button>
        </div> -->
        <div class="flex items-end gap-3">
          <div class="relative flex-1">
            <textarea
              v-model="inputText"
              rows="1"
              class="input max-h-36 min-h-[48px] resize-y"
              :placeholder="'输入问题…（Enter 发送，Shift+Enter 换行）'"
              :disabled="isSending"
              @keydown="handleKeydown"
            />
          </div>
          <input
            ref="fileInputRef"
            type="file"
            class="hidden"
            accept="image/*,application/pdf"
            @change="handleFileChange"
          />
          <!-- 附件按钮（回形针矢量图标） -->
          <button
            class="flex h-[48px] w-[48px] shrink-0 items-center justify-center rounded-full text-stone-400 transition hover:bg-stone-100 hover:text-stone-600"
            :disabled="isSending || isUploading"
            :title="isUploading ? '上传中…' : '添加附件'"
            @click="openFilePicker"
          >
            <svg v-if="!isUploading" class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/>
            </svg>
            <svg v-else class="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"/></svg>
          </button>
          <!-- 发送 / 停止按钮 -->
          <button
            v-if="store.isStreaming"
            class="flex h-[48px] w-[48px] shrink-0 items-center justify-center rounded-xl bg-stone-700 text-white transition hover:bg-stone-800"
            title="停止生成"
            @click="handleAbort"
          >
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
          </button>
          <button
            v-else
            class="btn-primary h-[48px] w-[48px] shrink-0 justify-center !rounded-full p-0"
            :disabled="(!inputText.trim() && attachmentMetas.length === 0) || isSending || isUploading"
            @click="handleSend"
          >
            <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
          </button>
        </div>
      </footer>
    </section>

  </div>
</template>

<style scoped>
.settings-panel-enter-active,
.settings-panel-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.settings-panel-enter-from,
.settings-panel-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(-6px);
}
.settings-panel-enter-to,
.settings-panel-leave-from {
  transform: translateX(-50%) translateY(0);
}

/* KaTeX 公式溢出处理 */
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

/* 公式容器 + 独立复制按钮 */
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

/* ═══════════════════════════════════════════════════════
   Cherry Studio 风格思维链块
   ═══════════════════════════════════════════════════════ */

/* 思维链外框 */
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

/* 折叠头部 */
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

/* 思维链标签文字 */
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

/* 旋转光圈（思考进行中） */
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

/* 思维链内容区 */
.thinking-body {
  border-top: 1px solid rgba(120, 100, 70, 0.12);
}
.thinking-content-inner {
  max-height: 320px;
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

/* 打字光标 */
.thinking-cursor {
  display: inline-block;
  width: 1px;
  height: 12px;
  background: #a08060;
  margin-left: 2px;
  vertical-align: middle;
  animation: blink 0.9s step-end infinite;
}

/* 展开/折叠动画 */
.thinking-expand-enter-active,
.thinking-expand-leave-active {
  transition: max-height 0.28s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.2s ease;
  overflow: hidden;
  max-height: 360px;
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

/* ═══════════════════════════════════════════════════════
   联网搜索切换按钮
   ═══════════════════════════════════════════════════════ */

.web-search-toggle {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border-radius: 20px;
  border: 1px solid rgba(168,162,158,0.28);
  background: rgba(255,255,255,0.7);
  color: #a8a29e;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.18s ease;
  position: relative;
}
.web-search-toggle:hover {
  border-color: rgba(120, 100, 70, 0.35);
  color: #7c6f5c;
  background: rgba(255,252,245,0.9);
}
.web-search-toggle--active {
  border-color: rgba(34, 197, 94, 0.45);
  color: #16a34a;
  background: rgba(240, 253, 244, 0.9);
}
.web-search-toggle--active:hover {
  border-color: rgba(34, 197, 94, 0.65);
  background: rgba(220, 252, 231, 0.95);
}
.web-search-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #22c55e;
  animation: pulse-green 1.5s ease-in-out infinite;
}

/* 来源徽章 web 类型 */
:global(.badge-web) {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.03em;
  background: #dcfce7;
  color: #15803d;
}

/* 动画关键帧 */
@keyframes thinking-spin {
  to { transform: rotate(360deg); }
}
@keyframes shimmer {
  to { background-position: -200% center; }
}
@keyframes blink {
  50% { opacity: 0; }
}
@keyframes pulse-green {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.6; transform: scale(0.85); }
}
</style>
