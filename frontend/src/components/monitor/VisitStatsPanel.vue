<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import SpinnerLoader from '@/components/SpinnerLoader.vue'
import { useVisitStatsController } from '@/composables/useVisitStatsController'
import {
  DONUT_RADIUS,
  PLATFORM_COLOR_SLOT,
  VISIT_PLATFORM_ORDER,
  VISIT_STATS_WINDOWS,
  automatedVisits,
  buildDonutSegments,
  computeShares,
  isEmptyStats,
  orderedPlatformShares,
  type VisitPlatformKey,
  type VisitStatsWindow,
} from '@/features/monitor/visitStatsViewModel'

const { t, locale } = useI18n()

// 自包含面板：状态与请求都留在卡片内部，MonitorView 只需挂载，不占用页面控制器。
const { data, loading, errorMsg, window: activeWindow, setWindow, load, dispose } =
  useVisitStatsController({ translate: t })

const WINDOW_LABEL_KEYS: Record<VisitStatsWindow, string> = {
  today: 'monitor.visitStats.window.today',
  '7d': 'monitor.visitStats.window.d7',
  '30d': 'monitor.visitStats.window.d30',
  all: 'monitor.visitStats.window.all',
}

const platforms = computed(() => orderedPlatformShares(data.value?.platforms))
const shares = computed(() => computeShares(data.value?.platforms))
const segments = computed(() => buildDonutSegments(data.value?.platforms))
const empty = computed(() => isEmptyStats(data.value))
const automated = computed(() => automatedVisits(data.value))

const platformLabel = (platform: VisitPlatformKey): string =>
  t(`monitor.visitStats.platform.${platform}`)

const seriesVar = (platform: VisitPlatformKey): string =>
  `var(--visit-series-${PLATFORM_COLOR_SLOT[platform]})`

const shareText = (platform: VisitPlatformKey): string =>
  shares.value[platform].toFixed(1)

const rangeText = computed(() => {
  const stats = data.value
  if (!stats) return ''
  return stats.start_date
    ? t('monitor.visitStats.range', { start: stats.start_date, end: stats.end_date })
    : t('monitor.visitStats.rangeAll', { end: stats.end_date })
})

// 屏幕阅读器文案：图是展示层，占比信息以图例数值为准，aria-label 同步复述
const chartAriaLabel = computed(() => {
  const separator = locale.value === 'zh-CN' ? '、' : ', '
  const breakdown = VISIT_PLATFORM_ORDER
    .map(platform => `${platformLabel(platform)} ${shareText(platform)}%`)
    .join(separator)
  return `${t('monitor.visitStats.chartAria')}: ${breakdown}`
})

onMounted(load)
onBeforeUnmount(dispose)
</script>

<template>
  <div class="visit-stats-panel stagger-enter glass-card shrink-0 p-5" style="animation-delay: 0.2s">
    <div class="flex flex-wrap items-center gap-2">
      <svg class="h-4 w-4 monitor-caption" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.21 15.89A10 10 0 1 1 8 2.83"/><path d="M22 12A10 10 0 0 0 12 2v10z"/></svg>
      <h3 class="monitor-section-title text-sm font-semibold">{{ t('monitor.visitStats.title') }}</h3>
      <span v-if="data" class="monitor-badge tabular-nums">{{ t('monitor.visitStats.total', { count: data.total_visits }) }}</span>
      <div class="ml-auto flex flex-wrap items-center gap-1" role="group" :aria-label="t('monitor.visitStats.title')">
        <button
          v-for="item in VISIT_STATS_WINDOWS"
          :key="item"
          type="button"
          class="monitor-btn-ghost visit-window-tab"
          :class="{ 'visit-window-tab-active': activeWindow === item }"
          :aria-pressed="activeWindow === item"
          :disabled="loading && activeWindow === item"
          @click="setWindow(item)"
        >
          {{ t(WINDOW_LABEL_KEYS[item]) }}
        </button>
      </div>
    </div>
    <p class="monitor-caption mt-1.5 text-xs leading-5">{{ t('monitor.visitStats.description') }}</p>

    <div v-if="errorMsg" class="mt-3 flex items-center justify-between rounded-md border px-4 py-2 text-xs monitor-status-error">
      <span>{{ errorMsg }}</span>
      <button class="ml-3 opacity-70 hover:opacity-100" @click="errorMsg = ''">✕</button>
    </div>

    <SpinnerLoader v-if="loading && !data" class="min-h-[180px]" />

    <template v-else-if="data">
      <hr class="monitor-divider mt-4 border-t" />
      <div class="visit-stats-body mt-4">
        <div class="visit-donut-wrap">
          <svg
            class="visit-donut"
            viewBox="0 0 200 200"
            role="img"
            :aria-label="chartAriaLabel"
          >
            <!-- 空态：灰环 + 提示，无分段 -->
            <circle
              v-if="empty"
              cx="100" cy="100" :r="DONUT_RADIUS"
              fill="none"
              class="visit-donut-empty-ring"
            />
            <g v-else transform="rotate(-90 100 100)">
              <circle
                v-for="segment in segments"
                :key="segment.platform"
                cx="100" cy="100" :r="DONUT_RADIUS"
                fill="none"
                class="visit-donut-segment"
                :style="{ stroke: seriesVar(segment.platform) }"
                :stroke-dasharray="segment.dasharray"
                :stroke-dashoffset="segment.dashoffset"
              />
            </g>
            <text x="100" y="96" text-anchor="middle" class="visit-donut-total tabular-nums">
              {{ data.total_visits }}
            </text>
            <text x="100" y="116" text-anchor="middle" class="visit-donut-total-label">
              {{ t('monitor.visitStats.totalLabel') }}
            </text>
          </svg>
        </div>

        <div class="visit-legend-wrap">
          <p class="monitor-caption text-2xs tabular-nums">{{ rangeText }}</p>
          <p v-if="empty" class="monitor-caption mt-2 text-xs">{{ t('monitor.visitStats.empty') }}</p>
          <ul v-else class="visit-legend mt-2">
            <li
              v-for="entry in platforms"
              :key="entry.platform"
              class="visit-legend-item"
            >
              <span class="visit-legend-dot" :style="{ background: seriesVar(entry.platform) }" />
              <span class="visit-legend-name">{{ platformLabel(entry.platform) }}</span>
              <span class="visit-legend-value tabular-nums">{{ entry.visits }}</span>
              <span class="visit-legend-share tabular-nums">{{ shareText(entry.platform) }}%</span>
            </li>
          </ul>
          <!-- 自动化访问不计入总访问、不进环图，虚线空心点与灰字区分于计数桶 -->
          <div class="visit-automated-row" :title="t('monitor.visitStats.automatedHint')">
            <span class="visit-legend-dot visit-automated-dot" aria-hidden="true" />
            <span class="visit-automated-name">{{ t('monitor.visitStats.automated') }}</span>
            <span class="visit-legend-value visit-automated-value tabular-nums">{{ automated }}</span>
            <span class="visit-legend-share" aria-hidden="true" />
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* 系列色：固定桶→槽位映射（颜色跟随实体而非排名），槽位色经 dataviz validate_palette 双模式验证；
   浅色下 aqua/yellow/magenta 对比度 WARN 由图例数值列表（table view）兜底 */
.visit-stats-panel {
  --visit-series-1: #2a78d6;
  --visit-series-2: #eb6834;
  --visit-series-3: #1baf7a;
  --visit-series-4: #eda100;
  --visit-series-5: #e87ba4;
  --visit-series-6: #008300;
}

:root[data-theme='dark'] .visit-stats-panel {
  --visit-series-1: #3987e5;
  --visit-series-2: #d95926;
  --visit-series-3: #199e70;
  --visit-series-4: #c98500;
  --visit-series-5: #d55181;
  --visit-series-6: #008300;
}

.visit-window-tab {
  padding: 3px 10px;
  font-size: 11px;
}

.visit-window-tab-active {
  border-color: var(--projects-accent);
  background: var(--projects-accent);
  color: var(--projects-paper-light);
}

.visit-stats-body {
  display: flex;
  align-items: center;
  gap: 24px;
  flex-wrap: wrap;
}

.visit-donut-wrap {
  flex: 0 0 auto;
}

.visit-donut {
  width: 180px;
  height: 180px;
  display: block;
}

.visit-donut-segment {
  stroke-width: 30;
  /* 分段切换动画；prefers-reduced-motion 由 style.css 的 .monitor-page 全局规则统一关停 */
  transition: stroke-dasharray 0.3s ease, stroke-dashoffset 0.3s ease;
}

.visit-donut-empty-ring {
  stroke-width: 30;
  stroke: var(--rule);
}

.visit-donut-total {
  fill: var(--projects-accent);
  font-size: 28px;
  font-weight: 800;
}

.visit-donut-total-label {
  fill: var(--ink-muted);
  font-size: 11px;
}

.visit-legend-wrap {
  flex: 1 1 220px;
  min-width: 0;
}

.visit-legend {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.visit-legend-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.visit-legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 3px;
  flex: 0 0 auto;
}

.visit-legend-name {
  color: var(--projects-accent);
  font-weight: 600;
}

.visit-legend-value {
  margin-left: auto;
  color: var(--projects-accent);
  font-weight: 700;
}

.visit-legend-share {
  width: 52px;
  text-align: right;
  color: var(--ink-muted);
}

.visit-automated-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px dashed var(--rule);
  font-size: 12px;
}

.visit-automated-dot {
  box-sizing: border-box;
  border: 1.5px dashed var(--ink-muted);
  background: transparent;
}

.visit-automated-name,
.visit-automated-value {
  color: var(--ink-muted);
}

@media (max-width: 560px) {
  .visit-stats-body {
    flex-direction: column;
    align-items: stretch;
  }

  .visit-donut-wrap {
    align-self: center;
  }
}
</style>
