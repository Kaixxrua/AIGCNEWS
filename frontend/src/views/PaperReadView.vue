<script setup lang="ts">
import { computed, onMounted, onUnmounted, toRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PaperConversationPanel from '../components/papers/PaperConversationPanel.vue'
import PaperDocumentPanel from '../components/papers/PaperDocumentPanel.vue'
import { useEventSource } from '../composables/useEventSource'
import { useLatexRenderer } from '../composables/useLatexRenderer'
import { usePaperReaderController } from '../composables/usePaperReaderController'
import { api, fetchPaperDetail, type PaperItem } from '../services/api'
import { useChatStore } from '../stores/chatStore'

const route = useRoute()
const router = useRouter()
const chatStore = useChatStore()
const { connect } = useEventSource()
const { renderMarkdown, copyFormulas, handleFormulaCopy } = useLatexRenderer()
const paperId = computed(() => String(route.params.id ?? ''))
const baseURL = (api.defaults.baseURL ?? '').replace(/\/+$/, '')

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
  sendMessage: (text, contextPaperId, conversationId) => chatStore.sendMessage(text, contextPaperId, conversationId),
  uploadScreenshot: async (payload) => {
    const response = await api.post<{ image_id: string }>('/chat/upload-screenshot', payload)
    return response.data
  },
  connectEventSource: connect,
  visionRelayUrl: `${baseURL}/chat/vision-relay`,
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

const updateVisionQuestion = (question: string) => {
  if (visionPopup.value) visionPopup.value.question = question
}

onMounted(() => { void initializePaperContext(paperId.value) })
watch(paperId, handlePaperIdChange)
onMounted(() => document.addEventListener('click', handleFormulaCopy))
onUnmounted(() => document.removeEventListener('click', handleFormulaCopy))
</script>

<template>
  <div class="paper-read-shell w-full flex-1 min-h-0 flex flex-col md:flex-row overflow-hidden">
    <PaperConversationPanel
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
    <PaperDocumentPanel
      :paper="paper"
      :paper-loading="paperLoading"
      :paper-error="paperError"
      :pdf-progress="pdfProgress"
      :vision-popup="visionPopup"
      :is-sending="isSending"
      @download-pdf="downloadPdf"
      @rightclick-region="onRightclickRegion"
      @progress="onPdfProgress"
      @update:vision-question="updateVisionQuestion"
      @popup-keydown="handlePopupKeydown"
      @send-vision="sendVision"
      @close-popup="closePopup"
      @popup-input-ref="setPopupInputRef"
    />
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
  box-shadow: 0 0 0 4px var(--lime);
}

.paper-read-shell :deep(button[class*="bg-stone-700"]) {
  border: 1px solid var(--ink);
  background: var(--ink) !important;
  color: var(--paper-raised) !important;
}

.paper-read-shell :deep(button[class*="bg-stone-700"]:hover:not(:disabled)) {
  background: var(--lime) !important;
  color: var(--ink) !important;
}

.paper-read-shell :deep([class*="text-cyan"]) { color: #4b6100 !important; }
.paper-read-shell :deep([class*="bg-cyan"]) { background-color: var(--lime) !important; }

.paper-read-shell :deep(textarea),
.paper-read-shell :deep(input) {
  border-color: rgba(25, 26, 22, 0.52);
  background: #fffef9;
}

.paper-read-shell :deep(.absolute.inset-0.z-\[60\]) {
  background: rgba(244, 240, 230, 0.9);
  backdrop-filter: none;
}

.paper-read-shell :deep(.absolute.inset-0.z-\[60\] > div) {
  border-color: var(--ink);
  border-radius: 6px;
  background: var(--paper-raised);
  box-shadow: 6px 6px 0 rgba(25, 26, 22, 0.16);
}

.paper-read-shell :deep(.absolute.top-full) {
  border-color: var(--ink) !important;
  border-radius: 4px;
  background: var(--paper-raised) !important;
  box-shadow: 4px 4px 0 rgba(25, 26, 22, 0.14);
}
</style>
