<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { AppLocale } from '@/i18n'
import type { GitHubProjectTrendPoint } from '@/services/projects/projectApi'
import {
  formatSparkDate,
  formatStarDelta,
  projectSparkDays,
  projectSparkSummary,
} from '@/features/projects/projectChart'

/**
 * 榜单一行的近两周火花线：每天一根柱，高低按这一行自己的最多一天比（看的是走势，不是和别的项目比大小）。
 * 最新一天的柱子用涨星的绿色，其余是淡墨；没统计的日子在底线上点一个点，涨了 0 或掉星的日子贴着底线一道细线。
 * 行情还没到时 points 为空：位置照留、整条透明，到了再淡入，行高不跳。
 */
const props = defineProps<{
  points?: readonly GitHubProjectTrendPoint[]
  metricDate: string
  days: number
}>()

const { locale, t } = useI18n()

const BAR = 5
const GAP = 2
const HEIGHT = 24
const MIN_BAR = 2

const width = computed(() => Math.max(1, props.days * (BAR + GAP) - GAP))
const ready = computed(() => Boolean(props.points && props.metricDate))
const series = computed(() => (props.points ? projectSparkDays(props.points, props.metricDate, props.days) : []))
const summary = computed(() => projectSparkSummary(series.value))

const bars = computed(() => {
  const peak = Math.max(0, ...series.value.map((day) => day.gain ?? 0))
  const last = series.value.length - 1
  return series.value.map((day, index) => {
    const x = index * (BAR + GAP)
    const date = formatSparkDate(day.date, locale.value as AppLocale)
    const title = day.gain === null
      ? t('projectChart.trendDayMissing', { date })
      : t('projectChart.trendDay', { date, gain: formatStarDelta(day.gain, locale.value as AppLocale) })
    if (day.gain === null) return { key: day.date, kind: 'missing' as const, x, y: HEIGHT - 1.5, height: 1.5, title, latest: index === last }
    if (day.gain <= 0 || peak <= 0) return { key: day.date, kind: 'flat' as const, x, y: HEIGHT - 1, height: 1, title, latest: index === last }
    const height = Math.max(MIN_BAR, Math.round((day.gain / peak) * HEIGHT * 10) / 10)
    return { key: day.date, kind: 'bar' as const, x, y: HEIGHT - height, height, title, latest: index === last }
  })
})

const label = computed(() => {
  if (!ready.value) return ''
  const { total, peak, counted } = summary.value
  if (!counted || !peak) return t('projectChart.trendEmpty', { days: props.days })
  return t('projectChart.trendSummary', {
    days: props.days,
    total: formatStarDelta(total, locale.value as AppLocale),
    date: formatSparkDate(peak.date, locale.value as AppLocale),
    peak: formatStarDelta(peak.gain ?? 0, locale.value as AppLocale),
  })
})
</script>

<template>
  <svg
    class="project-spark"
    :class="{ 'project-spark--ready': ready }"
    :width="width"
    :height="HEIGHT"
    :viewBox="`0 0 ${width} ${HEIGHT}`"
    :role="ready ? 'img' : undefined"
    :aria-label="label || undefined"
    :aria-hidden="ready ? undefined : 'true'"
  >
    <!-- 每天一列：整列透明的一块接住指针（贴底线的细线和点也好指），提示写那天的日期和新增 -->
    <g v-for="bar in bars" :key="bar.key" class="project-spark__col">
      <title>{{ bar.title }}</title>
      <rect class="project-spark__hit" :x="bar.x - GAP / 2" y="0" :width="BAR + GAP" :height="HEIGHT" />
      <rect
        class="project-spark__day"
        :class="[`project-spark__day--${bar.kind}`, { 'project-spark__day--latest': bar.latest }]"
        :x="bar.kind === 'missing' ? bar.x + 1.5 : bar.x"
        :y="bar.y"
        :width="bar.kind === 'missing' ? BAR - 3 : BAR"
        :height="bar.height"
        :rx="bar.kind === 'missing' ? 0.75 : 0.5"
      />
    </g>
  </svg>
</template>

<style scoped>
.project-spark { display: block; overflow: visible; opacity: 0; transition: opacity 240ms var(--motion-ease-out, ease-out); }
.project-spark--ready { opacity: 1; }
.project-spark__hit { fill: transparent; }
.project-spark__day { fill: currentColor; opacity: .38; transition: opacity 120ms ease; }
.project-spark__day--missing { opacity: .3; }
.project-spark__day--flat { opacity: .5; }
.project-spark__col:hover .project-spark__day { opacity: .85; }
.project-spark .project-spark__day--latest.project-spark__day--bar { fill: var(--p-today, var(--tone-mint)); opacity: 1; }
@media (prefers-reduced-motion: reduce) {
  .project-spark, .project-spark__day { transition: none; }
}
</style>
