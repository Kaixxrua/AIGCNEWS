<script setup lang="ts">
import type { ChatSettings } from '../../stores/chatStore'

defineProps<{
  visible: boolean
  settings: ChatSettings
}>()

const emit = defineEmits<{
  save: []
  cancel: []
}>()
</script>

<template>
  <Transition name="settings-panel">
    <div
      v-if="visible"
      class="chat-settings-popover absolute left-1/2 top-[60px] z-30 w-80 max-w-[calc(100%_-_24px)] max-h-[calc(100dvh-140px)] -translate-x-1/2 overflow-y-auto glass-card p-5"
      style="box-shadow: 0 4px 20px rgba(0,0,0,0.06)"
    >
      <h3 class="mb-4 text-sm font-semibold text-stone-800 font-serif">对话设置</h3>
      <div class="mb-4 space-y-1.5">
        <label class="flex items-center justify-between text-sm text-stone-500">
          <span>历史记忆轮次</span>
          <span class="font-bold text-stone-800">{{ settings.maxHistoryTurns }}</span>
        </label>
        <input v-model.number="settings.maxHistoryTurns" type="range" min="0" max="20" step="1" class="w-full accent-stone-600 h-1.5 rounded-full" />
        <div class="flex justify-between text-2xs text-stone-400"><span>0 无记忆</span><span>20</span></div>
      </div>
      <div class="mb-4 space-y-1.5">
        <label class="flex items-center justify-between text-sm text-stone-500">
          <span>Temperature</span>
          <span class="font-bold text-stone-800">{{ settings.temperature.toFixed(1) }}</span>
        </label>
        <input v-model.number="settings.temperature" type="range" min="0" max="2" step="0.1" class="w-full accent-stone-600 h-1.5 rounded-full" />
        <div class="flex justify-between text-2xs text-stone-400"><span>0.0 精确</span><span>2.0 创意</span></div>
      </div>
      <div class="flex gap-2">
        <button class="btn-secondary flex-1 justify-center" @click="emit('cancel')">取消</button>
        <button class="btn-primary flex-1 justify-center" @click="emit('save')">保存</button>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.chat-settings-popover button,
.chat-settings-popover input { border-radius: 4px; }
.chat-settings-popover button:focus-visible,
.chat-settings-popover input:focus-visible {
  outline: 2px solid var(--ink);
  outline-offset: 2px;
  box-shadow: 0 0 0 4px var(--lime);
}
.chat-settings-popover input[type="range"] { accent-color: var(--lime); }
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
</style>
