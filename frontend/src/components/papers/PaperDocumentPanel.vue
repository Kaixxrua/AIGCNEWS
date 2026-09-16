<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { PaperReaderPaper } from '@/composables/usePaperReaderController'

const { t } = useI18n()
defineProps<{
  paper: PaperReaderPaper | null
  paperLoading: boolean
  paperError: string
  renderMarkdown: (text: string) => string
}>()
</script>

<template>
  <section class="paper-document-panel flex-1 min-w-0 min-h-0 flex flex-col overflow-hidden" :aria-busy="paperLoading">
    <header class="shrink-0 border-b border-stone-200 px-5 py-3">
      <div v-if="paperLoading" class="h-4 w-48 max-w-full animate-pulse rounded bg-stone-200" />
      <template v-else-if="paper">
        <h1 class="text-sm font-semibold leading-snug font-serif">{{ paper.title }}</h1>
        <div class="mt-2 flex flex-wrap items-center gap-3 text-xs text-stone-500">
          <time v-if="paper.published_date">{{ paper.published_date.slice(0, 10) }}</time>
          <a v-if="paper.url" :href="paper.url" target="_blank" rel="noopener noreferrer" class="underline underline-offset-2">
            {{ t('paper.originalLink') }}
          </a>
        </div>
      </template>
      <p v-else role="alert" class="text-sm text-red-600">{{ paperError || t('paper.loadFailed') }}</p>
    </header>
    <div class="min-h-0 flex-1 overflow-y-auto px-5 py-6">
      <div v-if="paperLoading" class="space-y-3" aria-hidden="true">
        <div v-for="line in 5" :key="line" class="h-4 animate-pulse rounded bg-stone-200" />
      </div>
      <article v-else-if="paper" class="mx-auto max-w-3xl">
        <h2 class="mb-4 text-sm font-semibold">{{ t('paper.summary') }}</h2>
        <div v-if="paper.summary" class="paper-summary prose prose-sm max-w-none break-words" v-html="renderMarkdown(paper.summary)" />
        <p v-else class="text-sm leading-7 text-stone-500">{{ t('paper.summaryUnavailable') }}</p>
      </article>
    </div>
  </section>
</template>

<style scoped>
.paper-document-panel { color: var(--ink); background: var(--paper); }
.paper-document-panel header { border-color: var(--rule); }
.paper-summary { color: inherit; font-size: 0.9375rem; line-height: 1.8; overflow-wrap: anywhere; }
.paper-summary :deep(p), .paper-summary :deep(ul), .paper-summary :deep(ol), .paper-summary :deep(blockquote) { margin: 0 0 1rem; }
.paper-summary :deep(h1), .paper-summary :deep(h2), .paper-summary :deep(h3) { margin: 1.25rem 0 0.5rem; font-size: 1rem; font-weight: 600; line-height: 1.5; }
.paper-summary :deep(ul) { padding-left: 1.5rem; list-style: disc; }
.paper-summary :deep(ol) { padding-left: 1.5rem; list-style: decimal; }
.paper-summary :deep(li + li) { margin-top: 0.25rem; }
.paper-summary :deep(a) { text-decoration: underline; text-underline-offset: 2px; }
.paper-summary :deep(img) { max-width: 100%; height: auto; }
.paper-summary :deep(pre), .paper-summary :deep(table) { max-width: 100%; overflow-x: auto; }
.paper-document-panel :deep(a:focus-visible) { outline: 2px solid var(--ink); outline-offset: 3px; }
</style>
