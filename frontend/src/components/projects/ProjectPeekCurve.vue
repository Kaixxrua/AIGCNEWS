<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { AppLocale } from '@/i18n'
import { formatLocaleNumber } from '@/i18n/formatters'
import type { PeekCurveState } from '@/composables/useProjectPeek'
import { formatSparkDate, formatStarDelta } from '@/features/projects/projectChart'
import { PEEK_CURVE_DAYS, PEEK_CURVE_H, PEEK_CURVE_W, peekCurve } from '@/features/projects/projectPeek'

/**
 * 速览里近 30 天的星标曲线：标题旁是这段时间涨了多少，横轴两端标窗口的头尾。
 * 还在取时摆骨架，取失败（canRetry 时跟一个重试按钮，发 retry）或攒的天数不够时写一句话。
 * 悬停卡片里它压在最近一次提交下面，宽屏详情栏里它紧跟一组数字。
 */
const props = defineProps<{
  curve: PeekCurveState
  canRetry?: boolean
}>()

const emit = defineEmits<{
  retry: []
}>()

const { locale, t } = useI18n()
const appLocale = computed(() => locale.value as AppLocale)

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
</script>

<template>
  <section class="project-peek__part" :aria-busy="curve.status === 'loading'">
    <h3 class="project-peek__label">
      {{ t('projectPeek.stars', { days }) }}
      <span v-if="plot" class="project-peek__delta" :class="`project-peek__delta--${plot.trend}`">{{ plot.deltaText }}</span>
    </h3>
    <span v-if="curve.status === 'loading'" class="project-peek__skeleton project-peek__skeleton--plot" />
    <p v-else-if="curve.status === 'error'" class="project-peek__note">
      {{ t('projectPeek.starsFailed') }}
      <button v-if="canRetry" type="button" class="project-peek__retry" @click="emit('retry')">{{ t('common.retry') }}</button>
    </p>
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
</template>
