<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowUpRight, Star } from 'lucide-vue-next'
import type { AppLocale } from '@/i18n'
import { formatLocaleDate, formatLocaleNumber } from '@/i18n/formatters'
import type { PeekContent, PeekCurveState } from '@/composables/useProjectPeek'
import type { GitHubProjectItem } from '@/services/projects/projectApi'
import { formatProjectCount, formatProjectLastPush, projectName } from '@/features/projects/projectPresentation'
import { formatSparkDate, formatStarDelta } from '@/features/projects/projectChart'
import {
  PEEK_CURVE_DAYS,
  PEEK_CURVE_H,
  PEEK_CURVE_W,
  peekCurve,
  shortSha,
  type PeekPlacement,
} from '@/features/projects/projectPeek'

/**
 * 榜单悬停速览的卡片：README 开头几段（读下去到 GitHub）、默认分支最近一次提交、近 30 天的星标曲线。
 * 榜单够宽时分两栏，左边 README，右边提交压着曲线（.project-peek__side），卡片矮到大多数行旁边都放得下。
 * 摆在行的下面或上面（上面时底边贴着行、往上长），高不过那一边看得见的地方，再多就在卡片里滚。
 * 还没取到的部分先摆骨架；读不到 GitHub 时最近一次提交退回库里记的最近推送。
 * 点卡片里去 GitHub 的链接时发 visit，列表据此把这一行记为看过。
 */
const props = defineProps<{
  repo: GitHubProjectItem
  /** 速览查的仓库（owner/repo） */
  repoId: string
  content: PeekContent
  curve: PeekCurveState
  placement: PeekPlacement
}>()

const emit = defineEmits<{
  visit: [repo: GitHubProjectItem]
}>()

const { locale, t } = useI18n()
const appLocale = computed(() => locale.value as AppLocale)

const name = computed(() => projectName(props.repo) || props.repoId)
const nameParts = computed(() => {
  const slash = name.value.indexOf('/')
  return slash > 0 ? { owner: name.value.slice(0, slash + 1), repo: name.value.slice(slash + 1) } : { owner: '', repo: name.value }
})
const starsText = computed(() => formatProjectCount(props.repo.stars, appLocale.value))
const starsTitle = computed(() => t('projectChart.starsTitle', { count: formatLocaleNumber(Number(props.repo.stars ?? 0), appLocale.value) }))

const loading = computed(() => props.content.status === 'loading')
const peek = computed(() => (props.content.status === 'ready' ? props.content.peek : null))
const readmeUrl = computed(() => `https://github.com/${props.repoId}#readme`)
const readmeNote = computed(() => {
  if (props.content.status === 'error') return t('projectPeek.failed')
  if (peek.value?.status !== 'ok') return t('projectPeek.unavailable')
  return t(peek.value.has_readme ? 'projectPeek.noProse' : 'projectPeek.noReadme')
})

const commit = computed(() => peek.value?.commit ?? null)
const commitSha = computed(() => (commit.value ? shortSha(commit.value.sha) : ''))
const commitAgo = computed(() => (commit.value?.committed_at ? formatProjectLastPush(commit.value.committed_at, appLocale.value) : ''))
const commitTime = computed(() => (commit.value?.committed_at
  ? formatLocaleDate(commit.value.committed_at, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }, appLocale.value)
  : ''))
// 读到了 GitHub 却没有提交是空仓库；读不到 GitHub 时退回库里记的最近推送，连它也没有就不摆这一节
const commitNote = computed(() => {
  if (peek.value?.status === 'ok') return t('projectPeek.noCommit')
  const pushed = props.repo.pushed_at ? formatProjectLastPush(props.repo.pushed_at, appLocale.value) : ''
  return pushed ? t('projectPeek.lastPush', { time: pushed }) : ''
})

const days = computed(() => (props.curve.status === 'ready' ? props.curve.days : PEEK_CURVE_DAYS))
const plot = computed(() => {
  if (props.curve.status !== 'ready') return null
  const curve = peekCurve(props.curve.points, props.curve.metricDate, props.curve.days)
  if (!curve.first || !curve.last) return null
  const delta = formatStarDelta(curve.delta, appLocale.value)
  const startDate = formatSparkDate(curve.first.date, appLocale.value)
  const endDate = formatSparkDate(curve.last.date, appLocale.value)
  return {
    ...curve,
    startDate,
    endDate,
    // 横轴两端标窗口的头尾：收录晚、缺了头几天的仓库，曲线从框中间起
    axis: [formatSparkDate(curve.from, appLocale.value), formatSparkDate(curve.to, appLocale.value)],
    deltaText: delta,
    trend: curve.delta > 0 ? 'up' : curve.delta < 0 ? 'down' : 'flat',
    label: t('projectPeek.curveLabel', {
      days: days.value,
      start: startDate,
      from: formatLocaleNumber(curve.first.stars, appLocale.value),
      end: endDate,
      to: formatLocaleNumber(curve.last.stars, appLocale.value),
      delta,
    }),
  }
})

const style = computed(() => ({ top: `${props.placement.top}px`, '--peek-max': `${props.placement.maxHeight}px` }))
</script>

<template>
  <aside
    class="project-peek"
    :class="{ 'project-peek--above': placement.above }"
    :style="style"
    :aria-label="t('projectPeek.label', { name })"
    data-project-peek
  >
    <div class="project-peek__scroll">
      <header class="project-peek__head">
        <span class="project-peek__name"><span class="project-peek__owner">{{ nameParts.owner }}</span><wbr />{{ nameParts.repo }}</span>
        <span class="project-peek__stars" :title="starsTitle"><Star :size="12" :stroke-width="2" aria-hidden="true" />{{ starsText }}</span>
      </header>

      <section class="project-peek__part project-peek__part--readme" :aria-busy="loading">
        <h3 class="project-peek__label">{{ t('projectPeek.readme') }}</h3>
        <template v-if="loading">
          <span v-for="line in 4" :key="line" class="project-peek__skeleton" />
        </template>
        <template v-else-if="peek && peek.readme.length">
          <p v-for="(paragraph, index) in peek.readme" :key="index" class="project-peek__readme">{{ paragraph }}</p>
          <a
            class="project-peek__link"
            :href="readmeUrl"
            target="_blank"
            rel="noopener noreferrer"
            @click="emit('visit', repo)"
            @auxclick.middle="emit('visit', repo)"
          >{{ t(peek.readme_more ? 'projectPeek.readMore' : 'projectPeek.readOn') }}<ArrowUpRight :size="13" :stroke-width="2.2" aria-hidden="true" /></a>
        </template>
        <p v-else class="project-peek__note">
          {{ readmeNote }}
          <a
            v-if="peek && peek.has_readme"
            class="project-peek__link"
            :href="readmeUrl"
            target="_blank"
            rel="noopener noreferrer"
            @click="emit('visit', repo)"
            @auxclick.middle="emit('visit', repo)"
          >{{ t('projectPeek.readOn') }}<ArrowUpRight :size="13" :stroke-width="2.2" aria-hidden="true" /></a>
        </p>
      </section>

      <div class="project-peek__side">
        <section v-if="loading || commit || commitNote" class="project-peek__part" :aria-busy="loading">
          <h3 class="project-peek__label">{{ t('projectPeek.lastCommit') }}</h3>
          <template v-if="loading">
            <span class="project-peek__skeleton" />
            <span class="project-peek__skeleton is-short" />
          </template>
          <template v-else-if="commit">
            <a
              class="project-peek__commit"
              :href="commit.url"
              target="_blank"
              rel="noopener noreferrer"
              @click="emit('visit', repo)"
              @auxclick.middle="emit('visit', repo)"
            >{{ commit.message || commitSha }}</a>
            <p class="project-peek__facts">
              <code class="project-peek__sha">{{ commitSha }}</code>
              <span v-if="commit.author">{{ commit.author }}</span>
              <time v-if="commitAgo" :datetime="commit.committed_at" :title="commitTime">{{ commitAgo }}</time>
            </p>
          </template>
          <p v-else class="project-peek__note">{{ commitNote }}</p>
        </section>

        <section class="project-peek__part" :aria-busy="curve.status === 'loading'">
          <h3 class="project-peek__label">
            {{ t('projectPeek.stars', { days }) }}
            <span v-if="plot" class="project-peek__delta" :class="`project-peek__delta--${plot.trend}`">{{ plot.deltaText }}</span>
          </h3>
          <span v-if="curve.status === 'loading'" class="project-peek__skeleton project-peek__skeleton--plot" />
          <p v-else-if="curve.status === 'error'" class="project-peek__note">{{ t('projectPeek.starsFailed') }}</p>
          <p v-else-if="!plot" class="project-peek__note">{{ t('projectPeek.starsPending', { days }) }}</p>
          <div v-else class="project-peek__curve" role="img" :aria-label="plot.label">
            <div class="project-peek__plot">
              <svg :viewBox="`0 0 ${PEEK_CURVE_W} ${PEEK_CURVE_H}`" preserveAspectRatio="none" aria-hidden="true">
                <path class="project-peek__area" :d="plot.area" />
                <path v-for="(d, index) in plot.bridges" :key="`bridge-${index}`" class="project-peek__bridge" :d="d" />
                <path v-for="(d, index) in plot.lines" :key="`line-${index}`" class="project-peek__line" :d="d" />
              </svg>
              <!-- 拉伸的 SVG 里画圆会变扁，最后一天的点用 HTML 摆上去 -->
              <span v-if="plot.end" class="project-peek__dot" :style="{ left: `${plot.end.x}%`, top: `${plot.end.y}%` }" aria-hidden="true" />
            </div>
            <div class="project-peek__axis" aria-hidden="true">
              <span v-for="(date, index) in plot.axis" :key="index">{{ date }}</span>
            </div>
          </div>
        </section>
      </div>
    </div>
  </aside>
</template>
