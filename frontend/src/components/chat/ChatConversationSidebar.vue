<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
import type { ConversationSummary } from '@/stores/chatStore'

defineProps<{
  conversations: ConversationSummary[]
  activeConversationId: string | null
  loading: boolean
}>()

const emit = defineEmits<{
  create: []
  open: [conversationId: string]
}>()
</script>

<template>
  <aside
    class="chat-sidebar flex flex-col shrink-0 border-r overflow-hidden"
    style="width: 220px; border-color: rgba(168,162,158,0.18); background: rgba(255,255,255,0.6)"
  >
    <!-- 侧边栏标题 + 新建按钮 -->
    <div class="flex items-center justify-between px-3 py-3 shrink-0" style="border-bottom: 1px solid rgba(168,162,158,0.15)">
      <span class="text-xs font-semibold text-stone-500 tracking-wide">{{ t('chat.history') }}</span>
      <button
        class="rounded-lg p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-700 transition text-xs"
        :title="t('chat.newConversation')"
        @click="emit('create')"
      >
        <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
        </svg>
      </button>
    </div>

    <!-- 加载中 -->
    <div v-if="loading" class="flex items-center justify-center py-6">
      <svg class="h-4 w-4 animate-spin text-stone-400" viewBox="0 0 24 24" fill="none">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"/>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"/>
      </svg>
    </div>

    <!-- 会话列表 -->
    <div v-else class="flex-1 overflow-y-auto py-1">
      <div
        v-for="conv in conversations"
        :key="conv.id"
        class="mx-2 my-0.5 cursor-pointer rounded-xl px-3 py-2.5 transition-all"
        :class="conv.id === activeConversationId
          ? 'bg-stone-700 text-white'
          : 'hover:bg-stone-100 text-stone-600'"
        @click="emit('open', conv.id)"
      >
        <p class="truncate text-xs font-medium leading-5">{{ conv.title || t('chat.newConversation') }}</p>
        <p
          class="truncate text-2xs leading-4 mt-0.5"
          :class="conv.id === activeConversationId ? 'text-stone-300' : 'text-stone-400'"
        >
          {{ conv.lastMessagePreview || t('chat.noMessage') }}
        </p>
      </div>
      <div v-if="!conversations.length" class="px-4 py-6 text-center text-xs text-stone-400">
        {{ t('chat.noHistory') }}
      </div>
    </div>
  </aside>
</template>

<style scoped>
.chat-sidebar {
  border-color: var(--rule) !important;
  background: var(--paper-raised) !important;
}

.chat-sidebar [class*="bg-stone-700"] {
  border: 1px solid var(--ink);
  background: var(--lime) !important;
  color: var(--ink) !important;
}

@media (max-width: 639px) {
  .chat-sidebar {
    position: absolute;
    inset: 0 auto 0 0;
    z-index: 45;
    width: min(84vw, 300px) !important;
    box-shadow: 12px 0 28px rgba(68,64,60,0.12);
  }
}
</style>
