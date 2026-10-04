<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowUpRight, ChevronDown, ChevronUp, X } from 'lucide-vue-next'
import type { PeekPaper, PeekTarget } from '@/composables/useReportPeek'
import { paperBoardRank, paperDay, paperUpvotes, parsePaperAuthors, splitAuthors } from '@/features/papers/paperHead'
import { paperAbstractMarkup, paperPlainText } from '@/features/papers/paperLatex'
import type { PaperLink } from '@/features/report/reportPaperLinks'
import { vIndicator } from '@/motion/indicator'
import { vSwap } from '@/motion/swap'

/**
 * 宽屏简报右侧的论文详情栏：这条讲的论文的标题、作者、日期与榜单、摘要，和站内阅读、论文页、arXiv 三个去处。
 * 一条讲到几篇时顶上列出来，点哪篇看哪篇；上一条、下一条（或 k、j）接着看别的条目，Esc 或 × 收起。
 * 换篇时新内容从换去的方向浮进来，摘要滚回开头。
 */
const props = defineProps<{
  target: PeekTarget
  state: PeekPaper
  /** 这一条讲到的论文（多于一篇时列出来切换）。 */
  papers: PaperLink[]
  /** 这一条在讲到论文的条目里排第几（从 0 起）、一共几条。 */
  index: number
  total: number
  direction: 1 | -1 | 0
  withinItem: boolean
  renderMarkdown: (text: string) => string
}>()

const emit = defineEmits<{
  close: []
  step: [direction: 1 | -1]
  pick: [arxivId: string]
  retry: []
}>()

const { t } = useI18n()

const link = computed(() => props.papers.find((paper) => paper.arxivId === props.target.arxivId) ?? null)
const paper = computed(() => (props.state.status === 'ready' ? props.state.paper : null))
// 标题、摘要里的 LaTeX 写法（\emph{…}、2\%、---）与论文页一样换掉。
const heading = computed(() => paperPlainText(paper.value?.title) || link.value?.label || `arXiv:${props.target.arxivId}`)
const paperPage = computed(() => paper.value?.url || link.value?.href || `https://hf-mirror.com/papers/${props.target.arxivId}`)
const arxivPage = computed(() => `https://arxiv.org/abs/${props.target.arxivId}`)

const authors = computed(() => splitAuthors(parsePaperAuthors(paper.value?.authors)))
const authorCount = computed(() => authors.value.visible.length + authors.value.hidden.length)
const authorsOpen = ref(false)
const day = computed(() => paperDay(paper.value?.published_date))
const upvotes = computed(() => (paper.value ? paperUpvotes(paper.value) : null))
const boardRank = computed(() => (paper.value ? paperBoardRank(paper.value) : null))
const abstract = computed(() => (paper.value?.summary ? props.renderMarkdown(paperAbstractMarkup(paper.value.summary)) : ''))

// 取到之前不播，取到了从换去的方向浮进来：往后的条目从下方、往前的从上方，同一条里换篇从左右。
const swap = computed(() => ({
  key: props.state.status === 'loading' ? null : props.target.arxivId,
  x: props.withinItem ? props.direction * 18 : 0,
  y: props.withinItem ? 0 : props.direction * 14,
}))

const scroller = ref<HTMLElement | null>(null)
watch(() => props.target.arxivId, () => {
  authorsOpen.value = false
  if (scroller.value) scroller.value.scrollTop = 0
})
</script>

<template>
  <aside class="report-peek" :aria-label="t('report.peek.label')">
    <header class="report-peek__head">
      <span class="report-peek__kicker">{{ t('report.peek.kicker') }}</span>
      <span v-if="index >= 0" class="report-peek__count" :aria-label="t('report.peek.position', { index: index + 1, total })">{{ index + 1 }}<i aria-hidden="true">/</i>{{ total }}</span>
      <div class="report-peek__nav">
        <button type="button" class="report-peek__btn" :disabled="index <= 0" :aria-label="t('report.peek.prev')" :title="t('report.peek.prev')" aria-keyshortcuts="k" @click="emit('step', -1)">
          <ChevronUp aria-hidden="true" />
        </button>
        <button type="button" class="report-peek__btn" :disabled="index < 0 || index >= total - 1" :aria-label="t('report.peek.next')" :title="t('report.peek.next')" aria-keyshortcuts="j" @click="emit('step', 1)">
          <ChevronDown aria-hidden="true" />
        </button>
        <button type="button" class="report-peek__btn report-peek__close" :aria-label="t('report.peek.close')" :title="t('report.peek.close')" aria-keyshortcuts="Escape" @click="emit('close')">
          <X aria-hidden="true" />
        </button>
      </div>
    </header>

    <div v-if="papers.length > 1" v-indicator="{ active: '[aria-pressed=true]' }" class="report-peek__papers" role="group" :aria-label="t('report.peek.papers')">
      <button
        v-for="(item, i) in papers"
        :key="item.arxivId"
        type="button"
        class="report-peek__paper"
        :aria-pressed="item.arxivId === target.arxivId"
        @click="emit('pick', item.arxivId)"
      >
        {{ item.label || `${i + 1}` }}
      </button>
    </div>

    <div ref="scroller" class="report-peek__scroll">
      <article v-swap="swap" class="report-peek__body" :aria-busy="state.status === 'loading'">
        <template v-if="state.status === 'loading'">
          <div class="report-peek__skeleton is-title" />
          <div class="report-peek__skeleton is-short" />
          <div v-for="line in 7" :key="line" class="report-peek__skeleton" />
        </template>
        <template v-else>
          <h2 class="report-peek__title" aria-live="polite">{{ heading }}</h2>
          <template v-if="paper">
            <p v-if="authorCount" class="report-peek__authors">
              <span class="sr-only">{{ t('paper.head.authors') }}</span>
              {{ authors.visible.join(', ') }}<span v-if="authorsOpen">, {{ authors.hidden.join(', ') }}</span>
              <button
                v-if="authors.hidden.length"
                type="button"
                class="report-peek__more"
                :aria-expanded="authorsOpen"
                @click="authorsOpen = !authorsOpen"
              >{{ authorsOpen ? t('paper.head.authorsLess') : t('paper.head.authorsMore', { total: authorCount, more: authors.hidden.length }) }}</button>
            </p>
            <p class="report-peek__facts">
              <time v-if="day" :datetime="day">{{ day }}</time>
              <span>{{ t('paper.head.arxiv', { id: target.arxivId }) }}</span>
              <span v-if="upvotes">{{ t('paper.head.upvotes', { count: upvotes }) }}</span>
              <span v-if="boardRank">{{ t(`paper.head.board.${boardRank.board}`, { rank: boardRank.rank }) }}</span>
            </p>
          </template>
          <p v-else-if="state.status === 'missing'" class="report-peek__note">{{ t('report.peek.missing') }}</p>
          <p v-else role="alert" class="report-peek__note">
            {{ t('report.peek.failed') }}
            <button type="button" class="report-peek__more" @click="emit('retry')">{{ t('report.peek.retry') }}</button>
          </p>

          <div class="report-peek__actions">
            <RouterLink v-if="paper" class="report-peek__action is-primary" :to="{ name: 'paper-read', params: { id: paper.id } }">{{ t('report.peek.read') }}</RouterLink>
            <a class="report-peek__action" :href="paperPage" target="_blank" rel="noopener noreferrer">{{ t('report.peek.paperPage') }}<ArrowUpRight aria-hidden="true" /></a>
            <a class="report-peek__action" :href="arxivPage" target="_blank" rel="noopener noreferrer">{{ t('report.peek.arxiv') }}<ArrowUpRight aria-hidden="true" /></a>
          </div>

          <template v-if="paper">
            <h3 class="report-peek__label">{{ t('paper.summary') }}</h3>
            <div v-if="abstract" class="report-peek__abstract" v-html="abstract" />
            <p v-else class="report-peek__note">{{ t('paper.summaryUnavailable') }}</p>
          </template>
        </template>
      </article>
    </div>

    <p class="report-peek__keys" aria-hidden="true">
      <span><kbd>j</kbd><kbd>k</kbd>{{ t('report.peek.keysMove') }}</span>
      <span><kbd>Esc</kbd>{{ t('report.peek.keysClose') }}</span>
    </p>
  </aside>
</template>
