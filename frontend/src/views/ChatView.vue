<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useChatStore } from '../stores/chatStore'
import { useAuthStore } from '../stores/authStore'
import { useLatexRenderer } from '../composables/useLatexRenderer'
import { FileText, Image } from 'lucide-vue-next'
import ChatConversationSidebar from '../components/chat/ChatConversationSidebar.vue'
import ChatMessageList from '../components/chat/ChatMessageList.vue'
import { useChatAttachments } from '../composables/useChatAttachments'
import { getStreamPhaseLabel } from '../features/chat/chatPresentation'

const store = useChatStore()
const authStore = useAuthStore()
const router = useRouter()
const inputText = ref('')
const listRef = ref<HTMLElement | null>(null)
const showSettings = ref(false)
const isSending = ref(false)
const isLoadingInit = ref(false)
const showSidebar = ref(true)
const {
  isUploading,
  attachmentMetas,
  openFilePicker,
  removeAttachment,
  handleFileChange,
  clearAttachmentMetas,
} = useChatAttachments(inputText)

const localSettings = ref({ ...store.settings })

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
const streamPhaseLabel = computed(() => getStreamPhaseLabel(store.streamPhase))

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
    clearAttachmentMetas()
  }
  finally { isSending.value = false }
  await scrollToBottom()
}

const handleKeydown = async (e: KeyboardEvent) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); await handleSend() }
}

const handleCreateConversation = () => {
  if (!authStore.isLoggedIn) return
  void store.createNewConversation('global')
}
const handleOpenConversation = (conversationId: string) => {
  void store.openConversation(conversationId)
}

const openSettings = () => { localSettings.value = { ...store.settings }; showSettings.value = true }
const saveSettings = () => { store.updateSettings({ ...localSettings.value }); showSettings.value = false }
const cancelSettings = () => { showSettings.value = false }
</script>

<template>
  <!-- 双栏布局：左侧会话列表 + 右侧对话区 -->
  <div class="chat-shell relative flex h-full overflow-hidden">

    <!-- 左侧历史会话列表 -->
    <ChatConversationSidebar
      v-if="showSidebar"
      :conversations="conversationList"
      :active-conversation-id="store.activeConversationId"
      :loading="isLoadingInit"
      @create="handleCreateConversation"
      @open="handleOpenConversation"
    />

    <section class="relative flex flex-col overflow-hidden flex-1">

      <!-- 标题栏 -->
      <header class="stagger-enter chat-header flex flex-wrap items-center justify-between px-3 py-3.5 sm:px-5 shrink-0"
        style="border-bottom: 1px solid rgba(168,162,158,0.15)"
      >
        <div class="flex min-w-0 items-center gap-2 sm:gap-3">
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
          <div class="min-w-0">
            <h2 class="truncate text-sm font-semibold text-stone-800 font-serif">
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
          class="absolute left-1/2 top-[60px] z-30 w-80 max-w-[calc(100%_-_24px)] max-h-[calc(100dvh-140px)] -translate-x-1/2 overflow-y-auto glass-card p-5"
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
      <div ref="listRef" class="stagger-enter flex-1 overflow-y-auto px-5 py-5" style="animation-delay: 0.1s">
        <ChatMessageList
          :messages="messages"
          :render-markdown="renderMarkdown"
          :copy-formulas="copyFormulas"
          @regenerate="handleRegenerate"
          @delete="handleDeleteMessage"
        />
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
        <div class="flex flex-wrap items-end gap-2 sm:flex-nowrap sm:gap-3">
          <div class="relative min-w-[calc(100%_-_104px)] flex-1 sm:min-w-0">
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
    <div class="absolute inset-0 z-50 flex items-center justify-center bg-white/70 px-6 backdrop-blur-sm">
      <div class="glass-card max-w-md px-8 py-10 text-center shadow-2xl">
        <div class="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-3xl bg-stone-100">
          <svg class="h-8 w-8 text-stone-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
            <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>
            <path d="M8 9h8M8 13h5"/>
          </svg>
        </div>
        <h1 class="text-xl font-semibold text-stone-800 font-serif">服务暂未开放敬请期待</h1>
        <p class="mt-3 text-sm leading-6 text-stone-500">
          聊天与 AI 对话功能正在维护升级中，开放后将第一时间恢复使用。
        </p>
      </div>
    </div>

  </div>
</template>

<style scoped>
.chat-shell {
  --paper: #f4f0e6;
  --paper-raised: #fffdf6;
  --ink: #191a16;
  --rule: rgba(25, 26, 22, 0.72);
  --lime: #c7ff2e;
  background: var(--paper);
  color: var(--ink);
}

.chat-shell .chat-header,
.chat-shell footer {
  border-color: var(--rule) !important;
  background: var(--paper-raised) !important;
}

.chat-shell :deep(.glass-card) {
  border: 1px solid var(--rule);
  border-radius: 6px;
  background: var(--paper-raised);
  box-shadow: 3px 3px 0 rgba(25, 26, 22, 0.12);
  backdrop-filter: none;
}

.chat-shell button,
.chat-shell textarea,
.chat-shell input { border-radius: 4px; }

.chat-shell button:focus-visible,
.chat-shell textarea:focus-visible,
.chat-shell input:focus-visible {
  outline: 2px solid var(--ink);
  outline-offset: 2px;
  box-shadow: 0 0 0 4px var(--lime);
}

.chat-shell :deep(.btn-primary) {
  border: 1px solid var(--ink);
  border-radius: 4px !important;
  background: var(--ink);
  color: var(--paper-raised);
  box-shadow: none;
}

.chat-shell :deep(.btn-primary:hover:not(:disabled)) {
  background: var(--lime);
  color: var(--ink);
}

.chat-shell [class*="text-cyan"] { color: #4b6100 !important; }
.chat-shell [class*="bg-cyan"] { background-color: var(--lime) !important; }

.chat-shell textarea,
.chat-shell input:not([type="range"]) {
  border-color: rgba(25, 26, 22, 0.52);
  background: #fffef9;
}

.chat-shell input[type="range"] { accent-color: var(--lime); }

.chat-shell > .absolute.inset-0 {
  background: rgba(244, 240, 230, 0.9);
  backdrop-filter: none;
}

.chat-shell > .absolute.inset-0 > div {
  border: 1px solid var(--ink);
  border-radius: 6px;
  background: var(--paper-raised);
  box-shadow: 6px 6px 0 rgba(25, 26, 22, 0.16);
}

@media (max-width: 639px) {
  .chat-header > div:last-child {
    width: 100%;
    justify-content: flex-end;
  }
}

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

@keyframes pulse-green {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.6; transform: scale(0.85); }
}
</style>
