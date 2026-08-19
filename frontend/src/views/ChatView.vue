<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useChatStore, type ChatSettings } from '@/stores/chatStore'
import { useAuthStore } from '@/stores/authStore'
import { useLoginPrompt } from '@/composables/useLoginPrompt'
import { useLatexRenderer } from '@/composables/useLatexRenderer'
import ChatComposer from '@/components/chat/ChatComposer.vue'
import ChatConversationSidebar from '@/components/chat/ChatConversationSidebar.vue'
import ChatMessageList from '@/components/chat/ChatMessageList.vue'
import ChatSettingsPopover from '@/components/chat/ChatSettingsPopover.vue'
import { useChatAttachments } from '@/composables/useChatAttachments'
import { useChatViewport } from '@/composables/useChatViewport'
import { getStreamPhaseLabel } from '@/features/chat/chatPresentation'
import { CHAT_SERVICE_ENABLED } from '@/features/chat/chatFeatureFlags'

const { t } = useI18n()
const store = useChatStore()
const authStore = useAuthStore()
const { requestLogin } = useLoginPrompt()
const inputText = ref('')
const listRef = ref<HTMLElement | null>(null)
const showSettings = ref(false)
const isSending = ref(false)
const isLoadingInit = ref(false)
const showSidebar = ref(true)
const {
  isUploading,
  attachmentMetas,
  removeAttachment,
  handleFileChange,
  clearAttachmentMetas,
} = useChatAttachments(inputText)

const localSettings = ref<ChatSettings>({ ...store.settings })

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

const {
  autoScroll,
  scrollToBottom,
  resumeAutoScroll,
} = useChatViewport(listRef, messages)

/** 流式阶段文案映射 */
const streamPhaseLabel = computed(() => t(`chat.${getStreamPhaseLabel(store.streamPhase)}`))

onMounted(async () => {
  document.addEventListener('click', handleFormulaCopy)
  const pending = authStore.consumePendingMessage()
  if (pending) {
    inputText.value = pending
  }

  // 已登录时：加载历史会话列表 + 确保全局会话存在（解决首次无会话、消息被吞问题）
  // kill-switch 关闭期间遮罩盖住整个页面，跳过一切会话初始化请求
  if (CHAT_SERVICE_ENABLED && authStore.isLoggedIn) {
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
  document.removeEventListener('click', handleFormulaCopy)
})

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
    requestLogin('/chat')
    return
  }

  inputText.value = ''
  autoScroll.value = true
  isSending.value = true
  try {
    await store.sendMessage(text || t('chat.analyzeAttachments'))
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
        style="border-bottom: 1px solid rgb(var(--stone-400-rgb) / 0.15)"
      >
        <div class="flex min-w-0 items-center gap-2 sm:gap-3">
          <!-- 侧边栏折叠按钮 -->
          <button
            class="rounded-lg p-1.5 text-stone-400 hover:bg-stone-100 hover:text-stone-700 transition"
            :title="t(showSidebar ? 'chat.collapseSidebar' : 'chat.expandSidebar')"
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
              {{ store.activeConversation?.title || t('chat.assistant') }}
            </h2>
            <p class="text-2xs text-stone-400">
              {{ t('chat.memory', { turns: store.settings.maxHistoryTurns, temperature: store.settings.temperature.toFixed(1) }) }}
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
            {{ t('chat.clear') }}
          </button>
          <button class="rounded-full p-2 text-stone-400 transition hover:bg-stone-100 hover:text-stone-600" @click="openSettings">
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <circle cx="12" cy="12" r="3"/><path d="M19.07 4.93l-1.41 1.41M16.24 7.76A6 6 0 1 0 7.76 16.24M4.93 19.07l1.41-1.41"/>
            </svg>
          </button>
        </div>
      </header>

      <!-- 设置浮层 -->
      <ChatSettingsPopover
        :visible="showSettings"
        :settings="localSettings"
        @cancel="cancelSettings"
        @save="saveSettings"
      />

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
        <button class="pointer-events-auto btn-primary text-xs" @click="resumeAutoScroll">
          <svg class="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
          {{ t('chat.backToBottom') }}
        </button>
      </div>

      <!-- 输入区 -->
      <ChatComposer
        v-model="inputText"
        :attachments="attachmentMetas"
        :is-sending="isSending"
        :is-uploading="isUploading"
        :is-streaming="store.isStreaming"
        @abort="handleAbort"
        @file-change="handleFileChange"
        @keydown="handleKeydown"
        @remove-attachment="removeAttachment"
        @send="handleSend"
      />
    </section>
    <!-- 服务维护遮罩：与 usePaperReaderController 共用 CHAT_SERVICE_ENABLED 唯一开关 -->
    <div v-if="!CHAT_SERVICE_ENABLED" class="absolute inset-0 z-50 flex items-center justify-center bg-card/70 px-6 backdrop-blur-sm">
      <div class="glass-card max-w-md px-8 py-10 text-center shadow-2xl">
        <div class="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-3xl bg-stone-100">
          <svg class="h-8 w-8 text-stone-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
            <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>
            <path d="M8 9h8M8 13h5"/>
          </svg>
        </div>
        <h1 class="text-xl font-semibold text-stone-800 font-serif">{{ t('chat.unavailableTitle') }}</h1>
        <p class="mt-3 text-sm leading-6 text-stone-500">
          {{ t('chat.unavailableDescription') }}
        </p>
      </div>
    </div>

  </div>
</template>

<style scoped>
.chat-shell {
  --paper: var(--chat-paper);
  --paper-raised: var(--paper-warm);
  --ink: var(--chat-ink);
  --rule: rgb(var(--chat-ink-rgb) / 0.72);
  background: var(--paper);
  color: var(--ink);
}

.chat-shell .chat-header {
  border-color: var(--rule) !important;
  background: var(--paper-raised) !important;
}

.chat-shell :deep(.glass-card) {
  border: 1px solid var(--rule);
  border-radius: 6px;
  background: var(--paper-raised);
  box-shadow: 3px 3px 0 rgb(var(--chat-shadow-rgb) / 0.12);
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
  box-shadow: 0 0 0 4px var(--acid-bright);
}

.chat-shell :deep(.btn-primary) {
  border: 1px solid var(--ink);
  border-radius: 4px !important;
  background: var(--ink);
  color: var(--paper-raised);
  box-shadow: none;
}

.chat-shell :deep(.btn-primary:hover:not(:disabled)) {
  background: var(--acid-bright);
  color: var(--chat-on-acid);
}

.chat-shell [class*="text-cyan"] { color: var(--on-acid) !important; }
.chat-shell [class*="bg-cyan"] { background-color: var(--acid-bright) !important; }

.chat-shell > .absolute.inset-0 {
  background: rgb(var(--chat-paper-rgb) / 0.9);
  backdrop-filter: none;
}

.chat-shell > .absolute.inset-0 > div {
  border: 1px solid var(--ink);
  border-radius: 6px;
  background: var(--paper-raised);
  box-shadow: 6px 6px 0 rgb(var(--chat-shadow-rgb) / 0.16);
}

@media (max-width: 639px) {
  .chat-header > div:last-child {
    width: 100%;
    justify-content: flex-end;
  }
}

</style>
