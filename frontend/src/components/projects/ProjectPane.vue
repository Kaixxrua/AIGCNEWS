<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowUpRight, ChevronDown, ChevronUp, Sparkles, Star, X } from 'lucide-vue-next'
import ProjectLogo from './ProjectLogo.vue'
import ProjectPeekCurve from './ProjectPeekCurve.vue'
import ProjectPeekParts from './ProjectPeekParts.vue'
import type { AppLocale } from '@/i18n'
import { formatLocaleDate, formatLocaleNumber } from '@/i18n/formatters'
import type { PeekContent, PeekCurveState } from '@/composables/useProjectPeek'
import type { PaneTarget } from '@/composables/useProjectPane'
import type { GitHubProjectItem } from '@/services/projects/projectApi'
import {
  displayHotScore,
  favoriteButtonLabelKey,
  formatProjectCount,
  formatProjectLastPush,
  projectDailyGrowth,
  projectDescription,
  projectDisplayTags,
  projectGrowthTitle,
  projectHeatAvailable,
  projectHotScore,
  projectLastPushTitle,
  projectName,
  projectRollingGrowth,
  projectUrl,
  recommendButtonLabelKey,
  type ProjectChip,
} from '@/features/projects/projectPresentation'
import { formatStarDelta } from '@/features/projects/projectChart'
import { vSwap } from '@/motion/swap'

/**
 * 宽屏项目库右侧的详情栏：项目名、完整的描述、一组数字（星标、24 小时、热度、fork、未关 issue、语言、创建与最近推送）
 * 和紧跟着的近 30 天星标曲线、全部标签，去 GitHub、收藏（管理员还有推荐）几个动作，下面是速览的 README 开头和最近一次提交
 * （没取到的可以重试）。曲线提到数字下面，矮一点的屏幕不用往下滚也看得到走势。
 * 上一个、下一个（或 k、j）接着看别的项目，走到这一页的头尾时由列表翻页；Esc 或 × 收起。
 * 换项目时新内容从换去的方向浮进来，滚回开头。点里面去 GitHub 的链接时发 visit，列表据此把这一行记为看过。
 */
const props = defineProps<{
  repo: GitHubProjectItem
  target: PaneTarget
  content: PeekContent
  curve: PeekCurveState
  /** 在整个结果里排第几（从 1 起）、一共几个；这一行不在当前这一页里时为 null */
  position: number | null
  total: number
  direction: 1 | -1 | 0
  canFavorite: boolean
  canRecommend: boolean
  isLoggedIn: boolean
  favoriteBusy: boolean
  favoriteActionsBusy: boolean
  recommendBusy: boolean
  recommendActionsBusy: boolean
}>()

const emit = defineEmits<{
  close: []
  step: [direction: 1 | -1]
  retry: []
  visit: [repo: GitHubProjectItem]
  favorite: [repo: GitHubProjectItem]
  recommend: [repo: GitHubProjectItem]
  chipClick: [chip: ProjectChip]
}>()

const { locale, t } = useI18n()
const appLocale = computed(() => locale.value as AppLocale)

const name = computed(() => projectName(props.repo) || props.target.repoId)
const nameParts = computed(() => {
  const slash = name.value.indexOf('/')
  return slash > 0 ? { owner: name.value.slice(0, slash + 1), repo: name.value.slice(slash + 1) } : { owner: '', repo: name.value }
})
const url = computed(() => projectUrl(props.repo) || `https://github.com/${props.target.repoId}`)
const notFound = computed(() => props.repo.availability_status === 'not_found')
const description = computed(() => projectDescription(props.repo, appLocale.value, t('projects.fallbackProject')))
const chips = computed(() => projectDisplayTags(props.repo, false, appLocale.value, {
  project: t('projects.genericProjectTag'),
  website: t('projects.genericWebsiteTag'),
}))

const count = (value: GitHubProjectItem['stars']) => (value == null || value === '' || !Number.isFinite(Number(value)) ? null : Number(value))
const dateOf = (value: string | null | undefined) => (value ? formatLocaleDate(value, { year: 'numeric', month: 'short', day: 'numeric' }, appLocale.value) : '')

// 与榜单同一口径：24 小时有滚动窗口用它，否则退回当日增量；热度没算出来写破折号
const facts = computed(() => {
  const repo = props.repo
  const gain = projectRollingGrowth(repo) ?? projectDailyGrowth(repo)
  const heat = projectHeatAvailable(repo) ? displayHotScore(projectHotScore(repo)) : null
  const forks = count(repo.forks)
  const issues = count(repo.open_issues)
  const pushed = repo.pushed_at ? formatProjectLastPush(repo.pushed_at, appLocale.value) : ''
  const created = dateOf(repo.created_at)
  return [
    { key: 'stars', label: t('projectChart.stars'), value: formatProjectCount(repo.stars, appLocale.value), title: t('projectChart.starsTitle', { count: formatLocaleNumber(Number(repo.stars ?? 0), appLocale.value) }) },
    { key: 'gain', label: t('projectChart.gain'), value: formatStarDelta(gain, appLocale.value), title: projectGrowthTitle(repo, t, appLocale.value), flat: gain === 0 },
    { key: 'heat', label: t('projectChart.heat'), value: heat === null ? '—' : heat.toFixed(1), title: t(projectHeatAvailable(repo) ? 'projects.hotScoreTitle' : 'projects.heatPending'), flat: heat === null || heat < 0.05 },
    forks === null ? null : { key: 'forks', label: t('projectPane.forks'), value: formatProjectCount(forks, appLocale.value), title: formatLocaleNumber(forks, appLocale.value) },
    issues === null ? null : { key: 'issues', label: t('projectPane.issues'), value: formatProjectCount(issues, appLocale.value), title: formatLocaleNumber(issues, appLocale.value) },
    repo.language ? { key: 'language', label: t('projectPane.language'), value: repo.language, title: '' } : null,
    created ? { key: 'created', label: t('projectPane.created'), value: created, title: '' } : null,
    pushed ? { key: 'pushed', label: t('projectPane.pushed'), value: pushed, title: projectLastPushTitle(repo, t, appLocale.value) } : null,
  ].filter((fact) => fact !== null)
})

const favoriteLabel = computed(() => t(favoriteButtonLabelKey(props.repo, props.favoriteBusy, props.isLoggedIn)))
const recommendLabel = computed(() => t(recommendButtonLabelKey(props.repo, props.recommendBusy)))

// 往后换的从下方浮进来，往前换的从上方；刚打开时原地淡入
const swap = computed(() => ({ key: props.target.key, x: 0, y: props.direction * 14 }))

const scroller = ref<HTMLElement | null>(null)
watch(() => props.target.key, () => {
  if (scroller.value) scroller.value.scrollTop = 0
})
</script>

<template>
  <aside class="project-pane" :aria-label="t('projectPane.label', { name })" data-project-pane>
    <div class="project-pane__box">
      <header class="project-pane__head">
        <span class="project-pane__kicker">{{ t('projectPane.kicker') }}</span>
        <span v-if="position !== null" class="project-pane__count" :aria-label="t('projectPane.position', { index: position, total })">{{ position }}<i aria-hidden="true">/</i>{{ total }}</span>
        <div class="project-pane__nav">
          <button type="button" class="project-pane__btn" :disabled="position === null || position <= 1" :aria-label="t('projectPane.prev')" :title="t('projectPane.prev')" aria-keyshortcuts="k" @click="emit('step', -1)">
            <ChevronUp aria-hidden="true" />
          </button>
          <button type="button" class="project-pane__btn" :disabled="position === null || position >= total" :aria-label="t('projectPane.next')" :title="t('projectPane.next')" aria-keyshortcuts="j" @click="emit('step', 1)">
            <ChevronDown aria-hidden="true" />
          </button>
          <button type="button" class="project-pane__btn project-pane__close" :aria-label="t('projectPane.close')" :title="t('projectPane.close')" aria-keyshortcuts="Escape" @click="emit('close')">
            <X aria-hidden="true" />
          </button>
        </div>
      </header>

      <div ref="scroller" class="project-pane__scroll">
        <article v-swap="swap" class="project-pane__body">
          <div class="project-pane__title">
            <ProjectLogo class="project-pane__logo" :logo="repo.image_url" :repository-url="url" :name="name" :unavailable="notFound" />
            <h2 class="project-pane__name" aria-live="polite">
              <a :href="url" target="_blank" rel="noopener noreferrer" :title="t('projects.openRepository')" @click="emit('visit', repo)" @auxclick.middle="emit('visit', repo)"><span class="project-pane__owner">{{ nameParts.owner }}</span><wbr />{{ nameParts.repo }}</a>
            </h2>
          </div>
          <p v-if="repo.is_recommended || notFound" class="project-pane__marks">
            <span v-if="repo.is_recommended" class="project-pane__pick"><span aria-hidden="true">✦</span>{{ t('projectChart.pick') }}</span>
            <span v-if="notFound" class="project-pane__gone">{{ t('projects.unavailable') }}</span>
          </p>
          <p class="project-pane__desc">{{ description }}</p>

          <dl class="project-pane__facts">
            <div v-for="fact in facts" :key="fact.key" class="project-pane__fact" :class="[`project-pane__fact--${fact.key}`, { 'is-flat': fact.flat }]">
              <dt>{{ fact.label }}</dt>
              <dd :title="fact.title || undefined">{{ fact.value }}</dd>
            </div>
          </dl>

          <ProjectPeekCurve class="project-pane__curve" :curve="curve" can-retry @retry="emit('retry')" />

          <div v-if="chips.length" class="project-pane__chips" :aria-label="t('projects.categoryTags')">
            <button v-for="chip in chips" :key="`${chip.type}:${chip.value}`" type="button" class="project-pane__chip" @click="emit('chipClick', chip)">{{ chip.label }}</button>
          </div>

          <div class="project-pane__actions" role="group" :aria-label="t('projects.cardActions')">
            <a class="project-pane__action is-primary" :href="url" target="_blank" rel="noopener noreferrer" @click="emit('visit', repo)" @auxclick.middle="emit('visit', repo)">
              {{ t('projectPane.openGitHub') }}<ArrowUpRight aria-hidden="true" />
            </a>
            <button
              type="button"
              class="project-pane__action project-pane__favorite"
              :class="{ 'is-on': repo.is_favorited }"
              :aria-pressed="Boolean(repo.is_favorited)"
              :disabled="favoriteActionsBusy || !canFavorite"
              aria-keyshortcuts="s"
              @click="emit('favorite', repo)"
            ><Star :fill="repo.is_favorited ? 'currentColor' : 'none'" aria-hidden="true" />{{ favoriteLabel }}</button>
            <button
              v-if="canRecommend"
              type="button"
              class="project-pane__action project-pane__recommend"
              :class="{ 'is-on': repo.is_recommended }"
              :aria-pressed="Boolean(repo.is_recommended)"
              :disabled="recommendActionsBusy"
              @click="emit('recommend', repo)"
            ><Sparkles aria-hidden="true" />{{ recommendLabel }}</button>
          </div>

          <div class="project-pane__peek">
            <ProjectPeekParts :repo="repo" :repo-id="target.repoId" :content="content" can-retry @visit="emit('visit', $event)" @retry="emit('retry')" />
          </div>
        </article>
      </div>

      <p class="project-pane__keys" aria-hidden="true">
        <span><kbd>j</kbd><kbd>k</kbd>{{ t('projectPane.keysMove') }}</span>
        <span><kbd>o</kbd>{{ t('projectPane.keysOpen') }}</span>
        <span><kbd>s</kbd>{{ t('projectPane.keysSave') }}</span>
        <span><kbd>Esc</kbd>{{ t('projectPane.keysClose') }}</span>
      </p>
    </div>
  </aside>
</template>
