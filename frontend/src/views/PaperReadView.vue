<script setup lang="ts">
import { computed, onMounted, onUnmounted, toRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PaperConversationPanel from '@/components/papers/PaperConversationPanel.vue'
import PaperDocumentPanel from '@/components/papers/PaperDocumentPanel.vue'
import { useEventSource } from '@/composables/useEventSource'
import { useLatexRenderer } from '@/composables/useLatexRenderer'
import { usePaperReaderController } from '@/composables/usePaperReaderController'
import { api } from '@/services/http/apiClient'
import { fetchPaperDetail, type PaperItem } from '@/services/papers/paperApi'
import { useAuthStore } from '@/stores/authStore'
import { useLoginPrompt } from '@/composables/useLoginPrompt'
import { useChatStore } from '@/stores/chatStore'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const { requestLogin } = useLoginPrompt()
const chatStore = useChatStore()
const { connect } = useEventSource()
const { renderMarkdown, copyFormulas, handleFormulaCopy } = useLatexRenderer()
const paperId = computed(() => String(route.params.id ?? ''))
const baseURL = (api.defaults.baseURL ?? '').replace(/\/+$/, '')
// 游客只读：论文内容公开，对话/截图追问引导登录（会话 API 需鉴权，
// 匿名调用会触发全局 401 跳登录，故在控制器层整体关闭）。
const conversationEnabled = computed(() => authStore.status === 'authenticated')

const controller = usePaperReaderController<PaperItem>({
  paperId,
  activeConversationId: toRef(chatStore, 'activeConversationId'),
  conversationMap: toRef(chatStore, 'conversationMap'),
  messageMap: toRef(chatStore, 'messageMap'),
  isStreaming: toRef(chatStore, 'isStreaming'),
  fetchPaper: fetchPaperDetail,
  loadConversations: () => chatStore.loadConversations('global'),
  openConversation: (conversationId) => chatStore.openConversation(conversationId),
  ensureGlobalConversation: (title) => chatStore.ensureGlobalConversation(title),
  deleteActiveConversation: () => chatStore.deleteActiveConversation(),
  appendLocalMessage: (conversationId, message) => chatStore.appendLocalMessage(conversationId, message),
  patchMessage: (conversationId, messageId, patch) => chatStore.patchMessage(conversationId, messageId, patch),
  sendMessage: (text, contextPaperId, conversationId) => chatStore.sendMessage(text, contextPaperId, conversationId),
  uploadScreenshot: async (payload) => {
    const response = await api.post<{ image_id: string }>('/chat/upload-screenshot', payload)
    return response.data
  },
  connectEventSource: connect,
  visionRelayUrl: `${baseURL}/chat/vision-relay`,
  conversationEnabled,
})

const {
  paper, paperLoading, paperError, showConvPanel, currentConversationId,
  conversationList, activeConversationTitle, inputText, isSending, messages,
  visionPopup, pdfProgress, initializePaperContext, handlePaperIdChange,
  switchConversation, newConversation, deleteCurrentConversation, toggleThinking,
  isThinkingExpanded, onRightclickRegion, closePopup, sendVision, sendText,
  handleKeydown, handlePopupKeydown, onPdfProgress, downloadPdf, setChatListRef,
  setPopupInputRef,
} = controller

onMounted(() => { void initializePaperContext(paperId.value) })
watch(paperId, handlePaperIdChange)
onMounted(() => document.addEventListener('click', handleFormulaCopy))
onUnmounted(() => document.removeEventListener('click', handleFormulaCopy))

const loginRedirect = computed(() => route.fullPath)
const openLogin = () => requestLogin(loginRedirect.value)
</script>

<template>
  <div class="paper-read-shell w-full flex-1 min-h-0 flex flex-col overflow-hidden" :class="{ 'guest-mode': !conversationEnabled, 'md:flex-row': conversationEnabled }">
    <PaperConversationPanel
      v-if="conversationEnabled"
      v-model:show-conv-panel="showConvPanel"
      v-model:input-text="inputText"
      :active-conversation-title="activeConversationTitle"
      :conversation-list="conversationList"
      :current-conversation-id="currentConversationId"
      :messages="messages"
      :is-sending="isSending"
      :render-markdown="renderMarkdown"
      :is-thinking-expanded="isThinkingExpanded"
      :copy-formulas="copyFormulas"
      @back="router.push('/chat')"
      @new-conversation="newConversation"
      @switch-conversation="switchConversation"
      @delete-current-conversation="deleteCurrentConversation"
      @toggle-thinking="toggleThinking"
      @keydown="handleKeydown"
      @send-text="sendText"
      @chat-list-ref="setChatListRef"
    />
    <div v-if="!conversationEnabled" class="guest-cta flex items-center justify-center gap-3 px-4 py-2 text-sm">
      <span>{{ $t('paper.guestCta') }}</span>
      <button type="button" class="guest-cta-link" @click="openLogin">{{ $t('paper.guestLogin') }}</button>
    </div>
    <PaperDocumentPanel
      :paper="paper"
      :paper-loading="paperLoading"
      :paper-error="paperError"
      :pdf-progress="pdfProgress"
      v-model:vision-popup="visionPopup"
      :is-sending="isSending"
      @download-pdf="downloadPdf"
      @rightclick-region="onRightclickRegion"
      @progress="onPdfProgress"
      @popup-keydown="handlePopupKeydown"
      @send-vision="sendVision"
      @close-popup="closePopup"
      @popup-input-ref="setPopupInputRef"
    />
  </div>
</template>

<style scoped>
.paper-read-shell {
  --paper: var(--chat-paper);
  --paper-raised: var(--paper-warm);
  --ink: var(--chat-ink);
  --rule: rgb(var(--chat-ink-rgb) / 0.72);
  background: var(--paper);
  color: var(--ink);
}

.paper-read-shell.guest-mode .guest-cta {
  border-bottom: 1px solid var(--rule);
  background: var(--paper-raised);
}

.guest-cta-link {
  font-weight: 600;
  text-decoration: underline;
  text-underline-offset: 3px;
}

.paper-read-shell > div {
  border-color: var(--rule) !important;
  background: var(--paper) !important;
}

.paper-read-shell :deep(header),
.paper-read-shell :deep(footer) {
  border-color: var(--rule) !important;
  background: var(--paper-raised);
}

.paper-read-shell :deep(button),
.paper-read-shell :deep(textarea),
.paper-read-shell :deep(input) { border-radius: 4px; }

.paper-read-shell :deep(button:focus-visible),
.paper-read-shell :deep(textarea:focus-visible),
.paper-read-shell :deep(input:focus-visible) {
  outline: 2px solid var(--ink);
  outline-offset: 2px;
  box-shadow: 0 0 0 4px var(--acid-bright);
}

.paper-read-shell :deep(button[class*="bg-ink-solid"]) {
  border: 1px solid var(--ink);
  background: var(--ink) !important;
  color: var(--paper-raised) !important;
}

.paper-read-shell :deep(button[class*="bg-ink-solid"]:hover:not(:disabled)) {
  background: var(--acid-bright) !important;
  color: var(--chat-on-acid) !important;
}

.paper-read-shell :deep([class*="text-cyan"]) { color: var(--on-acid) !important; }
.paper-read-shell :deep([class*="bg-cyan"]) { background-color: var(--acid-bright) !important; }

.paper-read-shell :deep(textarea),
.paper-read-shell :deep(input) {
  border-color: rgb(var(--chat-ink-rgb) / 0.52);
  background: var(--chat-input-bg);
}

.paper-read-shell :deep(.absolute.inset-0.z-\[60\]) {
  background: rgb(var(--chat-paper-rgb) / 0.9);
  backdrop-filter: none;
}

.paper-read-shell :deep(.absolute.inset-0.z-\[60\] > div) {
  border-color: var(--ink);
  border-radius: 6px;
  background: var(--paper-raised);
  box-shadow: 6px 6px 0 rgb(var(--chat-shadow-rgb) / 0.16);
}

.paper-read-shell :deep(.absolute.top-full) {
  border-color: var(--ink) !important;
  border-radius: 4px;
  background: var(--paper-raised) !important;
  box-shadow: 4px 4px 0 rgb(var(--chat-shadow-rgb) / 0.14);
}
</style>
