<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { getSearchSourceLabelKey, getSearchSummaryPreview } from '@/features/search/globalSearchModel'
import type { PaperItem } from '@/services/papers/paperApi'

const { t } = useI18n()
const sourceLabel = (source?: string) => {
  const key = getSearchSourceLabelKey(source)
  return key ? t(key) : (source ?? '?')
}

const props = defineProps<{
  query: string
  results: PaperItem[]
}>()

const emit = defineEmits<{
  select: [item: PaperItem]
}>()
</script>

<template>
  <div
    class="absolute left-0 right-0 top-full mt-1.5 max-h-72 overflow-y-auto rounded-2xl py-1 shadow-xl"
    style="background: rgba(255,255,255,0.97); border: 1px solid rgba(168,162,158,0.20); backdrop-filter: blur(16px);"
  >
    <!-- 列表头部 -->
    <p class="px-3 py-1.5 text-2xs font-semibold uppercase tracking-widest text-stone-400">
      {{ props.query.trim() ? t('search.resultCount', { count: props.results.length }) : t('search.trending') }}
    </p>

    <button
      v-for="item in props.results"
      :key="item.id"
      class="search-result flex w-full items-start gap-2.5 px-3 py-2 text-left text-xs transition group"
      @mousedown.prevent="emit('select', item)"
    >
      <!-- 来源标签 -->
      <span
        class="mt-0.5 shrink-0 rounded-md border px-1.5 py-0.5 text-2xs font-medium text-stone-500 border-stone-200 bg-white"
      >{{ sourceLabel(item.source) }}</span>

      <!-- 标题 + 摘要 -->
      <span class="min-w-0 flex-1">
        <span class="block truncate font-medium text-stone-700 group-hover:text-stone-900">{{ item.title }}</span>
        <span v-if="item.summary" class="block mt-0.5 truncate text-stone-400">{{ getSearchSummaryPreview(item.summary) }}</span>
      </span>

      <!-- 论文可进入阅读的箭头提示 -->
      <svg v-if="item.source === 'arxiv'" class="mt-0.5 h-3.5 w-3.5 shrink-0 text-stone-300 group-hover:text-stone-500 transition" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
      </svg>
    </button>
  </div>
</template>

<style scoped>
.search-result:hover,
.search-result:focus-visible {
  color: var(--ink);
  background: var(--acid-soft);
}
</style>
