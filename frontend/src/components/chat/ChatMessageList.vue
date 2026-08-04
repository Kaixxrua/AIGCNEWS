<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
import { ref } from 'vue'
import { Clipboard, SquareCode } from 'lucide-vue-next'
import type { ChatMessage } from '@/stores/chatStore'
import {
  getSourceTitle,
  getSourceType,
  getSourceUrl,
  sourceTypeBadgeClass,
} from '@/features/chat/chatPresentation'

defineProps<{
  messages: ChatMessage[]
  renderMarkdown: (content: string) => string
  copyFormulas: (content: string) => void | Promise<void>
}>()

const emit = defineEmits<{
  regenerate: [messageId: string]
  delete: [messageId: string]
}>()

const rawModeSet = ref(new Set<number>())
const toggleRaw = (idx: number) => {
  if (rawModeSet.value.has(idx)) rawModeSet.value.delete(idx)
  else rawModeSet.value.add(idx)
  rawModeSet.value = new Set(rawModeSet.value)
}

const thinkingExpanded = ref<Record<string, boolean>>({})
const toggleThinking = (msgId: string) => {
  thinkingExpanded.value = { ...thinkingExpanded.value, [msgId]: !thinkingExpanded.value[msgId] }
}
const isThinkingExpanded = (msgId: string) => !!thinkingExpanded.value[msgId]
const visualAttachment = (message: ChatMessage) => message.attachments.find((attachment) => attachment.modality === 'vision')
const hasUnretainedScreenshot = (message: ChatMessage) => visualAttachment(message)?.imageRetained === false
const canRegenerate = (message: ChatMessage) => !visualAttachment(message)?.regenerationRequiresNewImage
</script>

<template>
  <div class="chat-message-list space-y-5" :class="{ 'h-full': !messages.length }">
    <div v-if="!messages.length" class="flex h-full flex-col items-center justify-center gap-3 text-stone-400">
      <div class="flex h-16 w-16 items-center justify-center rounded-3xl bg-stone-100">
        <svg class="h-8 w-8 opacity-40 text-stone-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>
        </svg>
      </div>
      <p class="text-sm font-medium text-stone-500 font-serif">{{ t('chat.startTitle') }}</p>
      <p class="text-xs text-center max-w-xs text-stone-400">{{ t('chat.startDescription') }}</p>
    </div>

    <div
      v-for="(msg, idx) in messages"
      :key="msg.id"
      class="flex animate-slide-up"
      :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
    >
      <div
        v-if="msg.role !== 'user'"
        class="mr-2.5 mt-1 h-7 w-7 shrink-0 flex items-center justify-center rounded-full bg-ink-solid text-ink-on-solid text-xs font-bold shadow-sm"
      >AI</div>

      <div class="max-w-[80%]" :class="msg.role === 'user' ? 'max-w-[70%]' : 'flex-1'">
        <div
          v-if="msg.role === 'user'"
          class="inline-block rounded-[20px] rounded-br-md bg-ink-solid px-4 py-3 text-sm leading-6 text-ink-on-solid shadow-sm"
        >
          <p v-if="hasUnretainedScreenshot(msg)" class="mb-2 rounded-md border border-white/20 bg-white/10 px-2.5 py-1.5 text-xs font-medium text-stone-100">
            截图内容未保存
          </p>
          {{ msg.content }}
        </div>

        <div v-else class="space-y-2">
          <div
            v-if="msg.hasThinking || msg.isThinking"
            class="thinking-block overflow-hidden"
            :class="msg.isThinking ? 'thinking-block--active' : ''"
          >
            <button
              class="thinking-header flex w-full items-center gap-2 px-4 py-3 text-left"
              :class="msg.isThinking ? 'cursor-default' : 'cursor-pointer'"
              @click="!msg.isThinking && toggleThinking(msg.id)"
            >
              <span v-if="msg.isThinking" class="thinking-spinner" />
              <svg v-else class="h-3.5 w-3.5 shrink-0" style="color: var(--warm-ink)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.347.346A3 3 0 0115 18H9a3 3 0 01-2.12-.879l-.347-.346a5 5 0 010-7.072z"/>
              </svg>
              <span class="flex-1 text-xs font-medium thinking-label">
                <template v-if="msg.isThinking"><span class="thinking-dots-text">{{ t('chat.thinking') }}</span></template>
                <template v-else>
                  {{ t('chat.thought') }}
                  <span v-if="msg.thinkingDurationSec > 0" class="thinking-duration">{{ t('chat.thoughtDuration', { seconds: msg.thinkingDurationSec }) }}</span>
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
                class="thinking-body px-4 pb-3"
              >
                <div class="thinking-content-inner">
                  <p v-if="msg.thinking" class="font-mono text-[11px] leading-[1.7] text-stone-500 whitespace-pre-wrap break-words">{{ msg.thinking }}</p>
                  <p v-else-if="msg.isThinking" class="text-[11px] text-stone-400 italic">{{ t('chat.retrieving') }}</p>
                  <span v-if="msg.isThinking" class="thinking-cursor" />
                </div>
              </div>
            </Transition>
          </div>

          <div v-if="!msg.content && !msg.hasThinking && !msg.isThinking" class="flex items-center gap-1.5 rounded-[20px] px-4 py-3 bg-stone-50">
            <span class="h-2 w-2 animate-bounce rounded-full bg-stone-300" style="animation-delay: 0ms"/>
            <span class="h-2 w-2 animate-bounce rounded-full bg-stone-300" style="animation-delay: 150ms"/>
            <span class="h-2 w-2 animate-bounce rounded-full bg-stone-300" style="animation-delay: 300ms"/>
          </div>

          <div v-if="msg.content" class="rounded-[20px] rounded-bl-md px-4 py-3" style="background: rgb(var(--card-rgb) / 0.85); border: 1px solid rgb(var(--stone-400-rgb) / 0.20)">
            <div class="flex justify-end gap-1 mb-1">
              <button class="inline-flex items-center gap-1 text-2xs px-2 py-0.5 rounded-md bg-stone-100 text-stone-400 hover:text-stone-600 transition" :title="t('chat.copyFormulaTitle')" @click="copyFormulas(msg.content)">
                <Clipboard class="h-3 w-3" /> {{ t('chat.copyFormula') }}
              </button>
              <button
                class="inline-flex items-center gap-1 text-2xs px-2 py-0.5 rounded-md transition"
                :class="rawModeSet.has(idx) ? 'bg-stone-200 text-stone-600' : 'bg-stone-100 text-stone-400 hover:text-stone-600'"
                @click="toggleRaw(idx)"
              >
                <SquareCode class="h-3 w-3" />
                {{ t(rawModeSet.has(idx) ? 'chat.renderFormula' : 'chat.sourceCode') }}
              </button>
            </div>
            <div v-if="!rawModeSet.has(idx)" class="prose-content text-sm leading-7 text-stone-700" v-html="renderMarkdown(msg.content)" />
            <pre v-else class="text-sm leading-6 text-stone-600 whitespace-pre-wrap break-all font-mono bg-stone-50 rounded-lg p-3">{{ msg.content }}</pre>
          </div>

          <div class="flex items-center gap-2 px-1 pt-1 text-2xs text-stone-400">
            <button v-if="canRegenerate(msg)" class="transition hover:text-stone-600" @click="emit('regenerate', msg.id)">{{ t('chat.regenerate') }}</button>
            <button class="transition hover:text-red-500" @click="emit('delete', msg.id)">{{ t('chat.delete') }}</button>
          </div>

          <div v-if="msg.sources?.length" class="space-y-1.5 pt-1">
            <p class="text-2xs font-semibold uppercase tracking-widest text-stone-400 px-1">{{ t('chat.references', { count: msg.sources.length }) }}</p>
            <div class="flex flex-col gap-1.5">
              <div
                v-for="(source, sidx) in msg.sources"
                :key="sidx"
                class="flex items-center gap-2 rounded-2xl px-3 py-2 text-xs card-hover"
                style="background: rgb(var(--card-rgb) / 0.85); border: 1px solid rgb(var(--stone-400-rgb) / 0.20)"
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
</template>

<style scoped>
.chat-message-list button { border-radius: 4px; }
.chat-message-list button:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; box-shadow: 0 0 0 4px var(--acid-bright); }
:deep(.katex-display) { overflow-x: auto; overflow-y: hidden; max-width: 100%; padding: 4px 0; }
:deep(.katex-display > .katex) { white-space: nowrap; }
:deep(.prose-content) { overflow: hidden; max-width: 100%; }
:deep(.formula-wrap) { position: relative; overflow-x: auto; overflow-y: hidden; padding: 6px 0; }
:deep(.formula-copy-btn) { position: absolute; top: 2px; right: 2px; z-index: 5; cursor: pointer; background: rgb(var(--stone-100-rgb) / 0.85); border: 1px solid rgb(var(--stone-400-rgb) / 0.2); border-radius: 6px; padding: 1px 5px; font-size: 11px; line-height: 1.4; opacity: 0; transition: opacity 0.15s; }
:deep(.formula-wrap:hover .formula-copy-btn) { opacity: 1; }
:deep(.katex-block-wrapper) { position: relative; overflow-x: auto; overflow-y: hidden; padding: 6px 0; }
.thinking-block { border-radius: 16px; border: 1px solid rgb(var(--glow-warm-rgb) / 0.18); background: linear-gradient(135deg, rgb(var(--cream-rgb) / 0.95) 0%, rgb(var(--cream-deep-rgb) / 0.92) 100%); overflow: hidden; transition: border-color 0.2s ease; }
.thinking-block--active { border-color: rgb(var(--glow-warm-rgb) / 0.32); background: linear-gradient(135deg, rgb(var(--cream-bright-rgb) / 0.98) 0%, rgb(var(--cream-warm-rgb) / 0.96) 100%); }
.thinking-header { width: 100%; background: transparent; border: none; outline: none; transition: background 0.15s ease; }
.thinking-header:hover { background: rgb(var(--glow-warm-rgb) / 0.05); }
.thinking-label { color: var(--warm-ink); font-size: 12px; font-weight: 500; letter-spacing: 0.01em; }
.thinking-dots-text { background: linear-gradient(90deg, var(--shimmer) 0%, var(--shimmer-bright) 40%, var(--shimmer) 80%); background-size: 200% auto; -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; animation: shimmer 1.8s linear infinite; }
.thinking-duration { color: var(--warm-ink-faint); font-weight: 400; }
.thinking-spinner { display: inline-block; width: 14px; height: 14px; border-radius: 50%; border: 2px solid rgb(var(--shimmer-rgb) / 0.25); border-top-color: var(--shimmer); animation: thinking-spin 0.8s linear infinite; flex-shrink: 0; }
.thinking-body { border-top: 1px solid rgb(var(--glow-warm-rgb) / 0.12); }
.thinking-content-inner { max-height: 320px; overflow-y: auto; padding: 2px 0; scrollbar-width: thin; scrollbar-color: rgb(var(--glow-warm-rgb) / 0.2) transparent; }
.thinking-content-inner::-webkit-scrollbar { width: 4px; }
.thinking-content-inner::-webkit-scrollbar-thumb { background: rgb(var(--glow-warm-rgb) / 0.2); border-radius: 2px; }
.thinking-cursor { display: inline-block; width: 1px; height: 12px; background: var(--shimmer); margin-left: 2px; vertical-align: middle; animation: blink 0.9s step-end infinite; }
.thinking-expand-enter-active, .thinking-expand-leave-active { transition: max-height 0.28s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.2s ease; overflow: hidden; max-height: 360px; }
.thinking-expand-enter-from, .thinking-expand-leave-to { max-height: 0; opacity: 0; }
.thinking-expand-enter-to, .thinking-expand-leave-from { opacity: 1; }
:global(.badge-web) { display: inline-flex; align-items: center; padding: 1px 6px; border-radius: 4px; font-size: 10px; font-weight: 600; letter-spacing: 0.03em; background: var(--badge-web-bg); color: var(--badge-web-ink); }
@keyframes thinking-spin { to { transform: rotate(360deg); } }
@keyframes shimmer { to { background-position: -200% center; } }
@keyframes blink { 50% { opacity: 0; } }
</style>
