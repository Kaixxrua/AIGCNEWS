<script setup lang="ts">
import { computed, onMounted, onUnmounted, toRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMediaQuery } from '@vueuse/core'
import PaperConversationPanel from '@/components/papers/PaperConversationPanel.vue'
import PaperDocumentPanel from '@/components/papers/PaperDocumentPanel.vue'
import PaperSameDayList from '@/components/papers/PaperSameDayList.vue'
import { useLatexRenderer } from '@/composables/useLatexRenderer'
import { usePaperReaderController } from '@/composables/usePaperReaderController'
import { useSameDayPapers } from '@/composables/useSameDayPapers'
import { paperDay } from '@/features/papers/paperHead'
import { paperPlainText } from '@/features/papers/paperLatex'
import { usePageHead } from '@/seo/pageHead'
import { fetchPaperDetail, type PaperItem } from '@/services/papers/paperApi'
import { useAuthStore } from '@/stores/authStore'
import { useLoginPrompt } from '@/composables/useLoginPrompt'
import { useChatStore } from '@/stores/chatStore'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const { requestLogin } = useLoginPrompt()
const chatStore = useChatStore()
const { renderMarkdown, copyFormulas, handleFormulaCopy } = useLatexRenderer()
const paperId = computed(() => String(route.params.id ?? ''))
// 游客只读：论文内容公开，对话引导登录（会话 API 需鉴权，
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
  sendMessage: (text, contextPaperId, conversationId) => chatStore.sendMessage(text, contextPaperId, conversationId),
  conversationEnabled,
})

const {
  paper, paperLoading, paperError, paperMissing, showConvPanel, currentConversationId,
  conversationList, activeConversationTitle, inputText, isSending, messages,
  initializePaperContext, handlePaperIdChange,
  switchConversation, newConversation, deleteCurrentConversation, toggleThinking,
  isThinkingExpanded, sendText,
  handleKeydown, setChatListRef,
} = controller

// 标签页标题和搜索摘要用论文自己的标题与摘要；站内确实没有这篇时，这个地址不让搜索引擎收录。
usePageHead(() => {
  if (paper.value) return { title: paperPlainText(paper.value.title), description: paperPlainText(paper.value.summary) }
  return paperMissing.value ? { noindex: true } : null
})

// 桌面（漫画版）版头多一行作者、arXiv 编号、点赞和名次，旁边列出同一天日榜上的论文；窄屏沿用原来的阅读布局。
const desktop = useMediaQuery('(min-width: 1024px)')
const { entries: sameDayPapers } = useSameDayPapers({
  day: computed(() => paperDay(paper.value?.published_date)),
  currentId: paperId,
  enabled: desktop,
})

onMounted(() => { void initializePaperContext(paperId.value) })
watch(paperId, handlePaperIdChange)
onMounted(() => document.addEventListener('click', handleFormulaCopy))
onUnmounted(() => document.removeEventListener('click', handleFormulaCopy))

const loginRedirect = computed(() => route.fullPath)
const openLogin = () => requestLogin(loginRedirect.value)
// 有站内来路时回到上一页；直接打开论文链接（无站内历史）时回首页
const goBack = () => {
  if (window.history.state?.back) router.back()
  else void router.push('/')
}
</script>

<template>
  <div class="paper-read-shell w-full flex-1 min-h-0 flex flex-col overflow-hidden" :class="{ 'guest-mode': !conversationEnabled, 'md:flex-row': conversationEnabled }">
    <!-- 页面标题只在桌面漫画版显示（comic-pages.css），其余宽度沿用原阅读布局。 -->
    <div class="paper-read-heading">
      <p class="paper-read-title comic-title">{{ $t('paper.pageTitle') }}</p>
      <p class="paper-read-subtitle">{{ $t('paper.pageSubtitle') }}</p>
    </div>
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
      @back="goBack"
      @new-conversation="newConversation"
      @switch-conversation="switchConversation"
      @delete-current-conversation="deleteCurrentConversation"
      @toggle-thinking="toggleThinking"
      @keydown="handleKeydown"
      @send-text="sendText"
      @chat-list-ref="setChatListRef"
    />
    <!-- 打开的论文不存在时只说「未找到论文」，不再请游客登录讨论它。 -->
    <div v-if="!conversationEnabled && (paperLoading || paper)" class="guest-cta flex items-center justify-center gap-3 px-4 py-2 text-sm">
      <span>{{ $t('paper.guestCta') }}</span>
      <button type="button" class="guest-cta-link" @click="openLogin">{{ $t('paper.guestLogin') }}</button>
    </div>
    <PaperDocumentPanel
      :paper="paper"
      :paper-loading="paperLoading"
      :paper-error="paperError"
      :render-markdown="renderMarkdown"
      :detailed="desktop"
    >
      <!-- 登录后右栏是对话，同一天的论文跟在摘要后面。 -->
      <template v-if="desktop && conversationEnabled && sameDayPapers.length" #after>
        <PaperSameDayList :entries="sameDayPapers" />
      </template>
    </PaperDocumentPanel>
    <!-- 游客的右栏：登录卡下面是同一天的论文。 -->
    <PaperSameDayList v-if="desktop && !conversationEnabled && sameDayPapers.length" :entries="sameDayPapers" />
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

.paper-read-heading { display: none; }

.paper-read-shell.guest-mode .guest-cta {
  border-bottom: 1px solid var(--rule);
  background: var(--paper-raised);
}

.guest-cta-link {
  font-weight: 600;
  text-decoration: underline;
  text-underline-offset: 3px;
}

/* 窄屏：游客提示文案较长时允许换行，避免把登录按钮挤出视口 */
@media (max-width: 639px) {
  .paper-read-shell.guest-mode .guest-cta {
    flex-wrap: wrap;
    gap: 4px 10px;
    padding: 8px 12px;
    text-align: center;
  }
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
