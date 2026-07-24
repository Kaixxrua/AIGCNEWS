<script setup lang="ts">
const props = defineProps<{
  reportContent: string
  isGenerating: boolean
  currentTypeLabel?: string
  autoScroll: boolean
  renderMarkdown: (content: string) => string
}>()

const emit = defineEmits<{
  resumeAutoScroll: []
}>()
</script>

<template>
  <!-- 空状态 -->
  <div v-if="!reportContent && !isGenerating" class="flex h-full flex-col items-center justify-center gap-2 text-stone-400 p-4">
    <div class="flex h-12 w-12 items-center justify-center rounded-2xl bg-stone-100">
      <svg class="h-6 w-6 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
    </div>
    <p class="text-sm font-medium text-stone-500 font-serif">选择类型查看简报</p>
    <p class="text-xs text-center max-w-sm text-stone-400">综合 · 学术 · 工程 · 行业 · 产品 · 社区 | 日报 / 周报 / 月报</p>
  </div>

  <!-- 生成中骨架 -->
  <div v-if="isGenerating && !reportContent" class="p-5">
    <div class="flex items-center gap-2 text-sm text-stone-500 mb-3">
      <span class="status-dot bg-cyan-500 animate-[pulseDot_2s_ease-in-out_infinite]" />
      正在生成「{{ currentTypeLabel }}」…
    </div>
    <div class="space-y-2.5 animate-pulse">
      <div class="h-5 w-48 rounded-lg bg-stone-100" />
      <div class="h-3.5 w-full rounded bg-stone-50" />
      <div class="h-3.5 w-5/6 rounded bg-stone-50" />
      <div class="h-3.5 w-4/6 rounded bg-stone-50" />
      <div class="h-5 w-36 rounded-lg bg-stone-100 mt-3" />
      <div class="h-3.5 w-full rounded bg-stone-50" />
      <div class="h-3.5 w-3/4 rounded bg-stone-50" />
    </div>
  </div>

  <!-- 报告正文 -->
  <div v-if="reportContent" class="p-5">
    <article class="prose-content prose-report max-w-none" v-html="renderMarkdown(reportContent)" />
    <span v-if="isGenerating" class="inline-block h-4 w-0.5 animate-pulse bg-cyan-500 align-middle ml-0.5" />
  </div>

  <!-- 回到底部按钮 -->
  <button
    v-if="isGenerating && !autoScroll"
    class="sticky bottom-4 ml-auto mr-4 btn-primary text-xs"
    @click="emit('resumeAutoScroll')"
  >
    <svg class="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
    回到底部
  </button>
</template>
