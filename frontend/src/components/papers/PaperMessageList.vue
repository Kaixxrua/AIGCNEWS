<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
import { Clipboard } from 'lucide-vue-next'
import type { PaperReaderMessage } from '@/features/papers/paperReaderModel'

defineProps<{
  messages: PaperReaderMessage[]
  renderMarkdown: (content: string) => string
  isThinkingExpanded: (messageId: string) => boolean
  copyFormulas: (content: string) => void | Promise<void>
}>()

const emit = defineEmits<{ toggleThinking: [messageId: string] }>()
</script>

<template>
  <div v-if="!messages.length" class="flex h-full flex-col items-center justify-center gap-2 text-stone-400">
    <svg class="h-12 w-12 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>
    </svg>
    <p class="text-sm font-medium">{{ t('paper.startTitle') }}</p>
    <p class="text-xs text-center max-w-[220px]">{{ t('paper.startDescription') }}</p>
  </div>

  <div v-for="msg in messages" :key="msg.id" class="flex" :class="msg.role === 'user' ? 'justify-end' : 'justify-start'">
    <div v-if="msg.role === 'assistant'" class="mr-2 mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ink-solid text-ink-on-solid text-2xs font-bold">AI</div>
    <div class="max-w-[85%]" :class="msg.role === 'user' ? '' : 'flex-1'">
      <div v-if="msg.role === 'user'" class="rounded-[18px] rounded-br-sm bg-ink-solid px-3.5 py-2.5 text-xs leading-6 text-ink-on-solid">
        <p v-if="msg.isVisual && msg.screenshotRetained === false" class="mb-2 rounded-md border border-white/20 bg-white/10 px-2.5 py-1.5 text-2xs font-medium text-stone-100">
          截图内容未保存
        </p>
        {{ msg.content }}
      </div>

      <div v-else class="space-y-1.5">
        <div v-if="msg.hasThinking || msg.isThinking || msg.thinking" class="thinking-block overflow-hidden" :class="msg.isThinking ? 'thinking-block--active' : ''">
          <button class="thinking-header flex w-full items-center gap-2 px-3.5 py-2.5 text-left" :class="msg.isThinking ? 'cursor-default' : 'cursor-pointer'" @click="!msg.isThinking && emit('toggleThinking', msg.id)">
            <span v-if="msg.isThinking" class="thinking-spinner" />
            <svg v-else class="h-3.5 w-3.5 shrink-0" style="color: var(--warm-ink)" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.347.346A3 3 0 0115 18H9a3 3 0 01-2.12-.879l-.347-.346a5 5 0 010-7.072z"/>
            </svg>
            <span class="flex-1 text-xs font-medium thinking-label">
              <template v-if="msg.isThinking"><span class="thinking-dots-text">{{ t('paper.thinking') }}</span></template>
              <template v-else>{{ t('paper.thought') }}<span v-if="(msg.thinkingDurationSec || 0) > 0" class="thinking-duration">{{ t('paper.thoughtDuration', { seconds: msg.thinkingDurationSec }) }}</span></template>
            </span>
            <svg v-if="!msg.isThinking" class="h-3.5 w-3.5 shrink-0 text-stone-400 transition-transform duration-300" :class="isThinkingExpanded(msg.id) ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
            </svg>
          </button>
          <Transition name="thinking-expand">
            <div v-if="msg.thinking || msg.isThinking" v-show="msg.isThinking || isThinkingExpanded(msg.id)" class="thinking-body px-3.5 pb-2.5">
              <div class="thinking-content-inner">
                <p v-if="msg.thinking" class="font-mono text-[11px] leading-[1.7] text-stone-500 whitespace-pre-wrap break-words">{{ msg.thinking }}</p>
                <p v-else-if="msg.isThinking" class="text-[11px] text-stone-400 italic">{{ t('paper.retrieving') }}</p>
                <span v-if="msg.isThinking" class="thinking-cursor" />
              </div>
            </div>
          </Transition>
        </div>

        <div v-if="!msg.content && msg.isStreaming && !msg.hasThinking && !msg.isThinking && !msg.thinking" class="flex items-center gap-1.5 rounded-[18px] px-3.5 py-2.5 bg-stone-50">
          <span v-for="i in 3" :key="i" class="h-1.5 w-1.5 animate-bounce rounded-full bg-stone-300" :style="`animation-delay:${(i-1)*150}ms`"/>
        </div>
        <div v-if="msg.content" class="rounded-[18px] rounded-bl-sm px-3.5 py-2.5" style="background: rgb(var(--card-rgb) / 0.9); border: 1px solid rgb(var(--stone-400-rgb) / 0.18)">
          <div class="flex justify-end gap-1 mb-1">
            <button class="text-2xs px-2 py-0.5 rounded-md bg-stone-100 text-stone-400 hover:text-stone-600 transition" @click="copyFormulas(msg.content)" :title="t('paper.copyFormulaTitle')">
              <Clipboard class="h-3 w-3" /> {{ t('paper.copyFormula') }}
            </button>
          </div>
          <div class="prose-content text-xs leading-6 text-stone-700" v-html="renderMarkdown(msg.content)"/>
          <span v-if="msg.isStreaming" class="inline-block h-3 w-0.5 animate-pulse bg-stone-500 ml-0.5 align-middle"/>
        </div>
      </div>
    </div>
    <div v-if="msg.role === 'user'" class="ml-2 mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-stone-200 text-stone-600 text-2xs font-bold">U</div>
  </div>
</template>

<style scoped>
.thinking-block { border-radius: 16px; border: 1px solid rgb(var(--glow-warm-rgb) / 0.18); background: linear-gradient(135deg, rgb(var(--cream-rgb) / 0.95) 0%, rgb(var(--cream-deep-rgb) / 0.92) 100%); overflow: hidden; transition: border-color 0.2s ease; }
.thinking-block--active { border-color: rgb(var(--glow-warm-rgb) / 0.32); background: linear-gradient(135deg, rgb(var(--cream-bright-rgb) / 0.98) 0%, rgb(var(--cream-warm-rgb) / 0.96) 100%); }
.thinking-header { width: 100%; background: transparent; border: none; outline: none; transition: background 0.15s ease; }
.thinking-header:hover { background: rgb(var(--glow-warm-rgb) / 0.05); }
.thinking-label { color: var(--warm-ink); font-size: 12px; font-weight: 500; letter-spacing: 0.01em; }
.thinking-dots-text { background: linear-gradient(90deg, var(--shimmer) 0%, var(--shimmer-bright) 40%, var(--shimmer) 80%); background-size: 200% auto; -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; animation: shimmer 1.8s linear infinite; }
.thinking-duration { color: var(--warm-ink-faint); font-weight: 400; }
.thinking-spinner { display: inline-block; width: 14px; height: 14px; border-radius: 50%; border: 2px solid rgb(var(--shimmer-rgb) / 0.25); border-top-color: var(--shimmer); animation: thinking-spin 0.8s linear infinite; flex-shrink: 0; }
.thinking-body { border-top: 1px solid rgb(var(--glow-warm-rgb) / 0.12); }
.thinking-content-inner { max-height: 260px; overflow-y: auto; padding: 2px 0; scrollbar-width: thin; scrollbar-color: rgb(var(--glow-warm-rgb) / 0.2) transparent; }
.thinking-content-inner::-webkit-scrollbar { width: 4px; }
.thinking-content-inner::-webkit-scrollbar-thumb { background: rgb(var(--glow-warm-rgb) / 0.2); border-radius: 2px; }
.thinking-cursor { display: inline-block; width: 1px; height: 12px; background: var(--shimmer); margin-left: 2px; vertical-align: middle; animation: blink 0.9s step-end infinite; }
.thinking-expand-enter-active, .thinking-expand-leave-active { transition: max-height 0.28s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.2s ease; overflow: hidden; max-height: 300px; }
.thinking-expand-enter-from, .thinking-expand-leave-to { max-height: 0; opacity: 0; }
.thinking-expand-enter-to, .thinking-expand-leave-from { opacity: 1; }
:deep(.katex-display) { overflow-x: auto; overflow-y: hidden; max-width: 100%; padding: 4px 0; }
:deep(.katex-display > .katex) { white-space: nowrap; }
:deep(.prose-content) { overflow: hidden; max-width: 100%; }
:deep(.formula-wrap) { position: relative; overflow-x: auto; overflow-y: hidden; padding: 6px 0; }
:deep(.formula-copy-btn) { position: absolute; top: 2px; right: 2px; z-index: 5; cursor: pointer; background: rgb(var(--stone-100-rgb) / 0.85); border: 1px solid rgb(var(--stone-400-rgb) / 0.2); border-radius: 6px; padding: 1px 5px; font-size: 11px; line-height: 1.4; opacity: 0; transition: opacity 0.15s; }
:deep(.formula-wrap:hover .formula-copy-btn) { opacity: 1; }
:deep(.katex-block-wrapper) { position: relative; overflow-x: auto; overflow-y: hidden; padding: 6px 0; }
@keyframes thinking-spin { to { transform: rotate(360deg); } }
@keyframes shimmer { to { background-position: -200% center; } }
@keyframes blink { 50% { opacity: 0; } }
</style>
