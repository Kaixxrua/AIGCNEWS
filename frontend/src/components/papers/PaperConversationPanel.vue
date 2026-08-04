<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
import type { PaperReaderMessage } from '@/features/papers/paperReaderModel'
import PaperMessageList from './PaperMessageList.vue'

interface PaperConversationSummary {
  id: string
  title: string
}

defineProps<{
  showConvPanel: boolean
  activeConversationTitle: string
  conversationList: PaperConversationSummary[]
  currentConversationId: string | null
  messages: PaperReaderMessage[]
  inputText: string
  isSending: boolean
  renderMarkdown: (content: string) => string
  isThinkingExpanded: (messageId: string) => boolean
  copyFormulas: (content: string) => void | Promise<void>
}>()

const emit = defineEmits<{
  back: []
  'update:showConvPanel': [value: boolean]
  'update:inputText': [value: string]
  newConversation: []
  switchConversation: [conversationId: string]
  deleteCurrentConversation: []
  toggleThinking: [messageId: string]
  keydown: [event: KeyboardEvent]
  sendText: []
  chatListRef: [element: Element | null]
}>()
</script>

<template>
  <div class="relative w-full h-1/2 md:h-full md:w-[35%] flex-shrink-0 flex flex-col bg-card border-r border-gray-100/80 hover:border-gray-200 transition-colors">
    <header class="flex shrink-0 items-center justify-between px-4 py-3 relative" style="border-bottom: 1px solid rgb(var(--stone-400-rgb) / 0.12)">
      <button class="flex items-center gap-1.5 text-xs text-stone-400 hover:text-stone-600 transition" @click="emit('back')">
        <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/></svg>
        {{ t('paper.back') }}
      </button>
      <div class="relative">
        <button class="flex items-center gap-1 text-xs font-semibold text-stone-600 font-serif hover:text-stone-800 transition select-none max-w-[140px]" @click="emit('update:showConvPanel', !showConvPanel)">
          <span class="truncate">{{ activeConversationTitle }}</span>
          <svg class="h-3 w-3 opacity-60 shrink-0" :class="showConvPanel ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24" style="transition: transform 0.15s"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
        </button>
        <Transition name="dropdown">
          <div v-if="showConvPanel" class="absolute top-full left-1/2 -translate-x-1/2 mt-2 w-56 rounded-xl bg-card shadow-lg z-50 overflow-hidden" style="border: 1px solid rgb(var(--stone-400-rgb) / 0.2)">
            <button class="w-full flex items-center gap-2 px-3 py-2.5 text-xs text-cyan-600 font-medium hover:bg-cyan-50 transition border-b border-stone-100" @click="emit('newConversation')">
              <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>
              {{ t('paper.newConversation') }}
            </button>
            <div class="max-h-48 overflow-y-auto">
              <button v-for="conv in conversationList" :key="conv.id" class="w-full flex items-center gap-2 px-3 py-2 text-xs text-stone-600 hover:bg-stone-50 transition" :class="conv.id === currentConversationId ? 'bg-stone-100 font-semibold text-stone-800' : ''" @click="emit('switchConversation', conv.id)">
                <svg class="h-3.5 w-3.5 shrink-0 opacity-40" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/></svg>
                <span class="truncate">{{ conv.title || t('paper.conversation') }}</span>
              </button>
              <div v-if="!conversationList.length" class="px-3 py-3 text-xs text-stone-400 text-center">{{ t('paper.noHistory') }}</div>
            </div>
          </div>
        </Transition>
      </div>
      <button class="text-xs text-stone-400 hover:text-red-500 transition" @click="emit('deleteCurrentConversation')">{{ t('paper.delete') }}</button>
    </header>

    <div v-if="showConvPanel" class="fixed inset-0 z-40" @click="emit('update:showConvPanel', false)"/>
    <div :ref="(element) => emit('chatListRef', element as Element | null)" class="flex-1 overflow-y-auto space-y-4 px-4 py-4">
      <PaperMessageList :messages="messages" :render-markdown="renderMarkdown" :is-thinking-expanded="isThinkingExpanded" :copy-formulas="copyFormulas" @toggle-thinking="emit('toggleThinking', $event)" />
    </div>
    <footer class="shrink-0 px-3 py-3" style="border-top: 1px solid rgb(var(--stone-400-rgb) / 0.12)">
      <div class="flex items-end gap-2">
        <textarea :value="inputText" rows="1" class="flex-1 resize-none rounded-2xl border border-stone-200 bg-card px-3 py-2 text-xs text-stone-700 placeholder:text-stone-400 focus:outline-none focus:ring-1 focus:ring-cyan-400/40 max-h-28 min-h-[38px]" :placeholder="t('paper.placeholder')" :disabled="isSending" @input="emit('update:inputText', ($event.target as HTMLTextAreaElement).value)" @keydown="emit('keydown', $event)" />
        <button class="flex h-[38px] w-[38px] shrink-0 items-center justify-center rounded-full bg-ink-solid text-ink-on-solid transition hover:bg-ink-solid-hover disabled:opacity-40" :disabled="!inputText.trim() || isSending" @click="emit('sendText')">
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
        </button>
      </div>
    </footer>
    <div class="absolute inset-0 z-[60] flex items-center justify-center bg-card/75 px-4 backdrop-blur-sm">
      <div class="max-w-xs rounded-3xl border border-stone-200 bg-card/95 px-6 py-8 text-center shadow-2xl">
        <div class="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-3xl bg-stone-100"><svg class="h-7 w-7 text-stone-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.6"><path stroke-linecap="round" stroke-linejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/></svg></div>
        <p class="text-base font-semibold text-stone-800 font-serif">{{ t('paper.unavailableTitle') }}</p>
        <p class="mt-2 text-xs leading-5 text-stone-500">{{ t('paper.unavailableDescription') }}</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dropdown-enter-active, .dropdown-leave-active { transition: opacity 0.15s ease, transform 0.15s ease; }
.dropdown-enter-from, .dropdown-leave-to { opacity: 0; transform: translateX(-50%) translateY(-6px) scale(0.97); }
.dropdown-enter-to, .dropdown-leave-from { opacity: 1; transform: translateX(-50%) translateY(0) scale(1); }
</style>
