<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { PaperReaderPaper } from '@/composables/usePaperReaderController'
import { paperBoardRank, paperUpvotes, parsePaperAuthors, splitAuthors } from '@/features/papers/paperHead'
import { paperAbstractMarkup, paperPlainText } from '@/features/papers/paperLatex'

const { t } = useI18n()
const props = defineProps<{
  paper: PaperReaderPaper | null
  paperLoading: boolean
  paperError: string
  renderMarkdown: (text: string) => string
  /** 桌面版头：作者、日期、arXiv 编号、HF 点赞、榜单名次和原文链接排在标题下的一行里。 */
  detailed?: boolean
}>()

const authors = computed(() => splitAuthors(parsePaperAuthors(props.paper?.authors)))
const authorCount = computed(() => authors.value.visible.length + authors.value.hidden.length)
const authorsOpen = ref(false)
const upvotes = computed(() => (props.paper ? paperUpvotes(props.paper) : null))
const boardRank = computed(() => (props.paper ? paperBoardRank(props.paper) : null))
// 作者照 LaTeX 写的标题、摘要（\emph{…}、2\%、---）：标题只留文字，摘要换成粗体、斜体这些排版再渲染。
const title = computed(() => paperPlainText(props.paper?.title))
const summaryHtml = computed(() => (props.paper?.summary ? props.renderMarkdown(paperAbstractMarkup(props.paper.summary)) : ''))

const panel = ref<HTMLElement | null>(null)
const body = ref<HTMLElement | null>(null)
// 桌面上从「同一天的论文」换到另一篇：作者重新收起，回到版头。
watch(() => props.paper?.id, () => {
  authorsOpen.value = false
  if (!props.detailed) return
  if (panel.value) panel.value.scrollTop = 0
  if (body.value) body.value.scrollTop = 0
})
</script>

<template>
  <section ref="panel" class="paper-document-panel flex-1 min-w-0 min-h-0 flex flex-col overflow-hidden" :class="{ 'paper-document-panel--detailed': detailed }" :aria-busy="paperLoading">
    <header class="shrink-0 border-b border-stone-200 px-5 py-3">
      <div v-if="paperLoading" class="h-4 w-48 max-w-full animate-pulse rounded bg-stone-200" />
      <template v-else-if="paper">
        <h1 class="text-sm font-semibold leading-snug font-serif">{{ title }}</h1>
        <div class="mt-2 flex flex-wrap items-center gap-3 text-xs text-stone-500">
          <template v-if="detailed">
            <p v-if="authorCount" class="paper-authors">
              <span class="sr-only">{{ t('paper.head.authors') }}</span>
              {{ authors.visible.join(', ') }}<span v-if="authorsOpen" class="paper-authors-rest">, {{ authors.hidden.join(', ') }}</span>
              <button
                v-if="authors.hidden.length"
                type="button"
                class="paper-authors-toggle"
                :aria-expanded="authorsOpen"
                @click="authorsOpen = !authorsOpen"
              >{{ authorsOpen ? t('paper.head.authorsLess') : t('paper.head.authorsMore', { total: authorCount, more: authors.hidden.length }) }}</button>
            </p>
            <!-- 日期和几项事实连成一组整体换行，分隔点不会落到行首；只留原文链接一张标签。 -->
            <span v-if="paper.published_date || paper.arxiv_id || upvotes || boardRank" class="paper-facts">
              <time v-if="paper.published_date" class="paper-fact" :datetime="paper.published_date.slice(0, 10)">{{ paper.published_date.slice(0, 10) }}</time>
              <span v-if="paper.arxiv_id" class="paper-fact">{{ t('paper.head.arxiv', { id: paper.arxiv_id }) }}</span>
              <span v-if="upvotes" class="paper-fact">{{ t('paper.head.upvotes', { count: upvotes }) }}</span>
              <span v-if="boardRank" class="paper-fact">{{ t(`paper.head.board.${boardRank.board}`, { rank: boardRank.rank }) }}</span>
            </span>
          </template>
          <time v-if="paper.published_date && !detailed">{{ paper.published_date.slice(0, 10) }}</time>
          <a v-if="paper.url" :href="paper.url" target="_blank" rel="noopener noreferrer" class="underline underline-offset-2">
            {{ t('paper.originalLink') }}
          </a>
        </div>
      </template>
      <p v-else role="alert" class="text-sm text-red-600">{{ paperError || t('paper.loadFailed') }}</p>
    </header>
    <div ref="body" class="min-h-0 flex-1 overflow-y-auto px-5 py-6">
      <div v-if="paperLoading" class="space-y-3" aria-hidden="true">
        <div v-for="line in 5" :key="line" class="h-4 animate-pulse rounded bg-stone-200" />
      </div>
      <article v-else-if="paper" class="mx-auto max-w-3xl">
        <h2 class="mb-4 text-sm font-semibold">{{ t('paper.summary') }}</h2>
        <div v-if="paper.summary" class="paper-summary prose prose-sm max-w-none break-words" v-html="summaryHtml" />
        <p v-else class="text-sm leading-7 text-stone-500">{{ t('paper.summaryUnavailable') }}</p>
      </article>
      <slot name="after" />
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
