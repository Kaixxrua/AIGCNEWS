<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  modelValue: string
  focused: boolean
  loading: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  focus: []
  blur: []
}>()

const inputRef = ref<HTMLInputElement | null>(null)

defineExpose({
  focus: () => inputRef.value?.focus(),
  blur: () => inputRef.value?.blur(),
})
</script>

<template>
  <div
    class="flex items-center gap-2 rounded-2xl px-3 py-1.5 text-sm transition-all"
    :class="props.focused
      ? 'bg-white border border-stone-300 shadow-md'
      : 'bg-stone-100/80 border border-transparent'"
  >
    <!-- 搜索图标 -->
    <svg class="h-3.5 w-3.5 shrink-0 text-stone-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-4.35-4.35M17 11A6 6 0 115 11a6 6 0 0112 0z"/>
    </svg>

    <input
      ref="inputRef"
      :value="props.modelValue"
      type="text"
      placeholder="搜索论文、项目…"
      class="flex-1 bg-transparent text-xs text-stone-700 outline-none placeholder:text-stone-400 min-w-0"
      @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
      @focus="emit('focus')"
      @blur="emit('blur')"
    />

    <!-- 加载动画 -->
    <svg v-if="props.loading" class="h-3 w-3 animate-spin text-stone-400 shrink-0" fill="none" viewBox="0 0 24 24">
      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"/>
      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"/>
    </svg>

    <!-- 快捷键提示（未聚焦时） -->
    <span v-if="!props.focused" class="shrink-0 text-2xs text-stone-400 font-mono select-none">⌘K</span>
  </div>
</template>
