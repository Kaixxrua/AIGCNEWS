<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import SpinnerLoader from '@/components/SpinnerLoader.vue'
import { useMcpUsageController } from '@/composables/useMcpUsageController'
import { vIndicator } from '@/motion/indicator'
import { vSwap } from '@/motion/swap'
import {
  DEFAULT_MCP_USAGE_METRIC,
  MCP_USAGE_AUDIENCES,
  MCP_USAGE_METRICS,
  MCP_USAGE_WINDOWS,
  barPercent,
  dailyMax,
  hasUsage,
  landingPathKey,
  landingSourceKey,
  limitKindKey,
  nonZeroAudiences,
  specialClientNameKey,
  specialToolKey,
  trackedDays,
  trackingStartsInWindow,
  type McpUsageMetric,
} from '@/features/monitor/mcpUsageViewModel'
import type { McpUsageAudienceCounts } from '@/features/monitor/monitorModel'
import { installMcpUsageMessages } from '@/i18n/locales/mcpUsage'

installMcpUsageMessages()

const { t, locale } = useI18n()

// 自包含面板：状态与请求都留在卡片内部，MonitorView 只需挂载。
const { data, days, errorMsg, load, loading, setDays, dispose } = useMcpUsageController({ translate: t })

const metric = ref<McpUsageMetric>(DEFAULT_MCP_USAGE_METRIC)

const dailyRows = computed(() => trackedDays(data.value))
const dailyPeak = computed(() => dailyMax(dailyRows.value, metric.value))
const empty = computed(() => !hasUsage(data.value))
const showSince = computed(() => trackingStartsInWindow(data.value))

const toolLabel = (tool: string): string => {
  const key = specialToolKey(tool)
  return key ? t(key) : tool
}

// 工具名只在下划线后可断行（配 <wbr>）：宽度够时一行，窄栏里不至于从词中间断开。
const toolParts = (tool: string): string[] => {
  const parts = toolLabel(tool).split('_')
  return parts.map((part, index) => (index < parts.length - 1 ? `${part}_` : part))
}

const clientLabel = (name: string): string => {
  const key = specialClientNameKey(name)
  return key ? t(key) : name
}

const limitLabel = (kind: string): string => {
  const key = limitKindKey(kind)
  return key ? t(key) : kind
}

const landingSourceLabel = (source: string): string => {
  const key = landingSourceKey(source)
  return key ? t(key) : source
}

const landingPathLabel = (path: string): string => {
  const key = landingPathKey(path)
  return key ? t(key) : path
}

// 客户端名下的分布小字逐段成块，只在受众之间换行（不会把「会员 1」拆成两行）。
const splitSeparator = computed(() => (locale.value === 'zh-CN' ? '、' : ', '))

const audienceParts = (counts: McpUsageAudienceCounts): string[] =>
  nonZeroAudiences(counts).map(({ audience, count }) => `${t(`mcpUsage.audience.${audience}`)} ${count}`)

onMounted(load)
onBeforeUnmount(dispose)
</script>

<template>
  <div class="mcp-usage-panel stagger-enter glass-card shrink-0 p-5" style="animation-delay: 0.3s">
    <div class="flex flex-wrap items-center gap-2">
      <svg class="h-4 w-4 monitor-caption" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3 3v18h18"/><path d="M7 15l4-4 3 3 5-6"/></svg>
      <h3 class="monitor-section-title text-sm font-semibold">{{ t('mcpUsage.title') }}</h3>
      <span v-if="data" class="monitor-badge tabular-nums">{{ t('mcpUsage.range', { start: data.start_date, end: data.end_date }) }}</span>
      <div
        v-indicator="{ active: '[aria-pressed=true]', pop: true }"
        class="mcp-usage-tabs ml-auto flex flex-wrap items-center gap-1"
        role="group"
        :aria-label="t('mcpUsage.windowLabel')"
      >
        <button
          v-for="item in MCP_USAGE_WINDOWS"
          :key="item"
          type="button"
          class="monitor-btn-ghost mcp-usage-tab"
          :class="{ 'mcp-usage-tab-active': days === item }"
          :aria-pressed="days === item"
          :disabled="loading && days === item"
          @click="setDays(item)"
        >
          {{ t(`mcpUsage.window.d${item}`) }}
        </button>
      </div>
    </div>
    <p class="monitor-caption mt-1.5 text-xs leading-5">{{ t('mcpUsage.description') }}</p>

    <div v-if="errorMsg" class="mt-3 flex items-center justify-between rounded-md border px-4 py-2 text-xs monitor-status-error">
      <span>{{ errorMsg }}</span>
      <button class="ml-3 opacity-70 hover:opacity-100" @click="errorMsg = ''">✕</button>
    </div>

    <SpinnerLoader v-if="loading && !data" class="min-h-[180px]" />

    <template v-else-if="data">
      <p v-if="!data.available" class="mcp-usage-note mt-3 rounded-md border px-4 py-2 text-xs monitor-status-unknown">
        {{ t('mcpUsage.unavailable') }}
      </p>
      <p v-else-if="empty" class="mcp-usage-note monitor-caption mt-3 text-xs">{{ t('mcpUsage.empty') }}</p>

      <template v-else>
        <p v-if="showSince" class="monitor-caption mt-2 text-2xs">{{ t('mcpUsage.since', { date: data.since }) }}</p>

        <section class="mt-4">
          <h4 class="mcp-usage-subtitle">{{ t('mcpUsage.summaryTitle') }}</h4>
          <div class="overflow-x-auto">
            <table class="monitor-table mcp-usage-summary">
              <thead>
                <tr>
                  <th scope="col">{{ t('mcpUsage.metricColumn') }}</th>
                  <th v-for="audience in MCP_USAGE_AUDIENCES" :key="audience" scope="col">{{ t(`mcpUsage.audience.${audience}`) }}</th>
                  <th scope="col">{{ t('mcpUsage.audience.total') }}</th>
                </tr>
              </thead>
              <tbody v-swap="{ key: data.days, stagger: true }">
                <tr v-for="item in MCP_USAGE_METRICS" :key="item">
                  <th scope="row" class="mcp-usage-row-head" :title="t(`mcpUsage.metricHint.${item}`)">{{ t(`mcpUsage.metric.${item}`) }}</th>
                  <td v-for="audience in MCP_USAGE_AUDIENCES" :key="audience" class="tabular-nums">{{ data.summary[audience][item] }}</td>
                  <td class="mcp-usage-total tabular-nums">{{ data.summary.total[item] }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <div class="mcp-usage-grid mt-5">
          <section class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <h4 class="mcp-usage-subtitle">{{ t('mcpUsage.dailyTitle') }}</h4>
              <div
                v-indicator="{ active: '[aria-pressed=true]', pop: true }"
                class="mcp-usage-tabs ml-auto flex flex-wrap items-center gap-1"
                role="group"
                :aria-label="t('mcpUsage.dailyMetricLabel')"
              >
                <button
                  v-for="item in MCP_USAGE_METRICS"
                  :key="item"
                  type="button"
                  class="monitor-btn-ghost mcp-usage-tab mcp-usage-metric-tab"
                  :class="{ 'mcp-usage-tab-active': metric === item }"
                  :aria-pressed="metric === item"
                  :title="t(`mcpUsage.metricHint.${item}`)"
                  @click="metric = item"
                >
                  {{ t(`mcpUsage.metric.${item}`) }}
                </button>
              </div>
            </div>
            <div class="mt-2 overflow-x-auto">
              <table class="monitor-table mcp-usage-daily">
                <thead>
                  <tr>
                    <th scope="col">{{ t('mcpUsage.date') }}</th>
                    <th v-for="audience in MCP_USAGE_AUDIENCES" :key="audience" scope="col">{{ t(`mcpUsage.audience.${audience}`) }}</th>
                    <th scope="col">{{ t('mcpUsage.audience.total') }}</th>
                  </tr>
                </thead>
                <tbody v-swap="{ key: `${data.days}-${metric}`, stagger: true }">
                  <tr v-for="day in dailyRows" :key="day.date">
                    <td class="whitespace-nowrap tabular-nums">{{ day.date }}</td>
                    <td v-for="audience in MCP_USAGE_AUDIENCES" :key="audience" class="tabular-nums">{{ day[audience][metric] }}</td>
                    <td class="mcp-usage-total mcp-usage-bar-cell tabular-nums">
                      {{ day.total[metric] }}
                      <span class="mcp-usage-bar-track" aria-hidden="true">
                        <span class="mcp-usage-bar" :style="{ width: `${barPercent(day.total[metric], dailyPeak)}%` }" />
                      </span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <section class="min-w-0">
            <h4 class="mcp-usage-subtitle">{{ t('mcpUsage.toolsTitle') }}</h4>
            <div class="mt-2 overflow-x-auto">
              <table class="monitor-table mcp-usage-tools">
                <thead>
                  <tr>
                    <th scope="col">{{ t('mcpUsage.tool') }}</th>
                    <th v-for="audience in MCP_USAGE_AUDIENCES" :key="audience" scope="col">{{ t(`mcpUsage.audience.${audience}`) }}</th>
                    <th scope="col">{{ t('mcpUsage.audience.total') }}</th>
                  </tr>
                </thead>
                <tbody v-swap="{ key: data.days, stagger: true }">
                  <tr v-if="!data.tools.length">
                    <td colspan="5" class="text-center monitor-caption">{{ t('mcpUsage.noTools') }}</td>
                  </tr>
                  <tr v-for="row in data.tools" :key="row.tool">
                    <td class="mcp-usage-tool" :class="{ 'font-mono': !specialToolKey(row.tool) }"><template v-for="(part, index) in toolParts(row.tool)" :key="index"><wbr v-if="index">{{ part }}</template></td>
                    <td v-for="audience in MCP_USAGE_AUDIENCES" :key="audience" class="tabular-nums">{{ row[audience] }}</td>
                    <td class="mcp-usage-total tabular-nums">{{ row.total }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <section class="min-w-0">
            <h4 class="mcp-usage-subtitle">{{ t('mcpUsage.clientsTitle') }}</h4>
            <div class="mt-2 overflow-x-auto">
              <table class="monitor-table mcp-usage-clients">
                <thead>
                  <tr>
                    <th scope="col">{{ t('mcpUsage.clientName') }}</th>
                    <th scope="col">{{ t('mcpUsage.clientsCount') }}</th>
                    <th scope="col">{{ t('mcpUsage.connectionsCount') }}</th>
                  </tr>
                </thead>
                <tbody v-swap="{ key: data.days, stagger: true }">
                  <tr v-if="!data.client_names.length">
                    <td colspan="3" class="text-center monitor-caption">{{ t('mcpUsage.noClients') }}</td>
                  </tr>
                  <tr v-for="row in data.client_names" :key="row.name">
                    <td class="mcp-usage-name">
                      <span class="mcp-usage-name-label">{{ clientLabel(row.name) }}</span>
                      <span v-if="audienceParts(row.clients).length" class="mcp-usage-split monitor-caption" :title="t('mcpUsage.audienceSplit')">
                        <template v-for="(part, index) in audienceParts(row.clients)" :key="part"><span v-if="index">{{ splitSeparator }}</span><span class="mcp-usage-split-part">{{ part }}</span></template>
                      </span>
                    </td>
                    <td class="mcp-usage-total tabular-nums">{{ row.clients.total }}</td>
                    <td class="tabular-nums">{{ row.connections.total }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p v-if="data.client_names_truncated" class="monitor-caption mt-1.5 text-2xs">{{ t('mcpUsage.clientNamesTruncated') }}</p>
          </section>

          <section class="min-w-0">
            <h4 class="mcp-usage-subtitle">{{ t('mcpUsage.limitedTitle') }}</h4>
            <div class="mt-2 overflow-x-auto">
              <table class="monitor-table mcp-usage-limited">
                <thead>
                  <tr>
                    <th scope="col">{{ t('mcpUsage.kind') }}</th>
                    <th v-for="audience in MCP_USAGE_AUDIENCES" :key="audience" scope="col">{{ t(`mcpUsage.audience.${audience}`) }}</th>
                    <th scope="col">{{ t('mcpUsage.audience.total') }}</th>
                  </tr>
                </thead>
                <tbody v-swap="{ key: data.days, stagger: true }">
                  <tr v-for="row in data.limited" :key="row.kind">
                    <th scope="row" class="mcp-usage-row-head">{{ limitLabel(row.kind) }}</th>
                    <td v-for="audience in MCP_USAGE_AUDIENCES" :key="audience" class="tabular-nums">{{ row[audience] }}</td>
                    <td class="mcp-usage-total tabular-nums">{{ row.total }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <!-- 429 之后有没有人点进网站：紧跟限流表，同一时间窗。早于本字段的后端不返回 landings，整块不画。 -->
            <template v-if="data.landings">
              <h4 class="mcp-usage-subtitle mt-4">{{ t('mcpUsage.landingTitle') }}</h4>
              <p class="monitor-caption mt-1 text-2xs">{{ t('mcpUsage.landingNote') }}</p>
              <p v-if="!data.landings.available" class="mcp-usage-note mt-2 rounded-md border px-4 py-2 text-xs monitor-status-unknown">
                {{ t('mcpUsage.landingUnavailable') }}
              </p>
              <div v-else class="mt-2 overflow-x-auto">
                <table class="monitor-table mcp-usage-landings">
                  <thead>
                    <tr>
                      <th scope="col">{{ t('mcpUsage.landingSourceColumn') }}</th>
                      <th scope="col">{{ t('mcpUsage.landingPathColumn') }}</th>
                      <th scope="col">{{ t('mcpUsage.landingCountColumn') }}</th>
                    </tr>
                  </thead>
                  <tbody v-swap="{ key: data.days, stagger: true }">
                    <tr v-if="!data.landings.rows.length">
                      <td colspan="3" class="text-center monitor-caption">{{ t('mcpUsage.noLandings') }}</td>
                    </tr>
                    <tr v-for="row in data.landings.rows" :key="`${row.source}|${row.path}`">
                      <th scope="row" class="mcp-usage-row-head">{{ landingSourceLabel(row.source) }}</th>
                      <td :class="{ 'font-mono': !landingPathKey(row.path) }">{{ landingPathLabel(row.path) }}</td>
                      <td class="mcp-usage-total tabular-nums">{{ row.landings }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </template>
          </section>
        </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
.mcp-usage-subtitle {
  font-size: 12px;
  font-weight: 700;
  color: var(--projects-accent);
}

.mcp-usage-tab {
  padding: 3px 10px;
  font-size: 11px;
}

.mcp-usage-tab-active {
  border-color: var(--projects-accent);
  background: var(--projects-accent);
  color: var(--projects-paper-light);
}

/* 选中底由 v-indicator 画在按钮组的 ::before 上，切换时弹簧滑动（同访问统计面板的时间窗按钮）；
   选中项把底让给它，反白字晚一拍换上，加载中选中项连同标记一起变淡。 */
.mcp-usage-tabs {
  position: relative;
  isolation: isolate;
}

.mcp-usage-tabs[data-indicator-mark]::before {
  z-index: -1;
  border-radius: 4px;
  background: var(--projects-accent);
}

.mcp-usage-tabs:has(.mcp-usage-tab-active:disabled)[data-indicator-mark]::before {
  opacity: 0.4;
}

.mcp-usage-tabs[data-indicator] .mcp-usage-tab-active,
.mcp-usage-tabs[data-indicator] .mcp-usage-tab-active:hover:not(:disabled) {
  border-color: transparent;
  background: transparent;
  box-shadow: none;
  color: var(--projects-paper-light);
  transform: none;
}

.mcp-usage-tabs[data-indicator] .mcp-usage-tab {
  transition: transform 150ms ease, box-shadow 150ms ease, background 150ms ease, color 90ms ease, border-color 150ms ease;
}

.mcp-usage-tabs[data-indicator] .mcp-usage-tab-active {
  transition: transform 150ms ease, box-shadow 150ms ease, background 150ms ease, color 160ms ease 70ms, border-color 150ms ease;
}

/* 两列成田字（日表 | 工具，客户端 | 429）；面板窄于两列所需时单列堆叠，表格各自横向滚动。 */
.mcp-usage-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 420px), 1fr));
  gap: 20px 24px;
}

.mcp-usage-panel .monitor-table th {
  white-space: nowrap;
}

/* 行首用 th（读屏按行报出指标名），边线跟数据格一致，不用表头那道深线。 */
.mcp-usage-panel .monitor-table tbody th {
  border-bottom-color: rgb(var(--stone-400-rgb) / 0.15);
}

.mcp-usage-row-head {
  text-align: left;
  white-space: nowrap;
  cursor: help;
}

.mcp-usage-limited .mcp-usage-row-head,
.mcp-usage-landings .mcp-usage-row-head {
  cursor: default;
}

.mcp-usage-name {
  max-width: 280px;
}

.mcp-usage-name-label {
  display: block;
  overflow-wrap: break-word;
}

.mcp-usage-split {
  display: block;
  margin-top: 2px;
  font-size: 12px;
  line-height: 1.4;
}

.mcp-usage-split-part {
  white-space: nowrap;
}

.mcp-usage-total {
  color: var(--projects-accent);
  font-weight: 700;
}

/* 合计数字下的细条：长度按当前指标的窗口峰值归一，只做趋势提示，读数以数字为准。 */
.mcp-usage-bar-cell {
  min-width: 72px;
}

.mcp-usage-bar-track {
  display: block;
  height: 3px;
  margin-top: 4px;
  border-radius: 2px;
  background: color-mix(in srgb, var(--projects-accent) 10%, transparent);
}

.mcp-usage-bar {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--projects-accent);
  opacity: 0.55;
  transition: width 0.3s ease;
}
</style>
