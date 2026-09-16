<script setup lang="ts">
import { useMediaQuery } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import { useDashboardData } from '@/composables/useDashboardData'
import { useDashboardStats } from '@/composables/useDashboardStats'
import { subscribeLiveStats } from '@/composables/useLiveStatsStream'
import GlassCalendar from '@/components/GlassCalendar.vue'
import SpinnerLoader from '@/components/SpinnerLoader.vue'
import DashboardEmptyState from '@/components/dashboard/DashboardEmptyState.vue'
import DashboardDailyUi from '@/components/dashboard/DashboardDailyUi.vue'
import DashboardOverviewPanel from '@/components/dashboard/DashboardOverviewPanel.vue'
import DashboardRadarCard from '@/components/dashboard/DashboardRadarCard.vue'
import DashboardRankingPanel from '@/components/dashboard/DashboardRankingPanel.vue'
import RollingNumber from '@/components/dashboard/RollingNumber.vue'
import { CalendarDays, ArrowRight, MailPlus, Plug, Terminal } from 'lucide-vue-next'
import type { Stats } from '@/features/dashboard/dashboardViewModel'

defineOptions({ name: 'DashboardView' })
const { t } = useI18n()
const isMobile = useMediaQuery('(max-width: 767px)')
let currentStats: () => Stats = () => ({})
const {
  statValues,
  visitorValues,
  mcpTotalCalls,
  mcpDshCalls,
  updateStatSources,
  updateVisitorSources,
} = useDashboardStats(() => currentStats())

const {
  activeTab,
  tabList,
  stats,
  loading,
  tabLoading,
  errorMsg,
  currentDate,
  availableDates,
  isViewingHistory,
  isFinalized,
  isEmbargoed,
  sourceStatus,
  selectSourceTab,
  onDateChange,
  hasData,
  applyLiveStats,
} = useDashboardData({
  updateStatSources,
  updateVisitorSources,
})
currentStats = () => stats.value

// 与顶栏共用 SSE；断流后的轮询由共享订阅统一管理。
subscribeLiveStats(applyLiveStats)

</script>

<template>
  <div class="dashboard-page flex h-full flex-col gap-2 overflow-y-auto px-6 py-3 pb-5">

    <!-- 页头 — 简洁标题 -->
    <div class="dashboard-heading stagger-enter flex items-center justify-between shrink-0">
      <h1 class="text-xl font-semibold text-stone-800 tracking-tight font-serif">{{ t(isMobile ? 'dashboard.mobileTitle' : 'dashboard.title') }}</h1>
      <div v-if="!loading && isViewingHistory" class="flex items-center gap-1.5 text-xs text-stone-400">
        <CalendarDays class="h-3.5 w-3.5" />
        <span class="text-stone-700 font-medium">{{ currentDate }}</span>
      </div>
    </div>

    <!-- 错误提示 -->
    <div
      v-if="errorMsg"
      class="shrink-0 glass-card flex items-center gap-2 px-5 py-3 text-sm text-rose-600"
    >
      <svg class="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
      </svg>
      {{ errorMsg }}
    </div>

    <!-- 顶部统计带：所有指标合并为一行分段条；加载期间整条隐藏，避免出现空段 -->
    <DashboardOverviewPanel
      v-if="!loading && !isMobile"
      :loading="loading"
      :active-tab="activeTab"
      :stat-values="statValues"
      :visitor-values="visitorValues"
      @select-source="selectSourceTab"
    />

    <DashboardDailyUi v-if="!loading" />

    <!-- 主区域：榜单/空态占满剩余高度，日历与订阅入口收入右侧栏 -->
    <div class="dashboard-main dashboard-content flex min-h-0 flex-1 flex-col gap-2 lg:flex-row">
      <!-- 加载中：仅转圈，数据就绪后内容卡片直接出现 -->
      <SpinnerLoader v-if="loading" class="order-2 min-h-[360px] min-w-0 flex-1 lg:order-1" />

      <!-- 静默期专用空状态 (Embargo Empty State) -->
      <DashboardEmptyState v-if="!loading && isEmbargoed" variant="embargoed" class="order-2 min-w-0 lg:order-1" />

      <!-- 全局空状态（非静默期） -->
      <DashboardEmptyState
        v-else-if="!loading && !hasData && !tabLoading && !isEmbargoed"
        variant="no-data"
        class="order-2 min-w-0 lg:order-1"
      />

      <!-- 榜单面板（静默期时隐藏） -->
      <DashboardRankingPanel
        v-if="!loading && hasData && !isEmbargoed"
        class="order-2 min-w-0 lg:order-1"
        :active-tab="activeTab"
        :tab-list="tabList"
        :tab-loading="tabLoading"
        :is-viewing-history="isViewingHistory"
        :is-finalized="isFinalized"
        :source-status="sourceStatus"
        @select-source="selectSourceTab"
      />

      <aside v-if="!loading" class="dashboard-sidebar order-1 flex min-h-0 w-full max-w-[320px] shrink-0 flex-col gap-2 self-center lg:order-2 lg:w-[212px] lg:max-w-none lg:self-stretch lg:overflow-y-auto">
          <GlassCalendar
            :model-value="currentDate"
            :available-dates="availableDates"
            @update:model-value="onDateChange"
          />
          <!-- 每日简报与 RSS 统一入口：点击后直接打开简报页订阅向导，RSS 在向导内按需复制。
               token 只在用户明确复制时进入内存与剪贴板，不在 Dashboard DOM 暴露。 -->
          <div
            class="digest-card stagger-enter glass-card flex flex-col gap-2 px-3 py-2.5"
            style="animation-delay: 0.35s"
          >
            <span class="flex items-center gap-2">
              <span class="flex h-7 w-7 shrink-0 items-center justify-center rounded-[4px] border border-ink bg-accent text-accent-ink">
                <MailPlus class="h-4 w-4" />
              </span>
              <span class="text-sm font-bold text-stone-800">{{ t('dashboard.digest.title') }}</span>
            </span>
            <span class="text-2xs leading-relaxed text-stone-400">{{ t('dashboard.digest.description') }}</span>
            <div class="mt-auto">
              <RouterLink
                :to="{ path: '/report', query: { subscribe: '1' } }"
                class="digest-cta inline-flex w-full items-center justify-center gap-1 rounded-[4px] border border-ink bg-ink px-2 py-1.5 text-xs font-bold text-accent transition-colors hover:bg-accent hover:text-accent-ink"
              >
                {{ t('dashboard.digest.cta') }}
                <ArrowRight class="h-3.5 w-3.5" />
              </RouterLink>
            </div>
          </div>

          <!-- MCP 总调用次数（点击前往 MCP 接入页）：紧凑单行卡，自然高度，不再撑满侧栏 -->
          <RouterLink
            to="/mcp"
            class="integration-card integration-card--mcp stagger-enter glass-card card-hover flex items-center gap-2 px-3 py-2 transition-colors"
            style="animation-delay: 0.4s"
            :aria-label="t('dashboard.mcpCalls.title')"
          >
            <span class="flex items-center gap-2">
              <span class="flex h-6 w-6 shrink-0 items-center justify-center rounded-[4px] border border-ink bg-accent text-accent-ink">
                <Plug class="h-3.5 w-3.5" />
              </span>
              <span class="text-2xs font-semibold text-stone-400">{{ t('dashboard.mcpCalls.title') }}</span>
            </span>
            <RollingNumber :value="mcpTotalCalls" grouping class="ml-auto text-lg font-extrabold tabular-nums" />
          </RouterLink>

          <!-- dsh 插件调用次数（MCP 调用中的 dsh 客户端分桶，点击前往插件页）：与 MCP 卡同为紧凑单行卡 -->
          <RouterLink
            to="/dsh"
            class="integration-card integration-card--dsh stagger-enter glass-card card-hover flex items-center gap-2 px-3 py-2 transition-colors"
            style="animation-delay: 0.45s"
            :aria-label="t('dashboard.dshCalls.title')"
          >
            <span class="flex items-center gap-2">
              <span class="flex h-6 w-6 shrink-0 items-center justify-center rounded-[4px] border border-ink bg-accent text-accent-ink">
                <Terminal class="h-3.5 w-3.5" />
              </span>
              <span class="text-2xs font-semibold text-stone-400">{{ t('dashboard.dshCalls.title') }}</span>
            </span>
            <RollingNumber :value="mcpDshCalls" grouping class="ml-auto text-lg font-extrabold tabular-nums" />
          </RouterLink>

          <!-- 侧栏末端纯装饰：AIGC Radar 雷达扫掠（three.js WebGL2 实时渲染，光点按查看日期播种，
               翻日历换一幅；悬停倾斜跟随、点击 ping 涟漪；WebGL2 不可用 / reduced-motion 退化为静态兜底）。
               flex-1 min-h-0 精确吸满侧栏剩余高度：卡片高度随行高伸缩，底部始终与排行榜下边缘对齐；
               极小视口下随 min-h-0 收缩而非撑出侧栏内部滚动 -->
          <DashboardRadarCard
            :seed-date="currentDate"
            :live="!isViewingHistory"
            class="stagger-enter flex-1 min-h-0"
            style="animation-delay: 0.5s"
          />
      </aside>
    </div>
    <details v-if="!loading && isMobile" class="dashboard-overview">
      <summary>{{ t('dashboard.dataOverview') }}</summary>
      <DashboardOverviewPanel
        :loading="loading"
        :active-tab="activeTab"
        :stat-values="statValues"
        :visitor-values="visitorValues"
        @select-source="selectSourceTab"
      />
    </details>
  </div>
</template>

<style scoped>
.dashboard-overview > summary { display: none; }
.dashboard-page {
  --paper: var(--projects-paper);
  --paper-light: var(--projects-paper-light);
  --ink: var(--projects-accent);
  --muted: var(--dash-muted);
  --acid: var(--projects-acid);
  --acid-soft: var(--projects-acid-soft);
  color: var(--ink);
  background-color: var(--paper);
  background-image: linear-gradient(rgb(var(--ink-grid-rgb) / .035) 1px, transparent 1px);
  background-size: 100% 32px;
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
}

.dashboard-page :deep(.font-serif) { font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
.dashboard-heading h1 { font-size: 22px; line-height: 28px; }
.dashboard-sidebar :is(.digest-cta, .integration-card):focus-visible { outline: 2px solid var(--ink); outline-offset: -4px; }
.dashboard-sidebar .digest-cta:focus-visible { outline-color: var(--paper-light); }
.dashboard-page :deep(h1),
.dashboard-page :deep(h2),
.dashboard-page :deep(h3) { color: var(--ink); font-weight: 850; letter-spacing: -.04em; }
.dashboard-page :deep(.glass-card) {
  border: 1px solid var(--ink);
  border-radius: 5px;
  background: var(--paper-light);
  box-shadow: 3px 3px 0 var(--shadow-hard);
  backdrop-filter: none;
}
.dashboard-page :deep(.card-hover:hover) { border-color: var(--ink); background: var(--acid-soft); box-shadow: 3px 3px 0 var(--shadow-hard); transform: none; }
.dashboard-page :deep(.text-stone-300),
.dashboard-page :deep(.text-stone-400) { color: var(--muted); }
/* 深色下 GitHub/X 指标的字面灰色不可读，统一映射为 ink */
:root[data-theme='dark'] .dashboard-page :deep(.stat-cell:not(.stat-cell--active) .text-gray-800),
:root[data-theme='dark'] .dashboard-page :deep(.stat-cell:not(.stat-cell--active) .text-gray-600) { color: var(--ink); }
/* 深色下 ink 按钮底色翻为浅色，简报 CTA 标签改用 paper 保证对比度 */
:root[data-theme='dark'] .dashboard-page .digest-cta { color: var(--paper); }
.dashboard-page :deep(.rounded-full),
.dashboard-page :deep(.rounded-xl),
.dashboard-page :deep(.rounded-2xl) { border-radius: 4px; }

/* 移动端：收窄页边距；榜单内容先于日历/订阅侧栏出现（手机首屏先看内容），
   侧栏卡片横向撑满避免 320px 限宽居中留下的两侧空槽。 */
@media (max-width: 1023px) {
  .dashboard-page { display: block; overflow-y: auto; padding: 16px; }
  .dashboard-main { display: flex; flex: none; margin-top: 16px; gap: 16px; }
  .dashboard-page :deep(.stat-strip) { margin-top: 12px; }
  .dashboard-page :deep(.dashboard-ranking-panel) { flex: none; min-height: 240px; }
  .dashboard-page .order-2 { order: 1; }
  .dashboard-page aside.order-1 { order: 2; max-width: none; align-self: stretch; }
}

@media (prefers-reduced-motion: reduce) {
  .dashboard-page *, .dashboard-page *::before, .dashboard-page *::after { transition-duration: .01ms !important; animation-duration: .01ms !important; }
}
.dashboard-page .integration-card, .dashboard-page .integration-card > span { gap: 6px; }
.dashboard-page .integration-card .text-2xs { font-size: 11px; white-space: nowrap; }
.dashboard-page .integration-card .text-lg { font-size: 17px; }
</style>
