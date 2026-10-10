<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Clock, ExternalLink, GitFork, Sparkles, Star } from 'lucide-vue-next'
import ProjectLogo from './ProjectLogo.vue'
import ProjectSparkline from './ProjectSparkline.vue'
import type { AppLocale } from '@/i18n'
import { formatLocaleNumber } from '@/i18n/formatters'
import type { GitHubProjectItem, GitHubProjectTrend } from '@/services/projects/projectApi'
import {
  displayHotScore,
  favoriteButtonLabelKey,
  formatProjectCount,
  formatProjectLastPush,
  projectDescription,
  projectDisplayTags,
  projectGrowthTitle,
  projectHeatAvailable,
  projectHotScore,
  projectLastPushTitle,
  projectName,
  projectGrowthValue,
  projectUrl,
  recommendButtonLabelKey,
  type ProjectChip,
} from '@/features/projects/projectPresentation'
import { CHART_ROW_TAGS, formatStarDelta, type ProjectRankMovement } from '@/features/projects/projectChart'

/**
 * 项目库紧凑版面（榜单）的一行：左边名次（今日热门再标比昨天升降），中间项目名、标签和完整的描述，
 * 右边一排对齐的数字（星标、24 小时新增、近两周火花线、热度）和操作。描述不截断，一行写不下就换行；
 * forks 和最近推送跟在描述末尾，不为它们多占一行。
 * 光标（is-cursor）、已读（is-read）和 data-list-key 由列表挂在根上；点项目名或外链图标时发 visit，列表据此记为看过。
 * 宽屏有详情栏时（opensPane）单击项目名或行里空白处发 open，在右侧看详情不跳页；按着修饰键、中键点项目名照常去 GitHub，
 * 点标签、按钮、链接或选中了文字时不算。
 */
const props = defineProps<{
  repo: GitHubProjectItem
  /** 名次；按更新、收录时间或名称排时不编号（null） */
  position: number | null
  /** 比昨天的升降；不是今日热门或行情还没到时为 null */
  movement: ProjectRankMovement | null
  /** 这一行的行情；还没到时火花线先空着 */
  trend?: GitHubProjectTrend
  metricDate: string
  days: number
  canFavorite: boolean
  canRecommend: boolean
  isLoggedIn: boolean
  favoriteBusy: boolean
  favoriteActionsBusy: boolean
  recommendBusy: boolean
  recommendActionsBusy: boolean
  /** 宽屏有详情栏：单击打开详情（open），不去 GitHub */
  opensPane?: boolean
}>()

const emit = defineEmits<{
  chipClick: [chip: ProjectChip]
  favorite: [repo: GitHubProjectItem]
  recommend: [repo: GitHubProjectItem]
  visit: [repo: GitHubProjectItem]
  open: [repo: GitHubProjectItem]
}>()

/** 全部标签是否展开；列表绑上它，键盘的 x 才能替这一行展开或收起。 */
const tagsOpen = defineModel<boolean>('tagsOpen', { default: false })

const { locale, t } = useI18n()
const appLocale = computed(() => locale.value as AppLocale)

const name = computed(() => projectName(props.repo))
// owner/repo：仓库名加粗，所有者淡一档，扫一眼先看到是什么项目。
const nameParts = computed(() => {
  const slash = name.value.indexOf('/')
  return slash > 0 ? { owner: name.value.slice(0, slash + 1), repo: name.value.slice(slash + 1) } : { owner: '', repo: name.value }
})
const url = computed(() => projectUrl(props.repo))
const notFound = computed(() => props.repo.availability_status === 'not_found')
const description = computed(() => projectDescription(props.repo, appLocale.value, t('projects.fallbackProject')))
const chips = computed(() => projectDisplayTags(props.repo, false, appLocale.value, {
  project: t('projects.genericProjectTag'),
  website: t('projects.genericWebsiteTag'),
}))
const visibleChips = computed(() => (tagsOpen.value ? chips.value : chips.value.slice(0, CHART_ROW_TAGS)))
// 最后一个标签和「+n」包在一起换行，「+n」不会单独掉到下一行。
const leadChips = computed(() => visibleChips.value.slice(0, -1))
const tailChip = computed(() => visibleChips.value[visibleChips.value.length - 1])

const starsText = computed(() => formatProjectCount(props.repo.stars, appLocale.value))
const starsTitle = computed(() => t('projectChart.starsTitle', { count: formatLocaleNumber(Number(props.repo.stars ?? 0), appLocale.value) }))
// 24 小时新增与卡片同一口径：有滚动 24h 用它，否则退回可用日增量；缺失时显示待更新；提示里写明是哪一种。
const gain = computed(() => projectGrowthValue(props.repo))
const gainText = computed(() => gain.value === null ? t('projects.growthPending') : formatStarDelta(gain.value, appLocale.value))
const gainTitle = computed(() => projectGrowthTitle(props.repo, t, appLocale.value))
const heatScore = computed(() => (projectHeatAvailable(props.repo) ? displayHotScore(projectHotScore(props.repo)) : null))
const heatText = computed(() => (heatScore.value === null ? '—' : heatScore.value.toFixed(1)))
// 没热度（或还没算）的行数字淡一档，和 24 小时为 0 一样，扫一眼先看到有动静的项目。
const heatFlat = computed(() => heatScore.value === null || heatScore.value < 0.05)
const heatTitle = computed(() => t(projectHeatAvailable(props.repo) ? 'projects.hotScoreTitle' : 'projects.heatPending'))
const forksText = computed(() => t('projects.forks', { count: formatProjectCount(props.repo.forks, appLocale.value) }))
const lastPush = computed(() => (props.repo.pushed_at ? formatProjectLastPush(props.repo.pushed_at, appLocale.value) : ''))

const plainClick = (event: MouseEvent) => event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey

// 项目名：有详情栏时单击在右侧打开；按着修饰键（新标签页、新窗口）照常去 GitHub，记为看过
const onNameClick = (event: MouseEvent) => {
  if (props.opensPane && plainClick(event)) {
    event.preventDefault()
    emit('open', props.repo)
    return
  }
  emit('visit', props.repo)
}

// 行里空白处（描述、数字、火花线）：有详情栏时单击打开；点到标签、按钮、链接，或是在选文字，都不算
const onRowClick = (event: MouseEvent) => {
  if (!props.opensPane || event.defaultPrevented || !plainClick(event)) return
  if ((event.target as Element | null)?.closest?.('a, button, input, label, summary, [role="button"]')) return
  if (window.getSelection?.()?.toString()) return
  emit('open', props.repo)
}

const movementText = computed(() => {
  const movement = props.movement
  if (!movement) return ''
  if (movement.kind === 'new') return t('projectChart.newEntry')
  if (movement.kind === 'same') return '–'
  return `${movement.kind === 'up' ? '▲' : '▼'}${movement.steps}`
})
const movementLabel = computed(() => {
  const movement = props.movement
  if (!movement) return ''
  if (movement.kind === 'new') return t('projectChart.newEntryTitle')
  if (movement.kind === 'same') return t('projectChart.unmoved')
  return t(movement.kind === 'up' ? 'projectChart.movedUp' : 'projectChart.movedDown', { count: movement.steps })
})
</script>

<template>
  <li
    class="project-row"
    :class="{
      'project-row--podium': position !== null && position <= 3,
      'project-row--recommended': repo.is_recommended,
      'project-row--not-found': notFound,
      'project-row--paneable': opensPane,
    }"
    @click="onRowClick"
  >
    <div v-if="position !== null" class="project-row__rank">
      <!-- 位数多了字号收小，五位数的名次也放得进名次列 -->
      <span class="project-row__position" :data-digits="String(position).length"><span class="sr-only">{{ t('projectChart.rank') }}</span>{{ position }}</span>
      <span v-if="movement" class="project-row__move" :class="`project-row__move--${movement.kind}`" :title="movementLabel">
        <span aria-hidden="true">{{ movementText }}</span><span class="sr-only">{{ movementLabel }}</span>
      </span>
    </div>

    <!-- 宽榜单里标签跟在项目名后面，放不下再折到名字下面；窄榜单里标签单独占一行，铺满数字列下方 -->
    <div class="project-row__head">
      <div class="project-row__title">
        <ProjectLogo class="project-row__logo" :logo="repo.image_url" :repository-url="url" :name="name" :unavailable="notFound" />
        <h2 class="project-row__name">
          <a v-if="url" :href="url" target="_blank" rel="noopener noreferrer" :title="opensPane ? undefined : t('projects.openRepository')" @click="onNameClick" @auxclick.middle="emit('visit', repo)"><span class="project-row__owner">{{ nameParts.owner }}</span><wbr /><span class="project-row__repo">{{ nameParts.repo }}</span></a>
          <template v-else><span class="project-row__owner">{{ nameParts.owner }}</span><wbr /><span class="project-row__repo">{{ nameParts.repo }}</span></template>
        </h2>
        <span v-if="repo.is_recommended" class="project-row__pick" :title="t('projectChart.pick')"><span aria-hidden="true">✦</span><span class="sr-only">{{ t('projectChart.pick') }}</span></span>
        <span v-if="notFound" class="project-row__gone">{{ t('projects.unavailable') }}</span>
      </div>
      <div v-if="tailChip" class="project-row__chips" :aria-label="t('projects.categoryTags')">
        <button
          v-for="chip in leadChips"
          :key="`${chip.type}:${chip.value}`"
          type="button"
          class="project-row__chip"
          @click="emit('chipClick', chip)"
        >{{ chip.label }}</button>
        <span class="project-row__chip-tail">
          <button type="button" class="project-row__chip" @click="emit('chipClick', tailChip)">{{ tailChip.label }}</button>
          <button
            v-if="chips.length > CHART_ROW_TAGS"
            type="button"
            class="project-row__chip project-row__chip--more"
            :aria-expanded="tagsOpen"
            :aria-label="t(tagsOpen ? 'projects.fewerTags' : 'projects.moreTags')"
            @click="tagsOpen = !tagsOpen"
          >{{ tagsOpen ? '−' : `+${chips.length - CHART_ROW_TAGS}` }}</button>
        </span>
      </div>
    </div>

    <p class="project-row__desc">
      {{ description }}
      <span class="project-row__meta">
        <!-- 窄榜单收起星标与热度两列，改在这里写 -->
        <span class="project-row__meta-narrow project-row__meta-stars" :title="starsTitle"><Star :size="12" :stroke-width="2" aria-hidden="true" />{{ starsText }}</span>
        <span class="project-row__meta-narrow project-row__meta-heat" :class="{ 'project-row__heat--flat': heatFlat }" :title="heatTitle">{{ t('projects.hotScore', { score: heatText }) }}</span>
        <span><GitFork :size="12" :stroke-width="2" aria-hidden="true" />{{ forksText }}</span>
        <span v-if="lastPush" :title="projectLastPushTitle(repo, t, appLocale)"><Clock :size="12" :stroke-width="2" aria-hidden="true" />{{ lastPush }}</span>
      </span>
    </p>

    <span class="project-row__num project-row__stars" :title="starsTitle"><span class="sr-only">{{ t('projectChart.stars') }}</span>{{ starsText }}</span>
    <span class="project-row__num project-row__gain" :class="{ 'project-row__gain--flat': gain === null || gain === 0 }" :title="gainTitle"><span class="sr-only">{{ t('projectChart.gain') }}</span>{{ gainText }}</span>
    <ProjectSparkline class="project-row__spark" :points="trend?.points" :metric-date="metricDate" :days="days" />
    <span class="project-row__num project-row__heat" :class="{ 'project-row__heat--flat': heatFlat }" :title="heatTitle"><span class="sr-only">{{ t('projectChart.heat') }}</span>{{ heatText }}</span>

    <div class="project-row__actions" role="group" :aria-label="t('projects.cardActions')">
      <a
        v-if="url"
        class="project-row__action project-row__link"
        :href="url"
        target="_blank"
        rel="noopener noreferrer"
        :aria-label="t('projects.openRepository')"
        :title="t('projects.openRepository')"
        @click="emit('visit', repo)"
        @auxclick.middle="emit('visit', repo)"
      ><ExternalLink :size="15" :stroke-width="1.8" aria-hidden="true" /></a>
      <button
        v-if="canRecommend"
        type="button"
        class="project-row__action project-row__recommend"
        :class="{ 'project-row__recommend--active': repo.is_recommended }"
        :aria-label="t(recommendButtonLabelKey(repo, recommendBusy))"
        :title="t(recommendButtonLabelKey(repo, recommendBusy))"
        :aria-pressed="Boolean(repo.is_recommended)"
        :disabled="recommendActionsBusy"
        @click="emit('recommend', repo)"
      ><Sparkles :size="15" :stroke-width="1.8" aria-hidden="true" /></button>
      <button
        type="button"
        class="project-row__action project-row__favorite"
        :class="{ 'project-row__favorite--active': repo.is_favorited }"
        :aria-label="t(favoriteButtonLabelKey(repo, favoriteBusy, isLoggedIn))"
        :title="t(favoriteButtonLabelKey(repo, favoriteBusy, isLoggedIn))"
        :aria-pressed="Boolean(repo.is_favorited)"
        :disabled="favoriteActionsBusy || !canFavorite"
        @click="emit('favorite', repo)"
      ><Star :size="15" :stroke-width="1.8" :fill="repo.is_favorited ? 'currentColor' : 'none'" aria-hidden="true" /></button>
    </div>
  </li>
</template>
