<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
import { ref } from 'vue'
import { FileText, Image } from 'lucide-vue-next'

interface AttachmentDisplay {
  id: string
  type: string
  filename?: string | null
  status: string
}

defineProps<{
  modelValue: string
  attachments: AttachmentDisplay[]
  isSending: boolean
  isUploading: boolean
  isStreaming: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  send: []
  abort: []
  keydown: [event: KeyboardEvent]
  fileChange: [event: Event]
  removeAttachment: [attachmentId: string]
}>()

const fileInput = ref<HTMLInputElement | null>(null)
const openFilePicker = () => {
  fileInput.value?.click()
}
</script>

<template>
  <footer class="chat-composer stagger-enter shrink-0 p-4" style="border-top: 1px solid rgb(var(--stone-400-rgb) / 0.15); animation-delay: 0.2s">
    <div v-if="attachments.length" class="mb-3 flex flex-wrap gap-2">
      <div
        v-for="attachment in attachments"
        :key="attachment.id"
        class="flex items-center gap-2 rounded-full border border-stone-200 bg-stone-50 px-3 py-1.5 text-xs text-stone-600"
      >
        <component :is="attachment.type === 'pdf' ? FileText : Image" class="h-3.5 w-3.5 shrink-0" />
        <span class="max-w-[180px] truncate">{{ attachment.filename || attachment.id }}</span>
        <span v-if="attachment.status !== 'ready'" class="text-cyan-600">{{ attachment.status }}</span>
        <button class="text-stone-400 hover:text-red-500" @click="emit('removeAttachment', attachment.id)">×</button>
      </div>
    </div>
    <!-- 工具栏（联网搜索等开关）— 暂时隐藏，待配置 KIMI_API_KEY 后启用 -->
    <!-- <div class="flex items-center gap-2 mb-2">
      <button
        class="web-search-toggle"
        :class="webSearchEnabled ? 'web-search-toggle--active' : ''"
        :title="t(webSearchEnabled ? 'chat.disableWebSearch' : 'chat.enableWebSearch')"
        @click="webSearchEnabled = !webSearchEnabled"
      >
        <Globe class="h-3.5 w-3.5" />
        <span>{{ t('chat.webSearch') }}</span>
        <span v-if="webSearchEnabled" class="web-search-dot" />
      </button>
    </div> -->
    <div class="flex flex-wrap items-end gap-2 sm:flex-nowrap sm:gap-3">
      <div class="relative min-w-[calc(100%_-_104px)] flex-1 sm:min-w-0">
        <textarea
          :value="modelValue"
          rows="1"
          class="input max-h-36 min-h-[48px] resize-y"
          :placeholder="t('chat.placeholder')"
          :disabled="isSending"
          @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
          @keydown="emit('keydown', $event)"
        />
      </div>
      <input
        ref="fileInput"
        type="file"
        class="hidden"
        accept="image/*,application/pdf"
        @change="emit('fileChange', $event)"
      />
      <!-- 附件按钮（回形针矢量图标） -->
      <button
        class="flex h-[48px] w-[48px] shrink-0 items-center justify-center rounded-full text-stone-400 transition hover:bg-stone-100 hover:text-stone-600"
        :disabled="isSending || isUploading"
        :title="t(isUploading ? 'chat.uploading' : 'chat.addAttachment')"
        @click="openFilePicker"
      >
        <svg v-if="!isUploading" class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/>
        </svg>
        <svg v-else class="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"/></svg>
      </button>
      <!-- 发送 / 停止按钮 -->
      <button
        v-if="isStreaming"
        class="flex h-[48px] w-[48px] shrink-0 items-center justify-center rounded-xl bg-ink-solid text-ink-on-solid transition hover:bg-ink-solid-hover"
        :title="t('chat.stop')"
        @click="emit('abort')"
      >
        <svg class="h-4 w-4" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
      </button>
      <button
        v-else
        class="btn-primary h-[48px] w-[48px] shrink-0 justify-center !rounded-full p-0"
        :disabled="(!modelValue.trim() && attachments.length === 0) || isSending || isUploading"
        @click="emit('send')"
      >
        <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
      </button>
    </div>
  </footer>
</template>

<style scoped>
.chat-composer {
  border-color: var(--rule) !important;
  background: var(--paper-raised) !important;
}
.chat-composer button,
.chat-composer textarea,
.chat-composer input { border-radius: 4px; }
.chat-composer button:focus-visible,
.chat-composer textarea:focus-visible,
.chat-composer input:focus-visible {
  outline: 2px solid var(--ink);
  outline-offset: 2px;
  box-shadow: 0 0 0 4px var(--acid-bright);
}
.chat-composer :deep(.btn-primary) {
  border: 1px solid var(--ink);
  border-radius: 4px !important;
  background: var(--ink);
  color: var(--paper-raised);
  box-shadow: none;
}
.chat-composer :deep(.btn-primary:hover:not(:disabled)) {
  background: var(--acid-bright);
  color: var(--chat-on-acid);
}
.chat-composer [class*="text-cyan"] { color: var(--on-acid) !important; }
.chat-composer [class*="bg-cyan"] { background-color: var(--acid-bright) !important; }
.chat-composer textarea,
.chat-composer input:not([type="range"]) {
  border-color: rgb(var(--chat-ink-rgb) / 0.52);
  background: var(--chat-input-bg);
}
.web-search-toggle {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border-radius: 20px;
  border: 1px solid rgb(var(--stone-400-rgb) / 0.28);
  background: rgb(var(--card-rgb) / 0.7);
  color: rgb(var(--stone-400-rgb));
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.18s ease;
  position: relative;
}
.web-search-toggle:hover {
  border-color: rgb(var(--glow-warm-rgb) / 0.35);
  color: var(--warm-ink);
  background: rgb(var(--cream-rgb) / 0.9);
}
.web-search-toggle--active {
  border-color: var(--success-border);
  color: var(--success-ink);
  background: var(--success-bg);
}
.web-search-toggle--active:hover {
  border-color: var(--success-border-strong);
  background: var(--success-bg-strong);
}
.web-search-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--success-strong);
  animation: pulse-green 1.5s ease-in-out infinite;
}
@keyframes pulse-green {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.6; transform: scale(0.85); }
}
</style>
