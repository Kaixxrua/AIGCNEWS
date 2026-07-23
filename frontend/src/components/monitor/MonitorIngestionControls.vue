<script setup lang="ts">
import {
  SOURCE_LIST,
  type SourceKey,
} from '../../features/monitor/monitorViewModel'

defineProps<{
  targetDate: string
  maxTargetDate: string
  ingestingByDate: boolean
  ingestingSource: SourceKey | null
}>()

const emit = defineEmits<{
  'update:targetDate': [date: string]
  ingestByDate: []
  ingestSource: [source: SourceKey]
}>()
</script>

<template>
  <div class="stagger-enter glass-card shrink-0 p-5" style="animation-delay: 0.13s">
    <div class="flex items-center gap-2 mb-3">
      <svg class="h-4 w-4 text-stone-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
      <h3 class="text-sm font-semibold text-stone-700">按日期采集数据</h3>
    </div>
    <div class="flex flex-wrap items-center gap-3">
      <div class="flex items-center gap-2">
        <span class="text-xs text-stone-400 shrink-0">目标日期：</span>
        <input :value="targetDate" type="date" class="input w-auto py-1.5 text-xs" :max="maxTargetDate" @input="emit('update:targetDate', ($event.target as HTMLInputElement).value)" />
      </div>
      <button class="btn-primary" :disabled="ingestingByDate || !targetDate" @click="emit('ingestByDate')">
        <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
        {{ ingestingByDate ? '采集中…' : '开始采集' }}
      </button>
      <p class="text-xs text-stone-400">将采集指定日期的 Arxiv 论文、GitHub 项目、HuggingFace 模型及 AI 新闻</p>
    </div>
  </div>

  <div class="stagger-enter glass-card shrink-0 p-5" style="animation-delay: 0.16s">
    <div class="flex items-center gap-2 mb-3">
      <svg class="h-4 w-4 text-stone-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z"/></svg>
      <h3 class="text-sm font-semibold text-stone-700">按数据源采集</h3>
      <span class="ml-auto text-2xs text-stone-400">点击任意源独立触发采集，不影响其他源</span>
    </div>
    <div class="flex flex-wrap gap-2">
      <button
        v-for="src in SOURCE_LIST"
        :key="src.key"
        class="inline-flex items-center gap-1.5 rounded-2xl px-3.5 py-2 text-xs font-medium transition-all
               border border-stone-200 hover:border-stone-300 hover:shadow-sm active:scale-[0.97]
               disabled:opacity-40 disabled:cursor-not-allowed"
        :class="[src.color, src.textColor, ingestingSource === src.key ? 'ring-2 ring-offset-1 ring-stone-400/40' : '']"
        :disabled="!!ingestingSource"
        @click="emit('ingestSource', src.key)"
      >
        <component :is="src.icon" class="h-3.5 w-3.5 shrink-0" />
        <span>{{ src.label }}</span>
        <span v-if="ingestingSource === src.key" class="inline-block h-3 w-3 rounded-full border-2 border-stone-300 border-t-stone-600 animate-spin ml-0.5" />
      </button>
    </div>
  </div>
</template>
